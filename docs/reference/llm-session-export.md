# LLM session export

**Sessions → Export for LLM** downloads one compact, distance-aligned JSON document for
analysis in ChatGPT or another LLM. It compares a whole stint without uploading every
60 Hz telemetry tick from every lap.

The download filename is
`<SessionID>-<YYYY-MM-DD_HH-mm-ss>-<Car-Name>-<Track-Name>-<LapCount>-Laps-llm.json`.
The timestamp is the session start in the app host's local timezone. Car and track
components contain ASCII letters and numbers separated by hyphens, are capped at 60
characters, and fall back to `Unknown-Car` or `Unknown-Track` when unavailable.

The envelope is identified by:

```json
{"format":"gt7-datalogger-llm-session","version":1}
```

Repeated data uses tables with `columns` declared once and numeric `rows`. Values are
rounded by meaning: milliseconds for time, 0.1 m for distances, 0.1 km/h for speed,
0.1 percent for inputs, 0.1 mm for body/suspension data, and four decimal places for
angles, angular velocity, and slip. Missing values are JSON `null`; a separate channel
availability table distinguishes missing telemetry from a real zero.
`channel_provenance` additionally groups each lap's channels by `persisted`,
`archive_replay`, or `unavailable`; provenance is not repeated in sample rows. Successful
on-demand recovery is committed before export and therefore appears as `persisted`.

## Detail levels

- `compact` includes session/lap metadata, whole-lap chassis statistics, fixed-distance
  timing, reference-lap corner definitions, events, recurring-event clusters, and
  per-corner racing-line metrics. It remains trace-free.
- `standard` (the UI default) adds per-corner comparisons, a bounded list of interesting
  ranges, approximately 5 m distance-resampled traces for those ranges, whole-lap
  reference geometry at 10 m, and projected racing-line traces at 10 m.
- `deep` additionally includes original source-rate samples inside those same bounded
  ranges and uses a 5 m grid for the whole-lap spatial tables. It never embeds a
  complete raw lap.

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

The lap table reports `fuel_consumed` and `fuel_refueled` in litres. Both are derived
from successive per-tick tank levels: downward changes are gross fuel burned and upward
changes are fuel added. Consequently, a pit stop cannot cancel the fuel burned earlier
on that lap. Historical rows written with the former start-minus-end calculation are
recovered directly from their stored tick series during export.

Standard/deep also add deterministic wheelspin characterization. The
`drivetrain_characterization` object preserves a per-car override alongside
torque-derived inference and conflicts. The `wheelspin_characterization` table separates
observations, comparator-relative derivations, onset sequence, comparator quality, and
bounded candidate evidence. Scores are heuristic rankings, not probabilities or causal
diagnoses. Torque remains in raw GT7 units; combined-load candidates use vehicle-motion
proxies and do not measure tire force or friction-circle saturation. Bottoming alone does
not invalidate a comparator or prove physical contact.

The characterization payload is nested columnar: its `*_columns` registries decode the
positional observation, derivation, sequence, comparator-quality, comparator, candidate,
and evidence rows. `resolution` is `resolved` or `mixed_or_unresolved`; unresolved state
is not a candidate and is accompanied by stable `unresolved_reasons`. Every stored
wheelspin event gets a row, including comparison-excluded or unalignable events. Ideal
controls stay at or below 1.10 peak slip; relative controls may cross that value when
they meet the documented peak/integral/duration dominance gate. `reference_corner` is
strict containment, while `context_corner` is descriptive nearest-corner context only.

`corner_line_analysis` is present at every detail level. It reports entry/apex/exit
lateral offset and heading error, line offset RMS/peak, projected path length and
curvature, plus RMS and peak projection distance. Standard/deep also include:

- `spatial_reference`: the selected reference lap's physical path, heading, and
  curvature on a uniform reference-progress grid.
- `line_traces`: one dynamic nested table per usable full lap. Each row includes
  reference progress, elapsed `time_ms`, actual world position, signed lateral offset,
  `projection_distance_m`, heading error, curvature, unsigned `speed_kmh`, signed
  `along_track_speed_kmh`, compact chassis heading/body-slip evidence, controls, and
  only the optional steering/yaw channels that lap actually recorded.

`chassis_heading_error_deg` compares the direction the vehicle nose points with the
selected reference direction. `body_slip_angle_deg` is
`wrap(travel_heading - chassis_heading)` and deliberately does not claim an automotive
left/right sign. It is `null` below 0.1 m/s horizontal motion. These differ from
`heading_error_deg` (the driven trajectory direction) and `yaw_rate_signed` (rotation
rate). The source quaternion maps vehicle-local coordinates to world coordinates in
`(x,y,z,w)` order; local `-Z` is the nose, local `+Y` is chassis up, and world `Y` is
elevation.

Spatial alignment projects each lap's recorded X/Y/Z position onto a continuity-bounded
reference polyline. If either path lacks Y, it falls back to X/Z. Reference progress and
path length use 3D arc length when reference Y is available; heading and curvature always
use the planar X/Z path. Positive lateral offset means left of the selected reference
lap's direction of travel; negative means right. The internal 2 m corner grid is separate
from the 10 m standard and 5 m deep public grids, and final partial grid intervals are
retained.

The reference path is one selected driven lap, not a surveyed track centerline.
Projection distance is the Euclidean distance from the actual lap position to its
selected projected point (3D when both paths have Y, X/Z otherwise). It is diagnostic
fit/confidence evidence, not a driving-quality score or a rejection threshold. Large
values can legitimately identify off-line driving, a spin, or an excursion; continuity
bounds prevent an unrestricted remap to a nearby unrelated section of track.

Line-trace `time_ms` is elapsed lap time at the corresponding spatial reference
progress. Duplicate projected progress keeps the latest elapsed time, so stops, spins,
and backward travel remain visible as time loss; a completed lap that reaches the
reference endpoint uses its stored finish time there without rescaling earlier values.

`along_track_speed_kmh` is derived from a five-sample centered world-position
difference before projected progress is clamped or coalesced. It is the signed velocity
component along the local selected-reference tangent: positive follows the normal
reference direction, zero is stationary or purely lateral, and negative is physical
motion in the opposite direction. XYZ is used when both paths have Y, otherwise X/Z.
Negative motion does not imply that GT7 reported reverse gear, and the comparison
progress axis intentionally remains monotonic.

The `events` table may contain export-derived `reverse_motion` rows. Detection enters
below -2.0 km/h, exits at -0.5 km/h, requires at least 500 ms of meaningful reverse
motion, and bridges near-zero interruptions up to 200 ms unless forward speed exceeds
0.5 km/h. These rows append `start_progress_m`, `end_progress_m`,
`peak_along_track_speed_kmh`, and `backward_distance_m`. Their generic `severity` is
`null`; the signed peak speed and integrated backward distance are the magnitude
evidence. The existing `start_m`/`end_m` fields remain cumulative driven distance; the
new progress fields are their spatial reference locations. Reverse events are
reference-dependent LLM-export evidence and are not added to stored raw-lap events.

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

When a requested normalized channel is absent from an historical lap, the export path
can recover it on demand from that session's complete raw `.gt7r` archive. Replay uses
the current production packet parser and lap processor, matches a reconstructed lap by
car ID, GT7 lap number, and completed lap time, then aligns recovered data onto the
persisted lap-relative time grid. Existing persisted channels always win. Missing
recovered channels are added atomically to old sample blobs. Missing, interrupted,
truncated, or corrupt archives simply leave the channel unavailable; outcomes are cached
per archive fingerprint and hydration version to prevent repeated failed replay.

For archival data or unrestricted source-rate analysis, the existing per-lap raw JSON
and CSV exports remain available.
