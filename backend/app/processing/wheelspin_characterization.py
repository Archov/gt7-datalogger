"""Pure, deterministic characterization of stored wheelspin events.

The module ranks compatible mechanisms; it does not diagnose causes.  All tuning
parameters live in immutable configuration below, and every score contribution is
retained in the pure result before the LLM exporter bounds the explanation.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Literal, cast

from app.processing import analysis, spatial
from app.processing.orientation import wrap_angle
from app.processing.surface import LOOSE_CODES, SURFACE_KERB, wheel_codes

Samples = dict[str, list[float]]
Drivetrain = Literal["fwd", "rwd", "awd", "unknown"]
Direction = Literal["support", "counter"]

WHEELS = ("fl", "fr", "rl", "rr")
FRONT = ("fl", "fr")
REAR = ("rl", "rr")
MECHANISMS = (
    "power_step_candidate",
    "combined_lateral_longitudinal_load_candidate",
    "single_wheel_differential_spin_candidate",
    "rotation_instability_candidate",
    "surface_or_vertical_disturbance_candidate",
    "shift_transient_candidate",
)
COMPARATOR_FEATURES = frozenset(
    {
        "throttle_slope_outlier",
        "torque_slope_outlier",
        "comparator_like_initial_rotation",
        "body_slip_deviation",
        "chassis_travel_mismatch",
        "yaw_deviation",
        "elevated_rotation_through_slip",
        "normal_motion_state",
        "peer_relative_asymmetry",
        "one_wheel_peer_normal",
        "pre_power_body_slip",
        "pre_power_yaw",
        "comparator_normal_power",
        "vertical_before_slip",
        "body_suspension_disturbance",
        "comparator_normal_controls",
    }
)


@dataclass(frozen=True)
class TemporalConfig:
    pre_ms: int = 1000
    post_ms: int = 1500
    persistence_ms: int = 100
    vertical_persistence_ms: int = 50
    order_tolerance_ms: int = 100
    throttle_rise_pct: float = 10.0
    throttle_exit_hysteresis_pct: float = 5.0
    throttle_slope_pct_s: float = 20.0
    local_torque_start_ms: int = -100
    local_torque_end_ms: int = 300
    baseline_end_ms: int = -750
    throttle_slope_window_ms: int = 250
    feature_slope_window_ms: int = 500
    motion_half_window_samples: int = 2
    causal_disturbance_lead_ms: int = 400


@dataclass(frozen=True)
class ComparatorConfig:
    max_count: int = 5
    minimum_slip_separation: float = 0.03
    strong_slip_separation: float = 0.10
    strong_peak_slip: float = 1.10
    speed_floor_kmh: float = 15.0
    speed_fraction: float = 0.15
    utility_weights: tuple[tuple[str, float], ...] = (
        ("slip_separation", 0.30),
        ("speed_similarity", 0.25),
        ("same_gear", 0.15),
        ("projection_quality", 0.15),
        ("cleanliness", 0.15),
    )
    quality_weights: tuple[tuple[str, float], ...] = (
        ("count", 0.20),
        ("speed_similarity", 0.20),
        ("gear_consistency", 0.15),
        ("slip_separation", 0.25),
        ("projection_quality", 0.10),
        ("cleanliness", 0.10),
    )
    strong_quality: float = 0.75
    moderate_quality: float = 0.50
    weak_coverage_factor: float = 0.50
    moderate_coverage_factor: float = 0.80
    strong_control_min_count: int = 2
    robust_min_count: int = 2
    target_count: int = 3
    projection_scale_m: float = 5.0
    quality_speed_scale_kmh: float = 15.0
    clean_utility: float = 1.0
    unknown_clean_utility: float = 0.7
    dirty_utility: float = 0.2
    relative_integral_or_duration_improvement: float = 0.20
    relative_max_regression: float = 0.10


@dataclass(frozen=True)
class ThresholdConfig:
    slip: float = 1.10
    peer_slip_floor: float = 0.05
    body_slip_deg: float = 1.0
    heading_deg: float = 1.0
    yaw_rad_s: float = 0.10
    throttle_pct: float = 5.0
    throttle_slope_pct_s: float = 20.0
    suspension_mm: float = 5.0
    body_height_mm: float = 5.0
    heave_raw: float = 0.20
    asymmetry: float = 0.08
    asymmetry_persistence_ms: int = 250
    shift_near_ms: int = 400
    shift_absent_ms: int = 750
    robust_spread_count: float = 2.0
    mad_consistency_scale: float = 1.4826
    torque_baseline_mad_multiplier: float = 3.0
    torque_window_peak_fraction: float = 0.10
    torque_slope_minimum_raw_s: float = 1.0
    motion_distance_epsilon_m: float = 1e-6
    minimum_travel_speed_mps: float = 0.1


@dataclass(frozen=True)
class ResolutionConfig:
    minimum_score: float = 0.45
    top_gap: float = 0.10
    minimum_coverage: float = 0.50
    exported_candidates: int = 3
    exported_support: int = 4
    exported_counter: int = 2


@dataclass(frozen=True)
class CharacterizationConfig:
    temporal: TemporalConfig = TemporalConfig()
    comparators: ComparatorConfig = ComparatorConfig()
    thresholds: ThresholdConfig = ThresholdConfig()
    resolution: ResolutionConfig = ResolutionConfig()
    support_weights: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = (
        (
            "power_step_candidate",
            (
                ("throttle_slope_outlier", 0.30),
                ("torque_slope_outlier", 0.20),
                ("power_before_rotation", 0.15),
                ("multiple_powered_wheels_spinning", 0.15),
                ("comparator_like_initial_rotation", 0.20),
            ),
        ),
        (
            "combined_lateral_longitudinal_load_candidate",
            (
                ("body_slip_deviation", 0.30),
                ("chassis_travel_mismatch", 0.20),
                ("yaw_deviation", 0.20),
                ("elevated_rotation_through_slip", 0.20),
                ("steering_with_motion_evidence", 0.10),
            ),
        ),
        (
            "single_wheel_differential_spin_candidate",
            (
                ("peer_relative_asymmetry", 0.45),
                ("one_wheel_peer_normal", 0.30),
                ("persistent_asymmetry", 0.25),
            ),
        ),
        (
            "rotation_instability_candidate",
            (
                ("pre_power_body_slip", 0.30),
                ("pre_power_yaw", 0.25),
                ("rotation_before_power", 0.25),
                ("comparator_normal_power", 0.20),
            ),
        ),
        (
            "surface_or_vertical_disturbance_candidate",
            (
                ("surface_before_slip", 0.35),
                ("vertical_before_slip", 0.30),
                ("body_suspension_disturbance", 0.15),
                ("comparator_normal_controls", 0.20),
            ),
        ),
        (
            "shift_transient_candidate",
            (
                ("shift_before_slip", 0.40),
                ("normal_pre_shift_slip", 0.20),
                ("post_shift_slip_crossing", 0.20),
                ("aligned_power_transient", 0.20),
            ),
        ),
    )
    counter_weights: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = (
        (
            "power_step_candidate",
            (("rotation_before_power", 0.25),),
        ),
        (
            "combined_lateral_longitudinal_load_candidate",
            (
                ("normal_motion_state", 0.30),
                ("power_before_motion", 0.20),
            ),
        ),
        (
            "single_wheel_differential_spin_candidate",
            (("symmetric_bilateral_spin", 0.35),),
        ),
        ("rotation_instability_candidate", (("power_before_rotation", 0.25),)),
        ("surface_or_vertical_disturbance_candidate", (("disturbance_after_slip", 0.35),)),
        (
            "shift_transient_candidate",
            (("slip_rising_before_shift", 0.50), ("shift_after_slip", 0.35)),
        ),
    )


DEFAULT_CONFIG = CharacterizationConfig()


@dataclass(frozen=True)
class Contribution:
    feature: str
    criterion: str
    event_value: Any
    comparator_median: float | None
    comparator_min: float | None
    comparator_max: float | None
    comparator_mad: float | None
    direction: Direction
    weight: float
    activation: int
    signed_contribution: float
    available: bool


@dataclass(frozen=True)
class Candidate:
    mechanism: str
    preclamp_score: float
    score: float
    evidence_coverage: float
    contributions: tuple[Contribution, ...]


@dataclass(frozen=True)
class CatalogDrivetrain:
    layout: str | None
    effective: Drivetrain
    source: str
    effective_powered_wheels: tuple[str, ...]


@dataclass(frozen=True)
class ComparatorQuality:
    count: int
    quality: str
    quality_score: float
    strong_control_count: int
    relative_control_count: int
    same_gear_count: int
    speed_spread_kmh: float | None
    median_projection_distance_m: float | None
    median_slip_separation: float | None
    clean_or_unknown_count: int
    bottoming_context_count: int
    lap_ids: tuple[int, ...]


@dataclass(frozen=True)
class WheelspinCharacterization:
    lap_id: int
    event_index: int
    reference_corner: int | None
    context_corner: int | None
    corner_relation: str | None
    corner_distance_m: float | None
    start_m: float
    end_m: float
    start_progress_m: float | None
    end_progress_m: float | None
    start_time_ms: int | None
    end_time_ms: int | None
    observed: dict[str, Any]
    derived: dict[str, Any]
    sequence: dict[str, int | None]
    comparators: ComparatorQuality
    comparator_details: tuple[dict[str, Any], ...]
    candidates: tuple[Candidate, ...]
    resolution: Literal["resolved", "mixed_or_unresolved"]
    unresolved_reasons: tuple[str, ...]


@dataclass(frozen=True)
class LapContext:
    lap: dict[str, Any]
    samples: Samples
    trajectory: spatial.ProjectedTrajectory | None
    motion: dict[str, list[float]]
    comparison_eligible: bool
    disqualifying_event_times_ms: tuple[float, ...]
    loose_surface_times_ms: tuple[float, ...]
    vertical_disturbance_times_ms: tuple[float, ...]


@dataclass(frozen=True)
class CharacterizationResult:
    drivetrain: CatalogDrivetrain
    events: tuple[WheelspinCharacterization, ...]


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _aligned(samples: Samples, name: str) -> list[float] | None:
    t = samples.get("t") or []
    values = samples.get(name) or []
    # Sample blobs are validated once when recorded/resolved. Re-scanning a full
    # channel here turns bounded event-window work back into event × lap × samples.
    return values if t and len(values) == len(t) else None


def _interp(xs: list[float], ys: list[float], x: float) -> float | None:
    if not xs or len(xs) != len(ys) or x < xs[0] or x > xs[-1]:
        return None
    return analysis.interp(xs, ys, x)


def _at_time(
    samples: Samples, channel: str, time_ms: float, *, discrete: bool = False
) -> float | None:
    values = _aligned(samples, channel)
    times = samples.get("t") or []
    if values is None:
        return None
    target = time_ms / 1000
    if target < times[0] or target > times[-1]:
        return None
    fn = analysis.nearest if discrete else analysis.interp
    return fn(times, values, target)


def _indices(samples: Samples, start_ms: float, end_ms: float) -> list[int]:
    times = samples.get("t") or []
    start_s, end_s = start_ms / 1000, end_ms / 1000
    return list(range(bisect_left(times, start_s), bisect_right(times, end_s)))


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _mad(values: list[float]) -> float | None:
    center = _median(values)
    return median([abs(value - center) for value in values]) if center is not None else None


def _slope(samples: Samples, channel: str, at_ms: float, span_ms: int) -> float | None:
    left = _at_time(samples, channel, at_ms - span_ms)
    right = _at_time(samples, channel, at_ms)
    return None if left is None or right is None else (right - left) * 1000 / span_ms


def _lap_usable(lap: dict[str, Any]) -> bool:
    samples = lap.get("samples") or {}
    return bool(lap.get("counts_for_best", True)) and len(samples.get("t") or []) >= 2


def _driven_wheels(drivetrain: Drivetrain) -> tuple[str, ...]:
    return (
        FRONT
        if drivetrain == "fwd"
        else REAR
        if drivetrain == "rwd"
        else WHEELS
        if drivetrain == "awd"
        else ()
    )


def catalog_drivetrain(layout: str | None) -> CatalogDrivetrain:
    effective: Drivetrain = (
        "fwd"
        if layout == "FF"
        else "rwd"
        if layout in {"FR", "MR", "RR"}
        else "awd"
        if layout == "4WD"
        else "unknown"
    )
    return CatalogDrivetrain(
        layout=layout,
        effective=effective,
        source="catalog" if effective != "unknown" else "catalog_missing",
        effective_powered_wheels=_driven_wheels(effective),
    )


def _progress_at_time(trajectory: spatial.ProjectedTrajectory, time_ms: float) -> float | None:
    return _interp(
        trajectory.dense.get("time_ms") or [], trajectory.dense.get("progress") or [], time_ms
    )


def _time_at_progress(trajectory: spatial.ProjectedTrajectory, progress: float) -> float | None:
    return _interp(trajectory.progress, trajectory.channels.get("time_ms") or [], progress)


def _event_time(samples: Samples, distance: float) -> float | None:
    value = _interp(samples.get("dist") or [], samples.get("t") or [], distance)
    return value * 1000 if value is not None else None


def _motion_series(
    trajectory: spatial.ProjectedTrajectory | None, config: CharacterizationConfig
) -> dict[str, list[float]]:
    """Derive motion once from the same dense vectors used by spatial line traces."""
    if trajectory is None:
        return {}
    dense = trajectory.dense
    times_ms = dense.get("time_ms") or []
    fx = dense.get("chassis_forward_x") or []
    fz = dense.get("chassis_forward_z") or []
    vx = dense.get("travel_velocity_x") or []
    vz = dense.get("travel_velocity_z") or []
    n = len(times_ms)
    if not n or any(len(values) != n for values in (fx, fz, vx, vz)):
        return {"time_ms": list(times_ms)} if times_ms else {}
    body: list[float] = []
    mismatch: list[float] = []
    chassis_headings: list[float] = []
    travel_headings: list[float] = []
    for forward_x, forward_z, velocity_x, velocity_z in zip(fx, fz, vx, vz, strict=True):
        forward_norm = math.hypot(forward_x, forward_z)
        if forward_norm <= config.thresholds.motion_distance_epsilon_m:
            body.append(math.nan)
            mismatch.append(math.nan)
            chassis_headings.append(math.nan)
            travel_headings.append(math.nan)
            continue
        chassis = math.atan2(forward_z, forward_x)
        chassis_headings.append(math.degrees(chassis))
        if math.hypot(velocity_x, velocity_z) < config.thresholds.minimum_travel_speed_mps:
            body.append(math.nan)
            mismatch.append(math.nan)
            travel_headings.append(math.nan)
            continue
        travel = math.atan2(velocity_z, velocity_x)
        difference = math.degrees(wrap_angle(travel - chassis))
        body.append(difference)
        mismatch.append(abs(difference))
        travel_headings.append(math.degrees(travel))
    return {
        "time_ms": list(times_ms),
        "body_slip": body,
        "chassis_travel_mismatch": mismatch,
        "chassis_heading": chassis_headings,
        "travel_heading": travel_headings,
    }


def _motion_at(motion: dict[str, list[float]], channel: str, time_ms: float) -> float | None:
    """Interpolate through finite local neighbors without rejecting a sparse motion series."""
    times = motion.get("time_ms") or []
    values = motion.get(channel) or []
    if not times or len(times) != len(values) or time_ms < times[0] or time_ms > times[-1]:
        return None
    right = bisect_left(times, time_ms)
    if right < len(times) and times[right] == time_ms and _finite(values[right]):
        return float(values[right])
    left = right - 1
    while left >= 0 and not _finite(values[left]):
        left -= 1
    while right < len(times) and not _finite(values[right]):
        right += 1
    if left < 0 or right >= len(times):
        return None
    span = times[right] - times[left]
    if span <= 0:
        return float(values[left])
    fraction = (time_ms - times[left]) / span
    return float(values[left]) + fraction * (float(values[right]) - float(values[left]))


def _window_values(samples: Samples, channel: str, start_ms: float, end_ms: float) -> list[float]:
    values = _aligned(samples, channel)
    return [values[i] for i in _indices(samples, start_ms, end_ms)] if values is not None else []


def _slip_metrics(
    samples: Samples,
    wheels: tuple[str, ...],
    onset_ms: float,
    end_ms: float,
    config: CharacterizationConfig,
) -> dict[str, Any]:
    start, stop = onset_ms, max(onset_ms, end_ms)
    indices = _indices(samples, start, stop)
    at_onset = {wheel: _at_time(samples, f"slip_{wheel}", onset_ms) for wheel in wheels}
    peaks: dict[str, float | None] = {}
    for wheel in wheels:
        values = _aligned(samples, f"slip_{wheel}")
        peaks[wheel] = (
            max((values[i] for i in indices), default=None) if values is not None else None
        )
    means = [value for value in at_onset.values() if value is not None]
    times = samples.get("t") or []
    excess = 0.0
    duration = 0.0
    if indices and wheels:
        series: list[float] = []
        for i in indices:
            vals = [
                samples[f"slip_{wheel}"][i]
                for wheel in wheels
                if len(samples.get(f"slip_{wheel}") or []) == len(times)
            ]
            series.append(sum(vals) / len(vals) if vals else 1.0)
        for j in range(len(indices) - 1):
            dt = max(0.0, times[indices[j + 1]] - times[indices[j]])
            a, b = (
                max(0.0, series[j] - config.thresholds.slip),
                max(0.0, series[j + 1] - config.thresholds.slip),
            )
            excess += (a + b) * 0.5 * dt
            if min(series[j], series[j + 1]) > config.thresholds.slip:
                duration += dt * 1000
    asymmetry = None
    persistent = 0.0
    if len(wheels) >= 2 and indices:
        a_values, b_values = (
            _aligned(samples, f"slip_{wheels[0]}"),
            _aligned(samples, f"slip_{wheels[1]}"),
        )
        if a_values is not None and b_values is not None:
            differences = [abs(a_values[i] - b_values[i]) for i in indices]
            asymmetry = max(differences, default=0.0)
            persistent = sum(
                max(0.0, times[indices[j + 1]] - times[indices[j]]) * 1000
                for j in range(len(indices) - 1)
                if min(differences[j], differences[j + 1]) >= config.thresholds.asymmetry
            )
    return {
        "slip_at_onset": at_onset,
        "peak_slip": peaks,
        "mean_powered_slip_at_onset": sum(means) / len(means) if means else None,
        "slip_excess_integral": excess,
        "duration_above_threshold_ms": duration,
        "same_axle_asymmetry_peak": asymmetry,
        "same_axle_asymmetry_duration_ms": persistent,
    }


def _has_loose_surface(samples: Samples, start_ms: float, end_ms: float) -> bool:
    values = _aligned(samples, "surface")
    return bool(
        values
        and any(
            any(code in LOOSE_CODES or code == SURFACE_KERB for code in wheel_codes(int(values[i])))
            for i in _indices(samples, start_ms, end_ms)
        )
    )


def _contains_time(values: tuple[float, ...], start_ms: float, end_ms: float) -> bool:
    index = bisect_left(values, start_ms)
    return index < len(values) and values[index] <= end_ms


def _indexed_event_times(lap: dict[str, Any], samples: Samples) -> tuple[float, ...]:
    values = [
        event_time
        for event in lap.get("events") or []
        if str(event.get("type", "")) in {"kerb", "reverse_motion"}
        and (
            event_time := _event_time(samples, float(event.get("start_dist", 0)))
        )
        is not None
    ]
    return tuple(sorted(values))


def _indexed_loose_surface_times(samples: Samples) -> tuple[float, ...]:
    times = samples.get("t") or []
    values = _aligned(samples, "surface")
    if values is None:
        return ()
    return tuple(
        times[index] * 1000
        for index, value in enumerate(values)
        if any(code in LOOSE_CODES or code == SURFACE_KERB for code in wheel_codes(int(value)))
    )


def _has_disqualifying_event(
    lap: dict[str, Any], samples: Samples, start_ms: float, end_ms: float
) -> bool:
    for event in lap.get("events") or []:
        if str(event.get("type", "")) not in {"kerb", "reverse_motion"}:
            continue
        event_ms = _event_time(samples, float(event.get("start_dist", 0)))
        if event_ms is not None and start_ms <= event_ms <= end_ms:
            return True
    return False


def _indexed_vertical_disturbance_times(
    samples: Samples, config: CharacterizationConfig
) -> tuple[float, ...]:
    times = samples.get("t") or []
    indices = range(1, len(times))
    if len(times) < 3:
        return ()
    active_by_family: dict[str, set[int]] = {"heave": set(), "body_suspension": set()}
    for channel, floor, family in (
        ("heave", config.thresholds.heave_raw, "heave"),
        ("body_height", config.thresholds.body_height_mm, "body_suspension"),
        ("sus_fl", config.thresholds.suspension_mm, "body_suspension"),
        ("sus_fr", config.thresholds.suspension_mm, "body_suspension"),
        ("sus_rl", config.thresholds.suspension_mm, "body_suspension"),
        ("sus_rr", config.thresholds.suspension_mm, "body_suspension"),
    ):
        values = _aligned(samples, channel)
        if values is None:
            continue
        differences = [abs(values[index] - values[index - 1]) for index in indices]
        center = _median(differences) or 0.0
        spread = config.thresholds.mad_consistency_scale * (_mad(differences) or 0.0)
        threshold = center + config.thresholds.robust_spread_count * spread + floor
        active_by_family[family].update(
            index
            for index in indices
            if abs(values[index] - values[index - 1]) > threshold
        )
    event_indices = {
        min(heave_index, body_index)
        for heave_index in active_by_family["heave"]
        for body_index in active_by_family["body_suspension"]
        if abs(heave_index - body_index) <= 2
    }
    return tuple(sorted(times[index] * 1000 for index in event_indices))


def _has_local_vertical_disturbance(
    samples: Samples, start_ms: float, end_ms: float, config: CharacterizationConfig
) -> bool:
    return _contains_time(
        _indexed_vertical_disturbance_times(samples, config), start_ms, end_ms
    )


def _projection_at(trajectory: spatial.ProjectedTrajectory, progress: float) -> float | None:
    return _interp(
        trajectory.progress, trajectory.channels.get("projection_distance") or [], progress
    )


def _corner_at_progress(
    path: spatial.ReferencePath, corners: list[dict[str, Any]], point: float
) -> int | None:
    for corner in corners:
        entry = spatial.progress_at_source_distance(path, float(corner["entry_dist"]))
        exit_ = spatial.progress_at_source_distance(path, float(corner["exit_dist"]))
        if (entry <= exit_ and entry <= point <= exit_) or (
            entry > exit_ and (point >= entry or point <= exit_)
        ):
            return int(corner["n"])
    return None


def _corner_context(
    path: spatial.ReferencePath, corners: list[dict[str, Any]], point: float
) -> tuple[int | None, int | None, str | None, float | None]:
    candidates: list[tuple[float, int, str]] = []
    contained: list[tuple[int, str]] = []
    total = path.total
    for corner in corners:
        number = int(corner["n"])
        entry = spatial.progress_at_source_distance(path, float(corner["entry_dist"]))
        apex = spatial.progress_at_source_distance(path, float(corner["apex_dist"]))
        exit_ = spatial.progress_at_source_distance(path, float(corner["exit_dist"]))
        span = (exit_ - entry) % total
        relative = (point - entry) % total
        apex_relative = (apex - entry) % total
        if relative <= span + 1e-9:
            relation = (
                "apex"
                if abs(relative - apex_relative) <= 1.0
                else "entry_to_apex"
                if relative < apex_relative
                else "apex_to_exit"
            )
            contained.append((number, relation))
            continue
        approach = (entry - point) % total
        after = (point - exit_) % total
        if approach <= 250.0:
            candidates.append((approach, number, "approach"))
        if after <= 250.0:
            candidates.append((after, number, "after_exit"))
    if contained:
        number, relation = min(contained, key=lambda item: item[0])
        return number, number, relation, 0.0
    if candidates:
        distance, number, relation = min(candidates, key=lambda item: (item[0], item[1]))
        return None, number, relation, distance
    return None, None, None, None


def _control_class(
    event_metrics: dict[str, Any], peer_metrics: dict[str, Any], config: CharacterizationConfig
) -> str | None:
    event_peaks = [value for value in event_metrics["peak_slip"].values() if value is not None]
    peer_peaks = [value for value in peer_metrics["peak_slip"].values() if value is not None]
    if not event_peaks or not peer_peaks:
        return None
    event_peak, peer_peak = max(event_peaks), max(peer_peaks)
    if event_peak - peer_peak < config.comparators.minimum_slip_separation:
        return None
    if peer_peak <= config.comparators.strong_peak_slip:
        return "ideal"
    comparable: list[tuple[float, float]] = []
    for name in ("slip_excess_integral", "duration_above_threshold_ms"):
        event_value, peer_value = event_metrics.get(name), peer_metrics.get(name)
        if _finite(event_value) and _finite(peer_value):
            comparable.append((float(cast(float, event_value)), float(cast(float, peer_value))))
    if not comparable:
        return None
    improvement = config.comparators.relative_integral_or_duration_improvement
    regression = config.comparators.relative_max_regression
    improved = any(event > 0 and peer <= event * (1 - improvement) for event, peer in comparable)
    not_worse = all(peer <= event * (1 + regression) for event, peer in comparable)
    return "relative" if improved and not_worse else None


def _comparator_pool(
    event_context: LapContext,
    contexts: dict[int, LapContext],
    start_progress: float,
    end_progress: float,
    event_metrics: dict[str, Any],
    event_speed: float | None,
    event_gear: float | None,
    wheels: tuple[str, ...],
    config: CharacterizationConfig,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not event_context.comparison_eligible:
        return candidates
    event_peaks = [value for value in event_metrics["peak_slip"].values() if value is not None]
    if not event_peaks:
        return candidates
    event_peak = max(event_peaks)
    speed_limit = max(
        config.comparators.speed_floor_kmh,
        abs(event_speed or 0) * config.comparators.speed_fraction,
    )
    for lap_id, context in contexts.items():
        lap = context.lap
        lap_id = int(lap["id"])
        trajectory = context.trajectory
        if (
            lap_id == int(event_context.lap["id"])
            or not context.comparison_eligible
            or trajectory is None
        ):
            continue
        peer_start = _time_at_progress(trajectory, start_progress)
        peer_end = _time_at_progress(trajectory, end_progress)
        if peer_start is None or peer_end is None or peer_end < peer_start:
            continue
        anchor = peer_start
        samples = context.samples
        start = anchor - config.temporal.pre_ms
        end = anchor + config.temporal.post_ms
        times = samples.get("t") or []
        if not times or start < times[0] * 1000 or end > times[-1] * 1000:
            continue
        if (
            _contains_time(context.disqualifying_event_times_ms, start, end)
            or _contains_time(context.loose_surface_times_ms, start, end)
            or _contains_time(context.vertical_disturbance_times_ms, start, end)
        ):
            continue
        metric = _slip_metrics(samples, wheels, peer_start, peer_end, config)
        peer_peaks = [value for value in metric["peak_slip"].values() if value is not None]
        if not peer_peaks:
            continue
        peer_peak = max(peer_peaks)
        separation = event_peak - peer_peak
        speed = _at_time(samples, "speed", anchor)
        if (
            speed is None
            or event_speed is None
            or abs(speed - event_speed) > speed_limit
        ):
            continue
        control_class = _control_class(event_metrics, metric, config)
        if control_class is None:
            continue
        gear = _at_time(samples, "gear", anchor, discrete=True)
        projection = _projection_at(trajectory, start_progress)
        speed_similarity = max(0.0, 1 - abs(speed - event_speed) / speed_limit)
        slip_score = min(1.0, separation / max(config.comparators.strong_slip_separation, 1e-6))
        projection_score = 1 / (
            1 + max(0.0, projection or 0.0) / config.comparators.projection_scale_m
        )
        cleanliness = (
            config.comparators.clean_utility
            if lap.get("clean_lap") is True
            else config.comparators.unknown_clean_utility
            if lap.get("clean_lap") is None
            else config.comparators.dirty_utility
        )
        same_gear = float(
            gear is not None and event_gear is not None and int(gear) == int(event_gear)
        )
        pieces = {
            "slip_separation": slip_score,
            "speed_similarity": speed_similarity,
            "same_gear": same_gear,
            "projection_quality": projection_score,
            "cleanliness": cleanliness,
        }
        utility = sum(pieces[name] * weight for name, weight in config.comparators.utility_weights)
        candidates.append(
            {
                "lap": lap,
                "context": context,
                "lap_id": lap_id,
                "anchor_ms": anchor,
                "end_ms": peer_end,
                "control_class": control_class,
                "metrics": metric,
                "peak": peer_peak,
                "separation": separation,
                "speed": speed,
                "speed_difference": abs(speed - event_speed),
                "gear": gear,
                "same_gear": bool(same_gear),
                "projection": projection,
                "utility": utility,
                "bottoming": any(
                    str(e.get("type")) == "bottoming" for e in lap.get("events") or []
                ),
            }
        )
    return sorted(
        candidates,
        key=lambda item: (
            0 if item["control_class"] == "ideal" else 1,
            -item["utility"],
            item["peak"],
            item["speed_difference"],
            item["projection"] or 0.0,
            item["lap_id"],
        ),
    )[: config.comparators.max_count]


def _quality(peers: list[dict[str, Any]], config: CharacterizationConfig) -> ComparatorQuality:
    count = len(peers)
    ideal = sum(item["control_class"] == "ideal" for item in peers)
    relative = sum(item["control_class"] == "relative" for item in peers)
    same_gear = sum(bool(item["same_gear"]) for item in peers)
    speeds = [float(item["speed"]) for item in peers]
    projections = [float(item["projection"]) for item in peers if item["projection"] is not None]
    separations = [float(item["separation"]) for item in peers]
    clean = sum(item["lap"].get("clean_lap") is not False for item in peers)
    components = {
        "count": min(1.0, count / config.comparators.target_count),
        "speed_similarity": sum(
            max(
                0.0,
                1 - item["speed_difference"] / config.comparators.quality_speed_scale_kmh,
            )
            for item in peers
        )
        / count
        if count
        else 0,
        "gear_consistency": same_gear / count if count else 0,
        "slip_separation": min(
            1.0,
            (median(separations) if separations else 0) / config.comparators.strong_slip_separation,
        ),
        "projection_quality": sum(
            1 / (1 + value / config.comparators.projection_scale_m) for value in projections
        )
        / len(projections)
        if projections
        else 0,
        "cleanliness": clean / count if count else 0,
    }
    score = sum(components[name] * weight for name, weight in config.comparators.quality_weights)
    quality = (
        "strong"
        if ideal >= config.comparators.strong_control_min_count
        and score >= config.comparators.strong_quality
        else "moderate"
        if count >= config.comparators.robust_min_count
        and score >= config.comparators.moderate_quality
        else "weak"
    )
    return ComparatorQuality(
        count,
        quality,
        score,
        ideal,
        relative,
        same_gear,
        max(speeds) - min(speeds) if speeds else None,
        _median(projections),
        _median(separations),
        clean,
        sum(bool(item["bottoming"]) for item in peers),
        tuple(int(item["lap_id"]) for item in peers),
    )


def _peer_stat(
    values: list[float],
) -> tuple[float | None, float | None, float | None, float | None]:
    return (
        _median(values),
        min(values) if values else None,
        max(values) if values else None,
        _mad(values),
    )


def _persistent_start(
    times: list[float], active: list[bool], persistence_ms: int, onset_ms: float
) -> int | None:
    start: int | None = None
    for i, enabled in enumerate(active):
        if enabled and start is None:
            start = i
        elif not enabled:
            start = None
        if start is not None and (times[i] - times[start]) * 1000 >= persistence_ms:
            return round(times[start] * 1000 - onset_ms)
    return None


def _sequence(
    samples: Samples,
    onset_ms: float,
    wheels: tuple[str, ...],
    peers: list[dict[str, Any]],
    motion: dict[str, list[float]],
    config: CharacterizationConfig,
) -> tuple[dict[str, int | None], tuple[str, ...]]:
    indices = _indices(
        samples, onset_ms - config.temporal.pre_ms, onset_ms + config.temporal.post_ms
    )
    times = samples.get("t") or []
    window_times = [times[index] for index in indices]
    baseline_indices = _indices(
        samples,
        onset_ms - config.temporal.pre_ms,
        onset_ms + config.temporal.baseline_end_ms,
    )
    throttle = _aligned(samples, "throttle")
    throttle_base = (
        _median([throttle[i] for i in baseline_indices]) if throttle is not None else None
    )
    throttle_active = [False] * len(indices)
    if throttle is not None and throttle_base is not None:
        rising = False
        for local_index, i in enumerate(indices):
            slope = _slope(
                samples,
                "throttle",
                times[i] * 1000,
                config.temporal.throttle_slope_window_ms,
            )
            if not rising:
                rising = (
                    throttle[i] >= throttle_base + config.temporal.throttle_rise_pct
                    and slope is not None
                    and slope >= config.temporal.throttle_slope_pct_s
                )
            elif throttle[i] < throttle_base + config.temporal.throttle_exit_hysteresis_pct:
                rising = False
            throttle_active[local_index] = rising
    torque_series: list[float] | None = None
    torque_channels = [_aligned(samples, f"torque_{wheel}") for wheel in wheels]
    if wheels and all(values is not None for values in torque_channels):
        torque_series = [
            sum(max(0.0, values[i]) for values in torque_channels if values is not None)
            for i in range(len(times))
        ]
    torque_active = [False] * len(indices)
    if torque_series is not None:
        base = [torque_series[i] for i in baseline_indices]
        window_peak = max((torque_series[i] for i in indices), default=0.0)
        threshold = (_median(base) or 0) + max(
            config.thresholds.torque_baseline_mad_multiplier * (_mad(base) or 0),
            config.thresholds.torque_window_peak_fraction * window_peak,
        )
        torque_active = [torque_series[index] > threshold for index in indices]
    slip_active = [False] * len(indices)
    for local_index, i in enumerate(indices):
        vals = [
            samples[f"slip_{wheel}"][i]
            for wheel in wheels
            if len(samples.get(f"slip_{wheel}") or []) == len(times)
        ]
        slip_active[local_index] = bool(vals and max(vals) > config.thresholds.slip)

    peer_body: list[float] = []
    peer_yaw: list[float] = []
    peer_mismatch: list[float] = []
    for peer in peers:
        context: LapContext = peer["context"]
        ps = context.samples
        pm = context.motion
        body = _motion_at(pm, "body_slip", peer["anchor_ms"])
        yaw = _at_time(ps, "yaw_rate_signed", peer["anchor_ms"])
        mismatch = _motion_at(pm, "chassis_travel_mismatch", peer["anchor_ms"])
        if body is not None and math.isfinite(body):
            peer_body.append(abs(body))
        if yaw is not None:
            peer_yaw.append(abs(yaw))
        if mismatch is not None and math.isfinite(mismatch):
            peer_mismatch.append(abs(mismatch))
    body_med, _, _, body_mad = _peer_stat(peer_body)
    yaw_med, _, _, yaw_mad = _peer_stat(peer_yaw)
    mismatch_med, _, _, mismatch_mad = _peer_stat(peer_mismatch)
    body_values = motion.get("body_slip")
    yaw_values = _aligned(samples, "yaw_rate_signed")
    mismatch_values = motion.get("chassis_travel_mismatch")
    motion_times = [(value / 1000) for value in motion.get("time_ms", [])]
    motion_start = bisect_left(motion_times, (onset_ms - config.temporal.pre_ms) / 1000)
    motion_end = bisect_right(motion_times, (onset_ms + config.temporal.post_ms) / 1000)
    motion_indices = range(motion_start, motion_end)
    motion_window_times = motion_times[motion_start:motion_end]
    body_active = [False] * len(motion_window_times)
    yaw_active = [False] * len(indices)
    mismatch_active = [False] * len(motion_window_times)
    if len(peers) >= config.comparators.robust_min_count and body_values and body_med is not None:
        threshold = (
            body_med
            + config.thresholds.robust_spread_count
            * config.thresholds.mad_consistency_scale
            * (body_mad or 0)
            + config.thresholds.body_slip_deg
        )
        body_active = [
            math.isfinite(body_values[index]) and abs(body_values[index]) > threshold
            for index in motion_indices
        ]
    if len(peers) >= config.comparators.robust_min_count and yaw_values and yaw_med is not None:
        threshold = (
            yaw_med
            + config.thresholds.robust_spread_count
            * config.thresholds.mad_consistency_scale
            * (yaw_mad or 0)
            + config.thresholds.yaw_rad_s
        )
        yaw_active = [abs(yaw_values[index]) > threshold for index in indices]
    if (
        len(peers) >= config.comparators.robust_min_count
        and mismatch_values
        and mismatch_med is not None
    ):
        threshold = (
            mismatch_med
            + config.thresholds.robust_spread_count
            * config.thresholds.mad_consistency_scale
            * (mismatch_mad or 0)
            + config.thresholds.heading_deg
        )
        mismatch_active = [
            math.isfinite(mismatch_values[index]) and abs(mismatch_values[index]) > threshold
            for index in motion_indices
        ]
    shift = None
    gear = _aligned(samples, "gear")
    if gear is not None:
        transitions: list[int] = []
        for i in indices[1:]:
            if gear[i] == gear[i - 1]:
                continue
            end = next(
                (
                    j
                    for j in range(i, len(times))
                    if (times[j] - times[i]) * 1000 >= config.temporal.persistence_ms
                ),
                None,
            )
            if end is not None and all(gear[j] == gear[i] for j in range(i, end + 1)):
                transitions.append(i)
        if transitions:
            shift = round(
                times[min(transitions, key=lambda i: abs(times[i] * 1000 - onset_ms))] * 1000
                - onset_ms
            )
    surface_transition = None
    surface = _aligned(samples, "surface")
    if surface is not None:
        contact = [
            any(code in LOOSE_CODES or code == SURFACE_KERB for code in wheel_codes(int(value)))
            for value in surface
        ]
        surface_active = [False] * len(indices)
        transition_seen = False
        for local_index, i in enumerate(indices):
            if contact[i] and i > 0 and not contact[i - 1]:
                transition_seen = True
            elif not contact[i]:
                transition_seen = False
            surface_active[local_index] = transition_seen
        surface_transition = _persistent_start(
            window_times, surface_active, config.temporal.persistence_ms, onset_ms
        )
    vertical = None
    vertical_families: set[str] = set()
    for channel, floor in (
        ("heave", config.thresholds.heave_raw),
        ("body_height", config.thresholds.body_height_mm),
        ("sus_fl", config.thresholds.suspension_mm),
        ("sus_fr", config.thresholds.suspension_mm),
        ("sus_rl", config.thresholds.suspension_mm),
        ("sus_rr", config.thresholds.suspension_mm),
    ):
        sample_values = _aligned(samples, channel)
        if sample_values is None:
            continue
        peer_values: list[float] = []
        for peer in peers:
            peer_samples: Samples = peer["context"].samples
            peer_value = _at_time(peer_samples, channel, peer["anchor_ms"])
            if peer_value is not None:
                peer_values.append(peer_value)
        peer_median = _median(peer_values)
        if len(peer_values) < 2 or peer_median is None:
            continue
        peer_spread = config.thresholds.mad_consistency_scale * (_mad(peer_values) or 0.0)
        vertical_active = [False] * len(indices)
        for local_index, i in enumerate(indices):
            vertical_active[local_index] = (
                abs(sample_values[i] - peer_median)
                > config.thresholds.robust_spread_count * peer_spread + floor
            )
        event_offset = _persistent_start(
            window_times,
            vertical_active,
            config.temporal.vertical_persistence_ms,
            onset_ms,
        )
        if event_offset is not None:
            vertical = event_offset if vertical is None else min(vertical, event_offset)
            vertical_families.add("heave" if channel == "heave" else "body_suspension")
    body_start = _persistent_start(
        motion_window_times, body_active, config.temporal.persistence_ms, onset_ms
    )
    yaw_start = _persistent_start(
        window_times, yaw_active, config.temporal.persistence_ms, onset_ms
    )
    mismatch_start = _persistent_start(
        motion_window_times, mismatch_active, config.temporal.persistence_ms, onset_ms
    )
    rotation = min(
        (value for value in (body_start, yaw_start, mismatch_start) if value is not None),
        default=None,
    )
    return {
        "meaningful_throttle_rise_start_ms": _persistent_start(
            window_times, throttle_active, config.temporal.persistence_ms, onset_ms
        ),
        "meaningful_torque_rise_start_ms": _persistent_start(
            window_times, torque_active, config.temporal.persistence_ms, onset_ms
        ),
        "rotation_deviation_start_ms": rotation,
        "body_slip_deviation_start_ms": body_start,
        "yaw_deviation_start_ms": yaw_start,
        "slip_threshold_cross_ms": _persistent_start(
            window_times, slip_active, config.temporal.persistence_ms, onset_ms
        ),
        "shift_ms": shift,
        "surface_transition_ms": surface_transition,
        "vertical_disturbance_ms": vertical,
    }, tuple(sorted(vertical_families))


def _contribution(
    feature: str,
    criterion: str,
    active: bool,
    available: bool,
    direction: Direction,
    weight: float,
    event_value: Any = None,
    peers: list[float] | None = None,
) -> Contribution:
    med, low, high, mad = _peer_stat(peers or [])
    activation = int(active and available)
    signed = weight * activation * (1 if direction == "support" else -1)
    return Contribution(
        feature,
        criterion,
        event_value,
        med,
        low,
        high,
        mad,
        direction,
        weight,
        activation,
        signed,
        available,
    )


def _criterion(feature: str, config: CharacterizationConfig) -> str:
    robust = config.thresholds.robust_spread_count
    tolerance = config.temporal.order_tolerance_ms
    slip = config.thresholds.slip
    criteria = {
        "throttle_slope_outlier": (
            f"event slope > peer median + {robust:g} robust spreads + "
            f"{config.thresholds.throttle_slope_pct_s:g} percentage-points/s"
        ),
        "torque_slope_outlier": (
            "event raw slope > peer median + robust spreads + "
            f"max({config.thresholds.torque_slope_minimum_raw_s:g},"
            f"abs(peer median)*{config.thresholds.torque_window_peak_fraction:g})"
        ),
        "power_before_rotation": f"power_ms <= rotation_ms - {tolerance}",
        "multiple_powered_wheels_spinning": f"at least two powered peaks > {slip:g}",
        "comparator_like_initial_rotation": "no robust body-slip or yaw outlier",
        "rotation_before_power": f"rotation_ms <= power_ms - {tolerance}",
        "body_slip_deviation": (
            "abs(event) > median(abs(peers)) + robust spreads + "
            f"{config.thresholds.body_slip_deg:g} deg"
        ),
        "chassis_travel_mismatch": (
            f"abs(heading mismatch) >= {config.thresholds.heading_deg:g} deg with motion outlier"
        ),
        "yaw_deviation": (
            "abs(event) > median(abs(peers)) + robust spreads + "
            f"{config.thresholds.yaw_rad_s:g} rad/s"
        ),
        "elevated_rotation_through_slip": "body-slip or yaw outlier persists into slip",
        "steering_with_motion_evidence": "steering present AND vehicle-motion outlier",
        "normal_motion_state": "available body-slip/yaw has no robust outlier",
        "power_before_motion": f"power_ms <= rotation_ms - {tolerance}",
        "peer_relative_asymmetry": (
            f"event asymmetry > peer median + robust spreads + {config.thresholds.asymmetry:g}"
        ),
        "one_wheel_peer_normal": "one wheel near peer peak while another deviates",
        "persistent_asymmetry": (
            f"asymmetry persists >= {config.thresholds.asymmetry_persistence_ms} ms"
        ),
        "symmetric_bilateral_spin": f"both powered wheels > {slip:g} with small asymmetry",
        "pre_power_body_slip": f"body-slip outlier AND rotation precedes power by {tolerance} ms",
        "pre_power_yaw": f"yaw outlier AND rotation precedes power by {tolerance} ms",
        "comparator_normal_power": "throttle and torque slopes are not robust peer outliers",
        "surface_before_slip": "surface transition in slip_ms -400 through slip_ms +100",
        "vertical_before_slip": "peer-relative vertical deviation in causal slip window",
        "body_suspension_disturbance": "a second independent vertical channel family corroborates",
        "comparator_normal_controls": "throttle and torque slopes are not robust peer outliers",
        "disturbance_after_slip": f"disturbance_ms > slip_ms + {tolerance}",
        "shift_before_slip": "persistent shift within configured pre-slip window",
        "normal_pre_shift_slip": f"powered slip before shift <= {slip:g}",
        "post_shift_slip_crossing": "persistent slip crossing follows shift",
        "aligned_power_transient": "power and shift onsets within configured shift window",
        "slip_rising_before_shift": "persistent slip crossing precedes shift",
        "shift_after_slip": "shift onset follows persistent slip crossing",
    }
    return criteria.get(feature, feature)


def _score_candidates(
    signals: dict[str, tuple[bool, bool, Any, list[float] | None]],
    quality: ComparatorQuality,
    config: CharacterizationConfig,
) -> tuple[Candidate, ...]:
    support = dict(config.support_weights)
    counter = dict(config.counter_weights)
    candidates: list[Candidate] = []
    quality_factor = (
        1.0
        if quality.quality == "strong"
        else config.comparators.moderate_coverage_factor
        if quality.quality == "moderate"
        else config.comparators.weak_coverage_factor
    )
    for mechanism in MECHANISMS:
        contributions: list[Contribution] = []
        rules: list[tuple[str, float, Direction]] = [
            *((name, weight, "support") for name, weight in support[mechanism]),
            *((name, weight, "counter") for name, weight in counter[mechanism]),
        ]
        available_count = 0
        for name, weight, direction in rules:
            active, available, value, peers = signals.get(name, (False, False, None, None))
            available_count += int(available)
            contributions.append(
                _contribution(
                    name,
                    _criterion(name, config),
                    active,
                    available,
                    direction,
                    weight,
                    value,
                    peers,
                )
            )
        preclamp = sum(item.signed_contribution for item in contributions)
        coverage = available_count / len(rules) if rules else 0.0
        if any(
            name in COMPARATOR_FEATURES and signals.get(name, (False, False))[1]
            for name, _, _ in rules
        ):
            coverage *= quality_factor
        candidates.append(
            Candidate(
                mechanism, preclamp, min(1.0, max(0.0, preclamp)), coverage, tuple(contributions)
            )
        )
    return tuple(sorted(candidates, key=lambda item: (-item.score, item.mechanism)))


def _event_characterization(
    context: LapContext,
    event: dict[str, Any],
    event_index: int,
    contexts: dict[int, LapContext],
    path: spatial.ReferencePath,
    corners: list[dict[str, Any]],
    drivetrain: CatalogDrivetrain,
    config: CharacterizationConfig,
) -> WheelspinCharacterization | None:
    lap = context.lap
    lap_id = int(lap["id"])
    trajectory = context.trajectory
    samples = context.samples
    if trajectory is None:
        return None
    start_m = float(event.get("start_dist", 0))
    end_m = float(event.get("end_dist", start_m))
    onset = _event_time(samples, start_m)
    end_time = _event_time(samples, end_m)
    if onset is None or end_time is None:
        return None
    progress = _progress_at_time(trajectory, onset)
    end_progress = _progress_at_time(trajectory, end_time)
    if progress is None or end_progress is None:
        return None
    effective_wheels = drivetrain.effective_powered_wheels
    event_wheels = tuple(sorted(str(w) for w in event.get("wheels") or [] if str(w) in WHEELS))
    trustworthy_powered_intersection = bool(set(effective_wheels) & set(event_wheels))
    analyzed = (
        tuple(w for w in effective_wheels if w in event_wheels)
        or event_wheels
    )
    metrics = _slip_metrics(samples, analyzed, onset, end_time, config)
    speed = _at_time(samples, "speed", onset)
    gear = _at_time(samples, "gear", onset, discrete=True)
    peers = _comparator_pool(
        context,
        contexts,
        progress,
        end_progress,
        metrics,
        speed,
        gear,
        analyzed,
        config,
    )
    quality = _quality(peers, config)
    motion = context.motion
    sequence, vertical_families = _sequence(samples, onset, analyzed, peers, motion, config)
    body = _motion_at(motion, "body_slip", onset)
    mismatch = _motion_at(motion, "chassis_travel_mismatch", onset)
    yaw = _at_time(samples, "yaw_rate_signed", onset)
    steering = _at_time(samples, "steering_wheel_rad", onset)
    throttle = _at_time(samples, "throttle", onset)
    slope_window = config.temporal.feature_slope_window_ms
    throttle_slope = _slope(samples, "throttle", onset, slope_window)
    torque_slopes = [_slope(samples, f"torque_{wheel}", onset, slope_window) for wheel in analyzed]
    torque_slope = (
        sum(value for value in torque_slopes if value is not None)
        if any(value is not None for value in torque_slopes)
        else None
    )
    torque_at_onset = {wheel: _at_time(samples, f"torque_{wheel}", onset) for wheel in WHEELS}
    torque_slope_by_wheel = {
        wheel: _slope(samples, f"torque_{wheel}", onset, slope_window) for wheel in WHEELS
    }
    torque_step_by_wheel = {
        wheel: (
            current - before
            if (current := _at_time(samples, f"torque_{wheel}", onset)) is not None
            and (
                before := _at_time(
                    samples,
                    f"torque_{wheel}",
                    onset + config.temporal.local_torque_start_ms,
                )
            )
            is not None
            else None
        )
        for wheel in WHEELS
    }

    def motion_at(channel: str) -> float | None:
        return _motion_at(motion, channel, onset)

    along_track_speed = _interp(
        trajectory.dense.get("time_ms") or [],
        trajectory.dense.get("along_track_speed_kmh") or [],
        onset,
    )
    peer_body: list[float] = []
    peer_yaw: list[float] = []
    peer_throttle_slope: list[float] = []
    peer_torque_slope: list[float] = []
    peer_asymmetry: list[float] = []
    peer_wheel_peaks: dict[str, list[float]] = {wheel: [] for wheel in analyzed}
    for peer in peers:
        peer_context: LapContext = peer["context"]
        ps = peer_context.samples
        pm = peer_context.motion
        anchor = peer["anchor_ms"]
        value = _motion_at(pm, "body_slip", anchor)
        if value is not None and math.isfinite(value):
            peer_body.append(abs(value))
        value = _at_time(ps, "yaw_rate_signed", anchor)
        if value is not None:
            peer_yaw.append(abs(value))
        value = _slope(ps, "throttle", anchor, slope_window)
        if value is not None:
            peer_throttle_slope.append(value)
        slopes = [_slope(ps, f"torque_{wheel}", anchor, slope_window) for wheel in analyzed]
        if any(value is not None for value in slopes):
            peer_torque_slope.append(sum(value for value in slopes if value is not None))
        pmx = peer["metrics"]
        for wheel, peak in pmx["peak_slip"].items():
            if peak is not None:
                peer_wheel_peaks[wheel].append(peak)
        if pmx["same_axle_asymmetry_peak"] is not None:
            peer_asymmetry.append(pmx["same_axle_asymmetry_peak"])

    def outlier(
        value: float | None, values: list[float], floor: float, *, absolute: bool = False
    ) -> bool:
        if value is None or len(values) < 2:
            return False
        compare = abs(value) if absolute else value
        center = median(values)
        spread = config.thresholds.mad_consistency_scale * (_mad(values) or 0)
        return compare > center + config.thresholds.robust_spread_count * spread + floor

    power_start = min(
        (
            v
            for v in (
                sequence["meaningful_throttle_rise_start_ms"],
                sequence["meaningful_torque_rise_start_ms"],
            )
            if v is not None
        ),
        default=None,
    )
    rotation_start = sequence["rotation_deviation_start_ms"]
    slip_start = sequence["slip_threshold_cross_ms"]
    rotation_before = (
        power_start is not None
        and rotation_start is not None
        and rotation_start <= power_start - config.temporal.order_tolerance_ms
    )
    power_before = (
        power_start is not None
        and rotation_start is not None
        and power_start <= rotation_start - config.temporal.order_tolerance_ms
    )
    body_out = outlier(body, peer_body, config.thresholds.body_slip_deg, absolute=True)
    yaw_out = outlier(yaw, peer_yaw, config.thresholds.yaw_rad_s, absolute=True)
    mismatch_out = (
        mismatch is not None
        and abs(mismatch) >= config.thresholds.heading_deg
        and (body_out or yaw_out)
    )
    throttle_out = outlier(
        throttle_slope, peer_throttle_slope, config.thresholds.throttle_slope_pct_s
    )
    torque_floor = (
        max(
            config.thresholds.torque_slope_minimum_raw_s,
            abs(median(peer_torque_slope)) * config.thresholds.torque_window_peak_fraction,
        )
        if peer_torque_slope
        else config.thresholds.torque_slope_minimum_raw_s
    )
    torque_out = outlier(torque_slope, peer_torque_slope, torque_floor)
    asymmetry = metrics["same_axle_asymmetry_peak"]
    asymmetry_out = outlier(asymmetry, peer_asymmetry, config.thresholds.asymmetry)
    persistent_asymmetry = (
        metrics["same_axle_asymmetry_duration_ms"] >= config.thresholds.asymmetry_persistence_ms
    )
    peaks = [value for value in metrics["peak_slip"].values() if value is not None]
    symmetric = (
        len(peaks) >= 2
        and max(peaks) - min(peaks) < config.thresholds.asymmetry
        and min(peaks) > config.thresholds.slip
    )
    near_peer_wheels = {
        wheel
        for wheel, peak in metrics["peak_slip"].items()
        if peak is not None
        and (peer_median := _median(peer_wheel_peaks.get(wheel, []))) is not None
        and peak <= peer_median + config.thresholds.peer_slip_floor
    }
    deviating_wheels = {
        wheel
        for wheel, peak in metrics["peak_slip"].items()
        if peak is not None
        and (peer_median := _median(peer_wheel_peaks.get(wheel, []))) is not None
        and peak > config.thresholds.slip
        and peak > peer_median + config.thresholds.peer_slip_floor
    }
    one_normal = bool(near_peer_wheels and deviating_wheels)
    surface = sequence["surface_transition_ms"]
    vertical = sequence["vertical_disturbance_ms"]
    def causal_disturbance(value: int | None) -> bool:
        return bool(
            value is not None
            and slip_start is not None
            and slip_start - config.temporal.causal_disturbance_lead_ms
            <= value
            <= slip_start + config.temporal.order_tolerance_ms
        )

    surface_before = causal_disturbance(surface)
    vertical_before = causal_disturbance(vertical)
    disturbance_after = any(
        v is not None
        and slip_start is not None
        and v > slip_start + config.temporal.order_tolerance_ms
        for v in (surface, vertical)
    )
    shift = sequence["shift_ms"]
    shift_before = (
        shift is not None
        and slip_start is not None
        and -config.thresholds.shift_near_ms <= shift <= slip_start
    )
    shift_after = shift is not None and slip_start is not None and shift > slip_start
    pre_shift_slip = None
    if shift is not None:
        pre_shift_values = [
            _at_time(samples, f"slip_{wheel}", onset + shift - 50) for wheel in analyzed
        ]
        finite_pre_shift = [value for value in pre_shift_values if value is not None]
        pre_shift_slip = max(finite_pre_shift) if finite_pre_shift else None
    normal_pre_shift = pre_shift_slip is not None and pre_shift_slip <= config.thresholds.slip
    signals: dict[str, tuple[bool, bool, Any, list[float] | None]] = {
        "throttle_slope_outlier": (
            throttle_out,
            throttle_slope is not None
            and len(peer_throttle_slope) >= config.comparators.robust_min_count,
            throttle_slope,
            peer_throttle_slope,
        ),
        "torque_slope_outlier": (
            torque_out,
            torque_slope is not None
            and len(peer_torque_slope) >= config.comparators.robust_min_count,
            torque_slope,
            peer_torque_slope,
        ),
        "power_before_rotation": (
            power_before,
            power_start is not None and rotation_start is not None,
            {"power_ms": power_start, "rotation_ms": rotation_start},
            None,
        ),
        "multiple_powered_wheels_spinning": (
            len(peaks) >= 2 and sum(v > config.thresholds.slip for v in peaks) >= 2,
            len(peaks) >= 2,
            peaks,
            None,
        ),
        "comparator_like_initial_rotation": (
            not body_out and not yaw_out,
            len(peer_body) >= config.comparators.robust_min_count
            or len(peer_yaw) >= config.comparators.robust_min_count,
            {"body_slip": body, "yaw": yaw},
            None,
        ),
        "rotation_before_power": (
            rotation_before,
            power_start is not None and rotation_start is not None,
            {"power_ms": power_start, "rotation_ms": rotation_start},
            None,
        ),
        "body_slip_deviation": (
            body_out,
            body is not None and len(peer_body) >= config.comparators.robust_min_count,
            body,
            peer_body,
        ),
        "chassis_travel_mismatch": (
            mismatch_out,
            mismatch is not None
            and (
                len(peer_body) >= config.comparators.robust_min_count
                or len(peer_yaw) >= config.comparators.robust_min_count
            ),
            mismatch,
            None,
        ),
        "yaw_deviation": (
            yaw_out,
            yaw is not None and len(peer_yaw) >= config.comparators.robust_min_count,
            yaw,
            peer_yaw,
        ),
        "elevated_rotation_through_slip": (
            body_out or yaw_out,
            slip_start is not None
            and (body is not None or yaw is not None)
            and quality.count >= config.comparators.robust_min_count,
            {"body_slip": body, "yaw": yaw},
            None,
        ),
        "steering_with_motion_evidence": (
            steering is not None and (body_out or yaw_out),
            steering is not None and (body is not None or yaw is not None),
            steering,
            None,
        ),
        "normal_motion_state": (
            not body_out and not yaw_out,
            quality.count >= config.comparators.robust_min_count
            and (body is not None or yaw is not None),
            {"body_slip": body, "yaw": yaw},
            None,
        ),
        "power_before_motion": (
            power_before,
            power_start is not None and rotation_start is not None,
            None,
            None,
        ),
        "peer_relative_asymmetry": (
            asymmetry_out,
            asymmetry is not None and len(peer_asymmetry) >= config.comparators.robust_min_count,
            asymmetry,
            peer_asymmetry,
        ),
        "one_wheel_peer_normal": (
            one_normal,
            len(peaks) >= 2 and all(peer_wheel_peaks.values()),
            {
                "near_peer_normal": sorted(near_peer_wheels),
                "deviating": sorted(deviating_wheels),
            },
            None,
        ),
        "persistent_asymmetry": (
            persistent_asymmetry,
            asymmetry is not None,
            metrics["same_axle_asymmetry_duration_ms"],
            None,
        ),
        "symmetric_bilateral_spin": (symmetric, len(peaks) >= 2, peaks, None),
        "pre_power_body_slip": (
            body_out and rotation_before,
            body is not None
            and len(peer_body) >= config.comparators.robust_min_count
            and power_start is not None,
            body,
            peer_body,
        ),
        "pre_power_yaw": (
            yaw_out and rotation_before,
            yaw is not None
            and len(peer_yaw) >= config.comparators.robust_min_count
            and power_start is not None,
            yaw,
            peer_yaw,
        ),
        "comparator_normal_power": (
            not throttle_out and not torque_out,
            quality.count >= config.comparators.robust_min_count
            and (throttle_slope is not None or torque_slope is not None),
            {"throttle_slope": throttle_slope, "torque_slope": torque_slope},
            None,
        ),
        "surface_before_slip": (
            surface_before,
            surface is not None and slip_start is not None,
            surface,
            None,
        ),
        "vertical_before_slip": (
            vertical_before,
            vertical is not None and slip_start is not None,
            vertical,
            None,
        ),
        "body_suspension_disturbance": (
            vertical_before and len(vertical_families) >= 2,
            vertical is not None,
            {"vertical_ms": vertical, "families": list(vertical_families)},
            None,
        ),
        "comparator_normal_controls": (
            not throttle_out and not torque_out,
            quality.count >= config.comparators.robust_min_count
            and (throttle_slope is not None or torque_slope is not None),
            None,
            None,
        ),
        "disturbance_after_slip": (
            disturbance_after,
            (surface is not None or vertical is not None) and slip_start is not None,
            None,
            None,
        ),
        "shift_before_slip": (
            shift_before,
            shift is not None and slip_start is not None,
            shift,
            None,
        ),
        "normal_pre_shift_slip": (
            shift_before and normal_pre_shift,
            shift is not None and slip_start is not None and pre_shift_slip is not None,
            pre_shift_slip,
            None,
        ),
        "post_shift_slip_crossing": (
            shift_before and normal_pre_shift,
            shift is not None and slip_start is not None,
            slip_start,
            None,
        ),
        "aligned_power_transient": (
            shift_before
            and power_start is not None
            and shift is not None
            and abs(power_start - shift) <= config.thresholds.shift_near_ms,
            shift is not None and power_start is not None,
            {"shift_ms": shift, "power_ms": power_start},
            None,
        ),
        "slip_rising_before_shift": (
            shift is not None and slip_start is not None and slip_start < shift,
            shift is not None and slip_start is not None,
            None,
            None,
        ),
        "shift_after_slip": (shift_after, shift is not None and slip_start is not None, None, None),
    }
    candidates = _score_candidates(signals, quality, config)
    leading = candidates[0] if candidates else None
    ordering = (
        "rotation_before_power"
        if rotation_before
        else "power_before_rotation"
        if power_before
        else "near_simultaneous_or_unknown"
    )
    leading_comparator_dependent = bool(
        leading
        and any(
            item.feature in COMPARATOR_FEATURES and item.signed_contribution > 0
            for item in leading.contributions
        )
    )
    unresolved_reasons: set[str] = set()
    if not context.comparison_eligible:
        unresolved_reasons.add("lap_not_comparison_eligible")
    if leading is None or leading.score < config.resolution.minimum_score:
        unresolved_reasons.add("leading_score_low")
    if leading is None or leading.evidence_coverage < config.resolution.minimum_coverage:
        unresolved_reasons.add("leading_coverage_low")
    if quality.quality == "weak" and leading_comparator_dependent:
        unresolved_reasons.add("comparator_quality_weak")
    if not trustworthy_powered_intersection:
        unresolved_reasons.add("powered_wheels_untrusted")
    if (
        len(candidates) > 1
        and leading
        and leading.score - candidates[1].score < config.resolution.top_gap
    ):
        unresolved_reasons.add("leading_candidates_close")
    if (
        leading
        and leading.mechanism
        in {
            "combined_lateral_longitudinal_load_candidate",
            "rotation_instability_candidate",
        }
        and body is None
        and yaw is None
        and mismatch is None
    ):
        unresolved_reasons.add("motion_state_unavailable")
    if (
        leading
        and leading.mechanism
        in {
            "power_step_candidate",
            "combined_lateral_longitudinal_load_candidate",
            "rotation_instability_candidate",
        }
        and ordering == "near_simultaneous_or_unknown"
    ):
        unresolved_reasons.add("temporal_order_ambiguous")
    observed = {
        "stored_type": "wheelspin",
        "stored_severity": event.get("severity"),
        "event_wheels": list(event_wheels),
        "effective_drivetrain": drivetrain.effective,
        "speed_at_onset_kmh": speed,
        "gear_at_onset": int(gear) if gear is not None else None,
        "throttle_at_onset_pct": throttle,
        "throttle_filtered_at_onset_pct": _at_time(samples, "throttle_filtered", onset),
        "brake_at_onset_pct": _at_time(samples, "brake", onset),
        "brake_filtered_at_onset_pct": _at_time(samples, "brake_filtered", onset),
        "along_track_speed_at_onset_kmh": along_track_speed,
        "chassis_heading_deg_at_onset": motion_at("chassis_heading"),
        "travel_heading_deg_at_onset": motion_at("travel_heading"),
        "body_slip_angle_deg_at_onset": body,
        "yaw_rate_signed_at_onset": yaw,
        "steering_wheel_rad_at_onset": steering,
        "steer_fl_rad_at_onset": _at_time(samples, "steer_fl_rad", onset),
        "steer_fr_rad_at_onset": _at_time(samples, "steer_fr_rad", onset),
        "surface_at_onset": _at_time(samples, "surface", onset, discrete=True),
        "aids_at_onset": _at_time(samples, "aids", onset, discrete=True),
        "body_height_at_onset_mm": _at_time(samples, "body_height", onset),
        "suspension_at_onset_mm": {
            wheel: _at_time(samples, f"sus_{wheel}", onset) for wheel in WHEELS
        },
        "sway_at_onset_raw": _at_time(samples, "sway", onset),
        "heave_at_onset_raw": _at_time(samples, "heave", onset),
        "surge_at_onset_raw": _at_time(samples, "surge", onset),
        "positive_torque_at_onset_raw": torque_at_onset,
        "slip_at_onset": metrics["slip_at_onset"],
        "peak_slip": metrics["peak_slip"],
    }
    derived = {
        "analyzed_powered_wheels": list(analyzed),
        "effective_powered_wheels": list(effective_wheels),
        "trustworthy_powered_wheel_intersection": trustworthy_powered_intersection,
        "mean_powered_slip_at_onset": metrics["mean_powered_slip_at_onset"],
        "slip_excess_integral_ratio_s": metrics["slip_excess_integral"],
        "duration_above_threshold_ms": metrics["duration_above_threshold_ms"],
        "same_axle_asymmetry_peak": asymmetry,
        "same_axle_asymmetry_duration_ms": metrics["same_axle_asymmetry_duration_ms"],
        "both_powered_wheels_crossed_threshold": (
            len(peaks) >= 2 and all(value > config.thresholds.slip for value in peaks)
        ),
        "vertical_disturbance_families": list(vertical_families),
        "slope_window_ms": slope_window,
        "throttle_slope_pct_s": throttle_slope,
        "throttle_filtered_slope_pct_s": _slope(samples, "throttle_filtered", onset, slope_window),
        "torque_slope_raw_s": torque_slope,
        "torque_slope_by_wheel_raw_s": torque_slope_by_wheel,
        "torque_step_by_wheel_raw": torque_step_by_wheel,
        "yaw_change_rad_s2": _slope(samples, "yaw_rate_signed", onset, slope_window),
        "brake_slope_pct_s": _slope(samples, "brake", onset, slope_window),
        "ordering": ordering,
    }
    resolution: Literal["resolved", "mixed_or_unresolved"] = (
        "mixed_or_unresolved" if unresolved_reasons else "resolved"
    )
    reference_corner, context_corner, corner_relation, corner_distance = _corner_context(
        path, corners, progress
    )
    return WheelspinCharacterization(
        lap_id=lap_id,
        event_index=event_index,
        reference_corner=reference_corner,
        context_corner=context_corner,
        corner_relation=corner_relation,
        corner_distance_m=corner_distance,
        start_m=start_m,
        end_m=end_m,
        start_progress_m=progress,
        end_progress_m=end_progress,
        start_time_ms=round(onset),
        end_time_ms=round(end_time),
        observed=observed,
        derived=derived,
        sequence=sequence,
        comparators=quality,
        comparator_details=tuple(
            {
                "lap_id": int(peer["lap_id"]),
                "control_class": peer["control_class"],
                "anchor_time_ms": peer["anchor_ms"],
                "end_time_ms": peer["end_ms"],
                "peak_slip": peer["peak"],
                "slip_excess_integral_ratio_s": peer["metrics"]["slip_excess_integral"],
                "duration_above_threshold_ms": peer["metrics"]["duration_above_threshold_ms"],
                "slip_separation": peer["separation"],
                "speed_kmh": peer["speed"],
                "gear": int(peer["gear"]) if peer["gear"] is not None else None,
                "speed_difference_kmh": peer["speed_difference"],
                "projection_distance_m": peer["projection"],
                "utility": peer["utility"],
                "bottoming_context": peer["bottoming"],
            }
            for peer in peers
        ),
        candidates=candidates,
        resolution=resolution,
        unresolved_reasons=tuple(sorted(unresolved_reasons)),
    )


def _minimal_characterization(
    context: LapContext,
    event: dict[str, Any],
    event_index: int,
    drivetrain: CatalogDrivetrain,
    reason: str,
) -> WheelspinCharacterization:
    start_m = float(event.get("start_dist", 0))
    end_m = float(event.get("end_dist", start_m))
    onset = _event_time(context.samples, start_m)
    end_time = _event_time(context.samples, end_m)
    reasons = {reason}
    if not context.comparison_eligible:
        reasons.add("lap_not_comparison_eligible")
    return WheelspinCharacterization(
        lap_id=int(context.lap["id"]),
        event_index=event_index,
        reference_corner=None,
        context_corner=None,
        corner_relation=None,
        corner_distance_m=None,
        start_m=start_m,
        end_m=end_m,
        start_progress_m=None,
        end_progress_m=None,
        start_time_ms=round(onset) if onset is not None else None,
        end_time_ms=round(end_time) if end_time is not None else None,
        observed={
            "stored_type": "wheelspin",
            "stored_severity": event.get("severity"),
            "event_wheels": sorted(event.get("wheels") or []),
            "effective_drivetrain": drivetrain.effective,
        },
        derived=(
            {"eligibility": "not_comparison_eligible"}
            if not context.comparison_eligible
            else {}
        ),
        sequence={
            "meaningful_throttle_rise_start_ms": None,
            "meaningful_torque_rise_start_ms": None,
            "rotation_deviation_start_ms": None,
            "body_slip_deviation_start_ms": None,
            "yaw_deviation_start_ms": None,
            "slip_threshold_cross_ms": None,
            "shift_ms": None,
            "surface_transition_ms": None,
            "vertical_disturbance_ms": None,
        },
        comparators=ComparatorQuality(0, "weak", 0.0, 0, 0, 0, None, None, None, 0, 0, ()),
        comparator_details=(),
        candidates=(),
        resolution="mixed_or_unresolved",
        unresolved_reasons=tuple(sorted(reasons)),
    )


def characterize_wheelspin_events(
    laps: list[dict[str, Any]],
    *,
    spatial_reference: spatial.ReferencePath | None,
    trajectories: dict[int, spatial.ProjectedTrajectory],
    corners: list[dict[str, Any]],
    comparison_lap_ids: set[int] | None = None,
    drivetrain_layout: str | None = None,
    config: CharacterizationConfig = DEFAULT_CONFIG,
) -> CharacterizationResult:
    """Return catalog-drivetrain-aware wheelspin explanations."""
    drivetrain = catalog_drivetrain(drivetrain_layout)
    eligible = comparison_lap_ids if comparison_lap_ids is not None else set(trajectories)
    contexts: dict[int, LapContext] = {}
    for lap in laps:
        lap_id = int(lap["id"])
        samples: Samples = lap.get("samples") or {}
        contexts[lap_id] = LapContext(
            lap=lap,
            samples=samples,
            trajectory=trajectories.get(lap_id),
            motion=_motion_series(trajectories.get(lap_id), config),
            comparison_eligible=lap_id in eligible and _lap_usable(lap),
            disqualifying_event_times_ms=_indexed_event_times(lap, samples),
            loose_surface_times_ms=_indexed_loose_surface_times(samples),
            vertical_disturbance_times_ms=_indexed_vertical_disturbance_times(samples, config),
        )
    output: list[WheelspinCharacterization] = []
    for lap in sorted(laps, key=lambda value: int(value["id"])):
        context = contexts[int(lap["id"])]
        indexed = [
            (position, event)
            for position, event in enumerate(lap.get("events") or [])
            if str(event.get("type", "")) == "wheelspin"
        ]
        indexed.sort(
            key=lambda pair: (
                float(pair[1].get("start_dist", 0)),
                float(pair[1].get("end_dist", pair[1].get("start_dist", 0))),
                tuple(sorted(pair[1].get("wheels") or [])),
                float(pair[1].get("severity", 0)),
                pair[0],
            )
        )
        for event_index, (_position, event) in enumerate(indexed):
            if spatial_reference is None or context.trajectory is None:
                start_m = float(event.get("start_dist", 0))
                end_m = float(event.get("end_dist", start_m))
                onset = _event_time(context.samples, start_m)
                end_time = _event_time(context.samples, end_m)
                reason = (
                    "spatial_projection_unavailable"
                    if context.trajectory is None
                    else "event_spatial_alignment_unavailable"
                )
                output.append(
                    WheelspinCharacterization(
                        lap_id=int(lap["id"]),
                        event_index=event_index,
                        reference_corner=None,
                        context_corner=None,
                        corner_relation=None,
                        corner_distance_m=None,
                        start_m=start_m,
                        end_m=end_m,
                        start_progress_m=None,
                        end_progress_m=None,
                        start_time_ms=round(onset) if onset is not None else None,
                        end_time_ms=round(end_time) if end_time is not None else None,
                        observed={
                            "stored_type": "wheelspin",
                            "stored_severity": event.get("severity"),
                            "event_wheels": sorted(event.get("wheels") or []),
                            "effective_drivetrain": drivetrain.effective,
                        },
                        derived={"eligibility": "not_comparison_eligible"}
                        if not context.comparison_eligible
                        else {},
                        sequence={
                            "meaningful_throttle_rise_start_ms": None,
                            "meaningful_torque_rise_start_ms": None,
                            "rotation_deviation_start_ms": None,
                            "body_slip_deviation_start_ms": None,
                            "yaw_deviation_start_ms": None,
                            "slip_threshold_cross_ms": None,
                            "shift_ms": None,
                            "surface_transition_ms": None,
                            "vertical_disturbance_ms": None,
                        },
                        comparators=ComparatorQuality(
                            0, "weak", 0.0, 0, 0, 0, None, None, None, 0, 0, ()
                        ),
                        comparator_details=(),
                        candidates=(),
                        resolution="mixed_or_unresolved",
                        unresolved_reasons=tuple(
                            sorted(
                                {
                                    reason,
                                    *(
                                        ("lap_not_comparison_eligible",)
                                        if not context.comparison_eligible
                                        else ()
                                    ),
                                }
                            )
                        ),
                    )
                )
                continue
            item = _event_characterization(
                context,
                event,
                event_index,
                contexts,
                spatial_reference,
                corners,
                drivetrain,
                config,
            )
            output.append(
                item
                if item is not None
                else _minimal_characterization(
                    context,
                    event,
                    event_index,
                    drivetrain,
                    "event_spatial_alignment_unavailable",
                )
            )
    return CharacterizationResult(drivetrain, tuple(output))


def drivetrain_json(value: CatalogDrivetrain) -> dict[str, Any]:
    result = asdict(value)
    result["effective_powered_wheels"] = list(value.effective_powered_wheels)
    return result


def _evidence_json(item: Contribution) -> dict[str, Any]:
    return {
        key: value
        for key, value in asdict(item).items()
        if key not in {"activation", "available"} and value is not None
    }


def bounded_candidates(
    value: WheelspinCharacterization, config: CharacterizationConfig = DEFAULT_CONFIG
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in value.candidates[: config.resolution.exported_candidates]:
        support = sorted(
            (item for item in candidate.contributions if item.signed_contribution > 0),
            key=lambda item: (-item.signed_contribution, item.feature),
        )[: config.resolution.exported_support]
        counter = sorted(
            (item for item in candidate.contributions if item.signed_contribution < 0),
            key=lambda item: (item.signed_contribution, item.feature),
        )[: config.resolution.exported_counter]
        rows.append(
            {
                "mechanism": candidate.mechanism,
                "score": round(candidate.score, 3),
                "evidence_coverage": round(candidate.evidence_coverage, 3),
                "evidence": [_evidence_json(item) for item in support],
                "counterevidence": [_evidence_json(item) for item in counter],
            }
        )
    return rows
