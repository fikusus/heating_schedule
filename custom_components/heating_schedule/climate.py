"""Climate platform: every zone is presented as a thermostat.

A zone is a room or loop with its own temperature sensors, an offset and a
bedroom flag. Some also own a valve actuator and a circulation pump; those are
the heating branches, and their hardware is driven by BranchController, which
holds the interlock keeping the pump off while the valve is shut. A zone with no
hardware controls nothing and exists to contribute an honest ambient reading,
with its offset applied, to the boiler's demand calculation -- useful wherever a
thermostatic head measures the air by the radiator, or reports no temperature at
all.

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
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .branch import BranchController, read_min_temperature
from .const import (
    BRANCH_ACTUATOR,
    BRANCH_HYSTERESIS,
    BRANCH_ID,
    BRANCH_IS_BEDROOM,
    BRANCH_NAME,
    BRANCH_OFFSET,
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
from .coordinator import HeatingScheduleCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeatingScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]
    controllers: dict[str, BranchController] = hass.data[DOMAIN][
        f"{entry.entry_id}_{DATA_BRANCHES}"
    ]
    async_add_entities(
        HeatingZoneClimate(
            coordinator, entry, branch, controllers.get(branch[BRANCH_ID])
        )
        for branch in entry.options.get(OPT_BRANCHES, []) or []
        if branch.get(BRANCH_ID)
    )


class HeatingZoneClimate(
    CoordinatorEntity[HeatingScheduleCoordinator], ClimateEntity, RestoreEntity
):
    """A zone, behaving like a thermostatic head."""

    _attr_has_entity_name = True
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
        coordinator: HeatingScheduleCoordinator,
        entry: ConfigEntry,
        branch: dict[str, Any],
        controller: BranchController | None,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._branch_id: str = branch[BRANCH_ID]
        self._controller = controller
        self._demand = False
        self._attr_unique_id = f"{entry.entry_id}_branch_{self._branch_id}"
        self._attr_name = branch.get(BRANCH_NAME) or "Zone"
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

        # Only the mode is restored. The setpoint comes from the schedule on
        # every coordinator pass, so remembering one would just be overwritten.
        last = await self.async_get_last_state()
        if last is not None and last.state in (HVACMode.HEAT, HVACMode.OFF):
            self._attr_hvac_mode = HVACMode(last.state)

        if self._controller is not None:
            self.async_on_remove(
                self._controller.add_listener(self._async_branch_changed)
            )
        self._pull_target()
        await self._async_control()

    @callback
    def _handle_coordinator_update(self) -> None:
        """New schedule pass: adopt the target and re-decide."""
        self._pull_target()
        self.hass.async_create_task(self._async_control_and_write())

    def _pull_target(self) -> None:
        targets = (self.coordinator.data or {}).get("zone_targets") or {}
        target = targets.get(self._branch_id)
        if target is not None:
            self._attr_target_temperature = float(target)

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
            "offset": cfg.get(BRANCH_OFFSET, 0.0),
            "is_bedroom": bool(cfg.get(BRANCH_IS_BEDROOM, False)),
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
        """Override the setpoint until the next schedule pass overwrites it."""
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
    def _async_branch_changed(self) -> None:
        """The controller moved the valve or the pump; hvac_action changed."""
        self.async_write_ha_state()
