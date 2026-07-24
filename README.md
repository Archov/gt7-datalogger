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
- **Admin view** — set the PlayStation IP and telemetry source (PlayStation / simulated) at
  runtime with no restart (persisted in the database), live log viewer with level filtering,
  connection diagnostics (packets, decode errors, uptime, connected clients), database
  stats with compact/clear actions, and one-click car-database updates.
- **Customizable overlay / dashboard** — a visual builder (Admin view) with a live preview:
  pick and reorder widgets (gear, speed, RPM, inputs, lap times, big delta, race position,
  tires, fuel, fuel strategy, in-game clock), choose a layout (transparent OBS strip,
  vertical stack, or phone dashboard grid), and tune scale, background opacity, and
  alignment. The whole config is encoded in the URL, so OBS, a phone, and a pit-wall
  tablet can each load their own setup.
- **Webhook / Discord notifications** — new personal bests and end-of-session summaries
  posted to any webhook URL (Discord URLs get a rich embed, others plain JSON).
- **CSV / MoTeC-compatible lap export** — open laps in MoTeC i2, Excel, or other analysis
  tools, alongside the existing JSON export.
- **Live race strategy** — fuel-to-empty countdown, pit-window lap, and race-distance fuel
  check computed from your rolling consumption, plus the in-game clock for endurance stints
  (time-of-day is also recorded per lap).
- **Track auto-identification** — name a circuit once (Sessions view) and every future
  session on it is tagged automatically from the lap geometry.

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

## Running on a Raspberry Pi (native, no Docker)

Docker is impractical on the smallest Pis — the official `python` and `node` images have
no ARMv6 build — so on a Raspberry Pi Zero W / Zero 2 W you run the backend natively and
serve a **pre-built** frontend. The capture workload itself is light (decrypt + decode a
~300-byte UDP packet at 60 Hz), so even a Zero W handles it comfortably.

> **Which Pi?** A **Pi Zero 2 W** (quad-core, runs 64-bit) is strongly recommended: on
> arm64 every dependency has a prebuilt wheel and the steps below "just work". A **Pi Zero W**
> (single-core, ARMv6) also works but depends on piwheels shipping ARMv6 wheels for the
> Rust-based packages (`pydantic-core`, `watchfiles`) — see the ARMv6 note at the end.

### 1. Build the frontend on your dev machine

Never run `npm run build` on the Pi (slow, and likely to run out of memory). Build it on
your laptop and copy the output across:

```bash
# on your dev machine, from the repo root
cd frontend
npm ci
npm run build          # produces frontend/dist

# copy the whole repo (or at least backend/ + frontend/dist) to the Pi
rsync -av --exclude node_modules --exclude .venv ../  pi@raspberrypi.local:~/gt7-datalogger/
```

The backend serves `frontend/dist` automatically when that folder is present, so no web
server or reverse proxy is needed.

### 2. Prepare the Pi

Use a current **Raspberry Pi OS (Trixie-based)** image, which ships Python 3.12+ (the
project requires ≥ 3.12). On an older Bookworm image you'd have to build Python 3.12
yourself. Install the build basics:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential
python3 --version      # must be 3.12 or newer
```

### 3. Install the backend

Raspberry Pi OS points pip at **piwheels**, which provides prebuilt ARM wheels for
`pydantic-core`, `pycryptodome`, and friends — this is what makes the install fast instead
of an hours-long compile.

```bash
cd ~/gt7-datalogger/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 4. Configure

Set the console IP (or leave it unset for broadcast auto-discovery) in an `.env` file in
the directory you launch from, or as environment variables:

```bash
# ~/gt7-datalogger/backend/.env
GT7_SOURCE=udp
GT7_PS_IP=192.168.1.50        # your PlayStation's IP
GT7_DB_PATH=/home/pi/gt7-data/gt7.db
GT7_CARS_CSV=data/cars.csv
```

### 5. Run it

```bash
cd ~/gt7-datalogger/backend
source .venv/bin/activate
python -m app.main            # listens on 0.0.0.0:8000
```

Open `http://<pi-ip>:8000` from any device on the LAN. Fetch the full car list once with
`python scripts/update_cars.py` (or from **Admin → Update car database**).

### 6. Start automatically with systemd

```ini
# /etc/systemd/system/gt7-datalogger.service
[Unit]
Description=GT7 Datalogger
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/gt7-datalogger/backend
EnvironmentFile=/home/pi/gt7-datalogger/backend/.env
ExecStart=/home/pi/gt7-datalogger/backend/.venv/bin/python -m app.main
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gt7-datalogger
journalctl -u gt7-datalogger -f      # follow the logs
```

Make sure the Pi and PlayStation share the same 2.4 GHz network and that UDP port 33740
is not firewalled.

> **ARMv6 (Pi Zero W) note:** if `pip install` tries to compile `pydantic-core` or
> `watchfiles` from source (i.e. piwheels has no wheel for the exact version), the build
> can take a very long time or exhaust the 512 MB of RAM. Options: pin to a package version
> piwheels does provide a wheel for, add temporary swap for the one-time build, or — the
> easy path — use a **Pi Zero 2 W** on 64-bit Raspberry Pi OS, where prebuilt wheels are
> always available.

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

The console IP, telemetry source, and log level can be changed at runtime from the
**Admin** view; those values persist in the database and override the environment on
the next start. Everything else is environment variables (or a `.env` file in the
working directory):

| Variable | Default | Description |
| --- | --- | --- |
| `GT7_SOURCE` | `udp` | `udp` (PlayStation) or `sim` (simulated laps) |
| `GT7_PS_IP` | *(empty)* | Console IP; empty = broadcast auto-discovery |
| `GT7_DB_PATH` | `data/gt7.db` | SQLite database path |
| `GT7_CARS_CSV` | `data/cars.csv` | Car ID → name lookup table |
| `GT7_WS_RATE` | `30` | Live stream rate to the browser (Hz) |
| `GT7_WEBHOOK_URL` | *(empty)* | Webhook for PB / session notifications (also settable in Admin) |
| `GT7_HTTP_PORT` | `8000` | HTTP port |

The bundled `cars.csv` only contains a sample entry. Fetch the full community-maintained
list with **Admin → Update car database**, or from the command line:

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
