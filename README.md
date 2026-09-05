# Heating Schedule

Home Assistant integration that drives a set of `climate` devices on a shared
day/night schedule, with smooth transitions, per-room offsets and optional
boiler control.

## Features

- Day and night target temperatures with a configurable transition ramp.
- Separate night temperature and schedule for bedrooms.
- Per-device temperature offset, adjustable at runtime.
- Boiler control driven by the climate entities themselves, so each room is
  assessed against the target it is actually held at, offset included.
- Zones: heating branches with their own valve and pump, interlocked so the pump
  cannot run against a closed valve, and sensor-only zones for rooms whose
  thermostatic head reports a poor temperature or none at all.
- A companion Lovelace card, distributed separately as
  [heating-schedule-card][card].

## Installation

### HACS

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/fikusus/heating_schedule`, category **Integration**.
3. Install "Heating Schedule", then restart Home Assistant.

### Manual

Copy `custom_components/heating_schedule` into your `<config>/custom_components/`
directory, keeping the `www/` and `translations/` subfolders, then restart
Home Assistant.

## Setup

Settings → Devices & Services → **Add Integration** → "Heating Schedule".
The entry is created with defaults and has no setup form; everything is
configured afterwards through **Configure**:

- **Globals** — day/night temperatures, bedroom night temperature, switch-over
  times and transition duration.
- **Devices** — the `climate` entities to drive, each with its own offset and a
  "bedroom" flag that selects the bedroom schedule.
- **Zones** — heating branches with a valve and pump, or sensor-only zones.
  Each carries its own sensors, offset and bedroom flag.
- **Boiler** — the power and switch entities and any pumps that follow the
  boiler directly. There is no room list: demand comes from the devices and
  zones.

## Configuration overview

Settings are spread across seven steps of the **Configure** menu, so the menu
opens with a summary of the lot: the schedule temperatures and switch-over
times, every tracked climate device with its offset, each branch with its
sensors, actuator, pump and tuning, and the boiler with its entities, pumps and
rooms. Checking a value no longer means walking into the step that owns it.

Switches driven from more than one place are listed separately at the bottom.
Validation refuses new conflicts, but a configuration written before that
existed can still carry one. Sensors read by two sections are not flagged —
that is ordinary, and marking it would bury the conflicts that matter.


## Zones

A zone is a room or loop with its own temperature sensors, an offset and a
bedroom flag, presented as a climate entity. The schedule sets its target the
way it sets any device's, and its shortfall feeds the boiler.

Two kinds, both under **Configure**:

- **Heating branch** — owns a valve actuator and a circulation pump, and
  controls them with a hysteresis loop around its coldest sensor.
- **Sensor-only zone** — controls nothing. It exists to give the boiler an
  honest reading for a room, with that room's offset applied. Use it wherever a
  thermostatic head measures the air beside the radiator, or reports no
  temperature at all.

### The pump interlock

Under a branch's control loop sits one rule that is not part of it:

> the pump runs only while the actuator is confirmed open

It is re-asserted from three independent triggers — the control loop, the
actuator reporting a state change, and a watchdog every 60 seconds — because a
pump running against a closed valve destroys itself, and a missed state update
must not be enough to cause that. Starting up opens the valve, waits out the
actuator travel time, then starts the pump. Shutting down stops the pump first,
and is never delayed by anything.

Per branch you configure the actuator and pump switches, the hysteresis, the
actuator travel time (around 180 s for a thermoelectric head, 30 s for a
motorised one) and a minimum interval between pump starts, which guards against
short cycling. `hvac_action` reports `preheating` while heat is wanted but the
pump is still held back, so a waiting branch does not look idle.

A pump cannot be configured without an actuator: with no valve to confirm open,
the interlock would never let it start.

Summer mode stops zones outright rather than driving them to maximum the way it
does with ordinary climate devices.

### How the boiler reads demand

Each tracked device and each zone contributes one shortfall, `target - ambient`,
measured against the target it is actually driven to. The worst one sets the
power level. Devices supply their `current_temperature`; zones supply their
coldest sensor.

Because the target includes the offset, a room deliberately kept a degree warmer
now counts as such. Earlier versions compared against the bare schedule target,
so raising a room's offset quietly left the boiler under-reading demand in
exactly that room.

### Seeing the breakdown

`sensor.*_boiler_max_diff` carries the whole calculation in a `demand`
attribute: one entry per room with its name, current temperature, target and
shortfall, worst first. The number itself is the largest shortfall and is **not**
clamped — it goes negative once every room is past its target, which is the
signal that the boiler has nothing left to do. Only the power level is floored,
at 1%.

The [card][card] renders that attribute behind a *Rooms* button.

### One owner per switch

A valve or a pump answers to exactly one part of this integration. The boiler
mirrors its own on/off state onto the switches in its pump list and knows
nothing about any actuator, so a switch listed both as a branch pump and as a
boiler pump would be driven by two controllers at once -- and the boiler would
happily start it against a closed valve. The options flow refuses that
combination, along with a switch serving as both actuator and pump.

The boiler pump list is for pumps with no valve of their own, such as a main
circulation pump, which cannot be run dry against anything.

## The card

The dashboard card lives in its own repository, [heating-schedule-card][card],
and installs as a separate HACS dashboard resource. It is optional — the
integration exposes ordinary entities and works without it.

Once installed, add it from the card picker ("Heating Schedule"), or by hand:

```yaml
type: custom:heating-schedule-card
```

## Upgrading from 0.2.0

Releases up to 0.2.0 bundled the card and registered a Lovelace resource
pointing at `/heating_schedule_static/heating-schedule-card.js`. The
integration no longer serves that URL, so:

1. Delete that resource under Settings → Dashboards → ⋮ → Resources.
2. Install [heating-schedule-card][card] through HACS.
3. Reload the browser.

## Requirements

Home Assistant 2024.6 or newer.

[card]: https://github.com/fikusus/heating-schedule-card
