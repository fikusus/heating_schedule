"""Valve and pump control for a single heating branch.

The controller owns the hardware and one safety invariant:

    the pump may run only while the actuator is confirmed open

That is deliberately not a branch of the control logic. A pump running against
a closed valve destroys itself, so the rule is re-asserted on every pass, from
three independent triggers: the policy layer asking for a change, the actuator
reporting a state change, and a watchdog that fires regardless of events.

Ordering is asymmetric and matters. Starting up goes valve first, then pump
once the actuator has had time to travel. Shutting down goes pump first, then
valve, and is never delayed by anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    BRANCH_ACTUATOR,
    BRANCH_MIN_CYCLE_S,
    BRANCH_NAME,
    BRANCH_PUMP,
    BRANCH_TRAVEL_S,
    DEFAULT_MIN_CYCLE_S,
    DEFAULT_TRAVEL_S,
    WATCHDOG_INTERVAL_S,
)

_LOGGER = logging.getLogger(__name__)

_UNUSABLE = ("unavailable", "unknown")


def read_min_temperature(hass: HomeAssistant, entity_ids) -> float | None:
    """Coldest readable sensor of a set, or None if none can be read.

    The coldest reading governs a zone, matching how the boiler has always
    picked the room furthest from its target. Shared by the climate entity
    that displays it and the coordinator that computes demand from it.
    """
    readings: list[float] = []
    for entity_id in entity_ids or []:
        state = hass.states.get(entity_id)
        if state is None or state.state in _UNUSABLE:
            continue
        try:
            readings.append(float(state.state))
        except (TypeError, ValueError):
            continue
    return min(readings) if readings else None


class BranchController:
    """Drives one branch's actuator and pump, and keeps them interlocked."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self.hass = hass
        self._config = dict(config)

        self._demand = False
        # When the actuator was first *observed* open. None means "not open, or
        # not known to be open" -- the state the pump may never run in.
        self._opened_at: datetime | None = None
        self._pump_commanded: bool | None = None
        self._valve_commanded: bool | None = None
        self._pump_stopped_at: datetime | None = None

        self._unsub_actuator: CALLBACK_TYPE | None = None
        self._unsub_watchdog: CALLBACK_TYPE | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------- lifecycle

    async def async_setup(self) -> None:
        """Start listening and bring the branch into a known-safe state."""
        self._register_actuator_listener()
        self._unsub_watchdog = async_track_time_interval(
            self.hass,
            self._async_watchdog,
            timedelta(seconds=WATCHDOG_INTERVAL_S),
        )
        # Travel state is unknown after a restart, so start from "not open".
        self._opened_at = None
        await self._async_enforce()

    async def async_teardown(self) -> None:
        """Stop the branch and drop every subscription."""
        self._cancel_timer()
        if self._unsub_watchdog:
            self._unsub_watchdog()
            self._unsub_watchdog = None
        if self._unsub_actuator:
            self._unsub_actuator()
            self._unsub_actuator = None
        self._demand = False
        await self._async_shut_down()

    def update_config(self, config: dict[str, Any]) -> None:
        """Adopt a new configuration, re-subscribing if the actuator moved."""
        old_actuator = self._config.get(BRANCH_ACTUATOR)
        self._config = dict(config)
        if self._config.get(BRANCH_ACTUATOR) != old_actuator:
            self._opened_at = None
            self._register_actuator_listener()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback fired when the branch's own state changes."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    # ---------------------------------------------------------------- policy

    async def async_set_demand(self, demand: bool) -> None:
        """Ask the branch to heat, or to stop. The interlock keeps its veto."""
        self._demand = bool(demand)
        await self._async_enforce()

    @property
    def demand(self) -> bool:
        return self._demand

    @property
    def is_heating(self) -> bool:
        """True only when the pump is actually commanded on."""
        return self._pump_commanded is True

    @property
    def is_opening(self) -> bool:
        """True while heat is wanted but the pump is still held back."""
        return self._demand and not self.is_heating

    # -------------------------------------------------------------- triggers

    def _register_actuator_listener(self) -> None:
        if self._unsub_actuator:
            self._unsub_actuator()
            self._unsub_actuator = None
        actuator = self._config.get(BRANCH_ACTUATOR)
        if not actuator:
            return
        self._unsub_actuator = async_track_state_change_event(
            self.hass, [actuator], self._async_actuator_changed
        )

    @callback
    def _async_actuator_changed(self, event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state != "on":
            # The valve left the open state, for whatever reason. Do not wait
            # for the next scheduled pass to notice.
            self._opened_at = None
        self.hass.async_create_task(self._async_enforce())

    @callback
    def _async_watchdog(self, _now: datetime) -> None:
        self.hass.async_create_task(self._async_enforce())

    def _schedule_recheck(self, delay: float) -> None:
        self._cancel_timer()
        self._unsub_timer = async_call_later(
            self.hass, max(1.0, delay), self._async_timer_fired
        )

    @callback
    def _async_timer_fired(self, _now: datetime) -> None:
        self._unsub_timer = None
        self.hass.async_create_task(self._async_enforce())

    def _cancel_timer(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    # ------------------------------------------------------------- interlock

    async def _async_enforce(self) -> None:
        """Re-assert the invariant and move the branch towards what is wanted."""
        before = (self._pump_commanded, self._valve_commanded)

        if self._demand:
            await self._async_start_up()
        else:
            await self._async_shut_down()

        if (self._pump_commanded, self._valve_commanded) != before:
            for listener in list(self._listeners):
                listener()

    async def _async_shut_down(self) -> None:
        """Pump first, then valve. Never delayed."""
        self._cancel_timer()
        await self._async_set_pump(False)
        await self._async_set_valve(False)
        self._opened_at = None

    async def _async_start_up(self) -> None:
        """Valve first; the pump only once the actuator is confirmed open."""
        await self._async_set_valve(True)

        if not self._valve_is_open():
            # Commanded open but not reporting open yet, or unavailable. Either
            # way the pump stays off; look again after the travel time.
            await self._async_set_pump(False)
            self._opened_at = None
            self._schedule_recheck(self._travel_s())
            return

        if self._opened_at is None:
            self._opened_at = dt_util.utcnow()

        travelled = (dt_util.utcnow() - self._opened_at).total_seconds()
        remaining = self._travel_s() - travelled
        if remaining > 0:
            await self._async_set_pump(False)
            self._schedule_recheck(remaining)
            return

        cooldown = self._min_cycle_remaining()
        if cooldown > 0:
            self._schedule_recheck(cooldown)
            return

        await self._async_set_pump(True)

    def _valve_is_open(self) -> bool:
        actuator = self._config.get(BRANCH_ACTUATOR)
        if not actuator:
            return False
        state = self.hass.states.get(actuator)
        return state is not None and state.state == "on"

    def _min_cycle_remaining(self) -> float:
        """Seconds the pump must still wait before it may start again."""
        min_cycle = float(self._config.get(BRANCH_MIN_CYCLE_S, DEFAULT_MIN_CYCLE_S))
        if min_cycle <= 0 or self._pump_stopped_at is None:
            return 0.0
        elapsed = (dt_util.utcnow() - self._pump_stopped_at).total_seconds()
        return max(0.0, min_cycle - elapsed)

    def _travel_s(self) -> float:
        return float(self._config.get(BRANCH_TRAVEL_S, DEFAULT_TRAVEL_S))

    # --------------------------------------------------------------- outputs

    async def _async_set_pump(self, on: bool) -> None:
        was_running = self._pump_commanded is True
        await self._async_switch(self._config.get(BRANCH_PUMP), on, "_pump_commanded")
        if on:
            self._pump_stopped_at = None
        elif was_running:
            # Only a genuine stop starts the cooldown. The unconditional
            # turn_off we issue at setup must not hold heating back after a
            # restart.
            self._pump_stopped_at = dt_util.utcnow()

    async def _async_set_valve(self, on: bool) -> None:
        await self._async_switch(
            self._config.get(BRANCH_ACTUATOR), on, "_valve_commanded"
        )

    async def _async_switch(
        self, entity_id: str | None, on: bool, commanded_attr: str
    ) -> None:
        """Call a switch, skipping the call once the wanted state is confirmed.

        Anything short of an explicit confirmation -- a missing entity, an
        unavailable one, a state that disagrees with what we last commanded --
        makes the call again. Repeating a turn_off costs nothing; skipping one
        can cost a pump.
        """
        if not entity_id:
            return

        wanted = "on" if on else "off"
        state = self.hass.states.get(entity_id)
        settled = (
            state is not None
            and state.state == wanted
            and getattr(self, commanded_attr) is on
        )
        if settled:
            return

        if state is None or state.state in _UNUSABLE:
            _LOGGER.warning(
                "Heating branch %s: %s is %s, commanding %s anyway",
                self._config.get(BRANCH_NAME) or "?",
                entity_id,
                "missing" if state is None else state.state,
                wanted,
            )

        setattr(self, commanded_attr, on)
        await self.hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": entity_id},
            blocking=False,
        )
