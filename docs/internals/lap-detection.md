# Lap detection & sessions

GT7 doesn't send "lap completed" messages — the datalogger has to cut clean laps out of
a 60 Hz packet stream that also includes menus, replays, pauses, and restarts. This page
explains exactly how.

## What gets sampled

For every packet, a sample is recorded onto the in-progress lap **only if all of these
hold**:

- the car is **on track** (flag bit 0) and the game is **not paused** (bit 1);
- `current_lap > 0` — GT7 reports the out-lap in time trials as "lap 0", which is never
  recorded;
- the race isn't already finished — after the checkered flag GT7 reports
  `current_lap = total_laps + 1` for the cool-down lap, which is skipped.

Packets with the `LOADING` flag set are dropped entirely before any processing.

**Time and distance** are synthesized from the console's own **packet counter**, not
from wall clocks or a fixed tick assumption:

- each sample covers `Δpacket_id` frames (clamped to 1–60; a pid reset,
  non-monotonic value, or a gap over 1 s falls back to a single frame);
- `t += Δframes × 1/60` seconds, `dist += speed_mps × Δframes × 1/60` meters.

Dropped datagrams therefore widen the time/distance steps instead of silently
compressing the axes. The pid tracker also advances on paused/off-track packets, so
unpausing sees a ~1-frame gap — pauses still add no lap time or distance. Frames
lost in transit are counted and reported as `frames_dropped` in `/api/status` and
the Admin diagnostics.

Input metrics (full-throttle %, braking %, coasting %, tire spin, TCS/ASM activity)
are **time-weighted** using the `t` deltas, so a sample recorded after a gap counts
for the whole gap it covers.

## When a lap completes

A lap-counter change is only accepted as a real completed lap when **all four**
conditions hold:

1. the previous lap number was `> 0` (a real lap, not the out-lap);
2. the counter moved **exactly +1** (monotonic step);
3. the game reported a positive `last_lap_time_ms`;
4. the lap collected at least **600 samples** (~10 s of received packets at 60 Hz).

Condition 4 is the **phantom-lap guard**: in menus and replays GT7's lap counter
flickers through stale values and re-reports an old `last_lap_time`. Requiring 10
seconds of actual on-track samples filters all of that out.

The lap time itself is taken **verbatim from GT7's `last_lap_time_ms`** — it is never
computed from tick counts, so it matches the in-game timing exactly. (The one exception
is the manual *Log lap now* action, which saves a partial lap and derives its time from
the sample clock.)

!!! note "Why state is committed before the database write"
    Packets keep arriving at 60 Hz while a lap is being written to SQLite. All processor
    state — lap counter, sample buffer, fuel and engine aggregates — is committed
    *before* the asynchronous save starts; otherwise the lap boundary would re-trigger
    on the next packet and duplicate the lap. There's a regression test for exactly this.

## What's stored per lap

- The **full 60 Hz sample series** (~28 channels — see
  [Derived channels](derived-channels.md)), JSON-encoded.
- Per-lap aggregates: fuel used, full-throttle / full-brake / coasting / tire-spin
  percentages, max speed, min body height, TCS/ASM usage, engine health, time of day.
- [Detected chassis events](event-detection.md), computed once at save time.
- Gearing metadata (ratios, tune top speed, redline) captured from the boundary packet.

## Session lifecycle

A **session** groups consecutive laps that belong together. A new session starts when:

- the **car changes** (`car_id` differs from the session's car), or
- the **lap counter resets** — `current_lap` drops below where it was (race restart,
  return to menu and back out).

When a new session starts, the previous one is closed first:

- a session that ended with **zero laps is deleted** — menu visits and quick restarts
  don't pile up as empty rows;
- a session with laps triggers the `session_summary`
  [webhook notification](../guide/admin.md#notifications) (car, track, laps, best lap,
  fuel used).

On the **first completed lap** of a session, the lap's geometry is compared against the
saved track signatures and the session is tagged automatically if it matches — see
[Track identification](track-identification.md).

## Best-lap tracking

The service tracks the session best and, separately, the best *before* the
just-completed lap (`prev_best_ms`). The live "Δ best" readout compares against
`prev_best_ms`, so when you set a new personal best you see the improvement
(e.g. `−0.312`) instead of a useless `+0.000`.

The `personal_best` webhook fires only when an existing session best is actually beaten —
never on the first lap of a session.

**Partial-lap guard.** A pit out-lap can pass the structural checks (GT7 reports a
time for it, and it lasts more than 10 s) while covering only part of the track —
with a distance axis anchored at the pit exit, not the line. Such a lap must never
become the session best or the live-delta reference: comparing positions against it
produces garbage deltas that then freeze into a bogus end-of-lap fallback. So a lap
only *counts for best* when its distance span is within **85 %** of the longest
counted lap of the session, and when a clearly longer lap arrives it **invalidates**
an earlier partial "best" (the first full lap takes over even if slower). The guard
is span-relative, so it needs no knowledge of the track's true length.

## What "invalid lap" means here

There is no track-limits detection (GT7 doesn't expose it). Laps are excluded only by
the structural rules above: lap-0 out-laps, laps under 600 ticks, post-finish laps, and
paused/off-track ticks. The Analysis view additionally hides laps that ended up with no
samples.
