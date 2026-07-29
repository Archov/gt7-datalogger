# Track identification

GT7 telemetry doesn't include the track name — but its world coordinates are fixed per
circuit. The datalogger exploits that: name a circuit once, and every future session on
it is tagged automatically from lap geometry.

## The signature

When you name a track (**Sessions → name track…**), a signature is computed from one
completed lap on it:

| Component | Meaning |
| --- | --- |
| `length_m` | total lap distance (integrated from speed) |
| `min_x`, `max_x`, `min_z`, `max_z` | the lap's world-coordinate bounding box |

That's the whole fingerprint — five numbers.

## Matching

On the **first completed lap** of every new session, if the session has no track name
yet, the lap's signature is compared against every stored track. A match requires **all
four** gates to pass:

1. Both lengths are positive.
2. **Length within 4 %**: `|lap_length − track_length| ÷ track_length ≤ 0.04` — loose
   enough to absorb different racing lines, tight enough to separate layouts.
3. **Bounding-box centre within 120 m** on both the x and z axes — different circuits
   sit in different places in GT7's world space.
4. **Each extent within 20 %** of the stored width/depth.

The first matching track's name is applied to the session and broadcast live, so the
track badge appears in the UI immediately.

## Why this works

- The signature is car- and pace-independent: a slow lap and a hot lap on the same
  circuit produce nearly identical bounding boxes and lengths.
- Different layouts of the same venue (e.g. full circuit vs short course) differ in
  length by far more than 4 %, so they register as separate tracks — name each layout
  once.
- Reverse layouts share geometry, so they will match the forward layout's signature.
  If you drive both directions regularly, include the direction in the name you give
  the first one you record.

## Managing tracks

- `POST /api/tracks {name, lap_id}` — what the *name track…* dialog calls; stores the
  signature and back-fills the current session's track name.
- `GET /api/tracks` / `DELETE /api/tracks/{id}` — list and remove signatures.

Deleting a track signature doesn't touch any session data — it only stops future
auto-matching.
