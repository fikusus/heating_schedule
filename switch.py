"""Switch platform for heating_schedule: boiler-control toggles."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    OPT_BOILER_ENABLED,
    OPT_BOILER_SUMMER,
)


SWITCH_SPECS: list[dict[str, Any]] = [
    {
        "key": OPT_BOILER_ENABLED,
        "name": "Boiler Control",
        "icon": "mdi:fire",
    },
    {
        "key": OPT_BOILER_SUMMER,
        "name": "Boiler Summer Mode",
        "icon": "mdi:weather-sunny",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([OptionSwitch(entry, spec) for spec in SWITCH_SPECS])


class OptionSwitch(SwitchEntity):
    """Boolean switch backed by entry.options[key]."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, spec: dict[str, Any]) -> None:
        self._entry = entry
        self._key: str = spec["key"]
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_translation_key = self._key
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._unsub = self._entry.add_update_listener(self._on_options)
        self.async_on_remove(self._cleanup_listeners)

    @callback
    def _cleanup_listeners(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def _on_options(self, _hass, _entry) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return bool((self._entry.options or {}).get(self._key, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, value: bool) -> None:
        new_options = dict(self._entry.options or {})
        new_options[self._key] = value
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
