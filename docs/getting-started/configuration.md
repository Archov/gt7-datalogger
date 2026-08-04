# Configuration

Most day-to-day settings — the console IP, telemetry source, log level, and webhook URL —
can be changed **at runtime from the Admin view** with no restart. Those values persist
in the database and override the environment on the next start.

Everything else is configured with environment variables, or a `.env` file in the
working directory.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `GT7_SOURCE` | `udp` | `udp` (PlayStation) or `sim` (simulated laps) |
| `GT7_PS_IP` | *(empty)* | Console IP; empty = broadcast auto-discovery |
| `GT7_PACKET_FORMAT` | `C` | Telemetry format requested from the console: `A`, `B`, `~`, or `C` (richest, needs GT7 v1.68+; also settable in Admin) |
| `GT7_DB_PATH` | `data/gt7.db` | SQLite database path — also accepts a full SQLAlchemy async URL (e.g. Postgres) |
| `GT7_CARS_CSV` | `data/cars.csv` | Car ID → name lookup table |
| `GT7_WS_RATE` | `30` | Live stream rate to the browser (Hz); capture stays at ~60 Hz |
| `GT7_WEBHOOK_URL` | *(empty)* | Webhook for race notifications (also settable in Admin) |
| `GT7_WEBHOOK_EVENTS` | *(all)* | Comma-separated events to send: `personal_best`, `session_summary`, `overtake`, `position_lost`, `off_road` (toggles in Admin) |
| `GT7_LOG_LEVEL` | `INFO` | Root log level (also settable in Admin) |
| `GT7_HTTP_HOST` | `0.0.0.0` | HTTP bind host |
| `GT7_HTTP_PORT` | `8000` | HTTP port |
| `GT7_TELEMETRY_PORT` | `33740` | Inbound telemetry UDP port |
| `GT7_HEARTBEAT_PORT` | `33739` | Outbound heartbeat UDP port |

!!! note "Precedence"
    Settings changed in the **Admin** view are persisted to the database and take
    precedence over environment variables on subsequent starts.

## The car database

Telemetry identifies the car by a numeric ID; a CSV lookup table maps IDs to names. The
bundled `cars.csv` only contains a sample entry. Fetch the full community-maintained
list either:

- from the UI: **Admin → Update car database**, or
- from the command line:

```bash
python backend/scripts/update_cars.py
```

## Units & browser settings

Display units (km/h vs mph) and other UI preferences are set from the dashboard itself
and persist in the browser's local storage — they are per-device, not server-side.

## Notifications

Set a webhook URL (environment variable or **Admin** view) to get:

- **New personal best** notifications as they happen
- **End-of-session summaries**
- **Overtakes** and **positions lost** (in race types where GT7 reports live positions)
- **Off-road excursions** (requires packet format C)

Every event type has its own toggle in the Admin view (`GT7_WEBHOOK_EVENTS` via env).
Discord webhook URLs receive a rich embed; any other URL receives plain JSON.
See [Admin view](../guide/admin.md) for details.
