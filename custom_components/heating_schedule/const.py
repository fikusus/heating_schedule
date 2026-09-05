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
OPT_BRANCHES = "branches"

OPT_BOILER_ROOMS = "boiler_rooms"
OPT_BOILER_POWER_ENTITY = "boiler_power_entity"
OPT_BOILER_SWITCH_ENTITY = "boiler_switch_entity"
OPT_BOILER_PUMPS = "boiler_pumps"
OPT_BOILER_ENABLED = "boiler_enabled"
OPT_BOILER_SUMMER = "boiler_summer_mode"
OPT_BOILER_KEEP_ON = "boiler_keep_on"

DEV_ENTITY_ID = "entity_id"
DEV_OFFSET = "offset"
DEV_IS_BEDROOM = "is_bedroom"

ROOM_SENSOR = "sensor"
ROOM_IS_BEDROOM = "is_bedroom"

# A branch is a heating loop with its own valve and pump, presented to the rest
# of Home Assistant as a climate entity.
BRANCH_ID = "id"
BRANCH_NAME = "name"
BRANCH_SENSORS = "sensors"
BRANCH_OFFSET = "offset"
BRANCH_IS_BEDROOM = "is_bedroom"
BRANCH_ACTUATOR = "actuator"
BRANCH_PUMP = "pump"
BRANCH_HYSTERESIS = "hysteresis"
BRANCH_TRAVEL_S = "actuator_travel_s"
BRANCH_MIN_CYCLE_S = "min_cycle_s"

# hass.data key suffix holding the per-branch controllers.
DATA_BRANCHES = "branches"

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
    OPT_BRANCHES: [],
    OPT_BOILER_POWER_ENTITY: None,
    OPT_BOILER_SWITCH_ENTITY: None,
    OPT_BOILER_PUMPS: [],
    OPT_BOILER_ENABLED: False,
    OPT_BOILER_SUMMER: False,
    OPT_BOILER_KEEP_ON: False,
}

PLATFORMS = ["number", "time", "sensor", "switch", "climate"]

HYSTERESIS_MIN = 0.2
HYSTERESIS_MAX = 5.0
HYSTERESIS_STEP = 0.1
DEFAULT_HYSTERESIS = 0.5

# Thermoelectric actuators need minutes to travel; motorised ones seconds.
TRAVEL_MIN = 0
TRAVEL_MAX = 600
TRAVEL_STEP = 10
DEFAULT_TRAVEL_S = 180

# Guards the pump against short cycling. It only ever delays a start, never a
# stop -- a stop is a safety action and must not wait for anything.
MIN_CYCLE_MIN = 0
MIN_CYCLE_MAX = 3600
MIN_CYCLE_STEP = 30
DEFAULT_MIN_CYCLE_S = 300

# The interlock is re-asserted on this interval regardless of events, so a
# missed state update cannot leave the pump running against a closed valve.
WATCHDOG_INTERVAL_S = 60

BOILER_POWER_MIN = 1
BOILER_POWER_MAX = 100

DEVICE_NAME = "Heating Schedule"
DEVICE_MANUFACTURER = "heating_schedule"
DEVICE_MODEL = "Schedule Controller"
