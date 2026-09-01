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
