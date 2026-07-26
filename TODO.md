# GT7 Datalogger — Feature TODO

Ideas for additional telemetry and functionality, ordered roughly by value-for-effort.
Grouped into: **quick wins** (data already decoded), **derived analytics**, and
**bigger features**.

---

## Tier 1 — Surface data already decoded

These fields are already parsed in `backend/app/telemetry/packet.py` and present on the
`TelemetryPacket` model, but never make it into the per-lap sample series or the UI. Most
require adding a column to `SAMPLE_COLUMNS` in `backend/app/processing/laps.py`, appending
it in `_append_sample`, adding it to the frontend `types.ts` column list, and drawing it.

- [ ] **Per-corner tire temperatures** in the lap series (FL/FR/RL/RR).
  Decoded (`tire_temp_fl/fr/rl/rr`) and shown live, but not stored per lap.
  Value: understeer (hot fronts) vs oversteer (hot rears); setup tuning.
- [ ] **Suspension travel per corner** (`suspension_fl/fr/rl/rr`).
  Decoded, currently unused. Value: bottoming-out, kerb strikes, ride-height behavior.
- [ ] **Engine health channels** — `oil_temp`, `water_temp`, `oil_pressure`.
  Decoded, not sampled. Value: endurance monitoring, catching overheating.
- [ ] **Per-wheel slip / lockup / wheelspin**.
  Today all four wheels are averaged into `tire_slip_ratio`. Keep per-wheel
  (`wheel_rps_*` × `tire_radius_*`) to show which wheel locks under braking or spins on exit.
- [ ] **Gearing panel** — `gear_ratios` + `transmission_top_speed`.
  Decoded, unused. Value: shift-point analysis, theoretical top speed per gear for tuning.
- [ ] **Driver-aid activation** — surface `TCS_ACTIVE`, `ASM_ACTIVE`, `HANDBRAKE` flags.
  Value: TCS cutting in marks where you're over the limit and losing time.
- [ ] **Clutch channels** — `clutch`, `clutch_engagement`, `rpm_after_clutch` (optional).
- [ ] **Suggested-gear vs actual-gear** comparison using the decoded `suggested_gear` nibble.

## Tier 2 — Derived analytics

Math on data already captured; add to `backend/app/processing/analysis.py` and new charts.

- [ ] **Sector splits + theoretical best lap** *(highest value)*.
  Split each lap into 2–3 sectors, track per-sector bests, show the optimal-lap sum.
  Needs sector-boundary detection (by distance fraction, or configurable per track).
- [ ] **Live predictive delta**.
  Project +/- vs the reference lap live as you drive, not only after lap completion.
  Extends the existing `time_delta_series` logic into the live WebSocket path.
- [ ] **Slip angle (understeer/oversteer balance)**.
  Angle between the full velocity vector (`velocity_x/z`, currently only scalar speed is
  used) and heading (`rel_orientation_to_north` / `rotation_yaw`). Balance metric per corner.
- [ ] **G-force / traction circle (g-g diagram)**.
  Lateral vs longitudinal acceleration scatter; shows how well braking and cornering are
  combined. Derive from velocity deltas between ticks.
- [ ] **Braking-point comparison**.
  Where braking starts before each corner vs the reference lap.
- [ ] **Tire-temp / degradation trend across a stint**.
  Per-lap tire-temp and lap-time drift over consecutive laps (depends on Tier 1 tire temps).
- [ ] **Lap-time consistency**.
  Session-level consistency score and a lap-time histogram/scatter (complements the existing
  speed-deviation chart).

## Tier 3 — Bigger features

Change who would use the tool.

- [x] **OBS / stream overlay mode**.
  A transparent browser-source view (speed / gear / delta / tires) for streamers.
- [x] **Webhook / Discord notifications**.
  On a new personal best, and an end-of-session summary.
- [x] **CSV / MoTeC-compatible export**.
  So laps open in external analysis tools (JSON export already exists).
- [x] **Live race strategy**.
  Fuel-to-empty countdown and pit-window calculator, building on the existing `fuel_map`.
- [x] **Track auto-identification + minimap library**.
  Detect the track from position bounds; store named tracks and reuse map orientation.
- [x] **Weather / time-of-day tracking** via `day_progression_ms` for endurance stints.

---

## Done beyond this list

Shipped along the way, not part of the original tiers:

- [x] Admin view: runtime PS IP / source / log level (persisted), live log viewer,
  diagnostics, car-DB updater, data management
- [x] Overlay builder: pick/order widgets, strip / stack / phone-grid layouts, scale,
  background opacity, green-screen page mode, placeholder telemetry for designing,
  per-device URLs (path-based for strict validators, LAN URL shown)
- [x] Multi-lap racing-line overlay on the track map (GT7 Data Logger-style) with a
  synced cursor dot per lap
- [x] Synchronized click-and-drag section zoom across all charts + track map +
  deviation chart (native ECharts dataZoomSelect), sector presets, double-click reset
- [x] Live delta vs previous best (was: always +0.000), FIN state after the checkered flag
- [x] Capture robustness: serialized UDP pipeline (duplicate-lap race fix), phantom-lap
  guard, empty-session cleanup
- [x] One-command dev environment (`./dev.sh`)

## Suggested starting point

Sector timing + theoretical best (Tier 2), plus wiring the already-decoded **tire temps**
and **suspension travel** (Tier 1) into the lap series — the biggest jump in usefulness for
the least new plumbing.

### Shared plumbing note

Adding any per-lap channel touches the same spots, so batch them:
`SAMPLE_COLUMNS` and `_append_sample` in `backend/app/processing/laps.py`, the persisted lap
schema in `backend/app/storage/`, the JSON lap export/import version, the frontend column
list in `frontend/src/lib/types.ts`, and the relevant chart components. Bump the lap-file
format version when the column set changes so older exports still import cleanly.
