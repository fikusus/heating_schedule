"""Coordinator for heating_schedule: phase computation and device application."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .branch import read_min_temperature
from .const import (
    BRANCH_ID,
    BRANCH_IS_BEDROOM,
    BRANCH_OFFSET,
    BRANCH_SENSORS,
    DEFAULTS,
    DEV_ENTITY_ID,
    DEV_IS_BEDROOM,
    DEV_OFFSET,
    DOMAIN,
    OPT_BED_DAY_TO_NIGHT,
    OPT_BED_NIGHT_TEMP,
    OPT_BED_NIGHT_TO_DAY,
    OPT_BOILER_SUMMER,
    OPT_BRANCHES,
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

_UNUSABLE = ("unavailable", "unknown")


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


def _with_offset(base: float, offset: Any) -> float:
    try:
        return round((base + float(offset)) * 2) / 2
    except (TypeError, ValueError):
        return base


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
        self._unsub_states: Callable[[], None] | None = None
        self._unsub_options: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        self._register_time_listeners()
        self._register_state_listeners()
        self._unsub_options = self.entry.add_update_listener(self._on_options)
        await self.async_refresh()

    async def async_teardown(self) -> None:
        for unsub in self._unsub_times:
            unsub()
        self._unsub_times.clear()
        if self._unsub_states:
            self._unsub_states()
            self._unsub_states = None
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

    def _register_state_listeners(self) -> None:
        """Watch everything that feeds boiler demand.

        That is the tracked climate entities, whose current_temperature is now
        the ambient reading, and the sensors behind each zone. The boiler used
        to keep this subscription for a room list of its own; there is no such
        list any more.
        """
        if self._unsub_states:
            self._unsub_states()
            self._unsub_states = None

        opts = self._opts()
        watched = {
            d[DEV_ENTITY_ID]
            for d in opts.get(OPT_DEVICES, []) or []
            if d.get(DEV_ENTITY_ID)
        }
        for branch in opts.get(OPT_BRANCHES, []) or []:
            watched.update(s for s in branch.get(BRANCH_SENSORS) or [] if s)

        if not watched:
            return

        self._unsub_states = async_track_state_change_event(
            self.hass, sorted(watched), self._async_source_changed
        )

    @callback
    def _async_boundary_reached(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_refresh())

    @callback
    def _async_source_changed(self, _event) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    async def _on_options(
        self, _hass: HomeAssistant, _entry: ConfigEntry
    ) -> None:
        self._register_time_listeners()
        self._register_state_listeners()
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

        shortfalls = await self._apply_to_devices(opts, main_target, bed_target)
        zone_targets, zone_shortfalls = self._evaluate_zones(
            opts, main_target, bed_target
        )
        shortfalls.extend(zone_shortfalls)

        boiler_state: dict[str, Any] = {
            "max_diff": None,
            "power": None,
            "switch": None,
            "active": False,
        }
        if self.boiler is not None:
            boiler_state = await self.boiler.evaluate_and_apply(opts, shortfalls)

        return {
            "main_phase": main_phase,
            "bed_phase": bed_phase,
            "main_target": main_target,
            "bed_target": bed_target,
            "zone_targets": zone_targets,
            "boiler": boiler_state,
        }

    async def _apply_to_devices(
        self,
        opts: dict,
        main_target: float,
        bed_target: float,
    ) -> list[float]:
        """Push targets to the tracked climate entities and read back demand.

        The shortfall is measured against the target the device is actually
        driven to, offset included, so a room deliberately kept warmer is not
        assessed as if it were not.
        """
        summer = bool(opts.get(OPT_BOILER_SUMMER, False))
        shortfalls: list[float] = []
        tasks = []

        for dev in opts.get(OPT_DEVICES, []) or []:
            entity_id: str = dev[DEV_ENTITY_ID]

            state = self.hass.states.get(entity_id)
            if state is None or state.state in _UNUSABLE:
                _LOGGER.debug("Skipping %s — state %s", entity_id, state)
                continue

            if summer:
                target = _max_temp_for(state)
            else:
                base = bed_target if dev.get(DEV_IS_BEDROOM) else main_target
                target = _with_offset(base, dev.get(DEV_OFFSET, 0.0))
                ambient = state.attributes.get("current_temperature")
                if ambient is not None:
                    try:
                        shortfalls.append(target - float(ambient))
                    except (TypeError, ValueError):
                        pass

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

        return shortfalls

    def _evaluate_zones(
        self, opts: dict, main_target: float, bed_target: float
    ) -> tuple[dict[str, float], list[float]]:
        """Target and shortfall for every zone this integration owns.

        Zones are driven from here rather than through a service call to our own
        climate entities: the entity reads its target straight out of the
        coordinator data.
        """
        targets: dict[str, float] = {}
        shortfalls: list[float] = []
        summer = bool(opts.get(OPT_BOILER_SUMMER, False))

        for branch in opts.get(OPT_BRANCHES, []) or []:
            branch_id = branch.get(BRANCH_ID)
            if not branch_id:
                continue
            base = bed_target if branch.get(BRANCH_IS_BEDROOM) else main_target
            target = _with_offset(base, branch.get(BRANCH_OFFSET, 0.0))
            targets[branch_id] = target

            if summer:
                continue
            ambient = read_min_temperature(
                self.hass, branch.get(BRANCH_SENSORS) or []
            )
            if ambient is not None:
                shortfalls.append(target - ambient)

        return targets, shortfalls


def _max_temp_for(state) -> float:
    """Read climate entity's `max_temp` attribute, with a sane fallback."""
    try:
        return float(state.attributes.get("max_temp", 30.0))
    except (TypeError, ValueError):
        return 30.0
