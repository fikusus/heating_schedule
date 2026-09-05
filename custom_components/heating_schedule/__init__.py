"""Heating Schedule integration."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .boiler import BoilerController
from .branch import BranchController
from .const import (
    BRANCH_ACTUATOR,
    BRANCH_HYSTERESIS,
    BRANCH_ID,
    BRANCH_IS_BEDROOM,
    BRANCH_MIN_CYCLE_S,
    BRANCH_NAME,
    BRANCH_OFFSET,
    BRANCH_PUMP,
    BRANCH_SENSORS,
    BRANCH_TRAVEL_S,
    DATA_BRANCHES,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_CYCLE_S,
    DEFAULT_TRAVEL_S,
    DEFAULTS,
    DEV_ENTITY_ID,
    DOMAIN,
    OPT_BOILER_ROOMS,
    OPT_BRANCHES,
    OPT_DEVICES,
    PLATFORMS,
    ROOM_IS_BEDROOM,
    ROOM_SENSOR,
)
from .coordinator import HeatingScheduleCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Schedule from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    options = _migrate_boiler_rooms(hass, {**DEFAULTS, **(entry.options or {})})
    if options != entry.options:
        hass.config_entries.async_update_entry(entry, options=options)

    coordinator = HeatingScheduleCoordinator(hass, entry)
    coordinator.boiler = BoilerController(hass, entry, coordinator)
    domain_data[entry.entry_id] = coordinator
    domain_data[f"{entry.entry_id}_sig"] = _structure_signature(entry.options)

    # Controllers come up before the platforms, both because the climate
    # entities need them and because each one starts by driving its branch into
    # the safe state: pump off, valve closed. Zones without hardware have
    # nothing to drive and get no controller at all.
    branches: dict[str, BranchController] = {}
    for branch in entry.options.get(OPT_BRANCHES, []) or []:
        if not (branch.get(BRANCH_ACTUATOR) or branch.get(BRANCH_PUMP)):
            continue
        controller = BranchController(hass, branch)
        await controller.async_setup()
        branches[branch[BRANCH_ID]] = controller
    domain_data[f"{entry.entry_id}_{DATA_BRANCHES}"] = branches

    await coordinator.async_setup()

    entry.async_on_unload(entry.add_update_listener(_async_reload_if_structure_changed))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _migrate_boiler_rooms(
    hass: HomeAssistant, options: dict[str, Any]
) -> dict[str, Any]:
    """Turn a stored boiler room list into sensor-only zones.

    Boiler demand used to come from a room list of its own, holding sensors that
    the climate entities already knew about and comparing them against the bare
    schedule target, offset excluded. Each of those rooms becomes a zone with the
    same sensor and bedroom flag, which restores the same readings to the boiler
    and gives them an offset they never had.
    """
    if OPT_BOILER_ROOMS not in options:
        return options

    migrated = dict(options)
    rooms = migrated.pop(OPT_BOILER_ROOMS) or []
    branches = [dict(b) for b in migrated.get(OPT_BRANCHES, []) or []]
    known = {s for b in branches for s in b.get(BRANCH_SENSORS) or []}

    for room in rooms:
        sensor = room.get(ROOM_SENSOR)
        if not sensor or sensor in known:
            continue
        branches.append(
            {
                BRANCH_ID: uuid4().hex[:8],
                BRANCH_NAME: _friendly_name(hass, sensor),
                BRANCH_SENSORS: [sensor],
                BRANCH_OFFSET: 0.0,
                BRANCH_IS_BEDROOM: bool(room.get(ROOM_IS_BEDROOM, False)),
                BRANCH_ACTUATOR: None,
                BRANCH_PUMP: None,
                BRANCH_HYSTERESIS: DEFAULT_HYSTERESIS,
                BRANCH_TRAVEL_S: DEFAULT_TRAVEL_S,
                BRANCH_MIN_CYCLE_S: DEFAULT_MIN_CYCLE_S,
            }
        )
        known.add(sensor)
        _LOGGER.info("Migrated boiler room %s into a sensor-only zone", sensor)

    migrated[OPT_BRANCHES] = branches
    return migrated


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state is not None:
        name = state.attributes.get("friendly_name")
        if name:
            return str(name)
    return entity_id


def _structure_signature(options: dict | None) -> str:
    """Fingerprint of the parts that require rebuilding entities and listeners.

    Branch configuration is included whole rather than by id: a branch that
    changes its actuator, pump or sensors needs its controller and its climate
    entity rebuilt around the new entities, not merely notified.
    """
    opts = options or {}
    devices = sorted(d[DEV_ENTITY_ID] for d in opts.get(OPT_DEVICES, []) or [])
    branches = sorted(
        (json.dumps(b, sort_keys=True) for b in opts.get(OPT_BRANCHES, []) or [])
    )
    return json.dumps({"devices": devices, "branches": branches}, sort_keys=True)


async def _async_reload_if_structure_changed(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the entry only when tracked devices or zones change."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    new_sig = _structure_signature(entry.options)
    old_sig = domain_data.get(f"{entry.entry_id}_sig")
    domain_data[f"{entry.entry_id}_sig"] = new_sig
    if old_sig != new_sig:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    domain_data = hass.data.get(DOMAIN, {})

    branches: dict[str, BranchController] = domain_data.pop(
        f"{entry.entry_id}_{DATA_BRANCHES}", {}
    )
    for controller in branches.values():
        await controller.async_teardown()

    coordinator: HeatingScheduleCoordinator | None = domain_data.pop(
        entry.entry_id, None
    )
    domain_data.pop(f"{entry.entry_id}_sig", None)
    if coordinator is not None:
        await coordinator.async_teardown()
    return ok
