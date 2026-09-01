"""Heating Schedule integration."""

from __future__ import annotations

import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .boiler import BoilerController
from .branch import BranchController
from .const import (
    BRANCH_ID,
    DATA_BRANCHES,
    DEFAULTS,
    DEV_ENTITY_ID,
    DOMAIN,
    OPT_BRANCHES,
    OPT_DEVICES,
    PLATFORMS,
)
from .coordinator import HeatingScheduleCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heating Schedule from a config entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    options = {**DEFAULTS, **(entry.options or {})}
    if options != entry.options:
        hass.config_entries.async_update_entry(entry, options=options)

    coordinator = HeatingScheduleCoordinator(hass, entry)
    boiler = BoilerController(hass, entry, coordinator)
    coordinator.boiler = boiler
    await coordinator.async_setup()
    await boiler.async_setup()
    domain_data[entry.entry_id] = coordinator
    domain_data[f"{entry.entry_id}_sig"] = _structure_signature(entry.options)

    # Branch controllers come up before the platforms, both because the climate
    # entities need them and because each one starts by driving its branch into
    # the safe state: pump off, valve closed.
    branches: dict[str, BranchController] = {}
    for branch in entry.options.get(OPT_BRANCHES, []) or []:
        controller = BranchController(hass, branch)
        await controller.async_setup()
        branches[branch[BRANCH_ID]] = controller
    domain_data[f"{entry.entry_id}_{DATA_BRANCHES}"] = branches

    entry.async_on_unload(entry.add_update_listener(_async_reload_if_structure_changed))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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
    """Reload the entry only when tracked devices or branches change."""
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
        if coordinator.boiler is not None:
            await coordinator.boiler.async_teardown()
        await coordinator.async_teardown()
    return ok
