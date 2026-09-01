"""Time platform for heating_schedule."""

from __future__ import annotations

from datetime import time
from typing import Any, Callable

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    OPT_BED_DAY_TO_NIGHT,
    OPT_BED_NIGHT_TO_DAY,
    OPT_DAY_TO_NIGHT,
    OPT_NIGHT_TO_DAY,
)

GLOBAL_TIMES: list[dict[str, Any]] = [
    {"key": OPT_DAY_TO_NIGHT, "name": "Day → Night", "icon": "mdi:weather-sunset-down"},
    {"key": OPT_NIGHT_TO_DAY, "name": "Night → Day", "icon": "mdi:weather-sunset-up"},
    {
        "key": OPT_BED_DAY_TO_NIGHT,
        "name": "Bedroom Day → Night",
        "icon": "mdi:bed-clock",
    },
    {
        "key": OPT_BED_NIGHT_TO_DAY,
        "name": "Bedroom Night → Day",
        "icon": "mdi:bed-clock",
    },
]


def _parse(value: str | time | None) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    parts = str(value).split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [ScheduleTime(entry, spec) for spec in GLOBAL_TIMES]
    )


class ScheduleTime(TimeEntity):
    """A time-of-day entity backed by entry.options[key]."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, spec: dict[str, Any]) -> None:
        self._entry = entry
        self._key: str = spec["key"]
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_translation_key = self._key
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._unsub: Callable[[], None] | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

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
    def native_value(self) -> time | None:
        return _parse(self._entry.options.get(self._key))

    async def async_set_value(self, value: time) -> None:
        new_options = dict(self._entry.options)
        new_options[self._key] = value.strftime("%H:%M:%S")
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
