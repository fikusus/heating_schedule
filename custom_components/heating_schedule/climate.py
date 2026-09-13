"""Climate platform: every zone is presented as a thermostat.

A zone is a room or loop with its own temperature sensors. Some also own a valve
actuator and a circulation pump; those are the heating branches, and their
hardware is driven by BranchController, which holds the interlock keeping the
pump off while the valve is shut. A zone with no hardware controls nothing and
exists to report an ambient temperature -- useful wherever a thermostatic head
measures the air by the radiator, or reports none at all.

Being a climate entity is the whole point: a zone is added to the tracked
devices like any thermostatic head, and from there the schedule sets its target
and its offset exactly as it does for the rest. There is no second, private
channel -- an earlier version had one, and its target quietly overwrote the one
the schedule had just set, which looked like the device offset being ignored.

Policy lives here: sensors, setpoint, hysteresis, hvac_mode. It asks the
controller to heat or stop, and the controller may refuse.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .branch import BranchController, read_min_temperature
from .const import (
    BRANCH_ACTUATOR,
    BRANCH_HYSTERESIS,
    BRANCH_ID,
    BRANCH_NAME,
    BRANCH_PUMP,
    BRANCH_SENSORS,
    DATA_BRANCHES,
    DEFAULT_HYSTERESIS,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
    OPT_BOILER_SUMMER,
    OPT_BRANCHES,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controllers: dict[str, BranchController] = hass.data[DOMAIN][
        f"{entry.entry_id}_{DATA_BRANCHES}"
    ]
    async_add_entities(
        HeatingZoneClimate(entry, zone, controllers.get(zone[BRANCH_ID]))
        for zone in entry.options.get(OPT_BRANCHES, []) or []
        if zone.get(BRANCH_ID)
    )


class HeatingZoneClimate(ClimateEntity, RestoreEntity):
    """A zone, behaving like a thermostatic head."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = TEMP_MIN
    _attr_max_temp = TEMP_MAX
    _attr_target_temperature_step = TEMP_STEP
    # HA 2024.x shim: we implement turn_on/turn_off ourselves.
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        entry: ConfigEntry,
        zone: dict[str, Any],
        controller: BranchController | None,
    ) -> None:
        self._entry = entry
        self._branch_id: str = zone[BRANCH_ID]
        self._controller = controller
        self._demand = False
        self._unsub_sensors = None
        self._attr_unique_id = f"{entry.entry_id}_branch_{self._branch_id}"
        self._attr_name = zone.get(BRANCH_NAME) or "Zone"
        self._attr_icon = "mdi:pipe-valve" if controller else "mdi:home-thermometer"
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_target_temperature: float | None = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

    # ------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Restoring both matters: until the zone is added to the tracked devices
        # nothing sets its target, and a blank setpoint would mean it can never
        # decide to heat.
        last = await self.async_get_last_state()
        if last is not None:
            if last.state in (HVACMode.HEAT, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last.state)
            restored = last.attributes.get(ATTR_TEMPERATURE)
            if restored is not None:
                try:
                    self._attr_target_temperature = float(restored)
                except (TypeError, ValueError):
                    pass

        self._subscribe_sensors()
        if self._controller is not None:
            self.async_on_remove(
                self._controller.add_listener(self._async_branch_changed)
            )
        self.async_on_remove(
            self._entry.add_update_listener(self._async_options_changed)
        )
        await self._async_control()

    def _subscribe_sensors(self) -> None:
        if self._unsub_sensors is not None:
            self._unsub_sensors()
            self._unsub_sensors = None
        sensors = [s for s in self._config().get(BRANCH_SENSORS) or [] if s]
        if not sensors:
            return
        self._unsub_sensors = async_track_state_change_event(
            self.hass, sensors, self._async_sensor_changed
        )
        self.async_on_remove(self._unsub_sensors)

    # ---------------------------------------------------------------- config

    def _config(self) -> dict[str, Any]:
        for zone in self._entry.options.get(OPT_BRANCHES, []) or []:
            if zone.get(BRANCH_ID) == self._branch_id:
                return zone
        return {}

    # ------------------------------------------------------------- readbacks

    @property
    def available(self) -> bool:
        return bool(self._config())

    @property
    def current_temperature(self) -> float | None:
        return read_min_temperature(self.hass, self._config().get(BRANCH_SENSORS))

    @property
    def hvac_action(self) -> HVACAction:
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._controller is None:
            # Nothing to drive. The zone still calls for heat, and that call is
            # what reaches the boiler, so report it rather than a flat idle.
            return HVACAction.HEATING if self._demand else HVACAction.IDLE
        if self._controller.is_heating:
            return HVACAction.HEATING
        if self._controller.is_opening:
            # Heat is wanted but the pump is still held back, waiting on either
            # the actuator or the anti-short-cycle delay.
            return HVACAction.PREHEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self._config()
        return {
            "sensors": cfg.get(BRANCH_SENSORS) or [],
            "actuator": cfg.get(BRANCH_ACTUATOR),
            "pump": cfg.get(BRANCH_PUMP),
            "hysteresis": self._hysteresis(),
            "demand": self._demand,
            "summer_mode": self._summer_mode(),
        }

    def _summer_mode(self) -> bool:
        return bool((self._entry.options or {}).get(OPT_BOILER_SUMMER, False))

    def _hysteresis(self) -> float:
        try:
            return float(self._config().get(BRANCH_HYSTERESIS, DEFAULT_HYSTERESIS))
        except (TypeError, ValueError):
            return DEFAULT_HYSTERESIS

    # -------------------------------------------------------------- commands

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the setpoint. This is how the schedule reaches a zone."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._attr_target_temperature = float(temperature)
        await self._async_control_and_write()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self._attr_hvac_modes:
            return
        self._attr_hvac_mode = hvac_mode
        await self._async_control_and_write()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    # --------------------------------------------------------------- control

    async def _async_control(self) -> None:
        """Decide whether the zone is calling for heat, and act on it."""
        if self._attr_hvac_mode == HVACMode.OFF or self._summer_mode():
            # Summer mode pushes tracked climate devices to their max_temp so
            # valves open. Taken literally that would run a branch pump all
            # summer, so a zone stops instead.
            self._demand = False
        else:
            current = self.current_temperature
            target = self._attr_target_temperature
            if current is None or target is None:
                # No readable sensor, or no setpoint yet. Do not guess.
                self._demand = False
            else:
                half = self._hysteresis() / 2
                diff = target - current
                if diff >= half:
                    self._demand = True
                elif diff <= -half:
                    self._demand = False
                # Inside the deadband the previous decision stands.

        if self._controller is not None:
            await self._controller.async_set_demand(self._demand)

    async def _async_control_and_write(self) -> None:
        await self._async_control()
        self.async_write_ha_state()

    @callback
    def _async_sensor_changed(self, _event) -> None:
        self.hass.async_create_task(self._async_control_and_write())

    @callback
    def _async_branch_changed(self) -> None:
        """The controller moved the valve or the pump; hvac_action changed."""
        self.async_write_ha_state()

    async def _async_options_changed(self, _hass, _entry) -> None:
        if self._controller is not None:
            self._controller.update_config(self._config())
        await self._async_control_and_write()
