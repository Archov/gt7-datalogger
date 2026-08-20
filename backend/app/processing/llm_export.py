"""Compact, deterministic session analysis intended for LLM consumption.

The exporter operates only on persisted dictionaries. It never mutates them,
never depends on live Race Engineer state, and only emits source-rate samples
inside bounded interesting ranges.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import median
from typing import Any, Literal, TypeGuard, cast

from app.models import AidsBits
from app.processing import analysis, events, spatial, wheelspin_characterization
from app.processing.laps import SAMPLE_COLUMNS, fuel_flow_totals
from app.processing.orientation import ORIENTATION_CHANNELS, normalize_quaternion
from app.processing.surface import (
    LOOSE_CODES,
    SURFACE_KERB,
    SURFACE_NONE,
    SURFACE_TARMAC,
    wheel_codes,
)

Detail = Literal["compact", "standard", "deep"]
Samples = dict[str, list[float]]
Table = dict[str, Any]
CANONICAL_SAMPLE_COLUMNS = frozenset(SAMPLE_COLUMNS)

FORMAT = "gt7-datalogger-llm-session"
VERSION = 1
TRACE_STEP_M = 5.0
THROTTLE_REAPPLICATION_PCT = 70.0
POWERED_THROTTLE_PCT = 70.0
POWERED_SPEED_MIN_KMH = 50.0
POWERED_SPEED_MAX_KMH = 220.0
POWERED_YAW_MIN = 0.05
POWERED_FRONT_STEER_MIN = 0.01
POWERED_WHEEL_STEER_MIN = 0.05
RECURRING_BUCKET_M = 120.0
RECURRING_MIN_OCCURRENCES = 3
RECURRING_MIN_LAPS = 2
CORNER_ASSOCIATION_M = 250.0
SEGMENT_LOSS_MIN_MS = 150
SEGMENT_LOSSES_PER_LAP = 3
ANOMALY_MAD_SCALE = 4.0
ANOMALY_MIN_RUN_M = 10.0
ANOMALY_FLOORS = {
    "front_steering": 0.02,
    "yaw": 0.10,
    "wheel_slip": 0.15,
    "body_height": 5.0,
    "suspension": 5.0,
}
RANGE_PADDING_M = 25.0
RANGE_MERGE_GAP_M = 25.0
MAX_RANGE_M = 300.0
MAX_INTERESTING_RANGES = 12
MAX_DEEP_DISTANCE_M = 1500.0
MAX_DEEP_LAP_FRACTION = 0.25

WHEELS = ("fl", "fr", "rl", "rr")
TRACE_CHANNELS = (
    "speed",
    "throttle",
    "brake",
    "throttle_filtered",
    "brake_filtered",
    "gear",
    "rpm",
    "steer_fl_rad",
    "steer_fr_rad",
    "steering_wheel_rad",
    "steering_angular_velocity",
    "yaw_rate_signed",
    "sway",
    "heave",
    "surge",
    "slip_fl",
    "slip_fr",
    "slip_rl",
    "slip_rr",
    "body_height",
    "sus_fl",
    "sus_fr",
    "sus_rl",
    "sus_rr",
    "tt_fl",
    "tt_fr",
    "tt_rl",
    "tt_rr",
    "torque_fl",
    "torque_fr",
    "torque_rl",
    "torque_rr",
    "energy_recovery",
    "road_plane_x",
    "road_plane_y",
    "road_plane_z",
    "road_plane_distance",
    "surface",
    "aids",
)
STANDARD_TRACE_CORE = frozenset(("speed", "throttle", "brake", "gear"))
STANDARD_BRAKING_CHANNELS = frozenset(
    ("brake_filtered", "surge", "slip_fl", "slip_fr", "slip_rl", "slip_rr", "aids")
)
STANDARD_WHEELSPIN_CHANNELS = frozenset(
    (
        "throttle_filtered",
        "slip_fl",
        "slip_fr",
        "slip_rl",
        "slip_rr",
        "torque_fl",
        "torque_fr",
        "torque_rl",
        "torque_rr",
        "aids",
    )
)
STANDARD_CHASSIS_CHANNELS = frozenset(
    (
        "body_height",
        "sus_fl",
        "sus_fr",
        "sus_rl",
        "sus_rr",
        "heave",
        "road_plane_distance",
    )
)
STANDARD_STEERING_CHANNELS = frozenset(
    (
        "steer_fl_rad",
        "steer_fr_rad",
        "steering_wheel_rad",
        "steering_angular_velocity",
        "yaw_rate_signed",
        "sway",
    )
)
STANDARD_SURFACE_CHANNELS = frozenset(
    ("surface", "body_height", "sus_fl", "sus_fr", "sus_rl", "sus_rr")
)
STANDARD_SEGMENT_LOSS_CHANNELS = frozenset(
    (
        "steer_fl_rad",
        "steer_fr_rad",
        "yaw_rate_signed",
        "slip_fl",
        "slip_fr",
        "slip_rl",
        "slip_rr",
        "aids",
    )
)


class ExportInputError(ValueError):
    """The stored session cannot satisfy the requested export."""


class ReferenceNotFoundError(LookupError):
    """An explicit reference is not part of this session."""


def table(columns: Iterable[str], rows: Iterable[list[Any]]) -> Table:
    return {"columns": list(columns), "rows": list(rows)}


def _finite(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: object, digits: int = 1) -> int | float | None:
    if not _finite(value):
        return None
    number = float(value)
    rounded = round(number, digits)
    return int(rounded) if digits == 0 else rounded


def strict_json_value(value: Any) -> Any:
    """Recursively replace non-finite numbers and stabilize unordered values."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): strict_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json_value(item) for item in value]
    if isinstance(value, set):
        return [strict_json_value(item) for item in sorted(value)]
    return value


def _samples(lap: dict[str, Any]) -> Samples:
    value = lap.get("samples")
    return value if isinstance(value, dict) else {}


def _aligned(samples: Samples, column: str) -> list[float] | None:
    t = samples.get("t") or []
    values = samples.get(column)
    if values is None or len(values) != len(t):
        return None
    return values


def _available_channels(samples: Samples) -> list[str]:
    n = len(samples.get("t") or [])
    orientation_arrays = [samples.get(channel) or [] for channel in ORIENTATION_CHANNELS]
    orientation_valid = all(len(values) == n for values in orientation_arrays) and all(
        normalize_quaternion(tuple(values[index] for values in orientation_arrays)) is not None
        for index in range(n)
    )
    out: list[str] = []
    for key, values in samples.items():
        if key not in CANONICAL_SAMPLE_COLUMNS:
            continue
        if len(values) != n:
            continue
        if key == "surface" and (not values or all(int(v) == SURFACE_NONE for v in values)):
            continue
        if key in ORIENTATION_CHANNELS and not orientation_valid:
            continue
        out.append(key)
    return sorted(out)


def _channel_provenance_table(bundle: dict[str, Any], laps: list[dict[str, Any]]) -> Table:
    provided = bundle.get("channel_provenance")
    by_lap = provided if isinstance(provided, dict) else {}
    rows: list[list[Any]] = []
    for lap in laps:
        lap_id = int(lap["id"])
        state = by_lap.get(lap_id, by_lap.get(str(lap_id)))
        if not isinstance(state, dict):
            state = {
                "persisted": _available_channels(_samples(lap)),
                "archive_replay": [],
                "unavailable": [],
            }
        rows.append(
            [
                lap_id,
                sorted(str(value) for value in state.get("persisted", [])),
                sorted(str(value) for value in state.get("archive_replay", [])),
                sorted(str(value) for value in state.get("unavailable", [])),
            ]
        )
    return table(("lap_id", "persisted", "archive_replay", "unavailable"), rows)


def _usable(lap: dict[str, Any]) -> bool:
    if not bool(lap.get("counts_for_best", True)):
        return False
    samples = _samples(lap)
    dist = samples.get("dist") or []
    times = samples.get("t") or []
    return (
        len(dist) >= 2
        and len(times) == len(dist)
        and all(_finite(v) for v in (*dist, *times))
        and dist[-1] > dist[0]
    )


def select_reference(
    laps: list[dict[str, Any]], explicit_ref: int | None = None
) -> tuple[dict[str, Any], str]:
    """Choose a full reference with stable, user-visible reason codes."""
    if explicit_ref is not None:
        selected = next((lap for lap in laps if int(lap["id"]) == explicit_ref), None)
        if selected is None:
            raise ReferenceNotFoundError(f"reference lap {explicit_ref} not found in session")
        if not _usable(selected):
            raise ExportInputError(f"reference lap {explicit_ref} is not a usable full lap")
        return selected, "explicit"

    usable = [lap for lap in laps if _usable(lap)]
    if not usable:
        raise ExportInputError("session has no usable full lap")
    clean = [lap for lap in usable if lap.get("clean_lap") is True]
    if clean:
        return min(
            clean, key=lambda lap: (int(lap["time_ms"]), int(lap["id"]))
        ), "fastest_clean_full_lap"
    unknown = [lap for lap in usable if lap.get("clean_lap") is None]
    if unknown:
        return min(
            unknown, key=lambda lap: (int(lap["time_ms"]), int(lap["id"]))
        ), "fastest_full_lap_cleanliness_unknown"
    return min(
        usable, key=lambda lap: (int(lap["time_ms"]), int(lap["id"]))
    ), "fastest_dirty_full_lap"


def _weighted_stats(values: list[float], weights: list[float]) -> dict[str, float] | None:
    pairs = [
        (float(value), max(float(weight), 0.0))
        for value, weight in zip(values, weights, strict=False)
        if _finite(value) and _finite(weight)
    ]
    if not pairs:
        return None
    if not any(weight > 0 for _, weight in pairs):
        pairs = [(value, 1.0) for value, _ in pairs]
    total = sum(weight for _, weight in pairs)
    ordered = sorted(pairs)

    def percentile(fraction: float) -> float:
        target = total * fraction
        running = 0.0
        for value, weight in ordered:
            running += weight
            if running >= target:
                return value
        return ordered[-1][0]

    return {
        "min": min(value for value, _ in pairs),
        "mean": sum(value * weight for value, weight in pairs) / total,
        "p05": percentile(0.05),
        "p95": percentile(0.95),
        "max": max(value for value, _ in pairs),
    }


def _mean(values: list[float], weights: list[float]) -> float | None:
    weighted_sum = 0.0
    total = 0.0
    fallback: list[float] = []
    for value, weight in zip(values, weights, strict=False):
        if not _finite(value) or not _finite(weight):
            continue
        numeric = float(value)
        fallback.append(numeric)
        safe_weight = max(float(weight), 0.0)
        weighted_sum += numeric * safe_weight
        total += safe_weight
    if total > 0:
        return weighted_sum / total
    return sum(fallback) / len(fallback) if fallback else None


def _mean_max_abs(values: list[float], weights: list[float]) -> tuple[float, float] | None:
    absolute = [abs(value) for value in values]
    mean = _mean(absolute, weights)
    return (mean, max(absolute)) if mean is not None and absolute else None


def _round_stats(stats: dict[str, float] | None, names: tuple[str, ...], digits: int) -> list[Any]:
    return [_number(stats.get(name), digits) if stats else None for name in names]


def _surface_shares(values: list[float], weights: list[float]) -> tuple[float, float, float] | None:
    totals = {"tarmac": 0.0, "kerb": 0.0, "loose": 0.0}
    total = 0.0
    for value, weight in zip(values, weights, strict=False):
        if int(value) == SURFACE_NONE:
            continue
        for code in wheel_codes(int(value)):
            total += weight
            if code == SURFACE_TARMAC:
                totals["tarmac"] += weight
            elif code == SURFACE_KERB:
                totals["kerb"] += weight
            elif code in LOOSE_CODES:
                totals["loose"] += weight
    if total <= 0:
        return None
    return (
        round(totals["tarmac"] * 100 / total, 1),
        round(totals["kerb"] * 100 / total, 1),
        round(totals["loose"] * 100 / total, 1),
    )


def _pair_average(a: list[float] | None, b: list[float] | None) -> list[float] | None:
    return [(x + y) / 2 for x, y in zip(a, b, strict=True)] if a and b else None


def _indexed(samples: Samples, column: str, indices: list[int]) -> list[float] | None:
    values = _aligned(samples, column)
    return [values[i] for i in indices] if values else None


def _mean_peak_abs(values: list[float] | None, weights: list[float], digits: int) -> list[Any]:
    if not values:
        return [None, None]
    return [
        _number(_mean([abs(value) for value in values], weights), digits),
        _number(max(abs(value) for value in values), digits),
    ]


def _sample_at(
    samples: Samples, column: str, distance: float, *, discrete: bool = False
) -> float | None:
    values = _aligned(samples, column)
    if not values:
        return None
    fn = analysis.nearest if discrete else analysis.interp
    return fn(samples["dist"], values, distance)


def _lap_fuel_flow(lap: dict[str, Any]) -> tuple[object, object]:
    """Prefer tick-level flows for historical rows written with the net formula."""
    levels = _samples(lap).get("fuel")
    if not levels or not all(_finite(value) for value in levels):
        return lap.get("fuel_consumed"), None
    start = lap.get("fuel_start")
    end = lap.get("fuel_end")
    if not _finite(start) or not _finite(end):
        return lap.get("fuel_consumed"), None
    return fuel_flow_totals(float(start), levels, float(end))


def _lap_table(laps: list[dict[str, Any]], ref: dict[str, Any]) -> Table:
    columns = (
        "lap_id",
        "gt7_lap",
        "time_ms",
        "delta_to_reference_ms",
        "finished_at",
        "counts_for_best",
        "clean_lap",
        "off_track_count",
        "fuel_start",
        "fuel_end",
        "fuel_consumed",
        "fuel_refueled",
        "full_throttle_pct",
        "full_brake_pct",
        "coast_pct",
        "tire_spin_pct",
        "max_speed_kmh",
        "minimum_body_height_mm",
        "tcs_pct",
        "asm_pct",
        "lockup_count",
        "wheelspin_count",
        "bottoming_count",
        "kerb_count",
        "gear_ratios",
        "gearing_top_speed",
        "rpm_alert",
        "packet_format",
        "wheelbase_m",
        "car_category",
        "fuel_capacity",
    )
    rows: list[list[Any]] = []
    ref_time = int(ref["time_ms"])
    for lap in laps:
        counts = lap.get("event_counts") or {}
        gearing = lap.get("gearing") or {}
        meta = lap.get("telemetry_meta") or {}
        full = bool(lap.get("counts_for_best", True))
        fuel_consumed, fuel_refueled = _lap_fuel_flow(lap)
        rows.append(
            [
                lap["id"],
                lap["number"],
                lap["time_ms"],
                int(lap["time_ms"]) - ref_time if full else None,
                lap.get("finished_at"),
                full,
                lap.get("clean_lap"),
                lap.get("off_track_count"),
                _number(lap.get("fuel_start"), 3),
                _number(lap.get("fuel_end"), 3),
                _number(fuel_consumed, 3),
                _number(fuel_refueled, 3),
                _number(lap.get("full_throttle_pct"), 1),
                _number(lap.get("full_brake_pct"), 1),
                _number(lap.get("coasting_pct"), 1),
                _number(lap.get("tire_spin_pct"), 1),
                _number(lap.get("max_speed"), 1),
                _number(lap.get("min_body_height"), 1),
                _number(lap.get("tcs_active_pct"), 1),
                _number(lap.get("asm_active_pct"), 1),
                counts.get("lockup", 0),
                counts.get("wheelspin", 0),
                counts.get("bottoming", 0),
                counts.get("kerb", 0),
                gearing.get("ratios"),
                _number(gearing.get("top_speed"), 1),
                _number(gearing.get("rpm_alert"), 0),
                meta.get("packet_format"),
                _number(meta.get("wheelbase_m"), 3),
                meta.get("car_category"),
                _number(meta.get("fuel_capacity"), 1),
            ]
        )
    return table(columns, rows)


def _chassis_table(laps: list[dict[str, Any]]) -> Table:
    columns: list[str] = ["lap_id"]
    columns += [f"body_height_{name}_mm" for name in ("min", "mean", "p05", "p95")]
    for wheel in WHEELS:
        columns += [f"suspension_{wheel}_{name}_mm" for name in ("min", "mean", "p95", "max")]
    for wheel in WHEELS:
        columns += [f"tire_temp_{wheel}_{name}_c" for name in ("min", "mean", "max", "p05", "p95")]
    for wheel in WHEELS:
        columns += [f"slip_{wheel}_{name}" for name in ("mean", "p95", "max")]
    columns += [
        "front_average_slip_mean",
        "rear_average_slip_mean",
        "front_lr_slip_difference_mean",
        "rear_lr_slip_difference_mean",
        "powered_corner_rear_slip_mean",
        "powered_corner_rear_slip_p95",
        "front_steering_mean_abs_rad",
        "front_steering_peak_abs_rad",
        "steering_wheel_mean_abs_rad",
        "steering_wheel_peak_abs_rad",
        "steering_angular_velocity_mean_abs_rad_s",
        "steering_angular_velocity_peak_abs_rad_s",
        "sway_mean_abs",
        "sway_peak_abs",
        "heave_mean_abs",
        "heave_peak_abs",
        "surge_mean_abs",
        "surge_peak_abs",
        "yaw_signed_mean_rad_s",
        "yaw_abs_mean_rad_s",
        "yaw_peak_abs_rad_s",
        "throttle_filter_difference_signed_mean_pct",
        "throttle_filter_difference_abs_mean_pct",
        "throttle_filter_difference_peak_abs_pct",
        "brake_filter_difference_signed_mean_pct",
        "brake_filter_difference_abs_mean_pct",
        "brake_filter_difference_peak_abs_pct",
        "tarmac_contact_pct",
        "kerb_contact_pct",
        "loose_surface_contact_pct",
        "off_track_excursion_count",
    ]
    rows: list[list[Any]] = []
    for lap in laps:
        samples = _samples(lap)
        times = samples.get("t") or []
        weights = analysis.time_weights(times)
        row: list[Any] = [lap["id"]]
        body = _aligned(samples, "body_height")
        row += _round_stats(
            _weighted_stats(body, weights) if body else None, ("min", "mean", "p05", "p95"), 1
        )
        for wheel in WHEELS:
            values = _aligned(samples, f"sus_{wheel}")
            row += _round_stats(
                _weighted_stats(values, weights) if values else None,
                ("min", "mean", "p95", "max"),
                1,
            )
        for wheel in WHEELS:
            values = _aligned(samples, f"tt_{wheel}")
            row += _round_stats(
                _weighted_stats(values, weights) if values else None,
                ("min", "mean", "max", "p05", "p95"),
                1,
            )
        slips: dict[str, list[float] | None] = {}
        for wheel in WHEELS:
            values = _aligned(samples, f"slip_{wheel}")
            slips[wheel] = values
            row += _round_stats(
                _weighted_stats(values, weights) if values else None,
                ("mean", "p95", "max"),
                4,
            )

        front = _pair_average(slips["fl"], slips["fr"])
        rear = _pair_average(slips["rl"], slips["rr"])
        front_diff = (
            [abs(a - b) for a, b in zip(slips["fl"], slips["fr"], strict=True)]
            if slips["fl"] and slips["fr"]
            else None
        )
        rear_diff = (
            [abs(a - b) for a, b in zip(slips["rl"], slips["rr"], strict=True)]
            if slips["rl"] and slips["rr"]
            else None
        )
        row += [
            _number(_mean(v, weights), 4) if v else None
            for v in (front, rear, front_diff, rear_diff)
        ]

        throttle = _aligned(samples, "throttle")
        speed = _aligned(samples, "speed")
        yaw = _aligned(samples, "yaw_rate_signed") or _aligned(samples, "yaw_rate")
        steer_fl = _aligned(samples, "steer_fl_rad")
        steer_fr = _aligned(samples, "steer_fr_rad")
        steering_wheel = _aligned(samples, "steering_wheel_rad")
        powered: list[float] = []
        powered_weights: list[float] = []
        if rear and throttle and speed:
            for i, value in enumerate(rear):
                activity = (
                    (yaw is not None and abs(yaw[i]) >= POWERED_YAW_MIN)
                    or (
                        steer_fl is not None
                        and steer_fr is not None
                        and (abs(steer_fl[i]) + abs(steer_fr[i])) / 2 >= POWERED_FRONT_STEER_MIN
                    )
                    or (
                        steering_wheel is not None
                        and abs(steering_wheel[i]) >= POWERED_WHEEL_STEER_MIN
                    )
                )
                if (
                    throttle[i] >= POWERED_THROTTLE_PCT
                    and POWERED_SPEED_MIN_KMH <= speed[i] <= POWERED_SPEED_MAX_KMH
                    and activity
                ):
                    powered.append(value)
                    powered_weights.append(weights[i])
        powered_stats = _weighted_stats(powered, powered_weights)
        row += _round_stats(powered_stats, ("mean", "p95"), 4)

        front_steering = (
            [(abs(a) + abs(b)) / 2 for a, b in zip(steer_fl, steer_fr, strict=True)]
            if steer_fl and steer_fr
            else None
        )
        for values in (
            front_steering,
            [abs(v) for v in steering_wheel] if steering_wheel else None,
        ):
            stats = _mean_max_abs(values, weights) if values else None
            row += [_number(stats[0], 4), _number(stats[1], 4)] if stats else [None, None]
        steering_velocity = _aligned(samples, "steering_angular_velocity")
        stats = _mean_max_abs(steering_velocity, weights) if steering_velocity else None
        row += [_number(stats[0], 4), _number(stats[1], 4)] if stats else [None, None]
        for channel in ("sway", "heave", "surge"):
            values = _aligned(samples, channel)
            stats = _mean_max_abs(values, weights) if values else None
            row += [_number(stats[0], 4), _number(stats[1], 4)] if stats else [None, None]
        yaw_signed = _aligned(samples, "yaw_rate_signed")
        if yaw_signed:
            row += [
                _number(_mean(yaw_signed, weights), 4),
                _number(_mean([abs(v) for v in yaw_signed], weights), 4),
                _number(max(abs(v) for v in yaw_signed), 4),
            ]
        else:
            row += [None, None, None]
        for requested, filtered in (("throttle", "throttle_filtered"), ("brake", "brake_filtered")):
            a, b = _aligned(samples, requested), _aligned(samples, filtered)
            if a and b:
                diff = [x - y for x, y in zip(a, b, strict=True)]
                row += [
                    _number(_mean(diff, weights), 1),
                    _number(_mean([abs(v) for v in diff], weights), 1),
                    _number(max(abs(v) for v in diff), 1),
                ]
            else:
                row += [None, None, None]
        surface = _aligned(samples, "surface")
        shares = _surface_shares(surface, weights) if surface else None
        row += list(shares) if shares else [None, None, None]
        row.append(lap.get("off_track_count"))
        rows.append(row)
    return table(columns, rows)


def _window_values(samples: Samples, column: str, start: float, end: float) -> list[float]:
    dist = samples.get("dist") or []
    values = samples.get(column) or []
    return [
        value
        for d, value in zip(dist, values, strict=False)
        if start <= d <= end and _finite(value)
    ]


def _elapsed_at(samples: Samples, distance: float) -> float:
    return analysis.interp(samples["dist"], samples["t"], distance)


def _timing_table(
    laps: list[dict[str, Any]], ref: dict[str, Any], segment_m: float
) -> tuple[Table, list[dict[str, Any]]]:
    ref_samples = _samples(ref)
    total = ref_samples["dist"][-1]
    boundaries: list[tuple[float, float]] = []
    start = 0.0
    while start < total:
        end = min(start + segment_m, total)
        boundaries.append((start, end))
        start += segment_m
    rows: list[list[Any]] = []
    losses: list[dict[str, Any]] = []
    ref_zero = _elapsed_at(ref_samples, 0.0)
    for lap in laps:
        if not _usable(lap):
            continue
        samples = _samples(lap)
        lap_zero = _elapsed_at(samples, 0.0)
        for boundary_index, (start, end) in enumerate(boundaries):
            finish_segment = boundary_index == len(boundaries) - 1
            required_distance = start if finish_segment else end
            if samples["dist"][-1] + 1e-6 < required_distance:
                continue
            lap_start = _elapsed_at(samples, start) - lap_zero
            ref_start = _elapsed_at(ref_samples, start) - ref_zero
            if finish_segment:
                lap_end = float(lap["time_ms"]) / 1000
                ref_end = float(ref["time_ms"]) / 1000
                speed_end = samples["dist"][-1]
            else:
                lap_end = _elapsed_at(samples, end) - lap_zero
                ref_end = _elapsed_at(ref_samples, end) - ref_zero
                speed_end = end
            segment_time = (lap_end - lap_start) * 1000
            segment_delta = ((lap_end - lap_start) - (ref_end - ref_start)) * 1000
            cumulative_delta = (lap_end - ref_end) * 1000
            speeds = _window_values(samples, "speed", start, speed_end)
            average_speed = (
                (end - start) / (lap_end - lap_start) * 3.6 if lap_end > lap_start else None
            )
            rows.append(
                [
                    lap["id"],
                    _number(start, 1),
                    _number(end, 1),
                    _number(segment_time, 0),
                    _number(segment_delta, 0),
                    _number(cumulative_delta, 0),
                    _number(min(speeds), 1) if speeds else None,
                    _number(average_speed, 1),
                ]
            )
            if int(lap["id"]) != int(ref["id"]) and segment_delta >= SEGMENT_LOSS_MIN_MS:
                losses.append(
                    {
                        "lap_id": int(lap["id"]),
                        "start": start,
                        "end": end,
                        "loss_ms": segment_delta,
                    }
                )
    return table(
        (
            "lap_id",
            "start_m",
            "end_m",
            "segment_time_ms",
            "segment_delta_vs_reference_ms",
            "cumulative_delta_vs_reference_ms",
            "minimum_speed_kmh",
            "average_speed_kmh",
        ),
        rows,
    ), losses


def _corner_definitions(corners: list[dict[str, Any]]) -> Table:
    return table(
        (
            "corner",
            "direction",
            "entry_m",
            "apex_m",
            "exit_m",
            "angle_deg",
            "reference_minimum_speed_kmh",
        ),
        (
            [
                corner["n"],
                corner["direction"],
                corner["entry_dist"],
                corner["apex_dist"],
                corner["exit_dist"],
                corner["angle_deg"],
                corner["min_speed"],
            ]
            for corner in corners
        ),
    )


def _corner_indices(samples: Samples, entry: float, exit_: float) -> list[int]:
    dist = samples.get("dist") or []
    if entry <= exit_:
        return [i for i, value in enumerate(dist) if entry <= value <= exit_]
    return [i for i, value in enumerate(dist) if value >= entry or value <= exit_]


def _event_start_m(event: dict[str, Any]) -> float:
    return float(event.get("start_progress_m", event.get("start_dist", 0)))


def _event_end_m(event: dict[str, Any]) -> float:
    return float(event.get("end_progress_m", event.get("end_dist", _event_start_m(event))))


def _associated_events(
    events: list[dict[str, Any]], entry: float, exit_: float
) -> list[dict[str, Any]]:
    if entry > exit_:
        return [
            event
            for event in events
            if _event_start_m(event) >= entry or _event_start_m(event) <= exit_
        ]
    out: list[dict[str, Any]] = []
    for event in events:
        distance = _event_start_m(event)
        kind = str(event.get("type", ""))
        if kind in ("lockup", "bottoming"):
            matched = entry - CORNER_ASSOCIATION_M <= distance <= exit_
        elif kind == "wheelspin":
            matched = entry <= distance <= exit_ + CORNER_ASSOCIATION_M
        else:
            matched = entry <= distance <= exit_
        if matched:
            out.append(event)
    return out


def _corner_analysis(
    laps: list[dict[str, Any]], ref: dict[str, Any], corners: list[dict[str, Any]]
) -> Table:
    columns = (
        "lap_id",
        "corner",
        "corner_elapsed_ms",
        "corner_delta_vs_reference_ms",
        "brake_application_m",
        "brake_point_delta_vs_reference_m",
        "minimum_speed_kmh",
        "minimum_speed_delta_vs_reference_kmh",
        "throttle_reapplication_m",
        "front_steering_mean_abs_rad",
        "front_steering_peak_abs_rad",
        "yaw_mean_abs_rad_s",
        "yaw_peak_abs_rad_s",
        "sway_mean_abs",
        "sway_peak_abs",
        "front_slip_mean",
        "front_slip_peak",
        "rear_slip_mean",
        "rear_slip_peak",
        "minimum_body_height_mm",
        "maximum_suspension_fl_mm",
        "maximum_suspension_fr_mm",
        "maximum_suspension_rl_mm",
        "maximum_suspension_rr_mm",
        "mean_tire_temp_fl_c",
        "mean_tire_temp_fr_c",
        "mean_tire_temp_rl_c",
        "mean_tire_temp_rr_c",
        "tcs_activity_pct",
        "tarmac_contact_pct",
        "kerb_contact_pct",
        "loose_surface_contact_pct",
        "event_count",
        "event_types",
    )
    ref_samples = _samples(ref)
    rows: list[list[Any]] = []
    for lap in laps:
        if not _usable(lap):
            continue
        samples = _samples(lap)
        weights = analysis.time_weights(samples.get("t") or [])
        events = list(lap.get("events") or [])
        for corner in corners:
            entry, apex, exit_ = (
                float(corner[key]) for key in ("entry_dist", "apex_dist", "exit_dist")
            )
            indices = _corner_indices(samples, entry, exit_)
            if not indices:
                continue
            wraps = entry > exit_
            elapsed = (
                None
                if wraps
                else (_elapsed_at(samples, exit_) - _elapsed_at(samples, entry)) * 1000
            )
            ref_elapsed = (
                None
                if wraps
                else (_elapsed_at(ref_samples, exit_) - _elapsed_at(ref_samples, entry)) * 1000
            )
            brake = None if wraps else analysis.brake_point(samples, entry)
            brake_delta = None if wraps else analysis.brake_point_delta(samples, ref_samples, entry)
            speed_values = [samples["speed"][i] for i in indices]
            min_speed = min(speed_values) if speed_values else None
            ref_min_speed = float(corner["min_speed"])
            throttle_reapply = None
            if not wraps:
                throttle = _aligned(samples, "throttle")
                if throttle:
                    throttle_reapply = next(
                        (
                            samples["dist"][i]
                            for i in indices
                            if samples["dist"][i] >= apex
                            and throttle[i] >= THROTTLE_REAPPLICATION_PCT
                        ),
                        None,
                    )

            window_weights = [weights[i] for i in indices]
            steer_fl = _indexed(samples, "steer_fl_rad", indices)
            steer_fr = _indexed(samples, "steer_fr_rad", indices)
            front_steer = (
                [(abs(a) + abs(b)) / 2 for a, b in zip(steer_fl, steer_fr, strict=True)]
                if steer_fl and steer_fr
                else None
            )
            yaw = _indexed(samples, "yaw_rate_signed", indices) or _indexed(
                samples, "yaw_rate", indices
            )
            sway = _indexed(samples, "sway", indices)
            slip_fl = _indexed(samples, "slip_fl", indices)
            slip_fr = _indexed(samples, "slip_fr", indices)
            slip_rl = _indexed(samples, "slip_rl", indices)
            slip_rr = _indexed(samples, "slip_rr", indices)
            front_slip = (
                [(a + b) / 2 for a, b in zip(slip_fl, slip_fr, strict=True)]
                if slip_fl and slip_fr
                else None
            )
            rear_slip = (
                [(a + b) / 2 for a, b in zip(slip_rl, slip_rr, strict=True)]
                if slip_rl and slip_rr
                else None
            )

            row: list[Any] = [
                lap["id"],
                corner["n"],
                _number(elapsed, 0),
                _number(elapsed - ref_elapsed, 0)
                if elapsed is not None and ref_elapsed is not None
                else None,
                _number(brake, 1),
                _number(brake_delta, 1),
                _number(min_speed, 1),
                _number(min_speed - ref_min_speed, 1) if min_speed is not None else None,
                _number(throttle_reapply, 1),
            ]
            row += _mean_peak_abs(front_steer, window_weights, 4)
            row += _mean_peak_abs(yaw, window_weights, 4)
            row += _mean_peak_abs(sway, window_weights, 4)
            for values in (front_slip, rear_slip):
                row += (
                    [_number(_mean(values, window_weights), 4), _number(max(values), 4)]
                    if values
                    else [None, None]
                )
            body = _indexed(samples, "body_height", indices)
            row.append(_number(min(body), 1) if body else None)
            for wheel in WHEELS:
                values = _indexed(samples, f"sus_{wheel}", indices)
                row.append(_number(max(values), 1) if values else None)
            for wheel in WHEELS:
                values = _indexed(samples, f"tt_{wheel}", indices)
                row.append(_number(_mean(values, window_weights), 1) if values else None)
            aids = _indexed(samples, "aids", indices)
            if aids:
                total_weight = sum(window_weights) or 1.0
                tcs = sum(
                    weight
                    for value, weight in zip(aids, window_weights, strict=True)
                    if int(value) & AidsBits.TCS
                )
                row.append(_number(tcs * 100 / total_weight, 1))
            else:
                row.append(None)
            surface = _indexed(samples, "surface", indices)
            shares = _surface_shares(surface, window_weights) if surface else None
            row += list(shares) if shares else [None, None, None]
            associated = _associated_events(events, entry, exit_)
            row += [len(associated), sorted({str(event.get("type", "")) for event in associated})]
            rows.append(row)
    return table(columns, rows)


def _event_table(laps: list[dict[str, Any]]) -> Table:
    columns = (
        "lap_id",
        "type",
        "start_m",
        "end_m",
        "wheels",
        "severity",
        "start_time_ms",
        "end_time_ms",
        "duration_ms",
        "speed_start_kmh",
        "minimum_speed_kmh",
        "speed_end_kmh",
        "throttle_start_pct",
        "throttle_end_pct",
        "brake_start_pct",
        "brake_end_pct",
        "gear_start",
        "gear_end",
        "minimum_body_height_mm",
        "relevant_wheel_slip",
        "surface_start",
        "surface_end",
        "kerb_contact_pct",
        "loose_surface_contact_pct",
        "start_progress_m",
        "end_progress_m",
        "peak_along_track_speed_kmh",
        "backward_distance_m",
    )
    rows: list[list[Any]] = []
    for lap in laps:
        samples = _samples(lap)
        if not samples.get("dist") or not samples.get("t"):
            continue
        for event in sorted(
            lap.get("events") or [],
            key=lambda value: (float(value.get("start_dist", 0)), str(value.get("type", ""))),
        ):
            start = float(event.get("start_dist", 0))
            end = float(event.get("end_dist", start))
            start_t, end_t = _elapsed_at(samples, start), _elapsed_at(samples, end)
            start_time_ms = (
                float(event["start_time_ms"])
                if _finite(event.get("start_time_ms"))
                else start_t * 1000
            )
            end_time_ms = (
                float(event["end_time_ms"]) if _finite(event.get("end_time_ms")) else end_t * 1000
            )
            duration_ms = (
                float(event["duration_ms"])
                if _finite(event.get("duration_ms"))
                else max(0.0, end_time_ms - start_time_ms)
            )

            speeds = _window_values(samples, "speed", start, end)
            body = _window_values(samples, "body_height", start, end)
            wheels = [str(wheel) for wheel in event.get("wheels") or []]
            slips = [
                value
                for wheel in wheels
                for value in _window_values(samples, f"slip_{wheel}", start, end)
            ]
            kind = str(event.get("type", ""))
            relevant_slip = (
                min(slips)
                if slips and kind == "lockup"
                else max(slips)
                if slips and kind == "wheelspin"
                else None
            )
            surface = _aligned(samples, "surface")
            if surface:
                indices = [i for i, value in enumerate(samples["dist"]) if start <= value <= end]
                shares = (
                    _surface_shares([surface[i] for i in indices], [1.0] * len(indices))
                    if indices
                    else None
                )
            else:
                shares = None
            rows.append(
                [
                    lap["id"],
                    kind,
                    _number(start, 1),
                    _number(end, 1),
                    wheels,
                    _number(event.get("severity"), 4),
                    _number(start_time_ms, 0),
                    _number(end_time_ms, 0),
                    _number(duration_ms, 0),
                    _number(_sample_at(samples, "speed", start), 1),
                    _number(min(speeds), 1) if speeds else None,
                    _number(_sample_at(samples, "speed", end), 1),
                    _number(_sample_at(samples, "throttle", start), 1),
                    _number(_sample_at(samples, "throttle", end), 1),
                    _number(_sample_at(samples, "brake", start), 1),
                    _number(_sample_at(samples, "brake", end), 1),
                    _number(_sample_at(samples, "gear", start, discrete=True), 0),
                    _number(_sample_at(samples, "gear", end, discrete=True), 0),
                    _number(min(body), 1) if body else None,
                    _number(relevant_slip, 4),
                    _number(_sample_at(samples, "surface", start, discrete=True), 0),
                    _number(_sample_at(samples, "surface", end, discrete=True), 0),
                    shares[1] if shares else None,
                    shares[2] if shares else None,
                    _number(event.get("start_progress_m"), 1),
                    _number(event.get("end_progress_m"), 1),
                    _number(event.get("peak_along_track_speed_kmh"), 1),
                    _number(event.get("backward_distance_m"), 1),
                ]
            )
    return table(columns, rows)


def _wheel_or_axle(wheels: list[str]) -> str:
    unique = sorted(set(wheels))
    if len(unique) == 1:
        return unique[0]
    if set(unique) <= {"fl", "fr"}:
        return "front"
    if set(unique) <= {"rl", "rr"}:
        return "rear"
    return "+".join(unique) if unique else "unknown"


def _corner_at(distance: float, corners: list[dict[str, Any]], kind: str = "") -> int | None:
    for corner in corners:
        entry, exit_ = float(corner["entry_dist"]), float(corner["exit_dist"])
        if (entry <= exit_ and entry <= distance <= exit_) or (
            entry > exit_ and (distance >= entry or distance <= exit_)
        ):
            return int(corner["n"])
    for corner in corners:
        entry, exit_ = float(corner["entry_dist"]), float(corner["exit_dist"])
        if entry > exit_:
            continue
        if kind in ("lockup", "bottoming") and 0 <= entry - distance <= CORNER_ASSOCIATION_M:
            return int(corner["n"])
        if kind == "wheelspin" and 0 <= distance - exit_ <= CORNER_ASSOCIATION_M:
            return int(corner["n"])
    return None


def _recurring_events(
    laps: list[dict[str, Any]], corners: list[dict[str, Any]]
) -> tuple[Table, list[dict[str, Any]]]:
    buckets: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for lap in laps:
        if not _usable(lap) or lap.get("clean_lap") is False:
            continue
        for event in lap.get("events") or []:
            kind = str(event.get("type", ""))
            if kind not in ("lockup", "wheelspin", "bottoming"):
                continue
            start = float(event.get("start_dist", 0))
            key = (
                kind,
                _wheel_or_axle(list(event.get("wheels") or [])),
                int(start // RECURRING_BUCKET_M),
            )
            buckets.setdefault(key, []).append({**event, "lap_id": int(lap["id"])})
    rows: list[list[Any]] = []
    clusters: list[dict[str, Any]] = []
    for key in sorted(buckets):
        events = buckets[key]
        lap_ids = sorted({int(event["lap_id"]) for event in events})
        if len(events) < RECURRING_MIN_OCCURRENCES or len(lap_ids) < RECURRING_MIN_LAPS:
            continue
        kind, wheel, _ = key
        distances = [float(event.get("start_dist", 0)) for event in events]
        severities = [float(event.get("severity", 0)) for event in events]
        distance = sum(distances) / len(distances)
        corner = _corner_at(distance, corners, kind)
        row = [
            kind,
            wheel,
            _number(distance, 1),
            corner,
            len(events),
            lap_ids,
            _number(min(severities), 4),
            _number(sum(severities) / len(severities), 4),
            _number(max(severities), 4),
        ]
        rows.append(row)
        clusters.append(
            {
                "type": kind,
                "wheel": wheel,
                "distance": distance,
                "corner": corner,
                "lap_ids": lap_ids,
            }
        )
    return table(
        (
            "type",
            "wheel_or_axle",
            "approximate_distance_m",
            "reference_corner",
            "occurrence_count",
            "lap_ids",
            "severity_min",
            "severity_mean",
            "severity_max",
        ),
        rows,
    ), clusters


def _derived_resampled(
    samples: Samples, name: str, total: float
) -> tuple[list[float], list[float]] | None:
    grid = [i * TRACE_STEP_M for i in range(int(total / TRACE_STEP_M) + 1)]
    dist = samples.get("dist") or []
    if name == "front_steering":
        a, b = _aligned(samples, "steer_fl_rad"), _aligned(samples, "steer_fr_rad")
        values = [(abs(x) + abs(y)) / 2 for x, y in zip(a, b, strict=True)] if a and b else None
    elif name == "yaw":
        source = _aligned(samples, "yaw_rate_signed") or _aligned(samples, "yaw_rate")
        values = [abs(value) for value in source] if source else None
    elif name == "wheel_slip":
        cols = [_aligned(samples, f"slip_{wheel}") for wheel in WHEELS]
        values = (
            [max(col[i] for col in cols if col is not None) for i in range(len(dist))]
            if all(cols)
            else None
        )
    elif name == "body_height":
        values = _aligned(samples, "body_height")
    else:
        cols = [_aligned(samples, f"sus_{wheel}") for wheel in WHEELS]
        values = (
            [max(col[i] for col in cols if col is not None) for i in range(len(dist))]
            if all(cols)
            else None
        )
    if values is None:
        return None
    return grid, [analysis.interp(dist, values, point) for point in grid]


def _anomaly_candidates(laps: list[dict[str, Any]], ref: dict[str, Any]) -> list[dict[str, Any]]:
    ref_samples = _samples(ref)
    candidates: list[dict[str, Any]] = []
    for lap in laps:
        if not _usable(lap) or int(lap["id"]) == int(ref["id"]):
            continue
        samples = _samples(lap)
        total = min(samples["dist"][-1], ref_samples["dist"][-1])
        for name, floor in ANOMALY_FLOORS.items():
            mine, theirs = (
                _derived_resampled(samples, name, total),
                _derived_resampled(ref_samples, name, total),
            )
            if mine is None or theirs is None:
                continue
            grid, mine_values = mine
            differences = [abs(a - b) for a, b in zip(mine_values, theirs[1], strict=True)]
            centre = median(differences)
            mad = median(abs(value - centre) for value in differences)
            threshold = max(floor, centre + ANOMALY_MAD_SCALE * mad)
            active = [value >= threshold for value in differences]
            start: int | None = None
            for i in range(len(active) + 1):
                on = active[i] if i < len(active) else False
                if on and start is None:
                    start = i
                elif not on and start is not None:
                    end = i - 1
                    if grid[end] - grid[start] >= ANOMALY_MIN_RUN_M:
                        candidates.append(
                            {
                                "start": grid[start],
                                "end": grid[end],
                                "reasons": [f"{name}_anomaly"],
                                "lap_ids": [int(lap["id"])],
                                "priority": 1,
                                "corner": None,
                            }
                        )
                    start = None
    return candidates


def _padded_candidate(candidate: dict[str, Any], total: float) -> dict[str, Any]:
    start = max(0.0, float(candidate["start"]) - RANGE_PADDING_M)
    end = min(total, float(candidate["end"]) + RANGE_PADDING_M)
    return {**candidate, "start": start, "end": end}


def _corner_segments(corner: dict[str, Any], total: float) -> list[tuple[float, float]]:
    entry = float(corner["entry_dist"])
    exit_ = float(corner["exit_dist"])
    return [(entry, exit_)] if entry <= exit_ else [(entry, total), (0.0, exit_)]


def _corner_overlap(corner: dict[str, Any], start: float, end: float, total: float) -> float:
    return sum(
        max(0.0, min(end, segment_end) - max(start, segment_start))
        for segment_start, segment_end in _corner_segments(corner, total)
    )


def _corner_intersects(corner: dict[str, Any], start: float, end: float, total: float) -> bool:
    return any(
        max(start, segment_start) <= min(end, segment_end) + 1e-6
        for segment_start, segment_end in _corner_segments(corner, total)
    )


def _corner_midpoint_distance(
    corner: dict[str, Any], start: float, end: float, total: float
) -> float:
    direct = abs(float(corner["apex_dist"]) - (start + end) / 2)
    return min(direct, max(0.0, total - direct))


def _primary_corner(
    candidates: list[dict[str, Any]],
    corners: list[dict[str, Any]],
    start: float,
    end: float,
    total: float,
) -> int | None:
    corner_by_number = {int(corner["n"]): corner for corner in corners}
    source_rank = {"segment_loss": 1, "event": 2, "recurring": 3}
    evidence: dict[int, tuple[int, int]] = {}
    for candidate in candidates:
        corner_number = candidate.get("corner")
        rank = source_rank.get(str(candidate.get("corner_source", "")), 0)
        if corner_number is None or rank == 0:
            continue
        number = int(corner_number)
        previous_rank, previous_count = evidence.get(number, (0, 0))
        if rank > previous_rank:
            evidence[number] = (rank, 1)
        elif rank == previous_rank:
            evidence[number] = (rank, previous_count + 1)
    if evidence:
        best_rank = max(rank for rank, _count in evidence.values())
        eligible = [number for number, (rank, _count) in evidence.items() if rank == best_rank]

        def evidence_key(number: int) -> tuple[int, float, float, int]:
            corner = corner_by_number.get(number)
            overlap = _corner_overlap(corner, start, end, total) if corner else 0.0
            midpoint_distance = (
                _corner_midpoint_distance(corner, start, end, total) if corner else math.inf
            )
            return (-evidence[number][1], -overlap, midpoint_distance, number)

        return min(eligible, key=evidence_key)

    intersecting = [corner for corner in corners if _corner_intersects(corner, start, end, total)]
    if not intersecting:
        return None
    selected = min(
        intersecting,
        key=lambda corner: (
            -_corner_overlap(corner, start, end, total),
            _corner_midpoint_distance(corner, start, end, total),
            int(corner["n"]),
        ),
    )
    return int(selected["n"])


def _candidate_intersects_window(candidate: dict[str, Any], start: float, end: float) -> bool:
    return max(start, float(candidate["start"])) < min(end, float(candidate["end"])) - 1e-6


def _finalize_ranges(
    candidates: list[dict[str, Any]], total: float, corners: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    padded = sorted(
        (_padded_candidate(candidate, total) for candidate in candidates),
        key=lambda item: (float(item["start"]), float(item["end"]), -int(item["priority"])),
    )
    components: list[dict[str, Any]] = []
    for candidate in padded:
        previous = components[-1] if components else None
        if previous and float(candidate["start"]) <= float(previous["end"]) + RANGE_MERGE_GAP_M:
            previous["end"] = max(float(previous["end"]), float(candidate["end"]))
            previous["members"].append(candidate)
        else:
            components.append(
                {
                    "start": float(candidate["start"]),
                    "end": float(candidate["end"]),
                    "members": [candidate],
                }
            )

    windows: list[dict[str, Any]] = []
    for component in components:
        window_start = float(component["start"])
        component_end = float(component["end"])
        while window_start < component_end - 1e-6:
            window_end = min(window_start + MAX_RANGE_M, component_end)
            members = [
                candidate
                for candidate in component["members"]
                if _candidate_intersects_window(candidate, window_start, window_end)
            ]
            windows.append(
                {
                    "start": window_start,
                    "end": window_end,
                    "reasons": sorted(
                        {str(reason) for candidate in members for reason in candidate["reasons"]}
                    ),
                    "lap_ids": sorted(
                        {int(lap_id) for candidate in members for lap_id in candidate["lap_ids"]}
                    ),
                    "priority": max(int(candidate["priority"]) for candidate in members),
                    "corner": _primary_corner(members, corners, window_start, window_end, total),
                    "suppress_start": False,
                }
            )
            window_start = window_end

    selected = sorted(
        windows,
        key=lambda item: (
            -int(item["priority"]),
            float(item["start"]),
            float(item["end"]),
            tuple(item["reasons"]),
            tuple(item["lap_ids"]),
        ),
    )[:MAX_INTERESTING_RANGES]
    for item in selected:
        item["suppress_start"] = any(
            other is not item
            and float(other["start"]) < float(item["start"])
            and abs(float(other["end"]) - float(item["start"])) <= 1e-6
            for other in selected
        )
    return [{**item, "id": i + 1} for i, item in enumerate(selected)]


def _interesting_ranges(
    laps: list[dict[str, Any]],
    ref: dict[str, Any],
    corners: list[dict[str, Any]],
    losses: list[dict[str, Any]],
    recurring: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    total = _samples(ref)["dist"][-1]
    candidates: list[dict[str, Any]] = []
    for lap in laps:
        for event in lap.get("events") or []:
            start = _event_start_m(event)
            end = _event_end_m(event)
            candidates.append(
                {
                    "start": start,
                    "end": end,
                    "reasons": [str(event.get("type", "event"))],
                    "lap_ids": [int(lap["id"])],
                    "priority": 2,
                    "corner": _corner_at(start, corners, str(event.get("type", ""))),
                    "corner_source": "event",
                }
            )
    for cluster in recurring:
        distance = float(cluster["distance"])
        candidates.append(
            {
                "start": distance,
                "end": distance,
                "reasons": [f"recurring_{cluster['type']}"],
                "lap_ids": cluster["lap_ids"],
                "priority": 3,
                "corner": cluster["corner"],
                "corner_source": "recurring",
            }
        )
    by_lap: dict[int, list[dict[str, Any]]] = {}
    for loss in losses:
        by_lap.setdefault(int(loss["lap_id"]), []).append(loss)
    for lap_id, lap_losses in by_lap.items():
        for loss in sorted(
            lap_losses, key=lambda item: (-float(item["loss_ms"]), float(item["start"]))
        )[:SEGMENT_LOSSES_PER_LAP]:
            midpoint = (float(loss["start"]) + float(loss["end"])) / 2
            candidates.append(
                {
                    "start": loss["start"],
                    "end": loss["end"],
                    "reasons": [f"segment_loss_{round(float(loss['loss_ms']))}ms"],
                    "lap_ids": [lap_id],
                    "priority": 2,
                    "corner": _corner_at(midpoint, corners),
                    "corner_source": "segment_loss",
                }
            )
    candidates += _anomaly_candidates(laps, ref)
    return _finalize_ranges(candidates, total, corners)


def _ranges_table(ranges: list[dict[str, Any]]) -> Table:
    return table(
        ("range_id", "start_m", "end_m", "reasons", "lap_ids", "reference_corner", "priority"),
        (
            [
                item["id"],
                _number(item["start"], 1),
                _number(item["end"], 1),
                item["reasons"],
                item["lap_ids"],
                item["corner"],
                item["priority"],
            ]
            for item in ranges
        ),
    )


def _round_channel(channel: str, value: float) -> int | float:
    if channel in ("gear", "aids", "surface", "rpm"):
        return round(value)
    if channel in (
        "speed",
        "throttle",
        "brake",
        "throttle_filtered",
        "brake_filtered",
        "body_height",
        "road_plane_distance",
    ) or channel.startswith(("sus_", "tt_")):
        return round(value, 1)
    return round(value, 4)


def _full_trace_columns(samples: Samples) -> list[str]:
    return [
        column
        for column in TRACE_CHANNELS
        if _aligned(samples, column) is not None
        and not (column == "surface" and all(int(v) == SURFACE_NONE for v in samples[column]))
    ]


def _standard_requested_channels(reasons: list[str]) -> set[str]:
    requested = set(STANDARD_TRACE_CORE)
    for reason in reasons:
        normalized = reason.lower().replace("-", "_")
        if normalized.startswith("recurring_"):
            normalized = normalized.removeprefix("recurring_")
        if normalized in ("braking", "lockup"):
            requested.update(STANDARD_BRAKING_CHANNELS)
        if normalized in ("wheelspin", "wheel_slip_anomaly"):
            requested.update(STANDARD_WHEELSPIN_CHANNELS)
        if normalized in ("bottoming", "suspension_anomaly", "body_height_anomaly"):
            requested.update(STANDARD_CHASSIS_CHANNELS)
        if normalized in ("front_steering_anomaly", "yaw_anomaly"):
            requested.update(STANDARD_STEERING_CHANNELS)
        if any(token in normalized for token in ("surface", "off_track", "kerb")):
            requested.update(STANDARD_SURFACE_CHANNELS)
        if normalized.startswith("segment_loss_"):
            requested.update(STANDARD_SEGMENT_LOSS_CHANNELS)
    return requested


def _standard_trace_columns(samples: Samples, reasons: list[str]) -> list[str]:
    requested = _standard_requested_channels(reasons)
    return [column for column in _full_trace_columns(samples) if column in requested]


def _distance_trace(
    samples: Samples,
    start: float,
    end: float,
    reasons: list[str],
    *,
    include_start: bool = True,
) -> tuple[list[str], list[list[Any]]]:
    channels = _standard_trace_columns(samples, reasons)
    grid: list[float] = []
    point = start if include_start else start + TRACE_STEP_M
    while point <= end + 1e-6:
        grid.append(point)
        point += TRACE_STEP_M
    if not grid or end - grid[-1] > 0.05:
        grid.append(end)
    rows: list[list[Any]] = []
    for distance in grid:
        row: list[Any] = [_number(distance, 1), _number(_elapsed_at(samples, distance) * 1000, 0)]
        for channel in channels:
            fn = analysis.nearest if channel in analysis.NEAREST_COLUMNS else analysis.interp
            row.append(_round_channel(channel, fn(samples["dist"], samples[channel], distance)))
        rows.append(row)
    return ["distance_m", "time_ms", *channels], rows


def _standard_traces(
    ranges: list[dict[str, Any]], laps: list[dict[str, Any]], ref_id: int
) -> Table:
    by_id = {int(lap["id"]): lap for lap in laps}
    rows: list[list[Any]] = []
    for item in ranges:
        lap_ids = sorted(set(int(value) for value in item["lap_ids"]) | {ref_id})
        for lap_id in lap_ids:
            lap = by_id.get(lap_id)
            if lap is None or not _usable(lap):
                continue
            samples = _samples(lap)
            end = min(float(item["end"]), samples["dist"][-1])
            if end <= float(item["start"]):
                continue
            columns, trace_rows = _distance_trace(
                samples,
                float(item["start"]),
                end,
                list(item["reasons"]),
                include_start=not bool(item.get("suppress_start")),
            )
            rows.append([item["id"], lap_id, columns, trace_rows])
    return table(("range_id", "lap_id", "columns", "rows"), rows)


def _source_trace(
    samples: Samples, start: float, end: float, *, include_start: bool = True
) -> tuple[list[str], list[list[Any]]]:
    channels = _full_trace_columns(samples)
    indices = [
        i
        for i, value in enumerate(samples["dist"])
        if (start <= value if include_start else start < value) and value <= end
    ]
    rows: list[list[Any]] = []
    for i in indices:
        row: list[Any] = [_number(samples["dist"][i], 1), _number(samples["t"][i] * 1000, 0)]
        row += [_round_channel(column, samples[column][i]) for column in channels]
        rows.append(row)
    return ["distance_m", "time_ms", *channels], rows


def _deep_traces(ranges: list[dict[str, Any]], laps: list[dict[str, Any]], ref_id: int) -> Table:
    by_id = {int(lap["id"]): lap for lap in laps}
    used: dict[int, float] = {}
    rows: list[list[Any]] = []
    for item in ranges:
        for lap_id in sorted(set(int(value) for value in item["lap_ids"]) | {ref_id}):
            lap = by_id.get(lap_id)
            if lap is None or not _usable(lap):
                continue
            samples = _samples(lap)
            budget = min(MAX_DEEP_DISTANCE_M, samples["dist"][-1] * MAX_DEEP_LAP_FRACTION)
            remaining = budget - used.get(lap_id, 0.0)
            if remaining <= 0:
                continue
            start = float(item["start"])
            end = min(float(item["end"]), samples["dist"][-1], start + remaining)
            if end <= start:
                continue
            columns, trace_rows = _source_trace(
                samples, start, end, include_start=not bool(item.get("suppress_start"))
            )
            if trace_rows:
                rows.append([item["id"], lap_id, columns, trace_rows])
                used[lap_id] = used.get(lap_id, 0.0) + end - start
    return table(("range_id", "lap_id", "columns", "rows"), rows)


def _corner_line_table(
    laps: list[dict[str, Any]],
    path: spatial.ReferencePath | None,
    trajectories: dict[int, spatial.ProjectedTrajectory],
    corners: list[dict[str, Any]],
) -> Table:
    columns = (
        "lap_id",
        "corner",
        "entry_lateral_offset_m",
        "apex_lateral_offset_m",
        "exit_lateral_offset_m",
        "entry_heading_error_deg",
        "apex_heading_error_deg",
        "exit_heading_error_deg",
        "line_rms_offset_m",
        "line_peak_offset_m",
        "projection_distance_rms_m",
        "projection_distance_peak_m",
        "corner_path_length_m",
        "mean_abs_curvature_1_per_m",
        "peak_abs_curvature_1_per_m",
        "peak_curvature_progress_m",
    )
    if path is None:
        return table(columns, [])
    rows: list[list[Any]] = []
    for lap in laps:
        trajectory = trajectories.get(int(lap["id"]))
        if trajectory is None:
            continue
        for metrics in spatial.corner_line_metrics(path, trajectory, corners):
            rows.append(
                [
                    lap["id"],
                    metrics["corner"],
                    _number(metrics["entry_lateral_offset"], 1),
                    _number(metrics["apex_lateral_offset"], 1),
                    _number(metrics["exit_lateral_offset"], 1),
                    _number(metrics["entry_heading_error"], 1),
                    _number(metrics["apex_heading_error"], 1),
                    _number(metrics["exit_heading_error"], 1),
                    _number(metrics["line_rms_offset"], 1),
                    _number(metrics["line_peak_offset"], 1),
                    _number(metrics["projection_distance_rms"], 1),
                    _number(metrics["projection_distance_peak"], 1),
                    _number(metrics["corner_path_length"], 1),
                    _number(metrics["mean_abs_curvature"], 6),
                    _number(metrics["peak_abs_curvature"], 6),
                    _number(metrics["peak_curvature_progress"], 1),
                ]
            )
    return table(columns, rows)


def _spatial_reference_table(path: spatial.ReferencePath, step: float) -> Table:
    geometry = spatial.reference_geometry(path, step)
    columns = ["progress_m", "x_m"]
    if "y" in geometry:
        columns.append("y_m")
    columns += ["z_m", "heading_deg", "curvature_1_per_m"]
    rows: list[list[Any]] = []
    for i, progress in enumerate(geometry["progress"]):
        row: list[Any] = [_number(progress, 1), _number(geometry["x"][i], 1)]
        if "y" in geometry:
            row.append(_number(geometry["y"][i], 1))
        row += [
            _number(geometry["z"][i], 1),
            _number(math.degrees(geometry["heading"][i]), 1),
            _number(geometry["curvature"][i], 6),
        ]
        rows.append(row)
    return table(columns, rows)


def _line_traces_table(
    laps: list[dict[str, Any]],
    path: spatial.ReferencePath,
    trajectories: dict[int, spatial.ProjectedTrajectory],
    step: float,
) -> Table:
    rows: list[list[Any]] = []
    for lap in laps:
        trajectory = trajectories.get(int(lap["id"]))
        if trajectory is None:
            continue
        trace = spatial.resample_projected(path, trajectory, step)
        if not trace["progress"]:
            continue
        columns = ["progress_m", "time_ms", "x_m"]
        if "y" in trace:
            columns.append("y_m")
        columns += [
            "z_m",
            "lateral_offset_m",
            "projection_distance_m",
            "heading_error_deg",
        ]
        if "chassis_heading_error" in trace:
            columns += ["chassis_heading_error_deg", "body_slip_angle_deg"]
        columns.append("curvature_1_per_m")
        source_columns = [
            (column, public_name)
            for column, public_name in (
                ("speed", "speed_kmh"),
                ("along_track_speed_kmh", "along_track_speed_kmh"),
                ("throttle", "throttle_pct"),
                ("brake", "brake_pct"),
                ("gear", "gear"),
                ("steering_wheel_rad", "steering_wheel_rad"),
                ("yaw_rate_signed", "yaw_rate_signed"),
            )
            if column in trace
        ]
        columns += [public_name for _column, public_name in source_columns]
        trace_rows: list[list[Any]] = []
        for i, progress in enumerate(trace["progress"]):
            row: list[Any] = [
                _number(progress, 1),
                _number(trace["time_ms"][i], 0),
                _number(trace["x"][i], 1),
            ]
            if "y" in trace:
                row.append(_number(trace["y"][i], 1))
            row += [
                _number(trace["z"][i], 1),
                _number(trace["lateral_offset"][i], 1),
                _number(trace["projection_distance"][i], 1),
                _number(trace["heading_error"][i], 1),
            ]
            if "chassis_heading_error" in trace:
                row += [
                    _number(trace["chassis_heading_error"][i], 1),
                    _number(trace["body_slip_angle"][i], 1),
                ]
            row.append(_number(trace["curvature"][i], 6))
            for column, _public_name in source_columns:
                digits = 0 if column == "gear" else 4 if column.endswith(("_rad", "_signed")) else 1
                row.append(_number(trace[column][i], digits))
            trace_rows.append(row)
        rows.append([lap["id"], columns, trace_rows])
    return table(("lap_id", "columns", "rows"), rows)


def _wheelspin_characterization_table(
    result: wheelspin_characterization.CharacterizationResult,
) -> Table:
    outer_columns = (
        "lap_id",
        "event_index",
        "reference_corner",
        "context_corner",
        "corner_relation",
        "corner_distance_m",
        "start_m",
        "end_m",
        "start_progress_m",
        "end_progress_m",
        "start_time_ms",
        "end_time_ms",
        "observed",
        "derived",
        "sequence",
        "comparator_quality",
        "comparators",
        "resolution",
        "unresolved_reasons",
        "candidates",
    )
    observed_columns = (
        "stored_type",
        "stored_severity",
        "event_wheels",
        "effective_drivetrain",
        "speed_at_onset_kmh",
        "gear_at_onset",
        "throttle_at_onset_pct",
        "throttle_filtered_at_onset_pct",
        "brake_at_onset_pct",
        "brake_filtered_at_onset_pct",
        "along_track_speed_at_onset_kmh",
        "chassis_heading_deg_at_onset",
        "travel_heading_deg_at_onset",
        "body_slip_angle_deg_at_onset",
        "yaw_rate_signed_at_onset",
        "steering_wheel_rad_at_onset",
        "steer_fl_rad_at_onset",
        "steer_fr_rad_at_onset",
        "surface_at_onset",
        "aids_at_onset",
        "body_height_at_onset_mm",
        "suspension_at_onset_mm",
        "sway_at_onset_raw",
        "heave_at_onset_raw",
        "surge_at_onset_raw",
        "positive_torque_at_onset_raw",
        "slip_at_onset",
        "peak_slip",
    )
    derived_columns = (
        "eligibility",
        "analyzed_powered_wheels",
        "event_local_powered_wheels",
        "effective_powered_wheels",
        "event_local_torque_shares",
        "event_power_conflict",
        "trustworthy_powered_wheel_intersection",
        "mean_powered_slip_at_onset",
        "slip_excess_integral_ratio_s",
        "duration_above_threshold_ms",
        "same_axle_asymmetry_peak",
        "same_axle_asymmetry_duration_ms",
        "both_powered_wheels_crossed_threshold",
        "vertical_disturbance_families",
        "slope_window_ms",
        "throttle_slope_pct_s",
        "throttle_filtered_slope_pct_s",
        "torque_slope_raw_s",
        "torque_slope_by_wheel_raw_s",
        "torque_step_by_wheel_raw",
        "yaw_change_rad_s2",
        "brake_slope_pct_s",
        "ordering",
    )
    sequence_columns = (
        "meaningful_throttle_rise_start_ms",
        "meaningful_torque_rise_start_ms",
        "rotation_deviation_start_ms",
        "body_slip_deviation_start_ms",
        "yaw_deviation_start_ms",
        "slip_threshold_cross_ms",
        "shift_ms",
        "surface_transition_ms",
        "vertical_disturbance_ms",
    )
    quality_columns = (
        "count",
        "quality",
        "quality_score",
        "ideal_control_count",
        "relative_control_count",
        "same_gear_count",
        "speed_spread_kmh",
        "median_projection_distance_m",
        "median_slip_separation",
        "clean_or_unknown_count",
        "bottoming_context_count",
        "lap_ids",
    )
    comparator_columns = (
        "lap_id",
        "control_class",
        "anchor_time_ms",
        "end_time_ms",
        "peak_slip",
        "slip_excess_integral_ratio_s",
        "duration_above_threshold_ms",
        "slip_separation",
        "speed_kmh",
        "gear",
        "speed_difference_kmh",
        "projection_distance_m",
        "utility",
        "bottoming_context",
    )
    candidate_columns = (
        "mechanism",
        "score",
        "evidence_coverage",
        "support",
        "counterevidence",
    )
    evidence_columns = (
        "feature",
        "event_value",
        "comparator_median",
        "comparator_min",
        "comparator_max",
        "comparator_mad",
        "weight",
        "signed_contribution",
    )

    def rounded(name: str, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: rounded(f"{name}_{key}", item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [rounded(name, item) for item in value]
        if not isinstance(value, float):
            return value
        if not math.isfinite(value):
            return None
        if name.endswith("_ms") or name in {"gear", "surface_at_onset", "aids_at_onset"}:
            return round(value)
        if "steer" in name or "yaw" in name:
            digits = 4
        elif any(
            token in name
            for token in (
                "score",
                "weight",
                "coverage",
                "quality",
                "utility",
                "share",
                "severity",
                "slip",
                "integral",
                "asymmetry",
                "projection",
                "torque",
                "sway",
                "heave",
                "surge",
            )
        ) and "body_slip_angle" not in name:
            digits = 3
        else:
            digits = 1
        result_value = round(value, digits)
        return 0.0 if result_value == 0 else result_value

    config = wheelspin_characterization.DEFAULT_CONFIG

    def evidence_row(item: wheelspin_characterization.Contribution) -> list[Any]:
        return [
            item.feature,
            rounded(item.feature, item.event_value),
            rounded(item.feature, item.comparator_median),
            rounded(item.feature, item.comparator_min),
            rounded(item.feature, item.comparator_max),
            rounded(item.feature, item.comparator_mad),
            rounded("weight", item.weight),
            rounded("score", item.signed_contribution),
        ]

    rows: list[list[Any]] = []
    for item in result.events:
        quality = item.comparators
        candidate_rows: list[list[Any]] = []
        for candidate in item.candidates[: config.resolution.exported_candidates]:
            support = sorted(
                (rule for rule in candidate.contributions if rule.signed_contribution > 0),
                key=lambda rule: (-rule.signed_contribution, rule.feature),
            )[: config.resolution.exported_support]
            counter = sorted(
                (rule for rule in candidate.contributions if rule.signed_contribution < 0),
                key=lambda rule: (rule.signed_contribution, rule.feature),
            )[: config.resolution.exported_counter]
            candidate_rows.append(
                [
                    candidate.mechanism,
                    rounded("score", candidate.score),
                    rounded("coverage", candidate.evidence_coverage),
                    [evidence_row(rule) for rule in support],
                    [evidence_row(rule) for rule in counter],
                ]
            )
        rows.append(
            [
                item.lap_id,
                item.event_index,
                item.reference_corner,
                item.context_corner,
                item.corner_relation,
                rounded("corner_distance_m", item.corner_distance_m),
                rounded("start_m", item.start_m),
                rounded("end_m", item.end_m),
                rounded("start_progress_m", item.start_progress_m),
                rounded("end_progress_m", item.end_progress_m),
                item.start_time_ms,
                item.end_time_ms,
                [rounded(name, item.observed.get(name)) for name in observed_columns],
                [rounded(name, item.derived.get(name)) for name in derived_columns],
                [item.sequence.get(name) for name in sequence_columns],
                [
                    quality.count,
                    quality.quality,
                    rounded("quality_score", quality.quality_score),
                    quality.strong_control_count,
                    quality.relative_control_count,
                    quality.same_gear_count,
                    rounded("speed_spread_kmh", quality.speed_spread_kmh),
                    rounded("projection_distance_m", quality.median_projection_distance_m),
                    rounded("slip_separation", quality.median_slip_separation),
                    quality.clean_or_unknown_count,
                    quality.bottoming_context_count,
                    list(quality.lap_ids),
                ],
                [
                    [rounded(name, detail.get(name)) for name in comparator_columns]
                    for detail in item.comparator_details
                ],
                item.resolution,
                list(item.unresolved_reasons),
                candidate_rows,
            ]
        )
    return {
        "columns": list(outer_columns),
        "observed_columns": list(observed_columns),
        "derived_columns": list(derived_columns),
        "sequence_columns": list(sequence_columns),
        "comparator_quality_columns": list(quality_columns),
        "comparator_columns": list(comparator_columns),
        "candidate_columns": list(candidate_columns),
        "evidence_columns": list(evidence_columns),
        "rows": rows,
    }


def build_export(
    bundle: dict[str, Any],
    *,
    detail: Detail = "standard",
    segment_m: float = 100.0,
    explicit_ref: int | None = None,
) -> dict[str, Any]:
    """Build an LLM session document from one repository session bundle."""
    if detail not in ("compact", "standard", "deep"):
        raise ExportInputError(f"invalid detail level {detail!r}")
    if not 25 <= segment_m <= 1000 or not math.isfinite(segment_m):
        raise ExportInputError("segment_m must be between 25 and 1000")
    laps = sorted(list(bundle.get("laps") or []), key=lambda lap: int(lap["id"]))
    ref, reason = select_reference(laps, explicit_ref)
    ref_samples = _samples(ref)
    corners = analysis.detect_corners(ref_samples)
    timing, losses = _timing_table(laps, ref, segment_m)
    recurring_table, recurring = _recurring_events(laps, corners)
    spatial_path = spatial.build_reference_path(ref_samples)
    spatial_trajectories: dict[int, spatial.ProjectedTrajectory] = {}
    characterization_trajectories: dict[int, spatial.ProjectedTrajectory] = {}
    if spatial_path is not None:
        for lap in laps:
            trajectory = spatial.project_lap(
                spatial_path,
                _samples(lap),
                completed_time_ms=int(lap["time_ms"]),
            )
            if trajectory is not None:
                characterization_trajectories[int(lap["id"])] = trajectory
                if _usable(lap):
                    spatial_trajectories[int(lap["id"])] = trajectory
    event_laps: list[dict[str, Any]] = []
    for lap in laps:
        trajectory = spatial_trajectories.get(int(lap["id"]))
        reverse_events = events.detect_reverse_motion(trajectory.dense) if trajectory else []
        event_laps.append({**lap, "events": [*(lap.get("events") or []), *reverse_events]})
    wheelspin_result: wheelspin_characterization.CharacterizationResult | None = None
    if detail != "compact":
        wheelspin_result = wheelspin_characterization.characterize_wheelspin_events(
            event_laps,
            spatial_reference=spatial_path,
            trajectories=characterization_trajectories,
            corners=corners,
            comparison_lap_ids=set(spatial_trajectories),
            drivetrain_override=cast(str | None, bundle.get("drivetrain_override")),
        )
    all_channels = sorted(
        {channel for lap in laps for channel in _available_channels(_samples(lap))}
    )
    formats = sorted(
        {str((lap.get("telemetry_meta") or {}).get("packet_format", "unknown")) for lap in laps},
        key=lambda value: ({"A": 0, "B": 1, "~": 2, "C": 3}.get(value, 4), value),
    )
    session = dict(bundle.get("session") or {})
    session.update(
        {
            "lap_count": len(laps),
            "available_telemetry_channels": all_channels,
            "telemetry_formats": formats,
        }
    )
    output: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "options": {"detail": detail, "segment_m": _number(segment_m, 1)},
        "schema": {
            "units": {
                "speed": "km/h",
                "distance": "m",
                "time_and_delta": "ms",
                "inputs": "percent",
                "fuel": "L",
                "body_and_suspension": "mm",
                "tire_temperature": "C",
                "front_and_wheel_steering": "rad",
                "yaw_and_steering_angular_velocity": "rad/s",
                "slip": "wheel surface speed / vehicle speed",
                "sway_heave_surge": "raw GT7 acceleration values; physical unit not established",
                "torque_energy_road_plane": "raw GT7 values unless a table field states otherwise",
                "world_position_and_lateral_offset": "m",
                "heading_and_heading_error": "degrees",
                "path_curvature": "1/m",
            },
            "notes": [
                "Missing channels are unavailable, not zero.",
                (
                    "fuel_consumed is gross burn from downward tick-level tank changes; "
                    "fuel_refueled is upward tank change, so a pit stop does not cancel "
                    "the fuel burned on that lap."
                ),
                (
                    "channel_provenance identifies persisted, archive-replayed, and unavailable "
                    "telemetry without repeating source metadata per sample."
                ),
                "surface is a packed four-wheel code; 0 means unavailable.",
                "aids is a bitmask: TCS=1, ASM=2, handbrake=4, rev_limiter=8.",
                "powered_corner_rear_slip is an analysis heuristic, not an official GT7 metric.",
                "Steering/yaw signs are preserved; their mutual convention is not assumed.",
                "The spatial reference is the selected reference lap path, not a track centerline.",
                "Positive lateral offset is left of the reference path in its direction of travel.",
                (
                    "Projection distance is diagnostic confidence evidence, not driving quality "
                    "by itself."
                ),
                "Large projection distances may represent off-line driving, spins, or excursions.",
                "Spatial projection uses X/Y/Z when both laps provide Y, otherwise X/Z.",
                "Spatial heading and curvature are planar X/Z measurements.",
                (
                    "Vehicle orientation is a local-to-world quaternion (x,y,z,w); local -Z is "
                    "the chassis nose and local +Y is chassis up."
                ),
                (
                    "Trajectory heading is direction of travel, chassis heading is direction "
                    "the nose points, and yaw rate is their rotational rate rather than either "
                    "angle."
                ),
                (
                    "Corner-line metrics use a 2 m internal grid; standard line tables use "
                    "10 m and deep line tables use 5 m."
                ),
                "Line-trace time_ms is elapsed lap time at spatial reference progress.",
                (
                    "speed_kmh is unsigned; along_track_speed_kmh is signed along the "
                    "selected reference path from a five-sample centered position difference."
                ),
                (
                    "Negative along-track speed means opposite physical motion, not "
                    "necessarily reverse gear; reference progress remains monotonic."
                ),
                (
                    "reverse_motion is derived from dense world-position motion before "
                    "progress coalescing; its severity is null and magnitude is carried by "
                    "peak_along_track_speed_kmh and backward_distance_m."
                ),
                (
                    "reverse_motion enters below -2.0 km/h, exits at -0.5 km/h, requires "
                    "500 ms, and bridges near-zero gaps up to 200 ms."
                ),
            ],
        },
        "session": session,
        "channel_availability": table(
            ("lap_id", "channels"),
            ([lap["id"], _available_channels(_samples(lap))] for lap in laps),
        ),
        "channel_provenance": _channel_provenance_table(bundle, laps),
        "reference": {"lap_id": ref["id"], "reason": reason},
        "laps": _lap_table(laps, ref),
        "whole_lap_chassis": _chassis_table(laps),
        "timing_segments": timing,
        "reference_corners": _corner_definitions(corners),
        "events": _event_table(event_laps),
        "recurring_events": recurring_table,
        "corner_line_analysis": _corner_line_table(
            laps, spatial_path, spatial_trajectories, corners
        ),
    }
    if detail != "compact":
        assert wheelspin_result is not None
        schema = cast(dict[str, Any], output["schema"])
        notes = cast(list[str], schema["notes"])
        notes.extend(
            (
                (
                    "wheelspin_characterization is heuristic derived evidence: weights are "
                    "ranking parameters, not a learned or calibrated model; candidate scores are "
                    "neither probabilities nor proven causes."
                ),
                (
                    "combined_lateral_longitudinal_load_candidate means power application during "
                    "an elevated rotational proxy state; tire force, load, and friction-circle "
                    "saturation are not measured."
                ),
                (
                    "Torque is in raw GT7 units; relative timing and distribution are usable, "
                    "but physical torque and tire force are unverified."
                ),
                (
                    "Bottoming is a sustained near-lap-maximum compression heuristic, not proof "
                    "of bump-stop, floor, or chassis contact."
                ),
                (
                    "Signed motion observations are preserved, while v1 mechanism scoring uses "
                    "absolute peer-relative magnitude unless direction is explicitly meaningful."
                ),
                (
                    "Steering magnitude alone does not support a combined-load candidate, and a "
                    "later correlated event does not establish an earlier cause."
                ),
                (
                    "Stored bottoming alone does not invalidate a comparator; independently timed "
                    "local vertical-motion evidence is required."
                ),
                (
                    "wheelspin_characterization is nested columnar; decode positional sub-rows "
                    "with their matching *_columns registry. mixed_or_unresolved is a resolution, "
                    "not a mechanism candidate, and every stored wheelspin event receives a row."
                ),
                (
                    "reference_corner requires strict containment; context_corner and "
                    "corner_relation are descriptive location context only and do not affect "
                    "scores."
                ),
            )
        )
        output["drivetrain_characterization"] = wheelspin_characterization.drivetrain_json(
            wheelspin_result.drivetrain
        )
        output["wheelspin_characterization"] = _wheelspin_characterization_table(wheelspin_result)
        ranges = _interesting_ranges(event_laps, ref, corners, losses, recurring)
        output["corner_analysis"] = _corner_analysis(event_laps, ref, corners)
        output["interesting_ranges"] = _ranges_table(ranges)
        output["detail_traces"] = _standard_traces(ranges, event_laps, int(ref["id"]))
        if spatial_path is not None:
            spatial_step = 5.0 if detail == "deep" else 10.0
            output["spatial_reference"] = _spatial_reference_table(spatial_path, spatial_step)
            output["line_traces"] = _line_traces_table(
                event_laps, spatial_path, spatial_trajectories, spatial_step
            )
        if detail == "deep":
            output["source_traces"] = _deep_traces(ranges, event_laps, int(ref["id"]))
    return cast(dict[str, Any], strict_json_value(output))
