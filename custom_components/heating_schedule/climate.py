"""Climate platform: each heating branch is presented as a thermostat.

This is the policy half of a branch. It reads the sensors, holds the setpoint,
applies hysteresis and asks BranchController to heat or stop. It never touches
the valve or the pump itself -- the interlock that keeps those two safe lives
below this layer and can veto anything asked here.

Presenting a branch as a climate entity is what lets the schedule drive it: the
coordinator already knows how to push a target into a climate entity, so a
branch added to the tracked devices needs no special handling at all.
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

from .branch import BranchController
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

_UNUSABLE = ("unavailable", "unknown")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controllers: dict[str, BranchController] = hass.data[DOMAIN][
        f"{entry.entry_id}_{DATA_BRANCHES}"
    ]
    entities = [
        HeatingBranchClimate(entry, branch, controllers[branch[BRANCH_ID]])
        for branch in entry.options.get(OPT_BRANCHES, []) or []
        if branch.get(BRANCH_ID) in controllers
    ]
    async_add_entities(entities)


class HeatingBranchClimate(ClimateEntity, RestoreEntity):
    """A heating branch, behaving like a thermostatic head."""

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
    _attr_icon = "mdi:pipe-valve"
    # HA 2024.x shim: we implement turn_on/turn_off ourselves.
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        entry: ConfigEntry,
        branch: dict[str, Any],
        controller: BranchController,
    ) -> None:
        self._entry = entry
        self._branch_id: str = branch[BRANCH_ID]
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_branch_{self._branch_id}"
        self._attr_name = branch.get(BRANCH_NAME) or "Branch"
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

        # Restoring the setpoint matters beyond convenience: the coordinator
        # runs its first pass before the platforms are up, so a fresh branch
        # would otherwise sit without a target until the next phase boundary.
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

        sensors = self._config().get(BRANCH_SENSORS) or []
        if sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, list(sensors), self._async_sensor_changed
                )
            )
        self.async_on_remove(self._controller.add_listener(self._async_branch_changed))
        self.async_on_remove(
            self._entry.add_update_listener(self._async_options_changed)
        )
        await self._async_control()

    # ---------------------------------------------------------------- config

    def _config(self) -> dict[str, Any]:
        for branch in self._entry.options.get(OPT_BRANCHES, []) or []:
            if branch.get(BRANCH_ID) == self._branch_id:
                return branch
        return {}

    # ------------------------------------------------------------- readbacks

    @property
    def available(self) -> bool:
        return bool(self._config())

    @property
    def current_temperature(self) -> float | None:
        """The coldest readable sensor on the branch governs, as for the boiler."""
        temps = self._sensor_readings()
        return min(temps.values()) if temps else None

    @property
    def hvac_action(self) -> HVACAction:
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._controller.is_heating:
            return HVACAction.HEATING
        if self._controller.is_opening:
            # Heat is wanted but the pump is still held back, either waiting on
            # the actuator or on the anti-short-cycle delay. Say so rather than
            # showing an idle branch that is plainly doing something.
            return HVACAction.PREHEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        cfg = self._config()
        return {
            "sensors": self._sensor_readings(),
            "actuator": cfg.get(BRANCH_ACTUATOR),
            "pump": cfg.get(BRANCH_PUMP),
            "hysteresis": self._hysteresis(),
            "demand": self._controller.demand,
            "summer_mode": self._summer_mode(),
        }

    def _sensor_readings(self) -> dict[str, float]:
        readings: dict[str, float] = {}
        for entity_id in self._config().get(BRANCH_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in _UNUSABLE:
                continue
            try:
                readings[entity_id] = float(state.state)
            except (TypeError, ValueError):
                continue
        return readings

    def _summer_mode(self) -> bool:
        return bool((self._entry.options or {}).get(OPT_BOILER_SUMMER, False))

    def _hysteresis(self) -> float:
        try:
            return float(self._config().get(BRANCH_HYSTERESIS, DEFAULT_HYSTERESIS))
        except (TypeError, ValueError):
            return DEFAULT_HYSTERESIS

    # -------------------------------------------------------------- commands

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._attr_target_temperature = float(temperature)
        await self._async_control()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self._attr_hvac_modes:
            return
        self._attr_hvac_mode = hvac_mode
        await self._async_control()
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    # --------------------------------------------------------------- control

    async def _async_control(self) -> None:
        """Decide whether the branch should be heating, and tell the controller."""
        if self._attr_hvac_mode == HVACMode.OFF or self._summer_mode():
            # Summer mode pushes every tracked climate entity to its max_temp
            # so valves open. Taken literally that would run the pump all
            # summer, so a branch stops instead.
            await self._controller.async_set_demand(False)
            return

        current = self.current_temperature
        target = self._attr_target_temperature
        if current is None or target is None:
            # No readable sensor, or no setpoint yet. Do not guess with a pump.
            await self._controller.async_set_demand(False)
            return

        half = self._hysteresis() / 2
        diff = target - current
        if diff >= half:
            demand = True
        elif diff <= -half:
            demand = False
        else:
            # Inside the deadband: hold whatever was decided last.
            demand = self._controller.demand

        await self._controller.async_set_demand(demand)

    @callback
    def _async_sensor_changed(self, _event) -> None:
        self.hass.async_create_task(self._async_control_and_write())

    async def _async_control_and_write(self) -> None:
        await self._async_control()
        self.async_write_ha_state()

    @callback
    def _async_branch_changed(self) -> None:
        """The controller moved the valve or the pump; hvac_action changed."""
        self.async_write_ha_state()

    async def _async_options_changed(self, _hass, _entry) -> None:
        self._controller.update_config(self._config())
        await self._async_control_and_write()
