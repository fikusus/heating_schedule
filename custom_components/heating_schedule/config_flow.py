"""Config and Options flow for the heating_schedule integration."""

from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import (
    BRANCH_ACTUATOR,
    BRANCH_HYSTERESIS,
    BRANCH_ID,
    BRANCH_MIN_CYCLE_S,
    BRANCH_NAME,
    BRANCH_PUMP,
    BRANCH_IS_BEDROOM,
    BRANCH_OFFSET,
    BRANCH_SENSORS,
    BRANCH_TRAVEL_S,
    DEFAULTS,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_CYCLE_S,
    DEFAULT_TRAVEL_S,
    DEV_ENTITY_ID,
    DEV_IS_BEDROOM,
    DEV_OFFSET,
    DOMAIN,
    DURATION_MAX,
    DURATION_MIN,
    DURATION_STEP,
    HYSTERESIS_MAX,
    HYSTERESIS_MIN,
    HYSTERESIS_STEP,
    MIN_CYCLE_MAX,
    MIN_CYCLE_MIN,
    MIN_CYCLE_STEP,
    OFFSET_MAX,
    OFFSET_MIN,
    OFFSET_STEP,
    OPT_BED_DAY_TO_NIGHT,
    OPT_BED_NIGHT_TEMP,
    OPT_BED_NIGHT_TO_DAY,
    OPT_BOILER_POWER_ENTITY,
    OPT_BOILER_PUMPS,
    OPT_BOILER_SWITCH_ENTITY,
    OPT_BRANCHES,
    OPT_DAY_TEMP,
    OPT_DAY_TO_NIGHT,
    OPT_DEVICES,
    OPT_NIGHT_TEMP,
    OPT_NIGHT_TO_DAY,
    OPT_TRANSITION_MIN,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
    TRAVEL_MAX,
    TRAVEL_MIN,
    TRAVEL_STEP,
)

from .summary import (
    boiler_owned_entities,
    branch_owned_entities,
    configuration_summary,
)


def _temp_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=TEMP_MIN,
            max=TEMP_MAX,
            step=TEMP_STEP,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="°C",
        )
    )


def _offset_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=OFFSET_MIN,
            max=OFFSET_MAX,
            step=OFFSET_STEP,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="°C",
        )
    )


def _duration_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=DURATION_MIN,
            max=DURATION_MAX,
            step=DURATION_STEP,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


def _hysteresis_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=HYSTERESIS_MIN,
            max=HYSTERESIS_MAX,
            step=HYSTERESIS_STEP,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="°C",
        )
    )


def _seconds_selector(minimum: int, maximum: int, step: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _branch_schema(
    current: dict[str, Any], *, with_remove: bool, with_hardware: bool
) -> vol.Schema:
    """Form for one zone. Shared by the add, add-sensor-only and edit steps."""
    fields: dict[Any, Any] = {
        vol.Required(
            BRANCH_NAME, default=current.get(BRANCH_NAME, "")
        ): TextSelector(),
        vol.Required(
            BRANCH_SENSORS, default=current.get(BRANCH_SENSORS, [])
        ): EntitySelector(
            EntitySelectorConfig(
                domain="sensor", device_class="temperature", multiple=True
            )
        ),
        vol.Required(
            BRANCH_OFFSET, default=current.get(BRANCH_OFFSET, 0.0)
        ): _offset_selector(),
        vol.Required(
            BRANCH_IS_BEDROOM, default=current.get(BRANCH_IS_BEDROOM, False)
        ): BooleanSelector(),
    }
    if with_hardware:
        fields.update(
            {
                vol.Optional(
                    BRANCH_ACTUATOR,
                    default=current.get(BRANCH_ACTUATOR) or vol.UNDEFINED,
                ): EntitySelector(EntitySelectorConfig(domain="switch")),
                vol.Optional(
                    BRANCH_PUMP, default=current.get(BRANCH_PUMP) or vol.UNDEFINED
                ): EntitySelector(EntitySelectorConfig(domain="switch")),
                vol.Required(
                    BRANCH_HYSTERESIS,
                    default=current.get(BRANCH_HYSTERESIS, DEFAULT_HYSTERESIS),
                ): _hysteresis_selector(),
                vol.Required(
                    BRANCH_TRAVEL_S,
                    default=current.get(BRANCH_TRAVEL_S, DEFAULT_TRAVEL_S),
                ): _seconds_selector(TRAVEL_MIN, TRAVEL_MAX, TRAVEL_STEP),
                vol.Required(
                    BRANCH_MIN_CYCLE_S,
                    default=current.get(BRANCH_MIN_CYCLE_S, DEFAULT_MIN_CYCLE_S),
                ): _seconds_selector(MIN_CYCLE_MIN, MIN_CYCLE_MAX, MIN_CYCLE_STEP),
            }
        )
    if with_remove:
        fields[vol.Optional("remove", default=False)] = BooleanSelector()
    return vol.Schema(fields)


def _validate_branch(
    user_input: dict[str, Any],
    draft: dict[str, Any],
    branch_id: str | None = None,
) -> dict[str, str]:
    """Reject the configurations that fail quietly or dangerously."""
    errors: dict[str, str] = {}
    if not (user_input.get(BRANCH_SENSORS) or []):
        # Without a reading the zone can never decide to heat, and would sit
        # cold forever with nothing in the log to say why.
        errors[BRANCH_SENSORS] = "no_sensors"

    actuator = user_input.get(BRANCH_ACTUATOR)
    pump = user_input.get(BRANCH_PUMP)
    if actuator and actuator == pump:
        # One switch for both would start the pump at the same instant as the
        # valve, against a valve that has not travelled yet.
        errors[BRANCH_PUMP] = "same_entity"
    if pump and not actuator:
        # The interlock gates the pump on a confirmed-open valve. With no valve
        # to confirm, the pump would simply never be allowed to run.
        errors[BRANCH_ACTUATOR] = "pump_needs_actuator"

    # A valve or pump must answer to exactly one owner. The boiler mirrors its
    # own on/off state onto its pumps and knows nothing about any actuator, so
    # a shared switch means the two controllers fight and the pump runs dry.
    taken = branch_owned_entities(draft, exclude_id=branch_id)
    taken |= boiler_owned_entities(draft)
    for key, entity_id in ((BRANCH_ACTUATOR, actuator), (BRANCH_PUMP, pump)):
        if entity_id and entity_id in taken and key not in errors:
            errors[key] = "entity_in_use"
    return errors


def _branch_from_input(
    user_input: dict[str, Any],
    branch_id: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stored zone. Hardware keys absent from the form are preserved."""
    base = dict(previous or {})
    zone = {
        BRANCH_ID: branch_id,
        BRANCH_NAME: user_input[BRANCH_NAME],
        BRANCH_SENSORS: list(user_input.get(BRANCH_SENSORS) or []),
        BRANCH_OFFSET: float(user_input.get(BRANCH_OFFSET, 0.0)),
        BRANCH_IS_BEDROOM: bool(user_input.get(BRANCH_IS_BEDROOM, False)),
        BRANCH_ACTUATOR: base.get(BRANCH_ACTUATOR),
        BRANCH_PUMP: base.get(BRANCH_PUMP),
        BRANCH_HYSTERESIS: base.get(BRANCH_HYSTERESIS, DEFAULT_HYSTERESIS),
        BRANCH_TRAVEL_S: base.get(BRANCH_TRAVEL_S, DEFAULT_TRAVEL_S),
        BRANCH_MIN_CYCLE_S: base.get(BRANCH_MIN_CYCLE_S, DEFAULT_MIN_CYCLE_S),
    }
    if BRANCH_HYSTERESIS in user_input:
        zone.update(
            {
                BRANCH_ACTUATOR: user_input.get(BRANCH_ACTUATOR) or None,
                BRANCH_PUMP: user_input.get(BRANCH_PUMP) or None,
                BRANCH_HYSTERESIS: float(user_input[BRANCH_HYSTERESIS]),
                BRANCH_TRAVEL_S: int(user_input[BRANCH_TRAVEL_S]),
                BRANCH_MIN_CYCLE_S: int(user_input[BRANCH_MIN_CYCLE_S]),
            }
        )
    return zone


class HeatingScheduleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow (singleton entry)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="Heating Schedule",
            data={},
            options=DEFAULTS.copy() | {OPT_DEVICES: []},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> "HeatingScheduleOptionsFlow":
        return HeatingScheduleOptionsFlow(entry)


class HeatingScheduleOptionsFlow(OptionsFlow):
    """Multi-step options flow for global config + device management."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._draft: dict[str, Any] = dict(entry.options or DEFAULTS)
        self._draft[OPT_DEVICES] = [
            dict(d) for d in self._draft.get(OPT_DEVICES, []) or []
        ]
        self._draft[OPT_BRANCHES] = [
            dict(b) for b in self._draft.get(OPT_BRANCHES, []) or []
        ]
        self._selected: str | None = None
        self._selected_branch: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            description_placeholders={
                "summary": configuration_summary(self._draft)
            },
            menu_options=[
                "globals",
                "add_device",
                "edit_devices",
                "boiler_settings",
                "boiler_pumps",
                "add_branch",
                "add_zone",
                "edit_branches",
            ],
        )

    # ------------------------------------------------------------ globals

    async def async_step_globals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._draft.update(user_input)
            return await self._async_save_and_finish()

        d = self._draft
        schema = vol.Schema(
            {
                vol.Required(OPT_DAY_TEMP, default=d[OPT_DAY_TEMP]): _temp_selector(),
                vol.Required(OPT_NIGHT_TEMP, default=d[OPT_NIGHT_TEMP]): _temp_selector(),
                vol.Required(
                    OPT_BED_NIGHT_TEMP, default=d[OPT_BED_NIGHT_TEMP]
                ): _temp_selector(),
                vol.Required(
                    OPT_TRANSITION_MIN, default=d[OPT_TRANSITION_MIN]
                ): _duration_selector(),
                vol.Required(
                    OPT_DAY_TO_NIGHT, default=d[OPT_DAY_TO_NIGHT]
                ): TimeSelector(),
                vol.Required(
                    OPT_NIGHT_TO_DAY, default=d[OPT_NIGHT_TO_DAY]
                ): TimeSelector(),
                vol.Required(
                    OPT_BED_DAY_TO_NIGHT, default=d[OPT_BED_DAY_TO_NIGHT]
                ): TimeSelector(),
                vol.Required(
                    OPT_BED_NIGHT_TO_DAY, default=d[OPT_BED_NIGHT_TO_DAY]
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="globals", data_schema=schema)

    # ------------------------------------------------------------ add_device

    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            entity_id = user_input[DEV_ENTITY_ID]
            existing = [
                d for d in self._draft[OPT_DEVICES] if d[DEV_ENTITY_ID] != entity_id
            ]
            existing.append(
                {
                    DEV_ENTITY_ID: entity_id,
                    DEV_OFFSET: float(user_input[DEV_OFFSET]),
                    DEV_IS_BEDROOM: bool(user_input[DEV_IS_BEDROOM]),
                }
            )
            self._draft[OPT_DEVICES] = existing
            return await self._async_save_and_finish()

        schema = vol.Schema(
            {
                vol.Required(DEV_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(domain="climate")
                ),
                vol.Required(DEV_OFFSET, default=0.0): _offset_selector(),
                vol.Required(DEV_IS_BEDROOM, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="add_device", data_schema=schema)

    # ------------------------------------------------------------ edit_devices

    async def async_step_edit_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        devices: list[dict] = self._draft.get(OPT_DEVICES, [])
        if not devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            self._selected = user_input["device"]
            return await self.async_step_edit_one()

        options = [
            {
                "value": d[DEV_ENTITY_ID],
                "label": (
                    f"{d[DEV_ENTITY_ID]} "
                    f"(offset {d.get(DEV_OFFSET, 0):+.1f}°C"
                    f"{', bedroom' if d.get(DEV_IS_BEDROOM) else ''})"
                ),
            }
            for d in devices
        ]
        schema = vol.Schema(
            {
                vol.Required("device"): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_devices", data_schema=schema)

    async def async_step_edit_one(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        target_id = self._selected
        current = next(
            (d for d in self._draft[OPT_DEVICES] if d[DEV_ENTITY_ID] == target_id),
            None,
        )
        if current is None:
            return self.async_abort(reason="device_not_found")

        if user_input is not None:
            if user_input.get("remove"):
                self._draft[OPT_DEVICES] = [
                    d
                    for d in self._draft[OPT_DEVICES]
                    if d[DEV_ENTITY_ID] != target_id
                ]
            else:
                current[DEV_OFFSET] = float(user_input[DEV_OFFSET])
                current[DEV_IS_BEDROOM] = bool(user_input[DEV_IS_BEDROOM])
            return await self._async_save_and_finish()

        schema = vol.Schema(
            {
                vol.Required(
                    DEV_OFFSET, default=current.get(DEV_OFFSET, 0.0)
                ): _offset_selector(),
                vol.Required(
                    DEV_IS_BEDROOM, default=current.get(DEV_IS_BEDROOM, False)
                ): BooleanSelector(),
                vol.Optional("remove", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_one",
            data_schema=schema,
            description_placeholders={"entity_id": target_id},
        )

    # ------------------------------------------------------------ boiler

    async def async_step_boiler_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            switch_entity = user_input.get(OPT_BOILER_SWITCH_ENTITY) or None
            if switch_entity and switch_entity in branch_owned_entities(self._draft):
                errors[OPT_BOILER_SWITCH_ENTITY] = "entity_in_use"
            else:
                self._draft[OPT_BOILER_POWER_ENTITY] = (
                    user_input.get(OPT_BOILER_POWER_ENTITY) or None
                )
                self._draft[OPT_BOILER_SWITCH_ENTITY] = switch_entity
                return await self._async_save_and_finish()

        d = user_input if user_input is not None else self._draft
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_BOILER_POWER_ENTITY,
                    default=d.get(OPT_BOILER_POWER_ENTITY) or vol.UNDEFINED,
                ): EntitySelector(EntitySelectorConfig(domain="number")),
                vol.Optional(
                    OPT_BOILER_SWITCH_ENTITY,
                    default=d.get(OPT_BOILER_SWITCH_ENTITY) or vol.UNDEFINED,
                ): EntitySelector(EntitySelectorConfig(domain="switch")),
            }
        )
        return self.async_show_form(
            step_id="boiler_settings", data_schema=schema, errors=errors
        )

    async def async_step_boiler_pumps(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            pumps = list(user_input.get(OPT_BOILER_PUMPS) or [])
            if set(pumps) & branch_owned_entities(self._draft):
                errors[OPT_BOILER_PUMPS] = "entity_in_use"
            else:
                self._draft[OPT_BOILER_PUMPS] = pumps
                return await self._async_save_and_finish()

        d = user_input if user_input is not None else self._draft
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_BOILER_PUMPS,
                    default=d.get(OPT_BOILER_PUMPS) or [],
                ): EntitySelector(
                    EntitySelectorConfig(domain="switch", multiple=True)
                ),
            }
        )
        return self.async_show_form(
            step_id="boiler_pumps", data_schema=schema, errors=errors
        )

    # ------------------------------------------------------------ branches

    async def async_step_add_branch(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_add_zone("add_branch", user_input, hardware=True)

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A zone with sensors but no hardware: it only feeds boiler demand."""
        return await self._async_add_zone("add_zone", user_input, hardware=False)

    async def _async_add_zone(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        *,
        hardware: bool,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_branch(user_input, self._draft)
            if not errors:
                zone = _branch_from_input(user_input, uuid.uuid4().hex[:8])
                self._draft[OPT_BRANCHES].append(zone)
                return await self._async_save_and_finish()

        return self.async_show_form(
            step_id=step_id,
            data_schema=_branch_schema(
                user_input or {}, with_remove=False, with_hardware=hardware
            ),
            errors=errors,
        )

    async def async_step_edit_branches(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        branches: list[dict] = self._draft.get(OPT_BRANCHES, [])
        if not branches:
            return self.async_abort(reason="no_branches")

        if user_input is not None:
            self._selected_branch = user_input["branch"]
            return await self.async_step_edit_branch()

        options = [
            {
                "value": b[BRANCH_ID],
                "label": f"{b.get(BRANCH_NAME) or b[BRANCH_ID]}"
                + (
                    f" ({b[BRANCH_ACTUATOR]} + {b[BRANCH_PUMP]})"
                    if b.get(BRANCH_ACTUATOR) and b.get(BRANCH_PUMP)
                    else " (sensors only)"
                ),
            }
            for b in branches
        ]
        schema = vol.Schema(
            {
                vol.Required("branch"): SelectSelector(
                    SelectSelectorConfig(
                        options=options, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_branches", data_schema=schema)

    async def async_step_edit_branch(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        target_id = self._selected_branch
        current = next(
            (b for b in self._draft[OPT_BRANCHES] if b[BRANCH_ID] == target_id),
            None,
        )
        if current is None:
            return self.async_abort(reason="branch_not_found")

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("remove"):
                self._draft[OPT_BRANCHES] = [
                    b for b in self._draft[OPT_BRANCHES] if b[BRANCH_ID] != target_id
                ]
                return await self._async_save_and_finish()
            errors = _validate_branch(user_input, self._draft, target_id)
            if not errors:
                updated = _branch_from_input(user_input, target_id, current)
                self._draft[OPT_BRANCHES] = [
                    updated if b[BRANCH_ID] == target_id else b
                    for b in self._draft[OPT_BRANCHES]
                ]
                return await self._async_save_and_finish()

        return self.async_show_form(
            step_id="edit_branch",
            data_schema=_branch_schema(
                user_input or current, with_remove=True, with_hardware=True
            ),
            description_placeholders={"name": current.get(BRANCH_NAME) or target_id},
            errors=errors,
        )

    # ------------------------------------------------------------ commit

    async def _async_save_and_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=self._draft)
