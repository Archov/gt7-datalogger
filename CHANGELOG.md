# Changelog

Notable changes to GT7 Datalogger. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
