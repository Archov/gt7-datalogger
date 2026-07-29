# Admin view

`#/admin` — runtime configuration, diagnostics, the overlay builder, and data
management. Settings changed here apply **immediately, no restart**, persist in the
database, and override environment variables on the next start.

## Connection

- **PlayStation IP address** — set or change the console IP at runtime; leave empty for
  broadcast auto-discovery. Applying resets discovery so the change takes effect at
  once.
- **Telemetry source** — switch between **PlayStation** (UDP capture) and **Simulated**
  (the built-in synthetic 60 Hz source) live. This is the in-app equivalent of
  `GT7_SOURCE=sim` — everything (live view, recording, analysis, overlay) works against
  the simulator.
- **Log level** — DEBUG / INFO / WARNING / ERROR, applied server-side immediately.

## Diagnostics

Auto-refreshing stats: telemetry connection state, console IP, packets received,
decode errors (amber when non-zero), server uptime, connected live clients,
session/lap counts, database size, and loaded car names. Two actions:

- **Restart telemetry source** — stop/start the current source (rebinds the UDP socket,
  restarts discovery).
- **Update car database** — downloads the community-maintained car list (from the
  [ddm999/gt7info](https://github.com/ddm999/gt7info) project) so car IDs resolve to
  real names. Run this once after install — the bundled `cars.csv` only has a sample
  entry.

## Notifications

Set a **webhook URL** to get notified about:

- **New personal bests** — fired the moment a session best is beaten (never on the
  first lap of a session), with lap, improvement, car, and track.
- **Session summaries** — when a session ends, with car, track, lap count, best lap,
  and fuel used.

**Discord** webhook URLs get a rich embed; **any other URL** receives plain JSON
(snake-cased fields), so n8n / Home Assistant–style automations work out of the box.
The **Test** button sends a test event so you can verify delivery. Notifications are
fire-and-forget — a failed delivery logs a warning and never blocks capture.

## Overlay & dashboard builder

Documented on its own page: [Overlay & streaming](overlay.md).

## Logs

A live viewer over the server's in-memory log ring buffer (last 2,000 records):
severity filter (`DEBUG+` … `ERROR+`), pause/resume, clear, auto-scroll that only
follows when you're already at the bottom. This is the first place to look when
telemetry isn't arriving.

## Data management

- **Compact database** — SQLite `VACUUM` to reclaim space after deleting laps.
- **Delete all recorded data** — removes **every session and lap** (confirmed). Settings
  and track signatures are kept. Export any laps you want to keep first
  (Sessions → json).
