# Project: GT7 Telemetry Datalogger & Dashboard

## Goal
Build a professional-grade telemetry datalogger and analysis dashboard for Gran Turismo 7. The application captures live telemetry from a PlayStation running GT7, records it, and serves it through a modern, responsive web interface. Functionally it should match or exceed [snipem/gt7dashboard](https://github.com/snipem/gt7dashboard), but with a significantly better, modern UI/UX and a cleaner, more scalable architecture.

## Background: GT7 telemetry interface
- GT7 broadcasts telemetry over UDP. The app sends a heartbeat packet ("A") to the PlayStation on port 33739 and receives telemetry packets on port 33740 at ~60 Hz.
- Packets are Salsa20-encrypted with a known key; the packet contains position, velocity, throttle/brake input, RPM, gear, speed, fuel, tire temps/speeds, boost, body height, lap number, lap times, and more.
- The console IP should be configurable (env var / settings UI), with UDP broadcast auto-discovery as a fallback.
- Handle connection loss gracefully: automatic reconnect, visible connection status in the UI.

## Architecture
Use a clean separation between capture, processing, storage, and presentation:

1. **Telemetry service (backend)**
   - Receives, decrypts, and decodes the UDP stream.
   - Normalizes packets into a typed telemetry model.
   - Derives lap-level data: lap detection, lap times, per-lap sample series, session grouping (track/car change detection).
   - Streams live data to the frontend over WebSockets (or Server-Sent Events); REST API for historical/session data.
2. **Storage**
   - Persist sessions and laps (SQLite by default; design the data layer so it can be swapped for Postgres later).
   - Import/export laps as JSON for compatibility and sharing.
3. **Frontend (web dashboard)**
   - SPA served by the backend or as a static build.
   - Real-time updates without page reloads; must comfortably handle 60 Hz live data (downsample/buffer client-side as needed).

## Technology constraints
- **Backend:** a modern, well-supported framework — preferred: Python 3.12+ with FastAPI (async, WebSockets, Pydantic models), or Node/TypeScript with Fastify/NestJS. Pick one and justify briefly in the README.
- **Frontend:** React 18+ with TypeScript and Vite. Styling with Tailwind CSS; component library such as shadcn/ui. Charting with a library that handles high-frequency streaming data well (e.g., ECharts, uPlot, or Recharts for lower-frequency views).
- Strict typing everywhere (type hints + mypy/pyright, or full TypeScript).
- Dockerfile + docker-compose for one-command deployment; document required ports (HTTP + 33740/udp).
- CI with linting and tests (GitHub Actions).

## Features (parity with gt7dashboard)
- Live connection status indicator.
- Lap list/table with lap number, time, diff to reference, fuel consumed, full-throttle/full-brake/coasting/tire-spin metrics, car name (via car ID → name lookup).
- Reference lap picker (default: best lap) and comparison of last lap vs reference:
  - Time-diff graph (delta over distance)
  - Speed, throttle, brake, coasting, gear, RPM, boost vs distance
  - Tire speed / car speed ratio
  - Yaw rate per second
- Race line map with throttle (green) / brake (red) / coast (blue) zones and speed peaks & valleys.
- Speed deviation graph across best laps (consistency analysis).
- Relative fuel map for fuel-setting strategy (laps/time remaining per fuel level).
- Save/load/reset laps; record replays toggle; manual "log lap now".
- Tuning info panel (max speed, min body height, etc.).

## Improvements over the original
- Modern dark-themed, responsive layout (usable on a second monitor, tablet, or phone).
- Dashboard organized into views: **Live/Race** (large readouts: speed, gear, RPM, fuel, tires, delta), **Analysis** (lap comparison charts, synced cursors across charts — hovering one chart highlights the same distance point on all others and on the race line map), **Sessions** (browse/manage historical sessions).
- Multi-lap overlay comparison (not just last vs reference).
- Track/car change auto-detection with prompt to start a new session instead of mixing data.
- Configurable units (km/h / mph) and settings persisted per user.

## Quality requirements
- Unit tests for packet decoding, lap detection, and all derived calculations (fuel map, deltas, deviation).
- Provide sample/replay telemetry data so the app can be developed and demoed without a PlayStation (a "simulated source" mode).
- Structured logging; clear error messages for common failures (firewall/UDP blocked, wrong IP).
- README with setup, Docker usage, and screenshots.

## Working conventions
- Conventional commit messages; small, focused commits.
- No AI-assistant references or attributions in code, comments, or commit messages.
