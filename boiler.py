"""Boiler power-level controller for heating_schedule.

Computes max(target - ambient) across configured rooms; maps to power level
[1..100] and on/off switch state. Mirrors the original automation:

    diff_per_room = target - ambient
    max_diff = max(diffs)
    clamped  = clamp(max_diff, 0, 1)
    power    = round(clamped * 99 + 1)
    switch   = OFF if max_diff < 0 else ON
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    OPT_BOILER_ENABLED,
    OPT_BOILER_POWER_ENTITY,
    OPT_BOILER_ROOMS,
    OPT_BOILER_SUMMER,
    OPT_BOILER_SWITCH_ENTITY,
    ROOM_IS_BEDROOM,
    ROOM_SENSOR,
)

_LOGGER = logging.getLogger(__name__)


class BoilerController:
    """Reacts to ambient sensor / target / config changes; drives power and on/off."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator,  # HeatingScheduleCoordinator (avoid circular import)
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._unsub_state: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        self._register_state_listener()

    async def async_teardown(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    def reload_state_listener(self) -> None:
        """Re-register the ambient-sensor state listener (after options change)."""
        self._register_state_listener()

    def _register_state_listener(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

        rooms = (self.entry.options or {}).get(OPT_BOILER_ROOMS) or []
        sensors = [r[ROOM_SENSOR] for r in rooms if r.get(ROOM_SENSOR)]
        if not sensors:
            return

        self._unsub_state = async_track_state_change_event(
            self.hass, sensors, self._on_sensor_change
        )

    @callback
    def _on_sensor_change(self, _event) -> None:
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def evaluate_and_apply(
        self,
        opts: dict[str, Any],
        main_target: float,
        bed_target: float,
    ) -> dict[str, Any]:
        """Compute boiler state and call services. Return state dict for sensors."""
        empty = {"max_diff": None, "power": None, "switch": None, "active": False}

        if not opts.get(OPT_BOILER_ENABLED, False):
            return empty
        if opts.get(OPT_BOILER_SUMMER, False):
            return empty

        rooms = opts.get(OPT_BOILER_ROOMS) or []
        diffs: list[float] = []
        for r in rooms:
            sensor_id = r.get(ROOM_SENSOR)
            if not sensor_id:
                continue
            state = self.hass.states.get(sensor_id)
            if state is None or state.state in ("unavailable", "unknown"):
                continue
            try:
                temp = float(state.state)
            except (TypeError, ValueError):
                continue
            target = bed_target if r.get(ROOM_IS_BEDROOM) else main_target
            diffs.append(target - temp)

        if not diffs:
            return empty

        max_diff = math.floor(max(diffs) * 100) / 100      # 2-decimal floor
        clamped = max(0.0, min(max_diff, 1.0))
        power = int(round(clamped * 99 + 1))
        switch_target = "off" if max_diff < 0 else "on"

        await self._apply_power(opts.get(OPT_BOILER_POWER_ENTITY), power)
        await self._apply_switch(opts.get(OPT_BOILER_SWITCH_ENTITY), switch_target)

        return {
            "max_diff": max_diff,
            "power": power,
            "switch": switch_target,
            "active": True,
        }

    async def _apply_power(self, power_entity: str | None, power: int) -> None:
        if not power_entity:
            return
        if self.hass.states.get(power_entity) is None:
            _LOGGER.debug("Boiler power entity %s not found, skipping", power_entity)
            return
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": power_entity, "value": power},
            blocking=False,
        )

    async def _apply_switch(self, switch_entity: str | None, target: str) -> None:
        if not switch_entity:
            return
        if self.hass.states.get(switch_entity) is None:
            _LOGGER.debug("Boiler switch entity %s not found, skipping", switch_entity)
            return
        service = "turn_on" if target == "on" else "turn_off"
        await self.hass.services.async_call(
            "switch",
            service,
            {"entity_id": switch_entity},
            blocking=False,
        )
