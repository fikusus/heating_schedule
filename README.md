# Heating Schedule

Home Assistant integration that drives a set of `climate` devices on a shared
day/night schedule, with smooth transitions, per-room offsets and optional
boiler control.

## Features

- Day and night target temperatures with a configurable transition ramp.
- Separate night temperature and schedule for bedrooms.
- Per-device temperature offset, adjustable at runtime.
- Boiler control: power target, max room/target difference, summer mode,
  keep-on mode and circulation pumps.
- Heating branches with their own valve and pump, presented as climate
  entities and interlocked so the pump cannot run against a closed valve.
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
- **Boiler** — power and switch entities, pumps, and the rooms whose sensors
  feed the boiler logic.

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


## Heating branches

A branch is a heating loop with its own temperature sensors, a valve actuator
and a circulation pump. Add one under **Configure → Add heating branch**, and it
appears as a climate entity you can drive by hand, from the card, or by adding
it to the tracked devices so the schedule sets its target like any other head.

Control is a plain hysteresis loop around the coldest sensor on the branch.
Underneath it sits one rule that is not part of that loop:

> the pump runs only while the actuator is confirmed open

It is re-asserted from three independent triggers — the control loop, the
actuator reporting a state change, and a watchdog every 60 seconds — because a
pump running against a closed valve destroys itself, and a missed state update
must not be enough to cause that. Starting up opens the valve, waits out the
actuator travel time, then starts the pump. Shutting down stops the pump first,
and is never delayed by anything.

Per branch you configure the sensors, the actuator and pump switches, the
hysteresis, the actuator travel time (around 180 s for a thermoelectric head,
30 s for a motorised one) and a minimum interval between pump starts, which
guards against short cycling. `hvac_action` reports `preheating` while heat is
wanted but the pump is still held back, so a waiting branch does not look idle.

Summer mode stops branches outright rather than driving them to maximum the way
it does with ordinary climate devices.

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
