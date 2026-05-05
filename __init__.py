"""Heating Schedule integration."""

from __future__ import annotations

import logging

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .boiler import BoilerController
from .const import (
    CARD_URL_PATH,
    CARD_URL_VERSIONED,
    CARD_VERSION,
    DEFAULTS,
    DEV_ENTITY_ID,
    DOMAIN,
    OPT_DEVICES,
    PLATFORMS,
)
from .coordinator import HeatingScheduleCoordinator

_LOGGER = logging.getLogger(__name__)


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

    await _async_register_frontend_card(hass)

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


async def _async_register_frontend_card(hass: HomeAssistant) -> None:
    """Serve the Lovelace card and auto-load it on the frontend."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_frontend_registered"):
        return

    fs_path = hass.config.path(
        f"custom_components/{DOMAIN}/www/heating-schedule-card.js"
    )

    static_ok = False
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_PATH, fs_path, False)]
        )
        static_ok = True
    except AttributeError:
        # Fallback for HA < 2024.7
        try:
            hass.http.register_static_path(CARD_URL_PATH, fs_path, False)
            static_ok = True
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("register_static_path fallback failed: %s", err)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not register static path for card at %s -> %s: %s",
            CARD_URL_PATH,
            fs_path,
            err,
        )

    if not static_ok:
        return

    # Persistent registration via Lovelace resource collection (storage mode).
    # This survives HA's service-worker cache and is loaded before any card
    # tries to mount its custom element.
    persistent_ok = await _async_register_lovelace_resource(hass)

    # Best-effort fallback: also add to extra_js_url so YAML-mode Lovelace
    # and freshly opened tabs pick it up immediately.
    try:
        add_extra_js_url(hass, CARD_URL_VERSIONED)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not auto-add card to frontend; add %s to Lovelace resources manually: %s",
            CARD_URL_VERSIONED,
            err,
        )

    _LOGGER.info(
        "Heating Schedule card registered at %s (file: %s, persistent=%s)",
        CARD_URL_VERSIONED,
        fs_path,
        persistent_ok,
    )
    domain_data["_frontend_registered"] = True


async def _async_register_lovelace_resource(hass: HomeAssistant) -> bool:
    """Register the card as a permanent Lovelace resource (storage mode only).

    Returns True if a fresh resource was added or one already exists at the
    expected URL prefix; False if Lovelace is in YAML mode or the API isn't
    available, in which case the caller should fall back to add_extra_js_url.
    """
    try:
        from homeassistant.components.lovelace import (
            DOMAIN as LOVELACE_DOMAIN,
            ResourceYAMLCollection,
        )
    except ImportError:
        return False

    lovelace = hass.data.get(LOVELACE_DOMAIN)
    if lovelace is None:
        return False

    resources = getattr(lovelace, "resources", None)
    if resources is None:
        resources = (
            lovelace.get("resources") if isinstance(lovelace, dict) else None
        )
    if resources is None:
        return False

    if isinstance(resources, ResourceYAMLCollection):
        return False

    if hasattr(resources, "async_load") and not getattr(resources, "loaded", True):
        try:
            await resources.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("resources.async_load failed: %s", err)

    try:
        items = list(resources.async_items())
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("resources.async_items failed: %s", err)
        return False

    desired_versioned = CARD_URL_VERSIONED
    matching = [
        item
        for item in items
        if str(item.get("url", "")).split("?", 1)[0] == CARD_URL_PATH
    ]

    if matching:
        # Update existing entry if version doesn't match, so the browser
        # picks up the new file on the next load.
        for item in matching:
            if item.get("url") != desired_versioned:
                try:
                    await resources.async_update_item(
                        item["id"],
                        {"url": desired_versioned, "res_type": "module"},
                    )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("resources.async_update_item failed: %s", err)
        return True

    try:
        await resources.async_create_item(
            {"url": desired_versioned, "res_type": "module"}
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not auto-add Lovelace resource %s: %s",
            desired_versioned,
            err,
        )
        return False

    _LOGGER.info(
        "Heating Schedule: registered Lovelace resource %s (version %s)",
        desired_versioned,
        CARD_VERSION,
    )
    return True
