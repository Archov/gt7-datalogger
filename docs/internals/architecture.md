# Architecture

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

## One process, one event loop

The whole backend is a **single-process, single-threaded asyncio** application
(FastAPI + uvicorn). There are no worker threads or subprocesses. The data flow is:

```
UdpTelemetrySource (or SimTelemetrySource)
        │  decrypt + parse (~60 Hz)
        ▼
   asyncio.Queue (600 packets ≈ 10 s buffer)
        │  single consumer task — strictly ordered
        ▼
TelemetryService._on_packet
        ├──▶ LapProcessor.feed  ──▶ lap/session callbacks ──▶ SQLite (async)
        └──▶ WebSocket broadcast (rate-limited to GT7_WS_RATE, default 30 Hz)
```

Design points worth knowing:

- **Strict ordering** — exactly one consumer task drains the packet queue, so lap
  detection never runs concurrently with itself. Overlapping feeds could duplicate a lap
  save while a database write is in flight.
- **Backpressure that favors freshness** — if the queue fills (e.g. a slow disk stalls a
  write), the *oldest* packet is dropped and counted in `packets_dropped`, so the live
  view always shows current data.
- **Commit before await** — inside the lap processor, all state transitions (lap counter,
  sample buffer, fuel/engine aggregates) are committed *before* any `await`. At 60 Hz, a
  lap boundary that stayed "open" across an await would re-trigger and duplicate laps.

## Why FastAPI?

Native async fits a 60 Hz UDP stream plus WebSocket fan-out in one process; Pydantic
gives typed models and settings; and the Python ecosystem has mature Salsa20 support
(`pycryptodome`).

## Storage

SQLite via SQLAlchemy 2.x **async** engine (`sqlite+aiosqlite`). Because the storage
layer only sees a SQLAlchemy URL, SQLite can be swapped for Postgres
(`postgresql+asyncpg://…`) by changing `GT7_DB_PATH` — no code changes.

Four tables:

| Table | Contents |
| --- | --- |
| `sessions` | one row per driving session: start time, car ID/name, note, track name |
| `laps` | one row per lap: timing, per-lap metrics, detected events (JSON), gearing (JSON), and the **full 60 Hz sample series** (JSON) |
| `tracks` | named track signatures for auto-identification (length + bounding box) |
| `settings` | runtime overrides set from the Admin view (console IP, source, log level, webhook URL) |

Schema evolution is handled with an idempotent additive-column migration list — on
startup, missing columns are added with `ALTER TABLE`, so old databases upgrade in place.

**No downsampling on write**: every 60 Hz tick of a lap is stored. Downsampling happens
at *read* time — the analysis endpoints resample onto a uniform distance grid (default
5 m steps), and the live WebSocket stream is capped at `GT7_WS_RATE` (default 30 Hz).

## Frontend

React 18 + TypeScript, built with Vite, styled with Tailwind. High-frequency charts
(the stacked analysis panels, race line map, sparklines) render with **ECharts**, which
handles thousands of points per series without breaking a sweat. State lives in small
stores (settings, telemetry, analysis); the current analysis view is fully encoded in
the URL hash so links reproduce exact comparisons.

In production the backend serves the built frontend from `frontend/dist` — one container,
one port. `GET /overlay` returns the SPA directly (a plain path, because some streaming
apps reject URLs with `#fragment`s).

## The simulator

`GT7_SOURCE=sim` replaces the UDP listener with a deterministic synthetic source: a
3,200 m rounded-rectangle circuit driven at 60 Hz with two braking zones, deliberate
front lockups under braking, rear wheelspin on slow launches, a kerb strike, and
TCS/ASM/rev-limiter activity. Lap detection, event detection, charts, and the overlay
all get realistic data with no console — it's how the project is developed, demoed, and
screenshotted.
