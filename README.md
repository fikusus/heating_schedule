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
- A bundled Lovelace card, served and registered by the integration itself.

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

## The card

The card is served by the integration and registered as a Lovelace resource
automatically. Add it from the dashboard card picker ("Heating Schedule"), or
by hand:

```yaml
type: custom:heating-schedule-card
```

If Lovelace runs in YAML mode, automatic resource registration is skipped —
add it yourself:

```yaml
lovelace:
  mode: yaml
  resources:
    - url: /heating_schedule_static/heating-schedule-card.js
      type: module
```

The served URL carries a hash of the card file, so a changed card invalidates
every cache on its own; there is no version to bump by hand.

## Requirements

Home Assistant 2024.6 or newer.
