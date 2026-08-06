# REST & WebSocket API

Everything the dashboard does goes through this API, so anything the UI can do, a
script can too. All REST routes live under `/api`; responses are JSON.

## Status & health

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | `{"status": "ok"}` |
| GET | `/api/status` | source kind, connection state, packet/error counters, recording flag, current session id, track name |

## Sessions & laps

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/sessions` | all sessions, newest first, with lap count and best lap |
| DELETE | `/api/sessions/{id}` | delete a session and its laps |
| GET | `/api/sessions/{id}/laps` | lap summaries for one session |
| GET | `/api/laps` | all lap summaries, newest first |
| GET | `/api/laps/{id}?samples=true` | full lap detail: metrics, events, gearing, and (optionally) the 60 Hz samples |
| DELETE | `/api/laps/{id}` | delete a lap |
| GET | `/api/laps/{id}/export` | JSON export envelope (see [Lap file format](lap-file-format.md)) |
| GET | `/api/laps/{id}/export.csv` | MoTeC-compatible CSV (one row per tick, 27 channels with units) |
| POST | `/api/laps/import` | import an exported lap file |

## Tracks

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/tracks` | stored track signatures |
| POST | `/api/tracks` | `{name, lap_id}` — name a circuit from a lap's geometry |
| DELETE | `/api/tracks/{id}` | remove a signature (session data untouched) |

## Overlay / dashboard layouts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/layouts` | all saved layouts with their grid configs |
| GET | `/api/layouts/{ref}` | one layout by numeric id or name (id wins if both match) |
| POST | `/api/layouts` | `{name, kind: "overlay"\|"dash", config}` — 409 on duplicate name |
| PUT | `/api/layouts/{id}` | `{name?, config?}` — rename and/or replace the config |
| DELETE | `/api/layouts/{id}` | delete the layout |

Configs are v2 grid layouts (`{version: 2, grid, cells, …}`) as produced by the Admin
builder; the server only checks the version and a 64 KB size cap.

## Analysis

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/analysis/compare` | `laps` (CSV ids), `ref` (id), `step` (m, default 5, 0.5–50), `channels` (optional CSV) → per-lap distance-resampled series, speed peaks/valleys, events, and delta-vs-reference |
| GET | `/api/analysis/deviation` | `session_id`, `count` (2–20, default 5) → median speed + standard deviation by distance across the best N laps |
| GET | `/api/analysis/fuel` | `lap_id` → relative fuel-map table for settings −5…+5 |

Default compare channels: `t, speed, throttle, brake, coast, gear, rpm, boost,
tire_slip, yaw_rate, pos_x, pos_z`. Any other stored column can be requested via
`channels=`; `t`, `pos_x`, `pos_z` are always included (the delta and map need them).
Delta values are milliseconds, **positive = slower than the reference**.

## Controls

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/control/recording` | `{"recording": bool}` — pause/resume lap recording |
| POST | `/api/control/log-lap-now` | save the in-progress lap immediately (409 if none) |

## Admin

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/admin/settings` | current runtime settings |
| PUT | `/api/admin/settings` | `{ps_ip?, source?, log_level?, webhook_url?, webhook_events?, packet_format?, race_engineer?, race_engineer_verbosity?, race_engineer_categories?, race_engineer_units?}` — applied live, persisted to the DB |
| POST | `/api/admin/test-webhook` | send a test notification |
| GET | `/api/admin/race-engineer` | Race Engineer diagnostics: counters, detector state, connected voice clients, last callout |
| POST | `/api/admin/race-engineer/test` | `{text?, event_type?}` — inject a callout into every connected browser |
| GET | `/api/admin/logs` | `limit` (≤2000), `level` — recent log records from the ring buffer |
| DELETE | `/api/admin/logs` | clear the ring buffer |
| GET | `/api/admin/stats` | uptime, DB stats, source stats, client count, LAN IP |
| POST | `/api/admin/restart-source` | stop/start the telemetry source |
| POST | `/api/admin/clear-data` | delete **all** sessions and laps (settings/tracks kept) |
| POST | `/api/admin/vacuum` | SQLite `VACUUM` |
| POST | `/api/admin/update-cars` | download the community car list and reload the lookup |

## WebSocket — `/ws/live`

One endpoint. Traffic is overwhelmingly server-push; the only client → server
messages are the Race Engineer voice protocol (below), and anything else a client
sends is ignored. Every message is `{"type": ..., "data": ...}`.

Server → browser:

- **`telemetry`** — the live frame, throttled to `GT7_WS_RATE` (default 30 Hz):
  speed, RPM + redline, gear + suggested gear, throttle/brake %, boost, fuel level and
  capacity, lap counters, best/last lap, session best and previous best, race position,
  tire temps (FL/FR/RL/RR), tire slip, water/oil temps, oil pressure, driver-aids
  bitmask (TCS=1, ASM=2, handbrake=4, rev limiter=8), car id/name, world position,
  in-game time of day, track name, on-track/paused flags.
- **`lap`** — sent when a lap is saved: id, session, number, time, per-lap metrics, and
  event counts. The UI uses this to refresh lists live.
- **`session`** — sent on new session, track identification, or track naming.
- **`status`** — sent on connect and whenever the source or console IP changes.
- **`voice_callout`** — a Race Engineer callout: `id`, `event_type`, `text`,
  `category`, `priority` (0–100), `created_at_ms`, `expires_at_ms`, `ttl_ms`,
  `interrupt`, `dedupe_key`, `message_key`/`message_args` (localization) and
  `metadata`. Sent to every client; only the active speaker should voice it.
- **`voice_output_status`** — `{active_client_id}`: which browser may speak.
- **`race_engineer_status`** — feature enabled/active, verbosity, emitted categories,
  and the connected voice-capable clients.

Browser → server (Race Engineer only; never token-gated, and unparseable messages are
ignored so older pages keep working):

| Message | Data |
| --- | --- |
| `client_capabilities` | `client_id`, `page`, `voice_supported`, `voice_enabled` |
| `claim_voice_output` | `client_id` |
| `release_voice_output` | `client_id` |
| `voice_callout_ack` | `callout_id`, `client_id`, `status`, `spoken_at_ms`, `reason?` |

Ack statuses: `spoken`, `expired`, `duplicate`, `disabled`, `category_disabled`,
`not_active_speaker`, `interrupted` (stopped on purpose — a critical callout, a
disconnect, or the user pressing Test voice) and `speech_error`, which carries the
engine's own `reason`. Acks are diagnostics only and never gate the pipeline.

On connect the client immediately receives a `status` and a `race_engineer_status`
message — never past callouts, which are live events. The frontend auto-reconnects
every 2 s if the socket closes.

!!! note "CORS"
    CORS is wide open (`*`) — the API is designed for a trusted home network, not
    public exposure. Don't port-forward it to the internet.
