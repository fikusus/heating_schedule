"""Coordinator for heating_schedule: phase computation and device application."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULTS,
    DEV_ENTITY_ID,
    DEV_IS_BEDROOM,
    DEV_OFFSET,
    DOMAIN,
    OPT_BED_DAY_TO_NIGHT,
    OPT_BED_NIGHT_TEMP,
    OPT_BED_NIGHT_TO_DAY,
    OPT_BOILER_SUMMER,
    OPT_DAY_TEMP,
    OPT_DAY_TO_NIGHT,
    OPT_DEVICES,
    OPT_NIGHT_TEMP,
    OPT_NIGHT_TO_DAY,
    OPT_TRANSITION_MIN,
    PHASE_DAY,
    PHASE_NIGHT,
    PHASE_TRANSITION_TO_DAY,
    PHASE_TRANSITION_TO_NIGHT,
)

_LOGGER = logging.getLogger(__name__)


def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    parts = str(value).split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def _in_range(now_min: int, start_min: int, end_min: int) -> bool:
    """[start, end) in modulo-1440 arithmetic; handles midnight wrap."""
    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= now_min < end_min
    return now_min >= start_min or now_min < end_min


def compute_phase(
    now: time,
    day_to_night: time,
    night_to_day: time,
    transition_min: int,
) -> str:
    """Return the current phase for a single schedule.

    Phase wheel: [day]──(d2n - t)──[trans→night]──d2n──[night]──(n2d - t)──[trans→day]──n2d──[day]
    """
    n = _mins(now)
    d2n = _mins(day_to_night)
    n2d = _mins(night_to_day)
    t = max(0, int(transition_min))

    if _in_range(n, (d2n - t) % 1440, d2n):
        return PHASE_TRANSITION_TO_NIGHT
    if _in_range(n, d2n, (n2d - t) % 1440):
        return PHASE_NIGHT
    if _in_range(n, (n2d - t) % 1440, n2d):
        return PHASE_TRANSITION_TO_DAY
    return PHASE_DAY


def compute_target(phase: str, day_temp: float, night_temp: float) -> float:
    """Map phase -> effective setpoint, snapped to 0.5 °C."""
    if phase == PHASE_DAY:
        return float(day_temp)
    if phase == PHASE_NIGHT:
        return float(night_temp)
    return round((day_temp + night_temp)) / 2


def _boundary_times(
    day_to_night: time,
    night_to_day: time,
    transition_min: int,
) -> set[time]:
    """Return the four clock instants where this schedule changes phase."""
    t = max(0, int(transition_min))
    d2n_min = _mins(day_to_night)
    n2d_min = _mins(night_to_day)
    boundaries = {
        (d2n_min - t) % 1440,
        d2n_min,
        (n2d_min - t) % 1440,
        n2d_min,
    }
    return {time(b // 60, b % 60) for b in boundaries}


class HeatingScheduleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Owns schedule logic, time subscriptions, and device application."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.entry = entry
        self.boiler = None  # set by __init__.py after construction
        self._unsub_times: list[Callable[[], None]] = []
        self._unsub_options: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        self._register_time_listeners()
        self._unsub_options = self.entry.add_update_listener(self._on_options)
        await self.async_refresh()

    async def async_teardown(self) -> None:
        for unsub in self._unsub_times:
            unsub()
        self._unsub_times.clear()
        if self._unsub_options:
            self._unsub_options()
            self._unsub_options = None

    def _register_time_listeners(self) -> None:
        for unsub in self._unsub_times:
            unsub()
        self._unsub_times.clear()

        opts = self._opts()
        transition_min = int(opts[OPT_TRANSITION_MIN])

        boundaries: set[time] = set()
        boundaries |= _boundary_times(
            _parse_time(opts[OPT_DAY_TO_NIGHT]),
            _parse_time(opts[OPT_NIGHT_TO_DAY]),
            transition_min,
        )
        boundaries |= _boundary_times(
            _parse_time(opts[OPT_BED_DAY_TO_NIGHT]),
            _parse_time(opts[OPT_BED_NIGHT_TO_DAY]),
            transition_min,
        )

        for t in boundaries:
            unsub = async_track_time_change(
                self.hass,
                self._async_boundary_reached,
                hour=t.hour,
                minute=t.minute,
                second=0,
            )
            self._unsub_times.append(unsub)

    @callback
    def _async_boundary_reached(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_refresh())

    async def _on_options(
        self, _hass: HomeAssistant, _entry: ConfigEntry
    ) -> None:
        self._register_time_listeners()
        if self.boiler is not None:
            self.boiler.reload_state_listener()
        await self.async_refresh()

    def _opts(self) -> dict[str, Any]:
        """Return entry options with defaults filled in for any missing keys."""
        return {**DEFAULTS, **(self.entry.options or {})}

    async def _async_update_data(self) -> dict[str, Any]:
        opts = self._opts()
        now_t = dt_util.now().time()
        transition_min = int(opts[OPT_TRANSITION_MIN])

        main_phase = compute_phase(
            now_t,
            _parse_time(opts[OPT_DAY_TO_NIGHT]),
            _parse_time(opts[OPT_NIGHT_TO_DAY]),
            transition_min,
        )
        bed_phase = compute_phase(
            now_t,
            _parse_time(opts[OPT_BED_DAY_TO_NIGHT]),
            _parse_time(opts[OPT_BED_NIGHT_TO_DAY]),
            transition_min,
        )

        day_t = float(opts[OPT_DAY_TEMP])
        night_t = float(opts[OPT_NIGHT_TEMP])
        bed_night_t = float(opts[OPT_BED_NIGHT_TEMP])

        main_target = compute_target(main_phase, day_t, night_t)
        bed_target = compute_target(bed_phase, day_t, bed_night_t)

        await self._apply_to_devices(opts, main_target, bed_target)

        boiler_state: dict[str, Any] = {
            "max_diff": None,
            "power": None,
            "switch": None,
            "active": False,
        }
        if self.boiler is not None:
            boiler_state = await self.boiler.evaluate_and_apply(
                opts, main_target, bed_target
            )

        return {
            "main_phase": main_phase,
            "bed_phase": bed_phase,
            "main_target": main_target,
            "bed_target": bed_target,
            "boiler": boiler_state,
        }

    async def _apply_to_devices(
        self,
        opts: dict,
        main_target: float,
        bed_target: float,
    ) -> None:
        summer = bool(opts.get(OPT_BOILER_SUMMER, False))
        tasks = []
        for dev in opts.get(OPT_DEVICES, []) or []:
            entity_id: str = dev[DEV_ENTITY_ID]

            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unavailable", "unknown"):
                _LOGGER.debug("Skipping %s — state %s", entity_id, state)
                continue

            if summer:
                target = _max_temp_for(state)
            else:
                offset = float(dev.get(DEV_OFFSET, 0.0))
                base = bed_target if dev.get(DEV_IS_BEDROOM) else main_target
                target = round((base + offset) * 2) / 2

            tasks.append(
                self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": target},
                    blocking=False,
                )
            )

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    _LOGGER.warning("set_temperature failed: %s", r)


def _max_temp_for(state) -> float:
    """Read climate entity's `max_temp` attribute, with a sane fallback."""
    try:
        return float(state.attributes.get("max_temp", 30.0))
    except (TypeError, ValueError):
        return 30.0
