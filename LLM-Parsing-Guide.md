# GT7 LLM Session Export Parsing Guide

This guide is for an LLM or software agent analyzing a JSON file produced by
**Export for LLM**. It describes the wire shape, joins, units, sign conventions,
derived evidence, missing-data rules, and a reliable analysis order.

## 1. Validate before analyzing

The document must begin with this identity:

```json
{"format":"gt7-datalogger-llm-session","version":1}
```

Reject or explicitly qualify conclusions from an unknown `format` or `version`.
`options.detail` is `compact`, `standard`, or `deep`; `options.segment_m` is the
requested fixed timing-segment length in metres.

The JSON is deterministic and strict:

- no `NaN` or infinity;
- unavailable numeric values are `null`;
- unavailable trace channels are omitted from that trace's `columns`;
- zero is a real recorded or derived value unless specifically documented otherwise;
- repeated data is columnar to reduce tokens.

Never treat `null`, an omitted column, and numeric zero as equivalent.

## 2. Decode columnar tables

Most values use this shape:

```json
{"columns":["lap_id","time_ms"],"rows":[[42,91234],[43,91880]]}
```

Interpret each row positionally. Conceptually:

```python
records = [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]
```

Do not infer a fixed position without consulting the adjacent `columns` array.
Optional channels make this especially important for nested traces.

There are two nested-table forms:

```json
{"columns":["lap_id","columns","rows"],"rows":[[42,["progress_m","speed_kmh"],[[0,100]]]]}
```

```json
{"columns":["range_id","lap_id","columns","rows"],"rows":[[1,42,["distance_m","speed"],[[500,120]]]]}
```

Decode the outer row first, then zip its nested `columns` and `rows`. Never assume
two laps or ranges have identical nested columns.

## 3. Top-level contents by detail level

| Key | Compact | Standard | Deep | Meaning |
| --- | :---: | :---: | :---: | --- |
| `format`, `version`, `options`, `schema` | yes | yes | yes | Contract and embedded notes |
| `session` | yes | yes | yes | Session metadata and channel union |
| `channel_availability` | yes | yes | yes | Structurally usable channels per lap |
| `channel_provenance` | yes | yes | yes | Persisted/replayed/unavailable sources |
| `reference` | yes | yes | yes | Selected comparison lap and reason |
| `laps` | yes | yes | yes | One summary row per persisted lap |
| `whole_lap_chassis` | yes | yes | yes | Time-weighted whole-lap statistics |
| `timing_segments` | yes | yes | yes | Exact reference-defined segment timing |
| `reference_corners` | yes | yes | yes | Corners detected once on the reference |
| `events` | yes | yes | yes | Stored and export-derived events |
| `recurring_events` | yes | yes | yes | Repeated lockup/wheelspin/bottoming clusters |
| `corner_line_analysis` | yes | yes | yes | Compact spatial line metrics per corner |
| `corner_analysis` | no | yes | yes | Detailed per-corner driving comparison |
| `interesting_ranges` | no | yes | yes | Bounded evidence windows |
| `detail_traces` | no | yes | yes | Reason-selected 5 m distance traces |
| `spatial_reference` | no | yes | yes | Reference path geometry; 10 m or 5 m |
| `line_traces` | no | yes | yes | Whole-lap projected line evidence |
| `drivetrain_characterization` | no | yes | yes | Override plus torque-derived powered-wheel evidence |
| `wheelspin_characterization` | no | yes | yes | Heuristic event mechanism compatibility ranking |
| `source_traces` | no | no | yes | Bounded stored-rate samples |

`spatial_reference` and `line_traces` are omitted if usable reference geometry is
unavailable. `corner_line_analysis` then remains present with no rows.

## 4. IDs, lap eligibility, and reference policy

- `lap_id` is the database/export identity used internally for every join.
- `gt7_lap` is the sequential GT7/internal lap number; it is not necessarily globally
  unique outside its session.
- `session.id` is the session ID.
- Join tables by `lap_id`, ranges by `range_id`, and corner tables by `corner`.
- Row order is deterministic, but use IDs rather than relying on position.

User-facing lap identity is mandatory: resolve each relevant `lap_id` through the
`laps` table, then write `Lap N` using its `gt7_lap`. Do not normally expose database
IDs in prose. Technical/debug output, when necessary: `Lap 7 (lap_id 70)`; never only
`lap_id 70`. Apply this convention to comparisons, events, recurring events, corners,
ranges, line/chassis analysis, and setup recommendations. Continue using `lap_id`
internally for all joins.

`laps.counts_for_best` is an eligibility flag for normal best-lap and reference-lap
comparison. `true` means eligible; `false` means deliberately excluded from those
comparisons. A partial/manual lap is false, but the inverse is not safe: a completed pit
lap or another intentionally excluded completed lap can also be false. Do not use this
flag alone to claim that a lap was incomplete.

Rows with `counts_for_best=false` remain visible in lap, chassis, and event evidence,
but are excluded from reference selection, distance-aligned timing, corner comparisons,
recurrence, spatial comparisons, and traces. Their `delta_to_reference_ms` is `null`.
The export's stable reference reason codes contain the historical phrase `full_lap`;
interpret that phrase as a structurally usable, comparison-eligible lap.

`clean_lap` is tri-state:

- `true`: recorded surface data found no qualifying off-track excursion;
- `false`: known dirty;
- `null`: cleanliness could not be established.

Automatic reference selection uses this order:

1. fastest structurally usable, comparison-eligible lap with `clean_lap=true` →
   `fastest_clean_full_lap`;
2. fastest structurally usable, comparison-eligible lap with `clean_lap=null` →
   `fastest_full_lap_cleanliness_unknown`;
3. fastest dirty structurally usable, comparison-eligible lap →
   `fastest_dirty_full_lap`.

An explicitly requested structurally usable, comparison-eligible lap, including a dirty
one, has reason `explicit`.
The selected reference is a comparison baseline, not proof of an ideal lap.

## 5. Units, precision, and common signs

| Suffix/name | Unit or interpretation |
| --- | --- |
| `_m` | metres |
| `_mm` | millimetres |
| `_ms` | milliseconds |
| `_kmh` | kilometres/hour |
| `_pct` | percent |
| `_rad` | radians |
| `_rad_s` / `_signed` yaw | radians/second |
| `_deg` | degrees |
| `_1_per_m` | inverse metres |
| slip | wheel surface speed divided by vehicle speed |

Typical rounding is 1 ms; 0.1 m; 0.1 km/h; 0.1%; 0.1 mm; four decimals for
steering, angular velocity, slip, and raw motion values; six decimals for curvature.
Fuel fields generally retain three decimals.

Delta conventions:

- time delta = lap minus reference; positive means the lap lost time;
- `brake_point_delta_vs_reference_m` = lap brake point minus reference; negative is
  earlier braking, positive is later;
- `minimum_speed_delta_vs_reference_kmh` = lap minimum minus reference minimum;
- positive `lateral_offset_m` is left of the reference path in its direction of travel;
- `body_slip_angle_deg = wrap(travel_heading - chassis_heading)` in `(-180,180]`.
  Its sign is the raw X/Z angular convention, not a claimed automotive left/right sign.

## 6. Two distance axes that must not be mixed

### Cumulative driven distance

Fields named `distance_m`, `start_m`, `end_m`, corner `entry_m`/`apex_m`/`exit_m`,
and timing segment boundaries use the lap processor's cumulative driven `dist`. It is
integrated from speed and remains monotonic even during a spin or reversal. Different
lines can accumulate different total distances.

### Spatial reference progress

Fields named `progress_m`, `start_progress_m`, and `end_progress_m` use arc length along
the selected reference lap's physical polyline. Other laps are continuity-constrained
projections onto that polyline. This is the correct axis for racing-line comparison.

The reference uses X/Y/Z arc length when Y exists and X/Z otherwise. Heading and
curvature always use the planar X/Z path. Projection searches only a bounded window
near the last accepted progress, and accepted progress is nondecreasing; it cannot
globally jump to an unrelated nearby track section.

Do not directly subtract a cumulative-distance location from a spatial-progress
location. Use tables that already share the same axis.

### User-facing track locations

Never report a metre position/range without a same-axis corner-relative description.
Retain metres for precision, but write forms such as `500–600 m, on the approach to
Turn 2`, `around 1,340 m, between Turns 4 and 5`, or `3,680–3,760 m, through the exit of
Turn 8`.

- Cumulative-distance locations: compare only with `reference_corners.entry_m`,
  `apex_m`, and `exit_m`; handle wrapping corners circularly around start/finish.
- Spatial-progress locations: use same-axis spatial corner evidence, principally
  the selected reference lap's `corner_line_analysis.peak_curvature_progress_m` and
  adjacent spatial corner order. Never compare `progress_m` directly with cumulative
  `entry_m`/`apex_m`/`exit_m`; do not claim entry/exit precision from apex anchors alone.
- Supported descriptions: `approach to Turn N`, `entry to Turn N`, `through Turn N`,
  `around the apex of Turn N`, `exit of Turn N`, `between Turns N and N+1`, or `the
  straight between Turns N and N+1`.
- No supported same-axis corner relationship => omit the metre location from the
  user-facing answer rather than inventing a translation.
- Do not invent official corner names absent from the export.

## 7. Availability and provenance

`channel_availability` columns:

```text
lap_id, channels
```

The channel array is the usable normalized telemetry for that lap in this export's
resolved, in-memory view. It can include channels supplied on demand by
`archive_replay`; it does not necessarily describe only fields physically stored in a
historical lap's `samples_json`. An absent channel means unavailable, not zero. Legacy
all-zero `surface` arrays are treated as unavailable.

`channel_provenance` columns:

```text
lap_id, persisted, archive_replay, unavailable
```

- `persisted`: already present in the saved normalized lap;
- `archive_replay`: recovered on demand from the session's raw packet archive;
- `unavailable`: requested but neither persisted nor safely recoverable.

Persisted data always takes precedence. Archive replay is read-only and aligned to the
persisted lap identity/time grid; it does not rewrite historical samples. Provenance is
confidence/context metadata, not a quality ranking. Currently it is especially relevant
to historical orientation recovery.

Packet-format channel groups:

- base/A: time, distance, speed, inputs, gear/RPM/boost, position, quaternion
  orientation, yaw, road plane, body/fuel, per-wheel slip/temperature/suspension, aids;
- B: steering-wheel angle/angular velocity and sway/heave/surge;
- `~`: filtered inputs, four torque values, energy recovery;
- C: front-wheel steering, packed per-wheel surface, wheelbase/category metadata.

An optional group is omitted for a lap if it was not consistently available. Do not
fabricate missing optional channels from zeros.

The following is the canonical normalized sample-channel registry. These names can
appear in availability lists; the trace registries select subsets of them.

<!-- canonical-sample-channels:start -->
```text
t, dist, speed, throttle, brake, coast, gear, rpm, boost, tire_slip,
yaw_rate, yaw_rate_signed,
pos_x, pos_y, pos_z,
body_height, fuel,
road_plane_x, road_plane_y, road_plane_z, road_plane_distance,
slip_fl, slip_fr, slip_rl, slip_rr,
tt_fl, tt_fr, tt_rl, tt_rr,
sus_fl, sus_fr, sus_rl, sus_rr, aids,
orientation_x, orientation_y, orientation_z, orientation_w,
steering_wheel_rad, steering_angular_velocity, sway, heave, surge,
throttle_filtered, brake_filtered,
torque_fl, torque_fr, torque_rl, torque_rr, energy_recovery,
steer_fl_rad, steer_fr_rad, surface
```
<!-- canonical-sample-channels:end -->

Normalized sample units are defined by capture-time normalization, not inferred from
field names:

- `t` is elapsed seconds and `dist` is cumulative metres;
- `speed` is km/h; throttle, brake, and filtered inputs are percent; `coast` is a flag;
- positions are metres; quaternion components are unitless;
- `body_height` and `sus_fl/fr/rl/rr` are converted from metres to millimetres;
- fuel is litres, tire temperatures are degrees Celsius, and boost is bar;
- steering is radians; yaw and steering angular velocity are radians/second;
- road-plane, sway/heave/surge, torque, and energy-recovery values retain raw GT7 units;
  in particular, do not interpret `road_plane_distance` as metres;
- slip channels are ratios, `gear` is an integer code, and `surface`/`aids` are masks.

Dynamic tables may rename fields with explicit unit suffixes. Trust each table's own
column names and the embedded `schema.units`; do not assign physical units to values the
schema identifies as raw.

## 8. Session, lap, and chassis tables

`session` contains at least `id`, `started_at`, `car_id`, `car_name`, `track_name`,
`note`, `lap_count`, `available_telemetry_channels`, and `telemetry_formats`.
`telemetry_formats` may contain `A`, `B`, `~`, `C`, or `unknown`.
`available_telemetry_channels` is the union of the same resolved export-time lap view
described by `channel_availability`.

`laps` columns:

```text
lap_id, gt7_lap, time_ms, delta_to_reference_ms, finished_at,
counts_for_best, clean_lap, off_track_count,
fuel_start, fuel_end, fuel_consumed,
full_throttle_pct, full_brake_pct, coast_pct, tire_spin_pct,
max_speed_kmh, minimum_body_height_mm, tcs_pct, asm_pct,
lockup_count, wheelspin_count, bottoming_count, kerb_count,
gear_ratios, gearing_top_speed, rpm_alert,
packet_format, wheelbase_m, car_category, fuel_capacity
```

`off_track_count=-1` means unknown. `gearing_top_speed` is the packet's configured
transmission top-speed value, used as the top-gear speed-scaling reference. It is not
the final-drive ratio and is not the maximum speed actually achieved on the lap.
Counts summarize persisted event types; export-time
`reverse_motion` does not change stored event counts.

`whole_lap_chassis` begins with `lap_id` and contains time-weighted statistics:

- body height: min/mean/p05/p95;
- suspension per `fl/fr/rl/rr`: min/mean/p95/max;
- tire temperature per wheel: min/mean/max/p05/p95;
- slip per wheel: mean/p95/max;
- front/rear average slip and left-right imbalance means;
- powered-corner rear-slip mean/p95;
- front and steering-wheel mean/peak absolute angle;
- steering angular-velocity mean/peak absolute value;
- sway/heave/surge mean/peak absolute value;
- signed/absolute/peak yaw;
- requested-minus-filtered throttle/brake differences;
- time-weighted tarmac/kerb/loose wheel-contact shares;
- off-track excursion count.

Powered-corner rear slip is a heuristic. It requires throttle at least 70%, speed
50–220 km/h, and meaningful cornering activity: absolute yaw ≥0.05 rad/s, front
steering ≥0.01 rad, or steering-wheel rotation ≥0.05 rad.

Surface percentages are wheel-contact time shares, so their denominator is wheel-time,
not simply the percentage of samples where any wheel touched that surface.

Tire temperatures are observations only. Do not label them overheated or underheated
unless a validated operating range for the relevant car, tire, and conditions is
supplied.

## 9. Timing segments

`timing_segments` columns:

```text
lap_id, start_m, end_m, segment_time_ms,
segment_delta_vs_reference_ms, cumulative_delta_vs_reference_ms,
minimum_speed_kmh, average_speed_kmh
```

Boundaries come from zero to the reference lap's finish using `options.segment_m`; the
last segment may be shorter. Ordinary boundaries use exact elapsed-time interpolation.
The final segment uses each comparison-eligible lap's stored finish time once it reaches the final
segment start. This ensures final cumulative delta equals stored lap-time delta even if
a lap's recorded distance ends slightly before or after the reference.

Interpretation:

- positive segment delta = time lost in that segment;
- negative segment delta = time gained;
- cumulative delta is the gap at the segment end;
- a missing lap/segment row means the lap did not reach the required boundary or was
  not structurally usable and comparison-eligible.

## 10. Reference corners and corner comparisons

`reference_corners` columns:

```text
corner, direction, entry_m, apex_m, exit_m, angle_deg,
reference_minimum_speed_kmh
```

Corners are detected once on the reference, making corner numbers and boundaries stable
across laps. `direction` is `L` or `R`. A wrapping corner has `entry_m > exit_m` and
occupies both sides of the start/finish line.

In user-facing prose, render corner number `N` as `Turn N`. A metre location must also
state its supported relation to that turn or adjacent turns; the number alone does not
replace the required corner-relative description.

`corner_line_analysis` exists at every detail level:

```text
lap_id, corner,
entry_lateral_offset_m, apex_lateral_offset_m, exit_lateral_offset_m,
entry_heading_error_deg, apex_heading_error_deg, exit_heading_error_deg,
line_rms_offset_m, line_peak_offset_m,
projection_distance_rms_m, projection_distance_peak_m,
corner_path_length_m,
mean_abs_curvature_1_per_m, peak_abs_curvature_1_per_m,
peak_curvature_progress_m
```

Peak lateral offset retains the sign of the largest absolute offset. Projection
distance is nonnegative. Metrics use a uniform internal 2 m spatial grid. Wrapping
corners aggregate both sides of the line.

`corner_analysis` exists in standard/deep and contains:

```text
lap_id, corner, corner_elapsed_ms, corner_delta_vs_reference_ms,
brake_application_m, brake_point_delta_vs_reference_m,
minimum_speed_kmh, minimum_speed_delta_vs_reference_kmh,
throttle_reapplication_m,
front_steering_mean_abs_rad, front_steering_peak_abs_rad,
yaw_mean_abs_rad_s, yaw_peak_abs_rad_s,
sway_mean_abs, sway_peak_abs,
front_slip_mean, front_slip_peak, rear_slip_mean, rear_slip_peak,
minimum_body_height_mm,
maximum_suspension_fl_mm, maximum_suspension_fr_mm,
maximum_suspension_rl_mm, maximum_suspension_rr_mm,
mean_tire_temp_fl_c, mean_tire_temp_fr_c,
mean_tire_temp_rl_c, mean_tire_temp_rr_c,
tcs_activity_pct, tarmac_contact_pct, kerb_contact_pct,
loose_surface_contact_pct, event_count, event_types
```

Throttle reapplication uses a 70% threshold. Braking is associated within the existing
250 m approach window. For a wrapping corner, non-time aggregates cover both sides, but
elapsed time, braking, brake delta, and throttle-reapplication values that would cross
the lap-time reset are `null`.

## 11. Events and recurrence

`events` preserves every stored event and enriches it at export time:

```text
lap_id, type, start_m, end_m, wheels, severity,
start_time_ms, end_time_ms, duration_ms,
speed_start_kmh, minimum_speed_kmh, speed_end_kmh,
throttle_start_pct, throttle_end_pct, brake_start_pct, brake_end_pct,
gear_start, gear_end, minimum_body_height_mm, relevant_wheel_slip,
surface_start, surface_end, kerb_contact_pct, loose_surface_contact_pct,
start_progress_m, end_progress_m, peak_along_track_speed_kmh,
backward_distance_m
```

Common `type` values:

- `lockup`: braking with slip ratio below 0.9 for roughly 0.1 s;
- `wheelspin`: powered slip ratio above 1.1 for roughly 0.1 s;
- `bottoming`: sustained suspension compression near that lap's maximum;
- `kerb`: sharp suspension spike;
- `reverse_motion`: export-time physical movement opposite the reference direction.

`wheels` contains `fl`, `fr`, `rl`, `rr`; reverse motion uses `[]`.
`relevant_wheel_slip` is the minimum associated slip for lockup and maximum for
wheelspin. `severity` is event-specific and must not be compared across event types:
lockup uses the minimum slip ratio, wheelspin the maximum slip ratio, and suspension
events a normalized compression/spike fraction.

For wheelspin, keep peak slip ratio, event duration, recurrence, and the lap-level
`tire_spin_pct` separate. A high localized peak does not by itself establish that
wheelspin was severe across the corner or lap. Avoid labels such as “massive” from peak
ratio alone; describe each magnitude and extent.

`bottoming` is a heuristic for suspension compression sustained near that lap's
observed maximum. `severity=1.0` means the event reached the observed per-lap normalized
maximum; it does not prove bump-stop contact, floor contact, chassis scraping, or
literal mechanical bottoming.

For `reverse_motion`, `severity` is intentionally `null`. Magnitude evidence is:

- `peak_along_track_speed_kmh`: most-negative signed speed;
- `backward_distance_m`: integrated negative motion;
- progress and elapsed-time endpoints.

Reverse detection enters below -2.0 km/h, exits at -0.5 km/h, requires at least 500 ms
below the enter threshold, and bridges interruptions up to 200 ms if speed never exceeds
+0.5 km/h. Negative along-track speed means physical motion opposite the selected
reference direction, not reverse gear.

### Wheelspin characterization

Standard/deep add the same bounded `wheelspin_characterization`; Compact is unchanged.
It is a nested columnar table. Decode each positional sub-row with its matching registry:
`observed_columns`, `derived_columns`, `sequence_columns`,
`comparator_quality_columns`, `comparator_columns`, `candidate_columns`, or
`evidence_columns`. Rows identify every stored wheelspin event, direct `observed` facts,
deterministic `derived` comparisons, onset `sequence`, comparator quality, explicit
`resolution`/`unresolved_reasons`, and up to three ranked real `candidates`.
Sequence values are integer milliseconds relative to stored wheelspin onset (`0`);
unavailable evidence is `null`.

`reference_corner` remains strict containment. `context_corner`, `corner_relation`, and
`corner_distance_m` provide non-causal location context for an event inside a corner or
within 250 m of its entry/exit. Comparison-excluded or spatially unalignable events still
receive rows with nullable derived fields and explicit unresolved reason codes.

`drivetrain_characterization` retains `override`, torque-derived `inferred`, effective
precedence (`override` before `inferred` before `unknown`), powered wheels, positive
front/rear torque shares, evidence counts/laps, and `conflict`. An override never erases
contrary inference. Event-local torque allocation is retained; conflict reduces
power-mechanism discrimination. Torque uses raw GT7 units: relative timing/distribution
is usable, but Nm, tire force, and physical torque are unverified.

Comparators are same-spatial-progress controls, not ideal laps. `ideal` means peak slip
at or below 1.10. A `relative` control may itself cross 1.10 when peak slip is at least
0.03 lower, integral or duration is at least 20% lower, and neither available integral
nor duration is more than 10% worse. A stored overlapping wheelspin event alone does not
exclude that control. Ranking
balances slip separation, speed, gear, projection fit, and local cleanliness/disturbance
evidence. `weak` quality reduces discrimination; one comparator cannot establish a
robust outlier, and relative controls alone cannot make quality `strong`. Stored
bottoming alone does not invalidate a comparator: independent, correctly timed local
vertical-motion evidence is required.

Weights are inspectable heuristic ranking parameters, not a learned model or calibrated
physical probabilities. A score is not a probability; a candidate is not a proven
cause. Signed motion remains in `observed`; v1 scoring normally compares absolute
peer-relative magnitudes, so opposite yaw/body-slip signs of similar magnitude are not
an outlier. Temporal order matters: a later correlated shift, kerb, or vertical event
does not explain earlier slip.

`combined_lateral_longitudinal_load_candidate` means power application during elevated
lateral/rotational proxy state relative to controls. It does not mean measured tire
force/load or friction-circle saturation. Steering alone supplies no support;
vehicle-motion evidence must also be active. Persistent peer-relative one-wheel
asymmetry can support `single_wheel_differential_spin_candidate`, but does not diagnose
an LSD. `mixed_or_unresolved` is a `resolution`, never a duplicated pseudo-candidate;
real alternatives remain in `candidates` and reason codes explain unresolved state.
Characterization contains no setup or driver recommendation.

`recurring_events` columns:

```text
type, wheel_or_axle, approximate_distance_m, reference_corner,
occurrence_count, lap_ids, severity_min, severity_mean, severity_max
```

Only lockup, wheelspin, and bottoming recur. Events are grouped in 120 m type and
wheel/axle buckets and require at least three occurrences across at least two usable
laps not known dirty. Reverse motion is never clustered. `wheel_or_axle` can be a
single wheel, `front`, `rear`, a `+`-joined wheel set, or `unknown`.

### Packed surface values

`surface`, `surface_start`, and `surface_end` pack four 4-bit wheel codes, FL in the
lowest nibble, then FR, RL, RR:

```text
FL = value & 0xF
FR = (value >> 4) & 0xF
RL = (value >> 8) & 0xF
RR = (value >> 12) & 0xF
```

Codes: `0` unavailable, `1` tarmac, `2` kerb, `3` dirt, `4` grass, `5` sand,
`6` snow, `7` other/unknown. Loose surfaces are 3–6.

`aids` is a bitmask: TCS=1, ASM=2, handbrake=4, rev limiter=8.

## 12. Interesting ranges and traces

`interesting_ranges` columns:

```text
range_id, start_m, end_m, reasons, lap_ids, reference_corner, priority
```

Candidate reasons come from events, recurring clusters, each lap's three largest
segment losses of at least 150 ms, and 5 m lap-versus-reference anomalies. Known anomaly
reasons are `front_steering_anomaly`, `yaw_anomaly`, `wheel_slip_anomaly`,
`body_height_anomaly`, and `suspension_anomaly`. Segment reasons have the form
`segment_loss_<milliseconds>ms`; recurring reasons use `recurring_<event_type>`.

Events and segment losses have priority 2, recurring evidence priority 3, anomalies
priority 1. Candidates are padded 25 m, transitively merged across overlaps/gaps up to
25 m, split into windows no longer than 300 m, then capped at 12 windows. Range IDs are
assigned after priority ranking, so ID order is not guaranteed to be distance order.
`reference_corner` is a single deterministic primary corner or `null`.

Public adjacent ranges may share a numeric seam. Internal half-open semantics ensure a
`(lap_id, distance)` trace sample appears in only one of them.

### `detail_traces`

Outer columns:

```text
range_id, lap_id, columns, rows
```

Nested rows use a 5 m cumulative-distance grid. The requested driving-context core,
when recorded, begins with:

```text
distance_m, time_ms, speed, throttle, brake, gear
```

The reference plus affected structurally usable, comparison-eligible laps are included.
Further columns are selected by the range reasons and omitted if unavailable:

- braking/lockup: `brake_filtered`, `surge`, `slip_fl/fr/rl/rr`, and `aids`;
- wheelspin/slip anomaly: `throttle_filtered`, `slip_fl/fr/rl/rr`,
  `torque_fl/fr/rl/rr`, and `aids`;
- bottoming/body/suspension anomaly: `body_height`, `sus_fl/fr/rl/rr`, `heave`, and
  `road_plane_distance`;
- steering/yaw anomaly: `steer_fl_rad`, `steer_fr_rad`, `steering_wheel_rad`,
  `steering_angular_velocity`, `yaw_rate_signed`, and `sway`;
- surface/off-track/kerb: `surface`, `body_height`, and `sus_fl/fr/rl/rr`;
- segment loss: `steer_fl_rad`, `steer_fr_rad`, `yaw_rate_signed`, `slip_fl/fr/rl/rr`,
  and `aids`;
- unknown future reason: only core speed/input/gear context.

Multiple reasons produce the deterministic union of their groups. Gear, aids, and
surface use nearest-neighbor sampling; continuous channels interpolate.

These 5 m rows are resampled comparison evidence, not guaranteed samples of a true
short-duration peak. Use event summaries first, then bounded deep `source_traces` when
the exact peak magnitude or timing matters.

### `source_traces` (deep only)

The outer/nested shapes match `detail_traces`, but rows are rounded values on the
resolved lap's persisted sample grid inside selected ranges. They are not raw archive
records. Persisted values remain authoritative; a trace-eligible channel could contain
archive-hydrated values aligned onto that grid if the request resolved it. In the
current LLM request path only the orientation quartet is requested from the archive,
and quaternion components are not source-trace columns, so current `source_traces`
contain persisted trace channels. Columns begin with `distance_m` and `time_ms`,
followed by all useful available trace channels in canonical order.

Coverage per lap is bounded to the lesser of 1,500 m or 25% of that lap's distance.
Never interpret absence outside these windows as absence of an event or behavior; the
deep export intentionally cannot reconstruct an entire raw lap.

## 13. Spatial reference and line traces

`spatial_reference` columns:

```text
progress_m, x_m, [y_m], z_m, heading_deg, curvature_1_per_m
```

`y_m` is omitted when elevation is unavailable. Standard uses a 10 m grid; deep uses
5 m. The final partial interval is retained.

`line_traces` outer columns:

```text
lap_id, columns, rows
```

Nested columns, in deterministic order when available:

```text
progress_m, time_ms, x_m, [y_m], z_m,
lateral_offset_m, projection_distance_m, heading_error_deg,
[chassis_heading_error_deg, body_slip_angle_deg],
curvature_1_per_m, speed_kmh, along_track_speed_kmh,
throttle_pct, brake_pct, gear,
[steering_wheel_rad], [yaw_rate_signed]
```

Only structurally usable, comparison-eligible laps are included, including eligible
dirty laps. Continuous values interpolate on reference progress; gear uses
nearest-neighbor.

Three different motion concepts must remain separate:

- `heading_error_deg`: direction of the lap's spatial trajectory minus reference
  heading;
- `chassis_heading_error_deg`: direction the chassis nose points minus reference
  heading;
- `yaw_rate_signed`: instantaneous rate of chassis rotation, not an angle.

`body_slip_angle_deg` compares actual travel direction with chassis direction and is
`null` below 0.1 m/s horizontal motion. Together these distinguish forward driving,
rolling backward while pointed forward, a 180° spin moving nose-first against the
track direction, and substantial sideways translation.

The native packet orientation is a vehicle-local-to-world quaternion `(x,y,z,w)`.
Local `-Z` is the chassis nose, local `+Y` is chassis up, and world `Y` is elevation.
Quaternion components are retained in normalized/raw lap telemetry but intentionally
not repeated in each LLM line-trace row.

`projection_distance_m` is the Euclidean distance from the actual position to the
selected point on the reference polyline, in 3D when both paths have Y and X/Z
otherwise. It is diagnostic projection-fit/confidence evidence, not a driving-quality
score or rejection threshold. A legitimate alternate line can have a nonzero value;
large values can identify an excursion, spin, or very off-line path.

`time_ms` is elapsed lap time at reference progress. Duplicate accepted progress keeps
the latest time, the most-negative along-track speed, and the maximum-projection-distance
sample for other evidence. If a completed trajectory reaches the reference endpoint,
only its terminal elapsed time is reconciled with stored lap time; intermediate times
are never rescaled.

`along_track_speed_kmh` comes from a five-sample centered world-position derivative
(one-sided near endpoints) dotted with the local reference tangent before progress is
clamped. It can be negative while exported progress remains stationary/nondecreasing.

The standard 10 m spatial rows are comparison evidence, not guaranteed true peak
samples. Deep spatial rows improve this to 5 m, but short transients can still fall
between rows. Use events or bounded deep source traces for peak timing/magnitude.

## 14. Recommended analysis order for an agent

Keep location and diagnosis separate:

1. Validate `format`, `version`, and `options.detail`; decode every table from its own
   `columns`, index laps by `lap_id`, and inspect availability/provenance.
2. Use `timing_segments` only to locate gains or losses and verify the final time
   consequence. A time loss does not identify its cause.
3. At that location, inspect `interesting_ranges`, spatial line/projection evidence,
   and chassis-heading versus trajectory-heading evidence.
4. Inspect steering angle/rate and signed yaw evidence.
5. Inspect brake and throttle timing/application.
6. Inspect wheel slip, body/suspension motion, aids, events, and surface evidence.
7. Return to speed and time to quantify the consequence; use bounded deep source rows
   or event summaries when resampled rows may hide a short peak.
8. Separate observation → possible mechanism → setup experiment. If the evidence
   cannot discriminate among mechanisms, say so. Treat a setup change as an A/B test,
   not a proven cure or proof that the named component caused the symptom.
9. Report `Lap N` by resolving internal `lap_id` to `gt7_lap`; do not normally expose
   `lap_id`. Report each metre location with a same-axis corner-relative description,
   plus magnitude, comparison baseline, and provenance. Distinguish measured values,
   derived metrics, and heuristics.

## 15. Interpretation guardrails

- The reference path is a selected driven lap, not a surveyed centerline or ideal line.
- A faster reference is not automatically better at every corner.
- Positive time delta means slower; do not invert it.
- Projection distance measures fit to the chosen reference projection, not driver skill.
- Slip is a proxy ratio, not tire slip angle and not a signed SAE slip ratio.
- Body-slip sign is deliberately neutral; describe its magnitude/direction numerically.
- Negative along-track speed means opposite physical motion, not a reported gear.
- Event severity is event-specific; never rank different event types by severity alone.
- User-facing lap identity: always `Lap N` from `laps.gt7_lap`; never bare `lap_id`.
- User-facing metre location: always include a same-axis Turn-relative description;
  never mix cumulative distance with spatial progress or invent a corner name.
- Body slip, yaw, steering rate, sway, and path disturbances establish what the vehicle
  did, not why it happened. Current telemetry does not directly report external contact
  or collisions. Do not label an excursion as power oversteer, a collision, or setup
  instability without corroborating evidence. User/replay context may establish a
  collision; telemetry can then support its timing and vehicle response.
- Do not recommend setup changes from one anomalous, dirty, or incident lap. Look for
  the same behavior in clean laps. Dirty laps remain valuable for incident analysis.
- Do not claim a specific setup component is causal merely because changing it could
  plausibly affect the observation. Telemetry may support several competing mechanisms.
- Fuel level and consumption are available, but no verified Fuel Map 1–6 channel is
  exposed. Do not explain behavior solely from a consumption change: the driver may
  have changed Fuel Map without that control being visible in the export.
- `null` can mean unavailable channel, wrapping/reset-crossing metric, stationary
  direction, or an inapplicable event field. Use the table and provenance context.
- Sway/heave/surge, torque, energy, and most road-plane fields retain raw GT7 units;
  avoid assigning physical units not stated by the schema.
- Standard/deep traces are curated and bounded. Raw lap JSON/CSV and `.gt7r` archives,
  not this LLM document, are the archival full-rate sources.
