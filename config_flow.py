"""Config and Options flow for the heating_schedule integration."""

from __future__ import annotations

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
    TimeSelector,
)

from .const import (
    DEFAULTS,
    DEV_ENTITY_ID,
    DEV_IS_BEDROOM,
    DEV_OFFSET,
    DOMAIN,
    DURATION_MAX,
    DURATION_MIN,
    DURATION_STEP,
    OFFSET_MAX,
    OFFSET_MIN,
    OFFSET_STEP,
    OPT_BED_DAY_TO_NIGHT,
    OPT_BED_NIGHT_TEMP,
    OPT_BED_NIGHT_TO_DAY,
    OPT_BOILER_POWER_ENTITY,
    OPT_BOILER_ROOMS,
    OPT_BOILER_SWITCH_ENTITY,
    OPT_DAY_TEMP,
    OPT_DAY_TO_NIGHT,
    OPT_DEVICES,
    OPT_NIGHT_TEMP,
    OPT_NIGHT_TO_DAY,
    OPT_TRANSITION_MIN,
    ROOM_IS_BEDROOM,
    ROOM_SENSOR,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
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
        self._draft[OPT_BOILER_ROOMS] = [
            dict(r) for r in self._draft.get(OPT_BOILER_ROOMS, []) or []
        ]
        self._selected: str | None = None
        self._selected_room: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "globals",
                "add_device",
                "edit_devices",
                "boiler_settings",
                "add_boiler_room",
                "edit_boiler_rooms",
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
        if user_input is not None:
            self._draft[OPT_BOILER_POWER_ENTITY] = (
                user_input.get(OPT_BOILER_POWER_ENTITY) or None
            )
            self._draft[OPT_BOILER_SWITCH_ENTITY] = (
                user_input.get(OPT_BOILER_SWITCH_ENTITY) or None
            )
            return await self._async_save_and_finish()

        d = self._draft
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
        return self.async_show_form(step_id="boiler_settings", data_schema=schema)

    async def async_step_add_boiler_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            sensor_id = user_input[ROOM_SENSOR]
            existing = [
                r
                for r in self._draft[OPT_BOILER_ROOMS]
                if r.get(ROOM_SENSOR) != sensor_id
            ]
            existing.append(
                {
                    ROOM_SENSOR: sensor_id,
                    ROOM_IS_BEDROOM: bool(user_input.get(ROOM_IS_BEDROOM, False)),
                }
            )
            self._draft[OPT_BOILER_ROOMS] = existing
            return await self._async_save_and_finish()

        schema = vol.Schema(
            {
                vol.Required(ROOM_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(ROOM_IS_BEDROOM, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="add_boiler_room", data_schema=schema)

    async def async_step_edit_boiler_rooms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        rooms: list[dict] = self._draft.get(OPT_BOILER_ROOMS, [])
        if not rooms:
            return self.async_abort(reason="no_rooms")

        if user_input is not None:
            self._selected_room = user_input["room"]
            return await self.async_step_edit_boiler_room()

        options = [
            {
                "value": r[ROOM_SENSOR],
                "label": (
                    f"{r[ROOM_SENSOR]}"
                    f"{' (bedroom)' if r.get(ROOM_IS_BEDROOM) else ''}"
                ),
            }
            for r in rooms
        ]
        schema = vol.Schema(
            {
                vol.Required("room"): SelectSelector(
                    SelectSelectorConfig(
                        options=options, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_boiler_rooms", data_schema=schema)

    async def async_step_edit_boiler_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        target_id = self._selected_room
        current = next(
            (
                r
                for r in self._draft[OPT_BOILER_ROOMS]
                if r[ROOM_SENSOR] == target_id
            ),
            None,
        )
        if current is None:
            return self.async_abort(reason="room_not_found")

        if user_input is not None:
            if user_input.get("remove"):
                self._draft[OPT_BOILER_ROOMS] = [
                    r
                    for r in self._draft[OPT_BOILER_ROOMS]
                    if r[ROOM_SENSOR] != target_id
                ]
            else:
                current[ROOM_IS_BEDROOM] = bool(user_input[ROOM_IS_BEDROOM])
            return await self._async_save_and_finish()

        schema = vol.Schema(
            {
                vol.Required(
                    ROOM_IS_BEDROOM,
                    default=current.get(ROOM_IS_BEDROOM, False),
                ): BooleanSelector(),
                vol.Optional("remove", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="edit_boiler_room",
            data_schema=schema,
            description_placeholders={"sensor": target_id},
        )

    # ------------------------------------------------------------ commit

    async def _async_save_and_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=self._draft)
