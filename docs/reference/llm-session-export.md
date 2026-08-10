# LLM session export

**Sessions → Export for LLM** downloads one compact, distance-aligned JSON document for
analysis in ChatGPT or another LLM. It compares a whole stint without uploading every
60 Hz telemetry tick from every lap.

The envelope is identified by:

```json
{"format":"gt7-datalogger-llm-session","version":1}
```

Repeated data uses tables with `columns` declared once and numeric `rows`. Values are
rounded by meaning: milliseconds for time, 0.1 m for distances, 0.1 km/h for speed,
0.1 percent for inputs, 0.1 mm for body/suspension data, and four decimal places for
angles, angular velocity, and slip. Missing values are JSON `null`; a separate channel
availability table distinguishes missing telemetry from a real zero.

## Detail levels

- `compact` includes session/lap metadata, whole-lap chassis statistics, fixed-distance
  timing, reference-lap corner definitions, events, and recurring-event clusters.
- `standard` (the UI default) adds per-corner comparisons, a bounded list of interesting
  ranges, and approximately 5 m distance-resampled traces for those ranges.
- `deep` additionally includes original source-rate samples inside those same bounded
  ranges. It never embeds a complete raw lap.

The API is:

```text
GET /api/sessions/{session_id}/export.llm.json
    ?detail=standard
    &segment_m=100
    &ref=optional_lap_id
```

`segment_m` accepts 25–1000 m. Without `ref`, the exporter chooses the fastest clean
full lap, then the fastest full lap whose cleanliness is unknown, then the fastest dirty
full lap. Partial laps are never automatic references.

## Data and units

The document contains one units/schema section, session-wide and per-lap channel
availability, a lap table, whole-lap chassis summaries, exact fixed-distance timing
segments, reference-defined corner comparisons, enriched events, and recurring
problems. Standard/deep documents add interesting ranges and trace tables.

Speeds use km/h, distance uses metres, time uses milliseconds, inputs use percent,
body/suspension values use millimetres, and tire temperatures use Celsius. Steering is
radians and established angular velocities are radians/second. Slip is tire surface
speed divided by vehicle speed. Sway/heave/surge and torque/energy fields remain labeled
as raw GT7 values because their physical units are not established.

Powered-corner slip and anomaly selection are analysis heuristics, not official GT7
metrics. Signed steering and yaw are retained without assuming their sign conventions
match.

Packet C is required for front-wheel steering and per-wheel surface data. Packet B adds
steering-wheel and motion data, and Packet `~` adds filtered inputs and torque/energy
channels. Older captures remain usable, with unavailable analysis fields omitted or
`null`.

For archival data or unrestricted source-rate analysis, the existing per-lap raw JSON
and CSV exports remain available.
