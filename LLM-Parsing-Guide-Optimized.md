# GT7 LLM Session Export: Token-Optimized Contract

Purpose: LLM/software-agent parsing and interpretation of **Export for LLM** JSON.
Style: controlled specification. Canonical field names unchanged.

## OPERATORS

```text
=>    implies / means
-/->  does NOT imply
<>    not equal
?=    uncertain / not established
```

`>=`, `<=`, `>`, `<`: ordinary mathematical comparisons.

## 1. Envelope and JSON rules

Required identity:

```json
{"format":"gt7-datalogger-llm-session","version":1}
```

- unknown `format` or `version` => reject OR explicitly qualify all conclusions.
- `options.detail`: `compact` | `standard` | `deep`.
- `options.segment_m`: requested fixed timing-segment length, metres.
- serialization: deterministic; strict JSON; no `NaN`; no infinity.
- unavailable numeric value => `null`.
- unavailable trace channel => omit from that trace's `columns`.
- zero => real recorded/derived value unless explicitly stated otherwise.
- `null` <> omitted column <> zero.
- repeated data => columnar tables.

## 2. Columnar decoding

Basic table:

```json
{"columns":["lap_id","time_ms"],"rows":[[42,91234],[43,91880]]}
```

Rule: `record = zip(table.columns, row)`. NEVER use undocumented fixed positions.

Nested forms:

```text
{columns:[lap_id,columns,rows],rows:[[lap_id,nested_columns,nested_rows],...]}
{columns:[range_id,lap_id,columns,rows],rows:[[range_id,lap_id,nested_columns,nested_rows],...]}
```

Decode outer row, then nested row. Optional channels => nested columns can differ by
lap/range. NEVER assume identical nested schemas.

## 3. Detail-level keys

All levels:

```text
format, version, options, schema,
session, channel_availability, channel_provenance, reference, laps,
whole_lap_chassis, timing_segments, reference_corners, events,
recurring_events, corner_line_analysis
```

All-level meanings:

```text
session: session metadata + resolved channel union
channel_availability: resolved usable channels/lap
channel_provenance: persisted/archive_replay/unavailable channels/lap
reference: comparison lap + selection reason
laps: every persisted lap summary
whole_lap_chassis: time-weighted whole-lap statistics
timing_segments: exact reference-defined timing
reference_corners: corners detected once on reference
events: stored + export-derived events
recurring_events: recurring lockup/wheelspin/bottoming clusters
corner_line_analysis: per-corner spatial-line metrics
```

`standard` + `deep` additions:

```text
corner_analysis: detailed per-corner comparison
interesting_ranges: bounded evidence windows
detail_traces: reason-selected 5 m cumulative-distance traces
spatial_reference: reference path; standard 10 m, deep 5 m
line_traces: whole-lap projected spatial evidence
```

`deep` only: `source_traces` = bounded persisted-grid-rate samples.

Reference geometry unavailable => omit `spatial_reference` and `line_traces`; retain
empty `corner_line_analysis`.

## 4. IDs, eligibility, reference

```text
session.id: session identity
lap_id: internal database/export identity; mandatory join key across lap tables
gt7_lap: sequential GT7/internal lap number; user-facing identity => Lap N
range_id: range join key
corner: corner join key
```

Row order: deterministic. Joins: use IDs, NOT row position.

User-facing lap rule:

```text
internal processing/join: lap_id
user-facing prose: resolve lap_id via laps => gt7_lap => "Lap N"
normal prose: NEVER expose bare lap_id
debug exception: "Lap 7 (lap_id 70)"; NEVER only "lap_id 70"
scope: comparisons,events,recurrence,corners,ranges,line analysis,chassis,setup advice
```

`gt7_lap`: NOT necessarily globally unique outside session. Internal joins remain
`lap_id`.

`counts_for_best`:

- `true` => eligible for normal best/reference comparison.
- `false` => deliberately excluded from normal comparison.
- partial/manual lap => false.
- false -/-> incomplete. Completed pit lap/other intentionally excluded completed lap
  can be false.
- false rows remain in `laps`, `whole_lap_chassis`, `events`.
- false rows excluded from reference selection, distance timing, corner comparison,
  recurrence, spatial comparison, all traces.
- false => `delta_to_reference_ms:null`.
- reason-code text `full_lap` => historical label meaning structurally usable +
  comparison-eligible; NOT independent proof of completion.

`clean_lap`: `true`=surface data found no qualifying off-track excursion;
`false`=known dirty; `null`=unknown cleanliness.

Automatic reference precedence:

```text
1 clean eligible usable fastest        => fastest_clean_full_lap
2 unknown-cleanliness eligible fastest => fastest_full_lap_cleanliness_unknown
3 dirty eligible usable fastest        => fastest_dirty_full_lap
```

Explicit eligible/usable reference, including dirty => `reason:explicit`.
Reference = comparison baseline; NOT guaranteed ideal lap/line/corner.

## 5. Units, rounding, signs

```text
_m: m                         _mm: mm
_ms: ms                       _kmh: km/h
_pct: percent                 _rad: rad
_rad_s or signed yaw: rad/s   _deg: degrees
_1_per_m: 1/m                 slip: wheel surface speed / vehicle speed
```

Typical rounding:

```text
time 1 ms; distance 0.1 m; speed 0.1 km/h; input 0.1%; length 0.1 mm;
steering/angular velocity/slip/raw motion 4 decimals; curvature 6 decimals;
fuel generally 3 decimals
```

Signs/formulas:

- time delta = lap - reference. positive => time loss; negative => gain.
- `brake_point_delta_vs_reference_m = lap brake point - reference brake point`.
  negative=>earlier braking; positive=>later.
- `minimum_speed_delta_vs_reference_kmh = lap minimum - reference minimum`.
- `lateral_offset_m > 0` => left of reference path in reference travel direction.
- `body_slip_angle_deg = wrap(travel_heading - chassis_heading)`; range `(-180,180]`.
  Sign: raw X/Z angular convention; NOT automotive left/right semantics.

## 6. Location axes: NEVER mix

`dist`/cumulative-distance axis:

- fields: `distance_m`, `start_m`, `end_m`, `entry_m`, `apex_m`, `exit_m`, timing
  boundaries.
- source: speed-integrated lap-processor distance.
- monotonic during spin/reversal.
- different driven lines => different final distance.

`progress_m`/spatial-reference axis:

- fields: `progress_m`, `start_progress_m`, `end_progress_m`.
- source: arc length on selected reference physical polyline.
- other laps: continuity-constrained projection onto reference.
- racing-line comparison axis.
- reference arc length: X/Y/Z if Y exists; X/Z otherwise.
- heading/curvature: planar X/Z always.
- projection search: bounded near last accepted progress; accepted progress
  nondecreasing; no unrestricted global remap to nearby unrelated track segment.

NOT valid: cumulative-distance location <> spatial-progress location. Compare only
fields/tables sharing one axis.

User-facing location rule: every reported metre position/range MUST include same-axis
corner-relative description. Metres may remain for precision.

```text
valid: "500–600 m, on the approach to Turn 2"
valid: "around 1,340 m, between Turns 4 and 5"
valid: "3,680–3,760 m, through the exit of Turn 8"
cumulative location => use reference_corners entry_m/apex_m/exit_m; wrap circularly
spatial progress => use selected-reference peak_curvature_progress_m + spatial corner order
progress_m vs entry_m/apex_m/exit_m => PROHIBITED; axes differ
spatial apex anchors alone => NOT sufficient for entry/exit precision
unsupported same-axis corner relation => omit metre location from user-facing answer
official corner name absent => NEVER invent
```

Allowed descriptions: `approach to Turn N`; `entry to Turn N`; `through Turn N`;
`around the apex of Turn N`; `exit of Turn N`; `between Turns N and N+1`; `the straight
between Turns N and N+1`.

## 7. Channel availability, provenance, registry

`channel_availability`:

```text
columns:[lap_id,channels]
```

`channels`: resolved export-time usable normalized telemetry. May include
`archive_replay`; NOT necessarily only persisted `samples_json`. Absent=>unavailable,
NOT zero. Legacy all-zero `surface`=>unavailable.

`channel_provenance`:

```text
columns:[lap_id,persisted,archive_replay,unavailable]
persisted: present in saved normalized lap
archive_replay: on-demand raw-archive recovery
unavailable: requested; neither persisted nor safely recoverable
```

Rules: persisted wins; replay read-only; replay aligned to persisted lap identity/time
grid; no historical sample rewrite; provenance = context/confidence, NOT quality rank.
Current principal use: historical orientation recovery.

Packet groups:

```text
base/A: time,distance,speed,inputs,gear,rpm,boost,position,quaternion,yaw,
        road-plane,body,fuel,wheel slip/temp/suspension,aids
B: steering-wheel angle/rate,sway,heave,surge
~: filtered inputs,4 torque channels,energy recovery
C: front steering,4-wheel packed surface,wheelbase,car category metadata
```

Optional group not consistently available for entire lap => omit whole group. NEVER
fabricate missing optional values with zero.

Canonical normalized sample registry:

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

Normalized sample units:

```text
t: elapsed s                      dist: cumulative m
speed: km/h                       throttle,brake,filtered inputs: percent
coast: flag                       pos_x,pos_y,pos_z: m
orientation_x/y/z/w: unitless     body_height,sus_fl/fr/rl/rr: mm
fuel: L                           tt_fl/fr/rl/rr: degrees Celsius
boost: bar                        steering: rad
yaw,steering angular velocity: rad/s
road-plane,sway,heave,surge,torque,energy recovery: raw GT7 units
slip: ratio                       gear: integer code
surface,aids: masks
```

`road_plane_distance`: raw GT7 unit; NOT metres. Dynamic table suffix/schema unit wins.
NEVER invent physical units for fields declared raw by embedded `schema.units`.

## 8. Session, lap, whole-lap chassis

`session` fields, minimum:

```text
id, started_at, car_id, car_name, track_name, note, lap_count,
available_telemetry_channels, telemetry_formats
```

`telemetry_formats`: subset of `A`,`B`,`~`,`C`,`unknown`.
`available_telemetry_channels`: union of resolved `channel_availability` view.

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

- `off_track_count=-1` => unknown.
- event counts: persisted events only; export-time `reverse_motion` does NOT change them.
- `gearing_top_speed`: packet configured transmission top-speed reference used for
  top-gear scaling; NOT final-drive ratio; NOT achieved lap maximum speed.

`whole_lap_chassis`: first column `lap_id`; time-weighted statistics:

```text
body height: min,mean,p05,p95
suspension/wheel: min,mean,p95,max
tire temperature/wheel: min,mean,max,p05,p95
slip/wheel: mean,p95,max
front/rear average slip + left/right imbalance means
powered-corner rear-slip mean,p95
front-steering + steering-wheel mean/peak absolute angle
steering angular velocity mean/peak absolute
sway/heave/surge mean/peak absolute
signed/absolute/peak yaw
requested-minus-filtered throttle/brake differences
time-weighted tarmac/kerb/loose wheel-contact shares
off-track excursion count
```

Powered-corner rear-slip heuristic gate:

```text
throttle >=70% AND 50<=speed<=220 km/h AND
(abs(yaw)>=0.05 rad/s OR front steering>=0.01 rad OR
 steering-wheel rotation>=0.05 rad)
```

Surface percentage denominator: wheel-contact time; NOT percentage of samples with any
wheel on surface.

Tire temperature: observation only. Overheated/underheated classification prohibited
without validated operating range for relevant car+tire+conditions.

## 9. Timing segments

```text
columns:[lap_id,start_m,end_m,segment_time_ms,
segment_delta_vs_reference_ms,cumulative_delta_vs_reference_ms,
minimum_speed_kmh,average_speed_kmh]
```

- boundaries: zero through reference finish, spaced `options.segment_m`; final segment may
  be shorter.
- ordinary boundary time: exact interpolation.
- finish segment: eligible lap reaching segment start => stored lap finish time as end.
- consequence: final cumulative delta = stored lap-time delta despite final lap distance
  slightly shorter/longer than reference.
- segment delta positive=>loss; negative=>gain.
- cumulative delta=>gap at segment end.
- absent lap/segment row=>boundary not reached OR lap structurally unusable/ineligible.

## 10. Corners

`reference_corners`:

```text
columns:[corner,direction,entry_m,apex_m,exit_m,angle_deg,
reference_minimum_speed_kmh]
```

- detection: once on reference => stable corner numbers/boundaries.
- `direction`: `L` | `R`.
- wrapping corner: `entry_m > exit_m`; intervals on both sides of start/finish.
- user-facing `corner:N` => `Turn N`.
- user-facing metre location => Turn-relative phrase mandatory; `Turn N` alone is not a
  location translation.

`corner_line_analysis`: all detail levels.

```text
columns:[lap_id,corner,
entry_lateral_offset_m,apex_lateral_offset_m,exit_lateral_offset_m,
entry_heading_error_deg,apex_heading_error_deg,exit_heading_error_deg,
line_rms_offset_m,line_peak_offset_m,
projection_distance_rms_m,projection_distance_peak_m,
corner_path_length_m,mean_abs_curvature_1_per_m,peak_abs_curvature_1_per_m,
peak_curvature_progress_m]
```

- grid: uniform 2 m internal spatial grid.
- `line_peak_offset_m`: sign retained from greatest absolute offset.
- projection-distance metrics: nonnegative.
- wrapping corner: aggregate both intervals.

`corner_analysis`: standard/deep.

```text
columns:[lap_id,corner,corner_elapsed_ms,corner_delta_vs_reference_ms,
brake_application_m,brake_point_delta_vs_reference_m,
minimum_speed_kmh,minimum_speed_delta_vs_reference_kmh,
throttle_reapplication_m,
front_steering_mean_abs_rad,front_steering_peak_abs_rad,
yaw_mean_abs_rad_s,yaw_peak_abs_rad_s,sway_mean_abs,sway_peak_abs,
front_slip_mean,front_slip_peak,rear_slip_mean,rear_slip_peak,
minimum_body_height_mm,
maximum_suspension_fl_mm,maximum_suspension_fr_mm,
maximum_suspension_rl_mm,maximum_suspension_rr_mm,
mean_tire_temp_fl_c,mean_tire_temp_fr_c,mean_tire_temp_rl_c,mean_tire_temp_rr_c,
tcs_activity_pct,tarmac_contact_pct,kerb_contact_pct,loose_surface_contact_pct,
event_count,event_types]
```

- throttle reapplication threshold: 70%.
- braking association: existing 250 m approach window.
- wrapping corner: non-time aggregates cover both intervals; reset-crossing elapsed,
  braking, brake-delta, throttle-reapplication => `null`.

## 11. Events, recurrence, surface, aids

`events`: all stored events retained + export-time enrichment.

```text
columns:[lap_id,type,start_m,end_m,wheels,severity,
start_time_ms,end_time_ms,duration_ms,
speed_start_kmh,minimum_speed_kmh,speed_end_kmh,
throttle_start_pct,throttle_end_pct,brake_start_pct,brake_end_pct,
gear_start,gear_end,minimum_body_height_mm,relevant_wheel_slip,
surface_start,surface_end,kerb_contact_pct,loose_surface_contact_pct,
start_progress_m,end_progress_m,peak_along_track_speed_kmh,backward_distance_m]
```

Types/detection meaning:

```text
lockup: braking + slip ratio <0.9 for ~0.1 s
wheelspin: powered + slip ratio >1.1 for ~0.1 s
bottoming: sustained compression near lap-observed maximum; heuristic
kerb: sharp suspension spike
reverse_motion: export-time motion opposite reference direction
```

`wheels`: subset `fl`,`fr`,`rl`,`rr`; `reverse_motion`=>`[]`.
`relevant_wheel_slip`: lockup minimum; wheelspin maximum.
`severity`: event-specific; NEVER compare across types.

```text
lockup severity: minimum slip ratio
wheelspin severity: maximum slip ratio
suspension-event severity: normalized compression/spike fraction
```

Wheelspin interpretation: keep peak slip ratio, duration, recurrence, and whole-lap
`tire_spin_pct` separate. Local peak alone -/-> overall corner/lap severity. NOT
“massive” from peak ratio alone. Report magnitude + extent.

Bottoming interpretation: sustained compression near lap-observed maximum.
`severity=1.0` => reached normalized observed per-lap maximum. NOT proof of bump-stop
contact, floor contact, chassis scraping, or literal mechanical bottoming.

`reverse_motion`:

```text
severity:null
peak_along_track_speed_kmh: most-negative signed speed
backward_distance_m: integrated negative motion
start/end progress + elapsed-time endpoints: location/duration evidence
enter: below -2.0 km/h
exit: -0.5 km/h
minimum accumulated enter-threshold time: 500 ms
bridge interruption: <=200 ms AND speed never >+0.5 km/h
```

Negative along-track speed => physical motion opposite reference; NOT reverse gear.

`recurring_events`:

```text
columns:[type,wheel_or_axle,approximate_distance_m,reference_corner,
occurrence_count,lap_ids,severity_min,severity_mean,severity_max]
```

- eligible types: `lockup`,`wheelspin`,`bottoming`; NOT `reverse_motion`.
- grouping: 120 m type + wheel/axle buckets.
- threshold: >=3 occurrences across >=2 structurally usable, eligible laps not known
  dirty.
- `wheel_or_axle`: wheel | `front` | `rear` | `+`-joined wheel set | `unknown`.

Packed `surface`, `surface_start`, `surface_end`:

```text
FL = value & 0xF
FR = (value >> 4) & 0xF
RL = (value >> 8) & 0xF
RR = (value >> 12) & 0xF
```

Codes: `0` unavailable; `1` tarmac; `2` kerb; `3` dirt; `4` grass; `5` sand;
`6` snow; `7` other/unknown. Loose: 3–6.

`aids` bitmask: TCS=1; ASM=2; handbrake=4; rev limiter=8.

## 12. Interesting ranges and distance traces

`interesting_ranges`:

```text
columns:[range_id,start_m,end_m,reasons,lap_ids,reference_corner,priority]
```

Candidate sources:

```text
all events
recurring clusters
each lap's 3 largest segment losses >=150 ms
5 m lap-vs-reference anomalies
```

Anomaly reasons:

```text
front_steering_anomaly, yaw_anomaly, wheel_slip_anomaly,
body_height_anomaly, suspension_anomaly
```

Other reason forms: `segment_loss_<milliseconds>ms`; `recurring_<event_type>`.
Priority: recurring=3; event=2; segment loss=2; anomaly=1.

Pipeline: pad candidates 25 m => transitively merge overlap/gap<=25 m => split into
windows<=300 m => rank/cap 12 => assign IDs. ID order NOT necessarily distance order.
`reference_corner`: one deterministic primary corner or `null`.
Adjacent public ranges may share numeric seam; internal half-open semantics => no
duplicate `(lap_id,distance)` trace sample.

`detail_traces` outer schema:

```text
columns:[range_id,lap_id,columns,rows]
```

Nested: 5 m cumulative-distance grid. Recorded context prefix:

```text
distance_m,time_ms,speed,throttle,brake,gear
```

Laps: reference + affected structurally usable, eligible laps. Reason-channel map;
unavailable channels omitted:

```text
braking/lockup:
  brake_filtered,surge,slip_fl,slip_fr,slip_rl,slip_rr,aids
wheelspin/slip anomaly:
  throttle_filtered,slip_fl,slip_fr,slip_rl,slip_rr,
  torque_fl,torque_fr,torque_rl,torque_rr,aids
bottoming/body/suspension anomaly:
  body_height,sus_fl,sus_fr,sus_rl,sus_rr,heave,road_plane_distance
steering/yaw anomaly:
  steer_fl_rad,steer_fr_rad,steering_wheel_rad,steering_angular_velocity,
  yaw_rate_signed,sway
surface/off-track/kerb:
  surface,body_height,sus_fl,sus_fr,sus_rl,sus_rr
segment loss:
  steer_fl_rad,steer_fr_rad,yaw_rate_signed,
  slip_fl,slip_fr,slip_rl,slip_rr,aids
unknown future reason:
  core speed/input/gear context only
```

Multiple reasons => deterministic union. Nearest-neighbor: `gear`,`aids`,`surface`.
Other continuous channels: interpolation.

5 m resampling = comparison evidence; NOT guaranteed true short-duration peak. Peak
magnitude/timing => event summary first; bounded deep `source_traces` if needed.

`source_traces` (deep only): same outer/nested shape. Rows: rounded resolved values on
persisted sample grid within selected ranges; NOT raw archive records. Persisted values
authoritative. A requested trace-eligible hydrated channel can appear after alignment.
Current request hydrates orientation quartet only; quaternion channels absent from
source-trace registry => current source-trace channels are persisted.

Source columns: `distance_m`,`time_ms`, then useful available canonical trace channels.
Coverage/lap <= min(1,500 m,25% lap distance). Missing outside windows -/-> behavior
absent. Deep export cannot reconstruct full raw lap.

## 13. Spatial reference and line traces

`spatial_reference`:

```text
columns:[progress_m,x_m,[y_m],z_m,heading_deg,curvature_1_per_m]
```

`y_m`: omit if elevation unavailable. Grid: standard 10 m; deep 5 m; retain final
partial interval.

`line_traces` outer:

```text
columns:[lap_id,columns,rows]
```

Nested deterministic order when available:

```text
progress_m,time_ms,x_m,[y_m],z_m,
lateral_offset_m,projection_distance_m,heading_error_deg,
[chassis_heading_error_deg,body_slip_angle_deg],
curvature_1_per_m,speed_kmh,along_track_speed_kmh,
throttle_pct,brake_pct,gear,[steering_wheel_rad],[yaw_rate_signed]
```

Included laps: structurally usable + eligible, including dirty. Continuous=>interpolate
on reference progress. `gear`=>nearest-neighbor.

Motion fields:

```text
heading_error_deg: lap spatial-trajectory direction - reference heading
chassis_heading_error_deg: chassis-nose direction - reference heading
yaw_rate_signed: instantaneous chassis rotation rate; NOT angle
body_slip_angle_deg: travel heading - chassis heading; null below 0.1 m/s horizontal
```

Use distinction to identify: forward travel; backward travel while nose forward;
180-degree chassis orientation moving against track direction; sideways translation.

Orientation convention:

```text
quaternion: (orientation_x,orientation_y,orientation_z,orientation_w)
mapping: vehicle-local => world
local -Z: chassis nose
local +Y: chassis up
world Y: elevation
```

Quaternion retained in normalized/raw telemetry; NOT repeated in line rows.

`projection_distance_m`: Euclidean actual position to selected projected reference
point; 3D if both paths have Y, else X/Z. Meaning: projection fit/confidence diagnostic.
NOT driving-quality score. NOT rejection threshold. Nonzero may be normal alternate
line. Large may be legitimate off-line path/spin/excursion.

`time_ms`: elapsed lap time at reference progress. Duplicate accepted progress:
latest time; most-negative along-track speed; maximum-projection-distance sample supplies
other evidence. Completed trajectory reaching reference endpoint: terminal elapsed time
only reconciled with stored lap time; intermediate values NOT rescaled.

`along_track_speed_kmh`: five-sample centered world-position derivative, one-sided near
endpoints, dotted with local reference tangent before progress clamp. Can be negative
while accepted/exported progress remains stationary/nondecreasing.

Spatial resampling: standard 10 m; deep 5 m. Comparison evidence, NOT guaranteed peak
samples. Short transient may fall between rows. Peak magnitude/timing => event or bounded
deep source trace.

## 14. Required analysis sequence

Location <> diagnosis.

```text
1 validate format/version/detail; decode own columns; index lap_id; inspect availability/provenance
2 timing_segments => locate gain/loss + verify final time consequence ONLY
3 location => interesting_ranges + spatial line/projection + chassis-vs-trajectory
4 steering angle/rate + signed yaw
5 brake + throttle timing/application
6 wheel slip + body/suspension + aids + events + surface
7 speed/time => quantify consequence; events/source traces for missed short peak
8 observation => possible mechanism => setup experiment
9 report Lap N (resolve lap_id => gt7_lap), NOT bare lap_id;
  every metre location => same-axis Turn-relative description;
  include magnitude,baseline,provenance; label measured vs derived vs heuristic
```

If evidence cannot discriminate mechanisms => mechanism `?=`. State ambiguity/alternatives. Setup
change => A/B experiment; NOT proven cure; NOT proof named component caused symptom.

## 15. Mandatory interpretation guardrails

- reference path: selected driven lap; NOT surveyed centerline; NOT ideal line.
- faster reference -/-> better at every corner.
- positive time delta => slower. NEVER invert.
- projection distance => projection fit; NOT skill/quality.
- slip => proxy ratio; NOT tire slip angle; NOT signed SAE slip ratio.
- body-slip sign => neutral X/Z convention; report numeric direction/magnitude.
- negative along-track speed => opposite physical motion; NOT reported reverse gear.
- event severity => event-specific; NEVER rank different event types by severity.
- user-facing lap => `Lap N` from `laps.gt7_lap`; NEVER bare `lap_id`.
- user-facing metre location => same-axis Turn-relative description mandatory; NEVER
  mix cumulative distance/spatial progress; NEVER invent corner name.
- body slip/yaw/steering rate/sway/path disturbance => what vehicle did; NOT cause.
- external collision/contact: NOT directly reported.
- excursion: do NOT label power oversteer, collision, or setup instability without
  corroboration.
- user/replay context may establish collision; telemetry then supports timing/response.
- setup recommendation: NOT from single anomalous/dirty/incident lap. Require clean-lap
  reproduction. Dirty laps remain useful for incident analysis.
- specific setup component: NOT causal merely because adjustment could affect symptom.
  Multiple mechanisms may remain compatible.
- tire temperature: no overheated/underheated label without validated car+tire+condition
  operating range.
- wheelspin: peak ratio alone -/-> overall severity; keep duration, recurrence,
  `tire_spin_pct` separate.
- bottoming `severity=1.0`: normalized lap-observed maximum only; NOT physical-contact
  proof.
- Fuel Map blind spot: fuel level/consumption available; verified Fuel Map 1–6 channel
  unavailable. Consumption change alone -/-> cause; driver may have changed Fuel Map.
- `null` may mean unavailable channel, wrap/reset-crossing metric, stationary direction,
  or inapplicable event field. Resolve from table + provenance context.
- sway/heave/surge, torque, energy, most road-plane values: raw units. Do NOT invent
  units.
- standard/deep traces: curated + bounded. Archival full-rate sources: raw lap JSON/CSV
  and `.gt7r`, NOT LLM export.
