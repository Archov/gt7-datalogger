# Lap comparison math

The Analysis view compares laps of different lengths and speeds on one set of axes.
This page explains the alignment, delta, consistency, and map math behind it.

## Distance resampling — how laps are aligned

Laps are aligned **by distance traveled**, not by time. Every lap's sample series is
resampled onto a uniform distance grid:

- grid points at `0, step, 2×step, …` up to the lap's total distance (default **step =
  5 m**; the API accepts 0.5–50 m);
- each channel is **linearly interpolated** onto the grid, with edge clamping (values
  before the first / after the last sample take the boundary value).

Two laps resampled this way have directly comparable values at every grid index: "what
was each lap doing 850 m into the lap?" This is also a read-time downsample — a 2-minute
lap goes from ~7,200 ticks to a few hundred grid points per channel.

## Time delta

For each compared lap, at every grid distance `d` up to the shorter of the two laps:

```
delta_ms(d) = t_lap(d) − t_ref(d)      # both via interpolation of dist → t
```

**Positive = slower than the reference** at that point. The curve's *slope* is the
insight: rising = losing time right here, flat = holding the gap, falling = gaining.
The reference lap compared with itself is exactly zero, so it isn't drawn.

## Speed deviation (consistency chart)

Across the session's best N laps (default 5), on the common distance grid (cut to the
shortest lap):

- **median speed** at each grid point (middle value, or mean of the two middles);
- **population standard deviation** `sqrt(Σ(v − mean)² ÷ n)` at each grid point.

A spike in the deviation band marks a corner where your speed varies lap to lap — the
first place to look for consistency gains.

## Race line map

The map is a raw top-down plot of the recorded world coordinates (`pos_x`, `pos_z`) —
no projection or rotation, GT7's coordinates are used as-is. Each reference-lap point is
classified into an input zone:

| Zone | Condition | Color |
| --- | --- | --- |
| Braking | brake ≥ 1 % | red |
| Throttle | else throttle ≥ 1 % | green |
| Coasting | otherwise | blue |

Other selected laps overlay as solid lines in their chart colors, so line differences
are visible spatially. The chart cursor maps distance → grid index → coordinates, which
is how hovering a chart moves the dots on the map.

## Speed peaks & valleys

The ▲/▼ markers on the map are local speed extrema, found with a sliding window:

- a point is a **peak** if it is the maximum of the surrounding ±30 ticks (~0.5 s each
  side), a **valley** if it is the minimum;
- consecutive markers of the same kind must be at least **100 m** apart.

Valleys approximate apexes (minimum corner speed) and peaks approximate the end of
acceleration zones — without needing full corner detection.

!!! note "Why no numbered corners?"
    Curvature-based corner numbering was prototyped and removed: unsigned curvature
    splits hairpins into two "corners" and merges S-sections into one. Doing it right
    needs signed curvature with hysteresis — it's on the roadmap; until then the
    peaks/valleys markers plus the **S1/S2/S3** section-zoom buttons (fixed thirds of
    the lap distance) cover the workflow.

## Cursor synchronization

All the "synced" behavior is one shared value: the cursor's grid index
(`round(distance ÷ step)`). Every consumer — each chart panel, the race line map dots,
the Corner Detail widget — reads the same index into its own resampled arrays, which is
why everything stays in lockstep as you scrub.
