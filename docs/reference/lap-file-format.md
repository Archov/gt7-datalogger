# Lap file format

Laps export and import as JSON (**Sessions → json** / **Import lap…**) so they can be
shared or backed up, and export as CSV for MoTeC i2 or Excel.

## JSON export (v3)

```json
{
  "format": "gt7-datalogger-lap",
  "version": 3,
  "lap": {
    "number": 4,
    "time_ms": 92450,
    "car_id": 3298,
    "fuel_start": 42.1,
    "fuel_end": 40.3,
    "...": "per-lap metrics, engine health, tod_ms",
    "events": [ { "type": "lockup", "start_dist": 812.4, "end_dist": 818.0,
                  "wheels": ["fl"], "severity": 0.71 } ],
    "gearing": { "ratios": [3.21, 2.44, 1.88, 1.51, 1.24, 1.03],
                 "top_speed": 289.0, "rpm_alert": 7500 },
    "telemetry_meta": { "packet_format": "C", "wheelbase_m": 2.65,
                        "car_category": "GR3", "fuel_capacity": 100.0 },
    "samples": { "t": [...], "dist": [...], "speed": [...], "...": "..." }
  }
}
```

The `samples` object holds the **full 60 Hz series** as parallel arrays, one per
channel — see [Derived channels & metrics](../internals/derived-channels.md) for the
complete column list with formulas and units (time, distance, speed,
inputs, gear, RPM, boost, per-wheel slip, per-corner tire temps and suspension travel,
world position, fuel, driver-aids bitmask, …).
New captures retain all three world-position axes as `pos_x`, `pos_y`, and `pos_z`.
Older v1/v2/v3 files without `pos_y` remain valid and use X/Z for spatial analysis.

### Importing

`POST /api/laps/import` (or the **Import lap…** button) accepts the envelope above:

- If no session is active, an `imported` session is created to hold the lap.
- **Events and aid-usage metrics are recomputed** from the samples on import (so
  imports benefit from detector improvements), while engine-health aggregates,
  gearing, partial-lap state, and v3 telemetry metadata are carried over.
- **v1/v2 files** import cleanly — newer channels and telemetry metadata are
  simply absent and the charts skip them; events stay empty since the columns they need
  aren't there.

## CSV export (MoTeC-compatible)

`GET /api/laps/{id}/export.csv` — a CSV that MoTeC i2's *CSV file* import (and Excel)
understands:

- Header rows: `Format`, `Device`, `Vehicle` (the car name), `Comment`, `Log Date`, and
  `Sample Rate: 60.000`
- Then a channel-name row and a unit row, followed by one row per tick

Recorded channels have explicit units: Time (s), Distance (m), Ground Speed (km/h), Throttle
Pos (%), Brake Pos (%), Gear, Engine RPM (rpm), Boost Pressure (bar), Tyre Slip Ratio,
Yaw Rate (rad/s), Pos X/Y/Z (m), Ride Height (mm), Fuel Level (L), Tyre Slip FL/FR/RL/RR,
Tyre Temp FL/FR/RL/RR (C), Susp Travel FL/FR/RL/RR (mm), and Driver Aids (bitmask).

!!! tip
    In MoTeC i2, create a new workspace, then *File → Import* and choose the CSV. The
    distance channel makes distance-based overlays work the same way they do in the
    built-in Analysis view.
