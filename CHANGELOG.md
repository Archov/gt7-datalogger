# Changelog

Notable changes to GT7 Datalogger. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Auto-numbered corners on the track map**: corners are detected from the
  reference lap's racing-line signed curvature (hysteresis segmentation,
  direction-aware split/merge, start/finish wrap stitching, apex at the
  curvature-weighted centroid) and numbered from the start line, GT7 Data
  Logger-style. Numbered circles while ≤ 30 corners are in view, dots beyond;
  the Corner Detail widget shows the current corner (e.g. `T5 R`) while
  scrubbing. Detection parameters were tuned against real GT7 laps for
  identical counts and < 30 m apex drift across laps of the same track.

### Fixed

- **Pit out-laps no longer poison the session best / live delta**: a short out-lap
  (GT7 reports a time for it, but it covers only part of the track with a
  pit-exit-anchored distance axis) could become the delta reference — the live
  delta then glitched for the first fraction of the next lap and froze on a bogus
  ~lap-sized fallback value. Laps now only count for best when their distance span
  matches the session's longest lap (85 %), and a full lap invalidates a partial
  "best" retroactively.
- **Fuel projection survives race restarts**: recent laps are filtered by car
  (not recording session), so a restart keeps the previous stint's consumption
  data — you get a range estimate from the first meters instead of after a full
  lap, which matters in races with aggressive fuel multipliers. Partial-lap
  outliers (a lap consuming < 50 % of the window max, i.e. pit out-laps) are
  excluded from the average.

## [0.3.0] - 2026-08-04

### Added

- **Extended telemetry packet support (B / `~` / C)**: the listener can request any
  of GT7's four packet formats via the heartbeat character, decrypts each format's
  distinct Salsa20 IV constant, and parses the extra fields — steering wheel
  rotation, sway/heave/surge, filtered inputs, per-wheel torque vectors, energy
  recovery, per-wheel surface type, the live lap timer, front-wheel steering angles,
  wheelbase, and car category. Default is now packet **C** (GT7 v1.68+);
  configurable via `GT7_PACKET_FORMAT` or live in the Admin view. The simulated
  source emits packet C.
- **Race-event webhooks**: in addition to personal bests and session summaries, the
  webhook can now announce **overtakes**, **positions lost**, and **off-road
  excursions** (3+ wheels on a loose surface — requires packet format C). Position
  changes must hold ~1 s before firing so side-by-side battles don't spam. Every
  event type has a toggle in Admin → Notifications (`GT7_WEBHOOK_EVENTS` for
  env-based setups).
- **Opt-in admin auth**: set `GT7_ADMIN_TOKEN` to require a token (`X-API-Key`
  header) for the Admin API and every destructive/mutating endpoint; overlay, dash,
  and read endpoints stay open. The UI stores the token per browser and prompts on
  401. Unset = fully open, as before.
- `GT7_CORS_ORIGINS` for cross-origin API consumers (see Breaking below).
- `frames_dropped` counter in `/api/status` and the Admin diagnostics — 60 Hz frames
  the console numbered but the network lost.
- Admin view polish: per-event notification toggles with plain-language hints, and
  descriptive subtitles on every panel.

### Changed

- **Lap timing is robust to packet loss**: the time/distance axes integrate the
  console's packet counter (gaps clamped to 1 s) instead of assuming a perfect
  60 Hz stream, and input percentages are time-weighted accordingly.
- **Per-client WebSocket queues**: a slow or stalled viewer (browser, OBS) can no
  longer stall telemetry capture — it just misses intermediate frames; lap and
  session events are never dropped.
- Lap CSV export is written with a proper CSV writer and neutralizes spreadsheet
  formula injection in text cells.
- The sessions list is a single aggregate query (was one query per session).
- `dev.sh` rebuilds the frontend on every start, so `:8000` always serves the
  current UI instead of a stale `dist`.

### Fixed

- **Fuel strategy widgets no longer mix sessions**: on a car change or race restart
  the lap feed is pruned to the new session, so "laps of fuel" / "pit before" no
  longer average fuel consumption from the previous car or track for the first laps
  of a session.
- Lap imports are validated (required columns, equal lengths, finite numbers, size
  cap) and return a clear 400 instead of storing a file that breaks analysis with a
  500 later; a rejected import no longer creates an empty session.
- Restarting or switching the telemetry source fully awaits task shutdown and port
  release — no more races when rebinding UDP 33740.

### Security

- Webhook requests never follow redirects, and the webhook trust model is
  documented (LAN targets are intentional; the admin token guards configuration).

### Breaking

- The API no longer sends wildcard CORS headers. The bundled UI is unaffected
  (same-origin in both dev and prod). Separate cross-origin consumers must set
  `GT7_CORS_ORIGINS`.

## [0.2.1] - 2026-07-31

### Added

- Docs: a full **widget reference** page (`guide/widgets.md`) covering every widget's
  styles, color thresholds, alert triggers, and behavior under each track condition
  (paused, menus, first lap, past the reference lap, race finished, unlimited
  sessions, lost telemetry, placeholder mode).

### Changed

- The delta widget (overlay, `/dash`, Live view) now updates **live during the lap**:
  it compares your current track position against the session-best lap's trace
  (positive = slower). Before a reference lap exists it falls back to the end-of-lap
  comparison, labeled *Δ best (last lap)*. Live frames gain `delta_ms` and
  `lap_elapsed_ms` fields.

## [0.2.0] - 2026-07-31

### Added

- **Grid overlay builder** (Admin view): drag-and-drop widget placement on a snapping
  grid with per-widget footprints (1×1 up to 4×4 cells), ghost-outline collision
  feedback, and corner-handle resizing.
- **Widget style variants** — choose how each metric looks: speed as digits / bar / arc
  gauge; RPM as bar / shift-light LED strip / gauge / digits; fuel as percent / bar /
  laps-remaining; lap times as list / big-last / big-best; delta as big number /
  centered ± bar; and more.
- **New widgets** from previously unexposed telemetry: engine temps (water / oil / oil
  pressure / boost), driver-aid badges (TCS / ASM / handbrake / rev limiter), boost,
  and race alerts.
- **Server-saved named layouts** (`layouts` table, `/api/layouts` CRUD): OBS browser
  sources use short stable URLs (`/overlay?layout=<name>`) that keep working while the
  layout is edited. JSON export/import and one-click migration of old browser-stored
  presets.
- **Driver dashboard** at `/dash`: full-screen race-engineer screen for a second
  display, with built-in *Race engineer* and *Endurance* presets, a fullscreen toggle,
  and a connection status dot.
- **Race alert engine**: low fuel (warning < 3 laps, pulsing critical < 1.5), pit-window
  callouts, water/oil overheat, low oil pressure, and hot tires — suppressed while
  paused or off-track, and shared with the engine/tire widget color thresholds.
- Docs: new *Driver dashboard* guide, rewritten *Overlay & streaming* guide, layouts
  API reference, and fresh builder/dashboard screenshots.

### Changed

- Demo/placeholder mode now slowly drains fuel so strategy and alert widgets can be
  designed without driving.
- The Admin overlay builder's URL-parameter workflow is replaced by saved layouts;
  existing URL-parameter overlays (`/overlay?w=…`) keep rendering pixel-identical.

### Fixed

- The GitHub Pages docs deploy job no longer runs (and fails) on pull requests.
- Concurrent layout create/rename with a duplicate name returns 409 instead of 500.

## [0.1.0] - 2026-07-23

Initial release.

### Added

- **Telemetry capture** from a PlayStation on the same network: Salsa20 decryption,
  heartbeat keep-alive, console auto-discovery via UDP broadcast, automatic reconnect,
  and a built-in **simulated telemetry source** for development without a console.
- **Per-lap recording** at 60 Hz across ~28 channels (per-wheel slip, per-corner tire
  temps, suspension travel, driver-aids bitmask, …) with per-lap aggregates: aid usage,
  engine health, gearing metadata, and chassis events (lockup / wheelspin / bottoming /
  kerb detection).
- **Live view**: real-time dashboard with race readouts, driver-aid pills, fuel
  strategy projection, and a clickable recent-lap feed, streamed over WebSocket.
- **Analysis view**: multi-lap comparison against a selectable reference lap with time
  delta, synced cursors, channel picker, event bands, race line map, corner detail,
  consistency (deviation) view, fuel map, and gearing panel.
- **Sessions view**: lap-time sparklines, per-lap metrics with event counts, JSON
  export/import, CSV / MoTeC-compatible export, and record on/off + log-lap-now
  controls.
- **Track auto-identification** from lap geometry — name a circuit once and future
  sessions are tagged automatically.
- **OBS overlay** at `/overlay` with a URL-encoded builder: strip / stack / grid
  layouts, exact-pixel canvas sizes, transparent / green-screen / dark page modes,
  per-widget scaling, browser-stored presets, and placeholder demo data.
- **Admin view**: connection settings, runtime source switching, log viewer, webhook
  notifications (Discord-aware), car database updater, and data management.
- **Deployment**: single Docker image (amd64/arm64) serving API + UI on one port,
  Raspberry Pi guide, and a MkDocs Material documentation site on GitHub Pages.
