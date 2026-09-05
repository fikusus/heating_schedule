"""Boiler power-level controller for heating_schedule.

Demand arrives already computed, as one shortfall per room:

    shortfall = target - ambient

The coordinator produces those, because it is the part that knows each room's
target including its offset. This module only maps the worst shortfall onto a
power level and an on/off state:

    max_diff = max(shortfalls)
    clamped  = clamp(max_diff, 0, 1)
    power    = round(clamped * 99 + 1)
    switch   = OFF if max_diff < 0 else ON

Earlier versions read a separate list of room sensors of their own. That list
duplicated what the climate entities already knew, and comparing against the
bare schedule target meant a room's offset was ignored: a room driven to
target + 1.0 was assessed as if it were driven to target, so the boiler
consistently under-read demand exactly where it had been raised by hand.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    OPT_BOILER_ENABLED,
    OPT_BOILER_KEEP_ON,
    OPT_BOILER_POWER_ENTITY,
    OPT_BOILER_PUMPS,
    OPT_BOILER_SUMMER,
    OPT_BOILER_SWITCH_ENTITY,
)

_LOGGER = logging.getLogger(__name__)

EMPTY_STATE: dict[str, Any] = {
    "max_diff": None,
    "power": None,
    "switch": None,
    "active": False,
}


class BoilerController:
    """Maps room shortfalls onto boiler power, on/off state and pumps."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator,  # HeatingScheduleCoordinator (avoid circular import)
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator

    async def evaluate_and_apply(
        self, opts: dict[str, Any], shortfalls: list[float]
    ) -> dict[str, Any]:
        """Compute boiler state and call services. Return state for the sensors."""
        if not opts.get(OPT_BOILER_ENABLED, False):
            return dict(EMPTY_STATE)
        if opts.get(OPT_BOILER_SUMMER, False):
            return dict(EMPTY_STATE)
        if not shortfalls:
            return dict(EMPTY_STATE)

        max_diff = math.floor(max(shortfalls) * 100) / 100  # 2-decimal floor
        clamped = max(0.0, min(max_diff, 1.0))
        power = int(round(clamped * 99 + 1))

        keep_on = bool(opts.get(OPT_BOILER_KEEP_ON, False))
        switch_target = "on" if (max_diff >= 0 or keep_on) else "off"

        await self._apply_power(opts.get(OPT_BOILER_POWER_ENTITY), power)
        await self._apply_switch(opts.get(OPT_BOILER_SWITCH_ENTITY), switch_target)
        await self._apply_pumps(opts.get(OPT_BOILER_PUMPS) or [], switch_target)

        return {
            "max_diff": max_diff,
            "power": power,
            "switch": switch_target,
            "keep_on": keep_on,
            "rooms": len(shortfalls),
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

    async def _apply_pumps(self, pumps: list[str], target: str) -> None:
        """Mirror the boiler switch state on each configured pump."""
        valid = [p for p in pumps if p and self.hass.states.get(p) is not None]
        if not valid:
            return
        service = "turn_on" if target == "on" else "turn_off"
        await self.hass.services.async_call(
            "switch",
            service,
            {"entity_id": valid},
            blocking=False,
        )
