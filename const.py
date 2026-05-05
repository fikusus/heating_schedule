"""Constants for the heating_schedule integration."""

from __future__ import annotations

DOMAIN = "heating_schedule"

OPT_DAY_TEMP = "day_temp"
OPT_NIGHT_TEMP = "night_temp"
OPT_BED_NIGHT_TEMP = "bedroom_night_temp"
OPT_TRANSITION_MIN = "transition_duration_min"
OPT_DAY_TO_NIGHT = "day_to_night_time"
OPT_NIGHT_TO_DAY = "night_to_day_time"
OPT_BED_DAY_TO_NIGHT = "bedroom_day_to_night_time"
OPT_BED_NIGHT_TO_DAY = "bedroom_night_to_day_time"
OPT_DEVICES = "devices"

OPT_BOILER_ROOMS = "boiler_rooms"
OPT_BOILER_POWER_ENTITY = "boiler_power_entity"
OPT_BOILER_SWITCH_ENTITY = "boiler_switch_entity"
OPT_BOILER_ENABLED = "boiler_enabled"
OPT_BOILER_SUMMER = "boiler_summer_mode"

DEV_ENTITY_ID = "entity_id"
DEV_OFFSET = "offset"
DEV_IS_BEDROOM = "is_bedroom"

ROOM_SENSOR = "sensor"
ROOM_IS_BEDROOM = "is_bedroom"

PHASE_DAY = "day"
PHASE_TRANSITION_TO_NIGHT = "transition_to_night"
PHASE_NIGHT = "night"
PHASE_TRANSITION_TO_DAY = "transition_to_day"

TEMP_MIN = 10.0
TEMP_MAX = 30.0
TEMP_STEP = 0.5

OFFSET_MIN = -5.0
OFFSET_MAX = 5.0
OFFSET_STEP = 0.5

DURATION_MIN = 0
DURATION_MAX = 120
DURATION_STEP = 5

DEFAULTS: dict = {
    OPT_DAY_TEMP: 21.0,
    OPT_NIGHT_TEMP: 18.0,
    OPT_BED_NIGHT_TEMP: 19.0,
    OPT_TRANSITION_MIN: 30,
    OPT_DAY_TO_NIGHT: "22:00:00",
    OPT_NIGHT_TO_DAY: "07:00:00",
    OPT_BED_DAY_TO_NIGHT: "21:30:00",
    OPT_BED_NIGHT_TO_DAY: "07:00:00",
    OPT_DEVICES: [],
    OPT_BOILER_ROOMS: [],
    OPT_BOILER_POWER_ENTITY: None,
    OPT_BOILER_SWITCH_ENTITY: None,
    OPT_BOILER_ENABLED: False,
    OPT_BOILER_SUMMER: False,
}

PLATFORMS = ["number", "time", "sensor", "switch"]

BOILER_POWER_MIN = 1
BOILER_POWER_MAX = 100

CARD_VERSION = "0.2.0"
CARD_URL_PATH = "/heating_schedule_static/heating-schedule-card.js"
CARD_URL_VERSIONED = f"{CARD_URL_PATH}?v={CARD_VERSION}"

DEVICE_NAME = "Heating Schedule"
DEVICE_MANUFACTURER = "heating_schedule"
DEVICE_MODEL = "Schedule Controller"
