# Changelog

Notable changes to GT7 Datalogger. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
