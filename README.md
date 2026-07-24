# GT7 Datalogger

A telemetry datalogger and analysis dashboard for **Gran Turismo 7**. It captures the
PlayStation's live telemetry stream, records every lap, and serves a modern dark-themed
web dashboard for live driving, lap comparison, and session management.

Functional parity with [snipem/gt7dashboard](https://github.com/snipem/gt7dashboard),
rebuilt with a cleaner architecture and a modern UI.

## Features

- **Live view** — large readouts for speed, gear, RPM (with limiter warning), throttle/brake,
  boost, fuel, tire temps, race position, lap delta, and a live feed of completed laps.
- **Analysis view** — multi-lap overlay comparison against a selectable reference lap:
  time diff over distance, speed, throttle, brake, coasting, gear, RPM, boost,
  tire-speed ratio, and yaw rate — all with **synced cursors** (hover one chart and the same
  distance point is highlighted everywhere, including on the race line map).
  Race line map with throttle/brake/coast zones and speed peaks (▲) / valleys (▼).
  Speed-deviation consistency chart across your best laps, relative fuel-map strategy table,
  and a tuning info panel.
- **Sessions view** — browse historical sessions, per-lap metrics (fuel, full throttle,
  full brake, coasting, tire spin, max speed), export/import laps as JSON, delete laps or
  whole sessions, manual "log lap now", and a record on/off toggle.
- **Robust capture** — Salsa20 decryption, heartbeat keep-alive, console auto-discovery via
  UDP broadcast, automatic reconnect, and a visible connection status indicator.
- **Sessions auto-split** on car change or race restart, so data never mixes.
- **Simulated source** (`GT7_SOURCE=sim`) drives laps around a synthetic circuit at 60 Hz —
  develop and demo everything without a PlayStation.
- Configurable units (km/h / mph), persisted in the browser.

## Architecture

```
PlayStation (GT7) ──UDP 33740──▶ Telemetry service (FastAPI, Python 3.12)
       ▲                          ├─ Salsa20 decrypt + typed packet parser
       └──heartbeat 33739──────── ├─ Lap detection, session grouping, metrics
                                  ├─ SQLite storage (SQLAlchemy async)
                                  ├─ REST API  (/api/…)  – history & analysis
                                  └─ WebSocket (/ws/live) – 30 Hz live stream
                                              │
                                              ▼
                                  React 18 + TypeScript + Vite + Tailwind
                                  (ECharts for high-frequency chart rendering)
```

**Why FastAPI?** Native async fits a 60 Hz UDP stream + WebSocket fan-out in one process;
Pydantic gives typed models and settings; the Python ecosystem has mature Salsa20 support.
The storage layer is behind SQLAlchemy's async engine, so SQLite can be swapped for
Postgres by changing one URL.

## Quick start (Docker)

```bash
GT7_PS_IP=<your playstation ip> docker compose up --build
```

Open http://localhost:8000 and start driving.

No PlayStation handy? Demo with the simulated source:

```bash
GT7_SOURCE=sim docker compose up --build
```

### Ports

| Port | Protocol | Purpose |
| --- | --- | --- |
| 8000 | HTTP | Dashboard, REST API, WebSocket |
| 33740 | UDP | Telemetry from the PlayStation |
| 33739 | UDP (outbound) | Heartbeat to the PlayStation |

> **Auto-discovery note:** broadcast discovery needs the container to share the LAN's
> broadcast domain. With the default bridge network, set `GT7_PS_IP` explicitly (recommended),
> or run with `network_mode: host` on Linux.

## Local development

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
GT7_SOURCE=sim python -m uvicorn app.main:app --reload
```

Frontend (Node 22+):

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api and /ws to :8000
```

Tests and linting:

```bash
cd backend
ruff check app tests scripts
pytest
```

## Configuration

All settings are environment variables (or a `.env` file in the working directory):

| Variable | Default | Description |
| --- | --- | --- |
| `GT7_SOURCE` | `udp` | `udp` (PlayStation) or `sim` (simulated laps) |
| `GT7_PS_IP` | *(empty)* | Console IP; empty = broadcast auto-discovery |
| `GT7_DB_PATH` | `data/gt7.db` | SQLite database path |
| `GT7_CARS_CSV` | `data/cars.csv` | Car ID → name lookup table |
| `GT7_WS_RATE` | `30` | Live stream rate to the browser (Hz) |
| `GT7_HTTP_PORT` | `8000` | HTTP port |

The bundled `cars.csv` only contains a sample entry. Fetch the full community-maintained
list with:

```bash
python backend/scripts/update_cars.py
```

## Lap files

Laps export/import as JSON (`Sessions → export` / `Import lap…`) with a versioned format
containing lap metadata plus full 60 Hz sample series (speed, inputs, position, fuel, …),
so laps can be shared or backed up.

## Troubleshooting

- **"Server up, no telemetry" (amber dot)** — check `GT7_PS_IP`, make sure the PlayStation
  and server are on the same network, and that UDP port 33740 isn't blocked by a firewall.
- **Wrong/garbled data (decode errors in `/api/status`)** — another tool may be consuming
  the stream, or the packet format changed after a game update.
- **No laps recorded** — laps are only recorded while the car is on track and not paused;
  the first (out) lap completes when you cross the start line.

## Screenshots

*(Add screenshots of the Live, Analysis, and Sessions views here.)*
