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
- [ ] **Track borders via edge tracing** *(tabled 2026-07-26 — prototyped, then reverted)*.
  GT7 doesn't broadcast track geometry, but the gt-telemetry.com approach works with
  data we already capture: drive one slow lap hugging the outer edge and one hugging
  the inner edge, mark those laps as edge traces, store the two [x, z] polylines on the
  named track, and render them under the racing lines. The reverted prototype
  (schema columns `tracks.outer_json/inner_json`, `POST /api/tracks/{name}/border`,
  `GET /api/tracks/{name}/geometry`, ⊂out/⊃in buttons in the Sessions lap table)
  worked end-to-end and can be recovered from this description. Note: the two columns
  already exist in live DBs (migration ran before the revert) — harmless, reusable.
  **Better source for real circuits (investigated 2026-07-26):** gt-telemetry.com's
  bundle ships Mapbox GL / OSM / CARTO — their outlines for real tracks come from
  geographic map data, not crowd traces. OpenStreetMap has real circuits mapped in
  detail (`highway=raceway`, often both edges + named corners) under ODbL (usable with
  attribution) via the Overpass API. Needs a lat/lon → GT7-world similarity transform
  (rotate/translate/scale) least-squares-fitted between a driven lap and the OSM
  centerline. Fictional GT7 tracks still need edge tracing. Their own backend
  (api.gt-telemetry.com/tracks) is auth-gated and its data unlicensed — don't scrape it;
  ask via GitHub issue if we ever want their fictional-track layouts.
- [ ] **Auto-numbered corners on the track map** *(tabled 2026-07-26 — prototyped, then
  reverted; the naive version was wrong)*. Detect corners from racing-line curvature and
  number them from the start line, GT7-Data-Logger style. Lesson from the failed attempt:
  UNSIGNED curvature is not enough — a long hairpin splits into two corners where curvature
  dips mid-arc, and an S-section merges into one. A correct detector needs **signed**
  curvature (split regions when turn direction flips, merge only same-direction arcs),
  hysteresis on the threshold, and probably apex-at-minimum-speed rather than
  apex-at-max-curvature. Display rule that worked: dots on the full map, numbered circles
  only when the zoomed section shows ≤ ~30 corners.

---

## Tier 4 — UI, navigation & polish

### Navigation / page linking

- [x] **Hash router + deep links** (`lib/router.ts`): `#/live`, `#/analysis`, `#/sessions`,
  `#/admin`, and Analysis accepts `#/analysis?session=<id>&laps=<ids>&ref=<id>`. The current
  Analysis selection is mirrored back into the URL (replaceState) so it's always shareable.
- [x] **Shared analysis-selection state** (`store/analysis.ts`): Analysis keeps
  `{ sessionId, selectedLapIds, refLapId }` current, and re-entering the tab restores it
  instead of resetting to latest-vs-best. Cross-view handoff itself rides the URL params.
- [x] **Sessions → Analysis link**: "Analyze" button on the session header row, plus per-lap
  "compare" (vs session best) and "set ref" actions in `LapTable`.
- [x] **Live feed → Analysis**: completed laps in `LiveView`'s feed are clickable.
- [x] **Active-route highlight** in `StatusBar`, driven by the route (with `aria-current`).

### Visual polish

Base theme (panel / ink-dim / accent tokens, tabular figures) is solid; these lift it to a
sellable-app finish.

- [x] **Replace native `prompt()` / `confirm()`** with in-app dialogs
  (`components/ui/Dialog.tsx`: focus trap, Escape, backdrop) and a global toast stack
  (`store/toasts.ts` + `components/ui/Toasts.tsx`). Covers track naming, session/lap delete,
  admin clear-data, and all flash messages; lap delete gained a confirm it never had.
- [x] **Consistent per-lap color identity** (`lib/colors.ts`): color keyed to lap id, used by
  the Analysis charts/map/picker chips, the Sessions lap table, and the Live feed.
- [x] **Color the Δ column** (green "best" / red +delta).
- [x] **Skeleton / empty states** for the sessions list and Analysis (`.skeleton` class),
  with friendlier empty-state copy.
- [x] **Session-row recognition** — best-lap-dot sparkline of lap times per session row
  (`components/LapSparkline.tsx`).
- [x] **Responsive pass** — Analysis lap-picker chips scroll horizontally on narrow screens;
  StatusBar nav scrolls instead of wrapping; global `:focus-visible` ring.
- [ ] **Adopt a component library** (shadcn/ui, per the project brief) for Select / Tabs /
  Tooltip. Deliberately deferred: the new in-house Dialog/Toast cover the acute need without
  pulling in Radix; revisit if the component surface keeps growing. Apply the dataviz palette
  method for accessible, consistent light/dark chart colors.

## Tier 5 — Overlay enhancements

`OverlayConfig` (in `frontend/src/lib/overlay.ts`) supports widgets + order, layout
(strip/stack/grid), align, scale, background opacity, and page mode — but **no explicit canvas
dimensions**, so sizing is a manual "1920×260" hint and the preview (a fixed-height iframe)
doesn't match what OBS actually shows.

- [x] **Custom canvas size**: `size` on `OverlayConfig`, encoded as `size=WxH` in the URL and
  applied in `OverlayView` (exact pixel box, global scale compensated). Presets: 1920×1080,
  1920×260 strip, 1080×1920 (TikTok / Shorts), 720×1280, plus custom W×H inputs and a
  "fill source" mode (the legacy behavior — old URLs without `size=` keep working).
- [x] **True-to-size preview**: the builder renders the overlay iframe at real pixel
  dimensions scaled to fit, with a size + "shown at N%" readout.
- [x] **Edge padding (x, y)**: `pad=XxY` in the URL, number inputs in the builder.
- [x] **Per-widget scale** (75–200%, encoded as `w=gear:1.5,…`); a drag-to-place canvas
  editor for free positioning remains future work.
- [x] **Named, saved overlay presets** (localStorage map) with save/load/delete chips and
  JSON export / import for sharing between machines.
- [x] **Safe-area guides** (action-safe 90% / title-safe 80%) toggle in the preview.


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
