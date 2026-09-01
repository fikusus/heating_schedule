"""Heating Schedule integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .boiler import BoilerController
from .const import (
    DEFAULTS,
    DEV_ENTITY_ID,
    DOMAIN,
    OPT_DEVICES,
    PLATFORMS,
)
from .coordinator import HeatingScheduleCoordinator
from .frontend import async_register_card


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
    domain_data[f"{entry.entry_id}_dev_sig"] = _devices_signature(entry.options)

    entry.async_on_unload(entry.add_update_listener(_async_reload_if_devices_changed))

    await async_register_card(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _devices_signature(options: dict | None) -> tuple[str, ...]:
    return tuple(
        sorted(
            d[DEV_ENTITY_ID]
            for d in (options or {}).get(OPT_DEVICES, []) or []
        )
    )


async def _async_reload_if_devices_changed(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the entry only when the tracked-device set changes."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    new_sig = _devices_signature(entry.options)
    old_sig = domain_data.get(f"{entry.entry_id}_dev_sig")
    domain_data[f"{entry.entry_id}_dev_sig"] = new_sig
    if old_sig != new_sig:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    domain_data = hass.data.get(DOMAIN, {})
    coordinator: HeatingScheduleCoordinator | None = domain_data.pop(
        entry.entry_id, None
    )
    domain_data.pop(f"{entry.entry_id}_dev_sig", None)
    if coordinator is not None:
        if coordinator.boiler is not None:
            await coordinator.boiler.async_teardown()
        await coordinator.async_teardown()
    return ok
