"""A readable dump of the current configuration, shown in the options menu.

Everything the integration was told to do ends up spread across seven menu
steps, and checking one value means walking into the step that owns it. This
renders the lot as markdown so the menu itself answers the question.

Two-column tables throughout: the options dialog is narrow, and a wide table
wraps into porridge.
"""

from __future__ import annotations

from typing import Any

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
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_CYCLE_S,
    DEFAULT_TRAVEL_S,
    DEFAULTS,
    DEV_ENTITY_ID,
    DEV_IS_BEDROOM,
    DEV_OFFSET,
    OPT_BED_DAY_TO_NIGHT,
    OPT_BED_NIGHT_TEMP,
    OPT_BED_NIGHT_TO_DAY,
    OPT_BOILER_ENABLED,
    OPT_BOILER_KEEP_ON,
    OPT_BOILER_POWER_ENTITY,
    OPT_BOILER_PUMPS,
    OPT_BOILER_SUMMER,
    OPT_BOILER_SWITCH_ENTITY,
    OPT_BRANCHES,
    OPT_DAY_TEMP,
    OPT_DAY_TO_NIGHT,
    OPT_DEVICES,
    OPT_NIGHT_TEMP,
    OPT_NIGHT_TO_DAY,
    OPT_TRANSITION_MIN,
)

_DASH = "—"
_TABLE_HEAD = ["| | |", "|---|---|"]


# --------------------------------------------------------------- ownership


def branch_owned_entities(
    options: dict[str, Any], exclude_id: str | None = None
) -> set[str]:
    """Actuators and pumps claimed by a branch."""
    owned: set[str] = set()
    for branch in options.get(OPT_BRANCHES, []) or []:
        if exclude_id is not None and branch.get(BRANCH_ID) == exclude_id:
            continue
        for key in (BRANCH_ACTUATOR, BRANCH_PUMP):
            if branch.get(key):
                owned.add(branch[key])
    return owned


def boiler_owned_entities(options: dict[str, Any]) -> set[str]:
    """Switches the boiler drives directly."""
    owned = {e for e in options.get(OPT_BOILER_PUMPS, []) or [] if e}
    if options.get(OPT_BOILER_SWITCH_ENTITY):
        owned.add(options[OPT_BOILER_SWITCH_ENTITY])
    return owned


# ------------------------------------------------------------- formatting


def _entity(entity_id: str | None) -> str:
    return f"`{entity_id}`" if entity_id else _DASH


def _entities(entity_ids: list[str] | None) -> str:
    items = [e for e in entity_ids or [] if e]
    return ", ".join(f"`{e}`" for e in items) if items else _DASH


def _temp(value: Any) -> str:
    try:
        return f"{float(value):.1f} °C"
    except (TypeError, ValueError):
        return _DASH


def _clock(value: Any) -> str:
    parts = str(value or "").split(":")
    return ":".join(parts[:2]) if len(parts) >= 2 else _DASH


def _onoff(value: Any) -> str:
    return "on" if value else "off"


def _row(label: str, value: str) -> str:
    return f"| {label} | {value} |"


# ---------------------------------------------------------------- sections


def _schedule_section(opts: dict[str, Any]) -> list[str]:
    return [
        "**Schedule**",
        "",
        *_TABLE_HEAD,
        _row("Day", _temp(opts.get(OPT_DAY_TEMP))),
        _row("Night", _temp(opts.get(OPT_NIGHT_TEMP))),
        _row("Bedroom night", _temp(opts.get(OPT_BED_NIGHT_TEMP))),
        _row("Transition", f"{int(opts.get(OPT_TRANSITION_MIN, 0))} min"),
        _row(
            "Day → Night",
            f"{_clock(opts.get(OPT_DAY_TO_NIGHT))} "
            f"(bedroom {_clock(opts.get(OPT_BED_DAY_TO_NIGHT))})",
        ),
        _row(
            "Night → Day",
            f"{_clock(opts.get(OPT_NIGHT_TO_DAY))} "
            f"(bedroom {_clock(opts.get(OPT_BED_NIGHT_TO_DAY))})",
        ),
        "",
    ]


def _devices_section(opts: dict[str, Any]) -> list[str]:
    devices = opts.get(OPT_DEVICES, []) or []
    if not devices:
        return ["**Devices** — none", ""]

    lines = [f"**Devices** — {len(devices)}", "", *_TABLE_HEAD]
    for dev in sorted(devices, key=lambda d: d.get(DEV_ENTITY_ID, "")):
        try:
            offset = f"{float(dev.get(DEV_OFFSET, 0)):+.1f} °C"
        except (TypeError, ValueError):
            offset = _DASH
        if dev.get(DEV_IS_BEDROOM):
            offset += ", bedroom"
        lines.append(_row(_entity(dev.get(DEV_ENTITY_ID)), offset))
    lines.append("")
    return lines


def _zones_section(opts: dict[str, Any]) -> list[str]:
    zones = opts.get(OPT_BRANCHES, []) or []
    if not zones:
        return ["**Zones** — none", ""]

    lines = [f"**Zones** — {len(zones)}", ""]
    for zone in zones:
        name = zone.get(BRANCH_NAME) or zone.get(BRANCH_ID, "?")
        actuator = zone.get(BRANCH_ACTUATOR)
        pump = zone.get(BRANCH_PUMP)
        kind = "branch" if (actuator or pump) else "sensors only"
        try:
            offset = f"{float(zone.get(BRANCH_OFFSET, 0)):+.1f} °C"
        except (TypeError, ValueError):
            offset = _DASH

        lines += [
            f"*{name}* — {kind}",
            "",
            *_TABLE_HEAD,
            _row("Sensors", _entities(zone.get(BRANCH_SENSORS))),
            _row("Offset", offset),
            _row("Bedroom", "yes" if zone.get(BRANCH_IS_BEDROOM) else "no"),
        ]
        if actuator or pump:
            lines += [
                _row("Actuator", _entity(actuator)),
                _row("Pump", _entity(pump)),
                _row(
                    "Hysteresis",
                    _temp(zone.get(BRANCH_HYSTERESIS, DEFAULT_HYSTERESIS)),
                ),
                _row(
                    "Actuator travel",
                    f"{int(zone.get(BRANCH_TRAVEL_S, DEFAULT_TRAVEL_S))} s",
                ),
                _row(
                    "Min pump interval",
                    f"{int(zone.get(BRANCH_MIN_CYCLE_S, DEFAULT_MIN_CYCLE_S))} s",
                ),
            ]
        lines.append("")
    return lines


def _boiler_section(opts: dict[str, Any]) -> list[str]:
    return [
        f"**Boiler** — control {_onoff(opts.get(OPT_BOILER_ENABLED))}, "
        f"summer {_onoff(opts.get(OPT_BOILER_SUMMER))}, "
        f"keep on {_onoff(opts.get(OPT_BOILER_KEEP_ON))}",
        "",
        *_TABLE_HEAD,
        _row("Power", _entity(opts.get(OPT_BOILER_POWER_ENTITY))),
        _row("On/off", _entity(opts.get(OPT_BOILER_SWITCH_ENTITY))),
        _row("Pumps", _entities(opts.get(OPT_BOILER_PUMPS))),
        "",
        "Demand comes from the devices and zones above, each measured against "
        "the target it is actually driven to, offset included.",
        "",
    ]


def _conflicts_section(opts: dict[str, Any]) -> list[str]:
    """Switches driven from more than one place.

    Only driven entities can clash. Two readers of one temperature sensor -- a
    branch and a boiler room, say -- are ordinary, and flagging those would bury
    the conflicts that matter.
    """
    drivers: dict[str, list[str]] = {}

    def claim(entity_id: str | None, owner: str) -> None:
        if entity_id:
            drivers.setdefault(entity_id, []).append(owner)

    for branch in opts.get(OPT_BRANCHES, []) or []:
        name = branch.get(BRANCH_NAME) or branch.get(BRANCH_ID, "?")
        claim(branch.get(BRANCH_ACTUATOR), f"branch {name} actuator")
        claim(branch.get(BRANCH_PUMP), f"branch {name} pump")

    claim(opts.get(OPT_BOILER_SWITCH_ENTITY), "boiler on/off")
    for pump in opts.get(OPT_BOILER_PUMPS) or []:
        claim(pump, "boiler pump")

    clashes = {e: owners for e, owners in drivers.items() if len(owners) > 1}
    if not clashes:
        return []

    lines = ["**⚠️ Driven from more than one place**", ""]
    for entity_id in sorted(clashes):
        lines.append(f"- `{entity_id}`: {', '.join(clashes[entity_id])}")
    lines.append("")
    return lines


# ------------------------------------------------------------------ public


def configuration_summary(options: dict[str, Any] | None) -> str:
    """Render the whole configuration as markdown for the options menu."""
    opts = {**DEFAULTS, **(options or {})}
    lines: list[str] = []
    lines += _schedule_section(opts)
    lines += _devices_section(opts)
    lines += _zones_section(opts)
    lines += _boiler_section(opts)
    lines += _conflicts_section(opts)
    return "\n".join(lines).rstrip()
