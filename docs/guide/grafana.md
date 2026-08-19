# Grafana telemetry analysis

The optional Grafana profile reads a dedicated `gt7-metrics.db`. It never receives the
primary application database or raw archive volume. The mirror is disposable derived
state: deleting it causes the current decoder to reconstruct it from primary lap JSON
and compatible archives.

## Start the bundled instance

```bash
docker compose --profile grafana up -d
```

Open `http://localhost:3000` (or set `GRAFANA_PORT`). The initial credentials default to
`admin` / `admin`; set `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` before starting
on a shared network. Compose pins Grafana OSS 13.1.1 and installs
`frser-sqlite-datasource` 4.0.6 synchronously. The datasource and the **GT7 Lap
Analysis** and **GT7 Packet Coverage** dashboards are provisioned automatically.

The application mounts `gt7-metrics` read/write at `/metrics`; Grafana mounts the same
volume read-only at `/var/lib/gt7-metrics`. SQLite uses rollback (`DELETE`) journaling,
foreign keys, batched lap transactions, and a busy timeout. Grafana therefore sees the
old complete lap or the new complete lap, never a partially replaced lap.

## Connect an existing Grafana

Install `frser-sqlite-datasource` 4.0.6, mount the metrics database read-only, and create
a datasource with an absolute path. In Compose that path is:

```text
/var/lib/gt7-metrics/gt7-metrics.db
```

Enable the plugin's query-only setting. The Grafana process must be able to traverse the
parent directory and read both the database and SQLite's transient lock state. Do not
point this datasource at `gt7.db` and do not mount `data/raw` into Grafana.

For a local non-container installation, set `GT7_METRICS_DB_PATH` to an absolute path and
give Grafana read access to that path. Unix timestamps exposed by `samples` are seconds,
as expected by the SQLite datasource.

See the [SQLite datasource documentation](https://grafana.com/grafana/plugins/frser-sqlite-datasource/)
and [Grafana provisioning documentation](https://grafana.com/docs/grafana/latest/administration/provisioning/)
when adapting the checked-in files.

## Public schema

| Table | Purpose |
| --- | --- |
| `sessions` | Source identity, car/track/note, archive fingerprint, decoder and mirror revision |
| `laps` | Timing, aggregates, clean/partial verdicts, format coverage, static gearing metadata |
| `samples` | One wide row per eligible tick, keyed by `(lap_id, sample_index)` |
| `events` | Event type, distance interval, severity, and four independent wheel flags |
| `channel_catalog` | Layer, source offset, storage type, format, native unit, confidence, formula, description |
| `lap_channel_provenance` | Per-lap availability and `live_capture`, `archive_replay`, `primary_fallback`, or `unavailable` source |
| `decoder_status` | Schema, exact supported sizes, byte coverage, and reject diagnostics |
| `mirror_status` | Backfill/reconciliation progress and latest error |

`samples` retains all 56 compatibility `SAMPLE_COLUMNS` under their existing names. Raw
protocol fields use a `native_` prefix, for example `native_speed_mps`,
`native_throttle_raw`, and `native_unknown_0x154_f32`. The prefix prevents native
evidence from being confused with transformed channels. It also contains packet size,
format, IDs, receiver ordering, nanosecond receipt time, decoder version, and row source.

The compatibility columns are:

```text
t, dist, speed, throttle, brake, coast, gear, rpm, boost, tire_slip,
yaw_rate, yaw_rate_signed, pos_x, pos_y, pos_z, velocity_x, velocity_y,
velocity_z, body_height, fuel, road_plane_x, road_plane_y, road_plane_z,
road_plane_distance, slip_fl, slip_fr, slip_rl, slip_rr, tt_fl, tt_fr,
tt_rl, tt_rr, sus_fl, sus_fr, sus_rl, sus_rr, aids, orientation_x,
orientation_y, orientation_z, orientation_w, steering_wheel_rad,
steering_angular_velocity, sway, heave, surge, throttle_filtered,
brake_filtered, torque_fl, torque_fr, torque_rl, torque_rr, energy_recovery,
steer_fl_rad, steer_fr_rad, surface
```

Packet-specific columns are `NULL` when that format did not emit the byte range. Missing,
non-finite, or misaligned history is also `NULL`; it is never synthesized as zero. Consult
`lap_channel_provenance` to distinguish live native capture, archive reconstruction,
primary compatibility fallback, and unavailable history. Complete historical native
coverage is only possible when a compatible complete `.gt7r` archive exists and aligns
unambiguously by car, lap, completion time, packet sequence, and persisted time grid.

## Example queries

Compare two laps by integrated distance:

```sql
SELECT lap_id, dist, speed, throttle, brake
FROM samples
WHERE lap_id IN (12, 19)
ORDER BY lap_id, sample_index;
```

Inspect every wheel independently:

```sql
SELECT t, slip_fl, slip_fr, slip_rl, slip_rr,
       susp_fl, susp_fr, susp_rl, susp_rr
FROM samples WHERE lap_id = 19 ORDER BY sample_index;
```

Research an undocumented field without assigning it a meaning:

```sql
SELECT t, native_unknown_0x154_f32, native_engine_rpm, native_speed_mps
FROM samples
WHERE lap_id = 19 AND native_unknown_0x154_f32 IS NOT NULL
ORDER BY sample_index;
```

Audit coverage and provenance:

```sql
SELECT c.name, c.source_offset, c.unit, c.confidence,
       p.source, p.available, p.diagnostic
FROM channel_catalog AS c
JOIN lap_channel_provenance AS p ON p.channel_name = c.name
WHERE p.lap_id = 19
ORDER BY c.source_offset, c.name;
```

The dashboard channel variable is generated directly from `channel_catalog`, so every
numeric known, unknown, padding, flag, normalized, and derived field can be selected. Use
receipt time, lap elapsed time, sample index, or integrated distance as the x-axis.
