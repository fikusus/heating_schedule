"""Number platform for heating_schedule."""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEV_ENTITY_ID,
    DEV_IS_BEDROOM,
    DEV_OFFSET,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    DURATION_MAX,
    DURATION_MIN,
    DURATION_STEP,
    OFFSET_MAX,
    OFFSET_MIN,
    OFFSET_STEP,
    OPT_BED_NIGHT_TEMP,
    OPT_DAY_TEMP,
    OPT_DEVICES,
    OPT_NIGHT_TEMP,
    OPT_TRANSITION_MIN,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
)


GLOBAL_NUMBERS: list[dict[str, Any]] = [
    {
        "key": OPT_DAY_TEMP,
        "name": "Day Temp",
        "min": TEMP_MIN,
        "max": TEMP_MAX,
        "step": TEMP_STEP,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:weather-sunny",
    },
    {
        "key": OPT_NIGHT_TEMP,
        "name": "Night Temp",
        "min": TEMP_MIN,
        "max": TEMP_MAX,
        "step": TEMP_STEP,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:weather-night",
    },
    {
        "key": OPT_BED_NIGHT_TEMP,
        "name": "Bedroom Night Temp",
        "min": TEMP_MIN,
        "max": TEMP_MAX,
        "step": TEMP_STEP,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:bed",
    },
    {
        "key": OPT_TRANSITION_MIN,
        "name": "Transition Duration",
        "min": DURATION_MIN,
        "max": DURATION_MAX,
        "step": DURATION_STEP,
        "unit": UnitOfTime.MINUTES,
        "icon": "mdi:transition",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[NumberEntity] = [
        GlobalOptionNumber(entry, spec) for spec in GLOBAL_NUMBERS
    ]
    for dev in entry.options.get(OPT_DEVICES, []) or []:
        entities.append(DeviceOffsetNumber(entry, dev[DEV_ENTITY_ID]))
    async_add_entities(entities)


class _OptionNumberBase(NumberEntity):
    """Common write-through behaviour for entities backed by entry.options."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
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

    async def _async_write_option(self, key: str, value: Any) -> None:
        new_options = dict(self._entry.options)
        new_options[key] = value
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)


class GlobalOptionNumber(_OptionNumberBase):
    """A global temperature/duration value backed by entry.options[key]."""

    def __init__(self, entry: ConfigEntry, spec: dict[str, Any]) -> None:
        super().__init__(entry)
        self._key: str = spec["key"]
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_translation_key = self._key
        self._attr_name = spec["name"]
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]
        self._attr_native_unit_of_measurement = spec["unit"]
        self._attr_icon = spec["icon"]

    @property
    def native_value(self) -> float | None:
        v = self._entry.options.get(self._key)
        return None if v is None else float(v)

    async def async_set_native_value(self, value: float) -> None:
        if self._key == OPT_TRANSITION_MIN:
            value = int(round(value))
        await self._async_write_option(self._key, value)


class DeviceOffsetNumber(_OptionNumberBase):
    """Offset for a tracked climate entity, stored inside the devices list."""

    _attr_native_min_value = OFFSET_MIN
    _attr_native_max_value = OFFSET_MAX
    _attr_native_step = OFFSET_STEP
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:plus-minus-variant"

    def __init__(self, entry: ConfigEntry, target_entity_id: str) -> None:
        super().__init__(entry)
        self._target = target_entity_id
        slug = target_entity_id.replace(".", "_")
        self._attr_unique_id = f"{entry.entry_id}_offset_{slug}"
        self._attr_name = f"Offset {target_entity_id}"

    def _device(self) -> dict | None:
        for dev in self._entry.options.get(OPT_DEVICES, []) or []:
            if dev.get(DEV_ENTITY_ID) == self._target:
                return dev
        return None

    @property
    def available(self) -> bool:
        return self._device() is not None

    @property
    def native_value(self) -> float | None:
        dev = self._device()
        return None if dev is None else float(dev.get(DEV_OFFSET, 0.0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self._device() or {}
        return {
            "target_entity": self._target,
            "is_bedroom": bool(dev.get(DEV_IS_BEDROOM, False)),
        }

    async def async_set_native_value(self, value: float) -> None:
        new_options = dict(self._entry.options)
        devices = [dict(d) for d in new_options.get(OPT_DEVICES, []) or []]
        for dev in devices:
            if dev.get(DEV_ENTITY_ID) == self._target:
                dev[DEV_OFFSET] = float(value)
                break
        new_options[OPT_DEVICES] = devices
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
