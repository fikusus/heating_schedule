"""Sensor platform for heating_schedule: phase + effective target sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    PHASE_DAY,
    PHASE_NIGHT,
    PHASE_TRANSITION_TO_DAY,
    PHASE_TRANSITION_TO_NIGHT,
)
from .coordinator import HeatingScheduleCoordinator

PHASE_OPTIONS = [
    PHASE_DAY,
    PHASE_TRANSITION_TO_NIGHT,
    PHASE_NIGHT,
    PHASE_TRANSITION_TO_DAY,
]


SENSOR_SPECS: list[dict[str, Any]] = [
    {
        "key": "current_main_phase",
        "name": "Main Phase",
        "icon": "mdi:home-thermometer",
        "data_path": ("main_phase",),
        "kind": "phase",
    },
    {
        "key": "current_bedroom_phase",
        "name": "Bedroom Phase",
        "icon": "mdi:bed-clock",
        "data_path": ("bed_phase",),
        "kind": "phase",
    },
    {
        "key": "current_main_target",
        "name": "Main Target",
        "icon": "mdi:thermometer",
        "data_path": ("main_target",),
        "kind": "temperature",
    },
    {
        "key": "current_bedroom_target",
        "name": "Bedroom Target",
        "icon": "mdi:thermometer",
        "data_path": ("bed_target",),
        "kind": "temperature",
    },
    {
        "key": "boiler_max_diff",
        "name": "Boiler Max Diff",
        "icon": "mdi:thermometer-alert",
        "data_path": ("boiler", "max_diff"),
        "kind": "temperature",
    },
    {
        "key": "boiler_power_target",
        "name": "Boiler Power Target",
        "icon": "mdi:fire",
        "data_path": ("boiler", "power"),
        "kind": "power",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeatingScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [HeatingScheduleSensor(coordinator, entry, spec) for spec in SENSOR_SPECS]
    )


class HeatingScheduleSensor(
    CoordinatorEntity[HeatingScheduleCoordinator], SensorEntity
):
    """Sensor reading derived state from the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HeatingScheduleCoordinator,
        entry: ConfigEntry,
        spec: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._spec = spec
        self._attr_unique_id = f"{entry.entry_id}_{spec['key']}"
        self._attr_translation_key = spec["key"]
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

        if spec["kind"] == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif spec["kind"] == "power":
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "%"
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = PHASE_OPTIONS

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        for key in self._spec["data_path"]:
            if not isinstance(data, dict):
                return None
            data = data.get(key)
            if data is None:
                return None
        return data
