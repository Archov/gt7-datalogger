# GT7 Datalogger — Feature TODO

Ideas for additional telemetry and functionality, ordered roughly by value-for-effort.
Grouped into: **quick wins** (data already decoded), **derived analytics**, and
**bigger features**.

---

## Tier 1 — Surface data already decoded

These fields are already parsed in `backend/app/telemetry/packet.py` and present on the
`TelemetryPacket` model, but never make it into the per-lap sample series or the UI.

**Display design principle (2026-07-27):** the Analysis view already stacks 10 chart
panels. Most Tier 1 data is per-corner (×4 channels), so "one line panel per field" would
triple that into an unreadable wall — and a 4-line spaghetti panel answers no question.
Each channel instead gets the display that answers its *driver question*
("which wheel locked?", "understeer or oversteer?", "can I turn TCS down?"), built on four
display primitives: **(a)** a channel picker for the stacked charts, **(b)** a
cursor-synced per-corner car widget, **(c)** detected events (bands/markers/counts), and
**(d)** per-lap aggregates in the existing tables/panels. Raw curves stay available but
off by default.

### 1.0 Plumbing prerequisites *(do first — everything below rides on this)*

- [x] **Channel-selectable compare API.** New columns go into `SAMPLE_COLUMNS`, but
  `GET /api/laps/compare` takes a `channels=` param defaulting to today's set, so the
  payload doesn't double for users who never open the new channels. Same for the live
  WebSocket frame: additions are cheap scalars only.
- [x] **Channel picker UI.** `PANELS` in `StackedCharts.tsx` becomes data-driven: a
  "Channels" popover in the Analysis toolbar, grouped (Driving · Tires & wheels ·
  Chassis · Engine), persisted to localStorage and mirrored into the analysis URL params
  so a shared deep link reproduces the same panel set. Default = the current 10 panels.
- [x] **Lap-file format version bump** (v2) + import shim (older exports lack new columns →
  fill with empty arrays, charts skip them gracefully).

### 1.1 Corner Detail widget — the flagship display *(primitive b)*

- [x] New Analysis side panel, placed **directly under the race-line map** — they are the
  cursor-synced pair: scrub a chart, the map dot moves, the car widget shows what the
  chassis was doing at that spot. (A live variant in the Live view / OBS overlay is a
  follow-up; the Analysis version is the one that answers setup questions.)
- [x] Top-down car outline with four corner cells, synced to the chart cursor / map dot.
  Scrubbing through a corner replays the load transfer story:
  - **Tire temp** as cell fill color (cold-blue → optimal-green → hot-red, same scale as
    the Live tire tiles).
  - **Suspension compression** as a vertical bar per corner, normalized to the lap's
    min–max travel.
  - **Slip state** badge per corner: LOCK (slip ≪ 1 while braking) / SPIN (slip ≫ 1 on
    throttle). Focus lap only — cross-lap event comparison belongs to the 1.2 map
    markers and lap-table counts, not this widget.
  - **F/R temp balance** readout ("F +6.2 °C" → understeer-hot) below the car.
- [x] **Multi-lap = focus model** (N laps × 4 corners × 3 channels at once is noise):
  - The widget renders **one focus lap**; a row of small `lapColor` chips at the top
    switches focus (default: most recently selected non-reference lap).
  - The **reference lap is always the ghost**: secondary numbers per corner
    (`78° / 71°`), hollow outlines on the suspension bars — focus-vs-ref at the same
    distance stays visible without any switching.
  - Corner cells tint toward red/blue when hotter/cooler than the ref, so flipping
    focus is scannable rather than a number-reading exercise.
  - With exactly 2 laps selected (latest vs best, the common case) this collapses to
    zero extra UI: chips hide, focus = latest, ghost = ref.
  This one widget makes all 12 per-corner channels legible without a single new line panel.

### 1.2 Per-wheel slip → lockup / wheelspin events *(primitives b, c)*

- [x] Store `slip_fl/fr/rl/rr` per tick (`|wheel_rps| × tire_radius / speed`); keep the
  averaged `tire_slip` column for compatibility and the existing panel.
- [x] Detect events server-side at lap save (new `processing/events.py`):
  **lockup** = braking ∧ min wheel slip < ~0.9 sustained ≥ N ticks;
  **wheelspin** = throttle ∧ max slip > 1.1. Each event: `{start_dist, end_dist, wheels,
  severity}`, persisted with the lap.
- [x] Display *(partial: chart bands + lap-table/tuning counts shipped; race-line map markers remain)*: shaded bands on the stacked charts (ECharts `markArea`, like coasting),
  markers on the race-line map at the event location (tooltip names the wheels), and
  counts in the lap table + tuning panel ("3 lockups · 2 spins"). Comparing event
  positions between laps is the actionable part — "you lock the inside-front into T3 on
  every fast lap".
- [x] The tire-slip panel gains picker variants: avg (default) · front/rear · per-wheel.

### 1.3 Per-corner tire temperatures *(primitives b, a, d)*

- [x] Per-tick columns `tt_fl/fr/rl/rr`; primary display is the Corner Detail widget (1.1).
- [x] Optional stacked channels (off by default): **front avg**, **rear avg**, and
  **F−R balance** — the balance line is *one* curve that answers the setup question
  directly, where four raw lines can't.
- [ ] *(remaining)* Race-line map gains a coloring-mode dropdown: input zones (today) · speed ·
  tire temp · F−R balance. "Where on the lap do the fronts overheat" as a picture.
- [ ] *(remaining)* Lap aggregates (avg/max per corner) into the tuning panel — feeds the Tier 2 stint
  degradation trend.

### 1.4 Suspension travel per corner *(primitives b, c, d)*

- [x] Per-tick columns (mm); Corner Detail bars (1.1).
- [x] **Bottoming / kerb-strike events** through the same event pipeline as 1.2: travel
  within ~2% of the lap's max compression (absolute range varies per car, so normalize
  per lap), or a single-tick spike ≫ neighbors = kerb strike. Bands + map markers +
  per-lap count.
- [x] Optional stacked channels: front avg / rear avg travel.
- [ ] *(remaining)* Tuning panel: min/max travel per corner, next to min body height.

### 1.5 Driver aids — TCS / ASM / handbrake / rev limiter *(primitives c, d)*

- [x] One per-tick `aids` bitmask column (bit0 TCS · bit1 ASM · bit2 handbrake ·
  bit3 rev-limiter) — four flags for the price of one column.
- [x] Stacked charts: **overlay bands, not new panels** — TCS activation shades the
  throttle panel, ASM shades the speed panel.
- [ ] *(remaining)* Race-line map: TCS-active dots along the line. "TCS catches you at the same exit
  every lap" is a direct coaching cue (over the limit there) and a setup cue (TCS can
  come down when the % falls without lap-time loss).
- [x] Lap metrics: `tcs_active_pct`, `asm_active_pct` in the lap table + tuning panel.
- [x] Live view: TCS/ASM/HB indicator pills that light on activation; rev-limiter flashes
  the RPM bar.

### 1.6 Engine health — oil/water temp, oil pressure *(primitive d only)*

- [x] **Not** per-tick lap channels — these move over minutes, not corners, so per-lap
  aggregates carry all the signal: max water temp, max oil temp, min oil pressure
  (sampled only above ~idle rpm).
- [ ] *(remaining)* Sessions view: per-lap trend columns/sparkline so an endurance stint shows drift.
- [x] Live view already shows both temps — added warning color thresholds *(one-shot exceedance toast remains)* and a one-shot
  toast on first exceedance (pairs with the existing webhook notifications).

### 1.7 Gearing panel *(static per lap, primitive d)*

- [x] Capture `gear_ratios`, `transmission_top_speed`, `rpm_alert_max` once per lap as
  metadata (not series — they only change when the tune changes).
- [x] *(partial: ratio table + est. redline speeds shipped; sawtooth chart remains)* Analysis side panel "Gearing": table of ratio + theoretical speed at redline per
  gear, and a **sawtooth chart** — speed-vs-RPM line per gear with the lap's actual
  (speed, rpm) samples scattered on top. Shows real shift points vs redline, ratio gaps,
  and whether top gear is ever reached (final drive too short/long).

### 1.8 Suggested vs actual gear *(rides on existing gear panel)*

- [ ] Per-tick `suggested_gear` column (15 = none → gap in the series).
- [ ] Display as a dashed ghost step-line on the *existing* gear panel, only where a
  suggestion is active; shade mismatches where actual > suggested through a corner.
- [ ] Lap metric: count of corners taken a gear high.

### 1.9 Clutch channels — deferred

- [ ] Record nothing for now. Revisit as a derived "shift duration" metric (from
  `clutch_engagement` dips) if manual-clutch users ask; near-zero value for the
  pad/paddle majority, and it would spend three columns.

**Suggested order:** 1.0 → 1.2 (slip/events — biggest driving-improvement payoff) →
1.3 (temps) + 1.1 (widget lands with two of its three data sources) → 1.5 (aids) →
1.4 (suspension) → 1.7 (gearing) → 1.6 (engine) → 1.8 → (1.9 deferred).

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
- [x] **Auto-numbered corners on the track map** *(shipped 2026-08-05; tabled
  2026-07-26 after a failed unsigned-curvature prototype)*. Signed curvature with
  hysteresis (enter 0.0030, stay 0.0022 rad/m), noise arcs dropped before same-direction
  merging (90 m gap), 25°–300° significance band, start/finish wrap stitching, apex at
  the curvature-weighted centroid (min-speed apexes wander ~100 m between laps —
  the spec's own assumption proved wrong when validated against real laps). Parameters
  tuned for identical counts + <30 m apex drift across 5 real GT7 sessions. Numbered
  circles ≤30 in view, dots beyond; detection on the reference lap only. Follow-up
  idea: per-track canonical corner store (median of clean laps) so numbering survives
  reference-lap switches.

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
- [x] **Adopt a component library**: shadcn-style owned wrappers over Radix primitives in
  `components/ui/` — `Select` (replaces every native `<select>`), `SegmentedControl`
  (ToggleGroup; replaces the ad-hoc button rows — chosen over Tabs because these are
  exclusive-choice pickers, not tabbed panels), `Tip` tooltip (replaces `title=` attrs on key
  actions), and `Dialog` re-ported onto Radix Dialog. Chart palette re-derived with the
  dataviz palette method: same six hue families, re-stepped into the dark-mode lightness band
  and re-ordered so it passes the full validator (CVD separation, normal-vision floor,
  contrast) on both app surfaces; trade-offs documented in `lib/colors.ts`.

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

Sector timing + theoretical best (Tier 2), plus Tier 1 in its suggested order: the 1.0
plumbing pass, then per-wheel slip + events (1.2) and tire temps (1.3) so the Corner
Detail widget (1.1) can land — the biggest jump in usefulness for the least new plumbing.

### Shared plumbing note

Adding any per-lap channel touches the same spots, so batch them (one 1.0 pass, not once
per feature): `SAMPLE_COLUMNS` and `_append_sample` in `backend/app/processing/laps.py`,
the persisted lap schema in `backend/app/storage/`, the JSON lap export/import version,
the frontend column list in `frontend/src/lib/types.ts`, and the relevant chart
components. Bump the lap-file format version when the column set changes so older exports
still import cleanly. New per-tick columns should also be added to the `channels=`
allowlist on the compare endpoint rather than the default response set.
