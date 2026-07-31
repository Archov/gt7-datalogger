"""Derived analytics: distance resampling, time deltas, deviation, fuel map.

All functions are pure and operate on the columnar lap sample dict produced by
LapProcessor (see SAMPLE_COLUMNS in laps.py).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

Samples = dict[str, list[float]]

DEFAULT_STEP_M = 5.0


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation with edge clamping. xs must be ascending."""
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_left(xs, x)
    x0, x1 = xs[i - 1], xs[i]
    y0, y1 = ys[i - 1], ys[i]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def resample_by_distance(
    samples: Samples, step: float = DEFAULT_STEP_M, columns: tuple[str, ...] | None = None
) -> Samples:
    """Resample tick-based series onto a uniform distance grid."""
    dist = samples["dist"]
    if not dist:
        return {"dist": []}
    total = dist[-1]
    grid = [i * step for i in range(int(total / step) + 1)]
    out: Samples = {"dist": grid}
    cols = columns or tuple(k for k in samples if k != "dist")
    for col in cols:
        ys = samples[col]
        out[col] = [round(_interp(dist, ys, d), 4) for d in grid]
    return out


def time_delta_at(dist_m: float, t_s: float, ref: Samples) -> float | None:
    """Live gap vs a reference lap at the same distance (ms; positive = slower).

    None when the reference is empty or dist_m runs past its final sample —
    edge clamping would otherwise inflate the gap at 1 ms per ms once the
    reference lap "finishes".
    """
    if not ref["dist"] or dist_m > ref["dist"][-1]:
        return None
    return (t_s - _interp(ref["dist"], ref["t"], dist_m)) * 1000


def time_delta_series(
    lap: Samples, reference: Samples, step: float = DEFAULT_STEP_M
) -> dict[str, list[float]]:
    """Time gained/lost vs the reference lap over distance (ms; positive = slower)."""
    if not lap["dist"] or not reference["dist"]:
        return {"dist": [], "delta_ms": []}
    total = min(lap["dist"][-1], reference["dist"][-1])
    grid = [i * step for i in range(int(total / step) + 1)]
    deltas = [
        round(
            (_interp(lap["dist"], lap["t"], d) - _interp(reference["dist"], reference["t"], d))
            * 1000,
            1,
        )
        for d in grid
    ]
    return {"dist": grid, "delta_ms": deltas}


def speed_deviation(laps: list[Samples], step: float = DEFAULT_STEP_M) -> dict[str, list[float]]:
    """Median speed and standard deviation across laps, by distance.

    High deviation at a distance = inconsistent driving there.
    """
    usable = [lap for lap in laps if lap["dist"]]
    if len(usable) < 2:
        return {"dist": [], "median": [], "deviation": []}
    total = min(lap["dist"][-1] for lap in usable)
    grid = [i * step for i in range(int(total / step) + 1)]
    median: list[float] = []
    deviation: list[float] = []
    for d in grid:
        speeds = sorted(_interp(lap["dist"], lap["speed"], d) for lap in usable)
        n = len(speeds)
        mid = n // 2
        med = speeds[mid] if n % 2 else (speeds[mid - 1] + speeds[mid]) / 2
        mean = sum(speeds) / n
        var = sum((v - mean) ** 2 for v in speeds) / n
        median.append(round(med, 2))
        deviation.append(round(var**0.5, 3))
    return {"dist": grid, "median": median, "deviation": deviation}


def race_line(samples: Samples) -> dict[str, list[float]]:
    """Race line with input zones: 2=throttle, 1=coast, 0=brake per point."""
    zones: list[float] = []
    for thr, brk in zip(samples["throttle"], samples["brake"], strict=True):
        if brk >= 1:
            zones.append(0)
        elif thr >= 1:
            zones.append(2)
        else:
            zones.append(1)
    return {
        "x": samples["pos_x"],
        "z": samples["pos_z"],
        "speed": samples["speed"],
        "zone": zones,
    }


def speed_peaks_valleys(
    samples: Samples, min_gap_m: float = 100.0
) -> dict[str, list[dict[str, float]]]:
    """Local speed maxima/minima along the lap, thinned to one per min_gap_m."""
    dist, speed = samples["dist"], samples["speed"]
    peaks: list[dict[str, float]] = []
    valleys: list[dict[str, float]] = []
    w = 30  # ticks (~0.5 s) on each side
    i = w
    while i < len(speed) - w:
        window = speed[i - w : i + w + 1]
        point = {
            "dist": dist[i],
            "speed": speed[i],
            "x": samples["pos_x"][i],
            "z": samples["pos_z"][i],
        }
        if speed[i] >= max(window):
            if not peaks or dist[i] - peaks[-1]["dist"] > min_gap_m:
                peaks.append(point)
            i += w
        elif speed[i] <= min(window):
            if not valleys or dist[i] - valleys[-1]["dist"] > min_gap_m:
                valleys.append(point)
            i += w
        i += 1
    return {"peaks": peaks, "valleys": valleys}


# --- Fuel map ---------------------------------------------------------------

# GT7's fuel map setting (1..6 in some cars, modeled here as -5..+5 relative
# to current) changes fuel consumption ~10% per step; leaner mixture also
# costs lap time. These factors approximate observed in-game behavior.
FUEL_CONSUMPTION_PER_STEP = 0.10
LAP_TIME_COST_PER_STEP_MS = 250


@dataclass(slots=True)
class FuelMapRow:
    setting: int
    fuel_per_lap: float
    laps_remaining: float
    time_remaining_ms: int
    lap_time_delta_ms: int


def fuel_map(
    fuel_level: float, fuel_per_lap: float, lap_time_ms: int, settings_range: int = 5
) -> list[FuelMapRow]:
    """Laps/time remaining for each relative fuel-map setting.

    Positive settings burn more fuel (richer, faster); negative save fuel.
    """
    rows: list[FuelMapRow] = []
    if fuel_per_lap <= 0 or lap_time_ms <= 0:
        return rows
    for setting in range(-settings_range, settings_range + 1):
        consumption = fuel_per_lap * (1 + FUEL_CONSUMPTION_PER_STEP * setting)
        lap_delta = -LAP_TIME_COST_PER_STEP_MS * setting
        adjusted_lap_ms = lap_time_ms + lap_delta
        laps_remaining = fuel_level / consumption if consumption > 0 else float("inf")
        rows.append(
            FuelMapRow(
                setting=setting,
                fuel_per_lap=round(consumption, 3),
                laps_remaining=round(laps_remaining, 2),
                time_remaining_ms=int(laps_remaining * adjusted_lap_ms),
                lap_time_delta_ms=lap_delta,
            )
        )
    return rows
