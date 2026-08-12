"""Pure racing-line geometry and continuity-aware reference-path projection."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any

from app.processing.orientation import (
    MIN_TRAVEL_SPEED_MPS,
    chassis_forward,
    wrap_angle,
)

Samples = dict[str, list[float]]

INITIAL_PROGRESS_WINDOW_M = 100.0
BACKWARD_TOLERANCE_M = 5.0
MIN_FORWARD_WINDOW_M = 30.0
MAX_FORWARD_WINDOW_M = 250.0
FORWARD_DISTANCE_SCALE = 3.0
FORWARD_DISTANCE_PADDING_M = 10.0
INTERNAL_STEP_M = 2.0
CURVATURE_HALF_WINDOW_M = 10.0
MOTION_DIFFERENCE_RADIUS = 2
TANGENT_HALF_WINDOW_M = 0.5
EPSILON = 1e-9

PROJECTED_SOURCE_CHANNELS = (
    "speed",
    "throttle",
    "brake",
    "gear",
    "steering_wheel_rad",
    "yaw_rate_signed",
)


@dataclass(slots=True)
class ReferencePath:
    progress: list[float]
    source_dist: list[float]
    x: list[float]
    y: list[float] | None
    z: list[float]

    @property
    def total(self) -> float:
        return self.progress[-1]


@dataclass(slots=True)
class ProjectedTrajectory:
    progress: list[float]
    channels: Samples
    dense: Samples


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _distance(
    x0: float,
    y0: float | None,
    z0: float,
    x1: float,
    y1: float | None,
    z1: float,
    *,
    use_y: bool,
) -> float:
    dy = float(y1) - float(y0) if use_y and y0 is not None and y1 is not None else 0.0
    return math.sqrt((x1 - x0) ** 2 + dy**2 + (z1 - z0) ** 2)


def build_reference_path(samples: Samples) -> ReferencePath | None:
    """Create a strictly ordered spatial polyline from one persisted reference lap."""
    dist = samples.get("dist") or []
    xs = samples.get("pos_x") or []
    zs = samples.get("pos_z") or []
    n = len(dist)
    if n < 2 or len(xs) != n or len(zs) != n:
        return None
    ys = samples.get("pos_y")
    use_y = ys is not None and len(ys) == n and all(_finite(value) for value in ys)

    source_dist: list[float] = []
    x: list[float] = []
    y: list[float] | None = [] if use_y else None
    z: list[float] = []
    progress: list[float] = []
    for i in range(n):
        if not (_finite(dist[i]) and _finite(xs[i]) and _finite(zs[i])):
            continue
        if source_dist and float(dist[i]) <= source_dist[-1]:
            continue
        px, pz = float(xs[i]), float(zs[i])
        py = float(ys[i]) if use_y and ys is not None else None
        if x:
            segment_length = _distance(x[-1], y[-1] if y else None, z[-1], px, py, pz, use_y=use_y)
            if segment_length <= EPSILON:
                continue
            progress.append(progress[-1] + segment_length)
        else:
            progress.append(0.0)
        source_dist.append(float(dist[i]))
        x.append(px)
        z.append(pz)
        if y is not None and py is not None:
            y.append(py)
    if len(progress) < 2 or progress[-1] <= EPSILON:
        return None
    return ReferencePath(progress=progress, source_dist=source_dist, x=x, y=y, z=z)


def spatial_grid(total: float, step: float) -> list[float]:
    if total <= 0 or step <= 0:
        return []
    grid = [i * step for i in range(int(total / step) + 1)]
    if not grid or total - grid[-1] > EPSILON:
        grid.append(total)
    return grid


def _interp(xs: list[float], ys: list[float], value: float) -> float:
    if value <= xs[0]:
        return ys[0]
    if value >= xs[-1]:
        return ys[-1]
    i = bisect_left(xs, value)
    x0, x1 = xs[i - 1], xs[i]
    if x1 <= x0:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (value - x0) / (x1 - x0)


def _nearest(xs: list[float], ys: list[float], value: float) -> float:
    i = bisect_left(xs, value)
    if i <= 0:
        return ys[0]
    if i >= len(xs):
        return ys[-1]
    return ys[i] if xs[i] - value < value - xs[i - 1] else ys[i - 1]


def path_point(path: ReferencePath, progress: float) -> tuple[float, float | None, float]:
    return (
        _interp(path.progress, path.x, progress),
        _interp(path.progress, path.y, progress) if path.y is not None else None,
        _interp(path.progress, path.z, progress),
    )


def _path_tangent(
    path: ReferencePath, progress: float, *, use_y: bool
) -> tuple[float, float, float]:
    left = max(0.0, progress - TANGENT_HALF_WINDOW_M)
    right = min(path.total, progress + TANGENT_HALF_WINDOW_M)
    x0, y0, z0 = path_point(path, left)
    x1, y1, z1 = path_point(path, right)
    dx, dz = x1 - x0, z1 - z0
    dy = float(y1) - float(y0) if use_y and y0 is not None and y1 is not None else 0.0
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    return (dx / length, dy / length, dz / length) if length > EPSILON else (0.0, 0.0, 0.0)


def _source_velocity(
    samples: Samples, index: int, *, use_y: bool
) -> tuple[float, float, float]:
    """Five-sample centered world velocity, with one-sided endpoint windows."""
    times = samples["t"]
    xs, zs = samples["pos_x"], samples["pos_z"]
    ys = samples.get("pos_y")
    left = max(0, index - MOTION_DIFFERENCE_RADIUS)
    right = min(len(times) - 1, index + MOTION_DIFFERENCE_RADIUS)
    dt = times[right] - times[left]
    if dt <= EPSILON:
        return (0.0, 0.0, 0.0)
    dy = ys[right] - ys[left] if use_y and ys is not None else 0.0
    return (
        (xs[right] - xs[left]) / dt,
        dy / dt,
        (zs[right] - zs[left]) / dt,
    )


def progress_at_source_distance(path: ReferencePath, distance: float) -> float:
    return _interp(path.source_dist, path.progress, distance)


def _wrap_angle(angle: float) -> float:
    while angle <= -math.pi:
        angle += 2 * math.pi
    while angle > math.pi:
        angle -= 2 * math.pi
    return angle


def _heading_curvature(
    progress: list[float], x: list[float], z: list[float]
) -> tuple[list[float], list[float]]:
    headings: list[float] = []
    curvature: list[float] = []
    for point in progress:
        left = max(progress[0], point - CURVATURE_HALF_WINDOW_M)
        right = min(progress[-1], point + CURVATURE_HALF_WINDOW_M)
        lx, lz = _interp(progress, x, left), _interp(progress, z, left)
        rx, rz = _interp(progress, x, right), _interp(progress, z, right)
        headings.append(math.atan2(rz - lz, rx - lx) if right > left else 0.0)

        left_span, right_span = point - left, right - point
        if left_span <= EPSILON or right_span <= EPSILON:
            curvature.append(0.0)
            continue
        cx, cz = _interp(progress, x, point), _interp(progress, z, point)
        incoming = math.atan2(cz - lz, cx - lx)
        outgoing = math.atan2(rz - cz, rx - cx)
        incoming_length = math.hypot(cx - lx, cz - lz)
        outgoing_length = math.hypot(rx - cx, rz - cz)
        curvature_scale = (incoming_length + outgoing_length) / 2
        curvature.append(
            _wrap_angle(outgoing - incoming) / curvature_scale
            if curvature_scale > EPSILON
            else 0.0
        )
    return headings, curvature


def reference_geometry(path: ReferencePath, step: float) -> Samples:
    grid = spatial_grid(path.total, step)
    x = [_interp(path.progress, path.x, point) for point in grid]
    z = [_interp(path.progress, path.z, point) for point in grid]
    heading, curvature = _heading_curvature(grid, x, z)
    out: Samples = {
        "progress": grid,
        "x": x,
        "z": z,
        "heading": heading,
        "curvature": curvature,
    }
    if path.y is not None:
        out["y"] = [_interp(path.progress, path.y, point) for point in grid]
    return out


def _project_in_window(
    path: ReferencePath,
    x: float,
    y: float | None,
    z: float,
    low: float,
    high: float,
    expected: float,
    *,
    use_y: bool,
) -> tuple[float, float, float | None, float] | None:
    first = max(0, bisect_left(path.progress, low) - 1)
    last = min(len(path.progress) - 2, bisect_right(path.progress, high))
    best: tuple[tuple[float, float, int], tuple[float, float, float | None, float]] | None = None
    for i in range(first, last + 1):
        p0, p1 = path.progress[i], path.progress[i + 1]
        if p1 < low or p0 > high:
            continue
        x0, x1 = path.x[i], path.x[i + 1]
        z0, z1 = path.z[i], path.z[i + 1]
        y0 = path.y[i] if path.y is not None else None
        y1 = path.y[i + 1] if path.y is not None else None
        dx, dz = x1 - x0, z1 - z0
        dy = float(y1) - float(y0) if use_y and y0 is not None and y1 is not None else 0.0
        denom = dx * dx + dy * dy + dz * dz
        if denom <= EPSILON:
            continue
        ay = float(y) if use_y and y is not None else 0.0
        by = float(y0) if use_y and y0 is not None else 0.0
        fraction = ((x - x0) * dx + (ay - by) * dy + (z - z0) * dz) / denom
        progress_fraction_low = max(0.0, (low - p0) / (p1 - p0))
        progress_fraction_high = min(1.0, (high - p0) / (p1 - p0))
        fraction = min(progress_fraction_high, max(progress_fraction_low, fraction))
        projected_progress = p0 + fraction * (p1 - p0)
        px, pz = x0 + fraction * dx, z0 + fraction * dz
        py = float(y0) + fraction * dy if path.y is not None and y0 is not None else None
        distance = _distance(x, y, z, px, py, pz, use_y=use_y)
        key = (distance * distance, abs(projected_progress - expected), i)
        value = (projected_progress, px, py, pz)
        if best is None or key < best[0]:
            best = (key, value)
    return best[1] if best is not None else None


def project_lap(
    path: ReferencePath,
    samples: Samples,
    *,
    completed_time_ms: int | None = None,
) -> ProjectedTrajectory | None:
    """Project one full trajectory without ever globally re-acquiring another track section."""
    dist = samples.get("dist") or []
    times = samples.get("t") or []
    xs = samples.get("pos_x") or []
    zs = samples.get("pos_z") or []
    n = len(dist)
    if n < 2 or len(times) != n or len(xs) != n or len(zs) != n:
        return None
    ys = samples.get("pos_y")
    lap_has_y = ys is not None and len(ys) == n and all(_finite(value) for value in ys)
    use_y = lap_has_y and path.y is not None
    available = [
        channel
        for channel in PROJECTED_SOURCE_CHANNELS
        if len(samples.get(channel) or []) == n
    ]
    orientation_arrays = [samples.get(channel) or [] for channel in (
        "orientation_x",
        "orientation_y",
        "orientation_z",
        "orientation_w",
    )]
    orientation_forwards = (
        [chassis_forward(tuple(values[i] for values in orientation_arrays)) for i in range(n)]
        if all(len(values) == n for values in orientation_arrays)
        else []
    )
    has_orientation = bool(orientation_forwards) and all(
        value is not None for value in orientation_forwards
    )
    channels: Samples = {
        "time_ms": [],
        "x": [],
        "z": [],
        "lateral_offset": [],
        "projection_distance": [],
        "along_track_speed_kmh": [],
        **({"y": []} if lap_has_y else {}),
        **(
            {
                "chassis_forward_x": [],
                "chassis_forward_z": [],
                "travel_velocity_x": [],
                "travel_velocity_z": [],
            }
            if has_orientation
            else {}
        ),
        **{channel: [] for channel in available},
    }
    dense: Samples = {
        "time_ms": [],
        "dist": [],
        "progress": [],
        "along_track_speed_kmh": [],
        **(
            {
                "chassis_forward_x": [],
                "chassis_forward_z": [],
                "travel_velocity_x": [],
                "travel_velocity_z": [],
            }
            if has_orientation
            else {}
        ),
    }
    projected_progress: list[float] = []
    last_progress = 0.0
    last_accepted_dist = float(dist[0]) if _finite(dist[0]) else 0.0
    for i in range(n):
        if not (
            _finite(times[i])
            and _finite(dist[i])
            and _finite(xs[i])
            and _finite(zs[i])
        ):
            continue
        x, z = float(xs[i]), float(zs[i])
        y = float(ys[i]) if lap_has_y and ys is not None else None
        if not projected_progress:
            low, high, expected = 0.0, min(path.total, INITIAL_PROGRESS_WINDOW_M), 0.0
        else:
            driven_advance = max(0.0, float(dist[i]) - last_accepted_dist)
            forward = min(
                MAX_FORWARD_WINDOW_M,
                max(
                    MIN_FORWARD_WINDOW_M,
                    FORWARD_DISTANCE_SCALE * driven_advance + FORWARD_DISTANCE_PADDING_M,
                ),
            )
            low = max(0.0, last_progress - BACKWARD_TOLERANCE_M)
            high = min(path.total, last_progress + forward)
            expected = min(path.total, last_progress + driven_advance)
        projected = _project_in_window(path, x, y, z, low, high, expected, use_y=use_y)
        if projected is None:
            continue
        raw_progress, _px, _py, _pz = projected
        velocity = _source_velocity(samples, i, use_y=use_y)
        tangent = _path_tangent(path, raw_progress, use_y=use_y)
        along_track_speed = 3.6 * sum(
            component * direction
            for component, direction in zip(velocity, tangent, strict=True)
        )
        progress = max(last_progress, raw_progress) if projected_progress else raw_progress
        px, py, pz = path_point(path, progress)
        tx0, _ty0, tz0 = path_point(path, max(0.0, progress - 0.5))
        tx1, _ty1, tz1 = path_point(path, min(path.total, progress + 0.5))
        tangent_length = math.hypot(tx1 - tx0, tz1 - tz0)
        lateral = (
            (x - px) * (-(tz1 - tz0) / tangent_length)
            + (z - pz) * ((tx1 - tx0) / tangent_length)
            if tangent_length > EPSILON
            else 0.0
        )
        projection_distance = _distance(x, y, z, px, py, pz, use_y=use_y)
        elapsed_ms = float(times[i]) * 1000
        values = {
            "time_ms": elapsed_ms,
            "x": x,
            "z": z,
            "lateral_offset": lateral,
            "projection_distance": projection_distance,
            "along_track_speed_kmh": along_track_speed,
            **({"y": float(y)} if y is not None else {}),
            **{channel: float(samples[channel][i]) for channel in available},
        }
        if has_orientation:
            chassis_vector = orientation_forwards[i]
            assert chassis_vector is not None
            values.update(
                {
                    "chassis_forward_x": chassis_vector[0],
                    "chassis_forward_z": chassis_vector[2],
                    "travel_velocity_x": velocity[0],
                    "travel_velocity_z": velocity[2],
                }
            )
        dense["time_ms"].append(elapsed_ms)
        dense["dist"].append(float(dist[i]))
        dense["progress"].append(progress)
        dense["along_track_speed_kmh"].append(along_track_speed)
        if has_orientation:
            chassis_vector = orientation_forwards[i]
            assert chassis_vector is not None
            dense["chassis_forward_x"].append(chassis_vector[0])
            dense["chassis_forward_z"].append(chassis_vector[2])
            dense["travel_velocity_x"].append(velocity[0])
            dense["travel_velocity_z"].append(velocity[2])
        if projected_progress and progress <= projected_progress[-1] + EPSILON:
            # Keep the most spatially significant sample at a duplicated progress
            # (for example the outer point of a spin). Time and reverse motion carry
            # their own evidence-preserving coalescing semantics.
            if projection_distance >= channels["projection_distance"][-1]:
                for channel, value in values.items():
                    if channel not in {"time_ms", "along_track_speed_kmh"}:
                        channels[channel][-1] = value
            channels["time_ms"][-1] = max(channels["time_ms"][-1], elapsed_ms)
            channels["along_track_speed_kmh"][-1] = min(
                channels["along_track_speed_kmh"][-1], along_track_speed
            )
        else:
            projected_progress.append(progress)
            for channel, value in values.items():
                channels[channel].append(value)
        last_progress = progress
        last_accepted_dist = float(dist[i])
    if len(projected_progress) < 2:
        return None
    if (
        completed_time_ms is not None
        and completed_time_ms > 0
        and projected_progress[-1] >= path.total - EPSILON
    ):
        channels["time_ms"][-1] = max(
            channels["time_ms"][-1], float(completed_time_ms)
        )
    return ProjectedTrajectory(progress=projected_progress, channels=channels, dense=dense)


def resample_projected(
    path: ReferencePath, trajectory: ProjectedTrajectory, step: float
) -> Samples:
    full_grid = spatial_grid(path.total, step)
    grid = [
        point
        for point in full_grid
        if trajectory.progress[0] - 1e-6 <= point <= trajectory.progress[-1] + 1e-6
    ]
    out: Samples = {"progress": grid}
    for channel, values in trajectory.channels.items():
        fn = _nearest if channel == "gear" else _interp
        out[channel] = [fn(trajectory.progress, values, point) for point in grid]
    heading, curvature = _heading_curvature(grid, out["x"], out["z"])
    ref_x = [_interp(path.progress, path.x, point) for point in grid]
    ref_z = [_interp(path.progress, path.z, point) for point in grid]
    ref_heading, _ref_curvature = _heading_curvature(grid, ref_x, ref_z)
    out["heading_error"] = [
        math.degrees(_wrap_angle(actual - reference))
        for actual, reference in zip(heading, ref_heading, strict=True)
    ]
    if all(
        channel in out
        for channel in (
            "chassis_forward_x",
            "chassis_forward_z",
            "travel_velocity_x",
            "travel_velocity_z",
        )
    ):
        chassis_errors: list[float] = []
        body_slips: list[float] = []
        for i, reference in enumerate(ref_heading):
            forward_x = out["chassis_forward_x"][i]
            forward_z = out["chassis_forward_z"][i]
            forward_norm = math.hypot(forward_x, forward_z)
            if forward_norm <= EPSILON:
                chassis_errors.append(math.nan)
                body_slips.append(math.nan)
                continue
            chassis_heading = math.atan2(forward_z, forward_x)
            chassis_errors.append(math.degrees(wrap_angle(chassis_heading - reference)))
            velocity_x = out["travel_velocity_x"][i]
            velocity_z = out["travel_velocity_z"][i]
            if math.hypot(velocity_x, velocity_z) < MIN_TRAVEL_SPEED_MPS:
                body_slips.append(math.nan)
            else:
                travel_heading = math.atan2(velocity_z, velocity_x)
                body_slips.append(math.degrees(wrap_angle(travel_heading - chassis_heading)))
        out["chassis_heading_error"] = chassis_errors
        out["body_slip_angle"] = body_slips
    out["curvature"] = curvature
    return out


def _at(trace: Samples, channel: str, progress: float) -> float | None:
    grid = trace.get("progress") or []
    values = trace.get(channel) or []
    if not grid or len(values) != len(grid) or progress < grid[0] or progress > grid[-1]:
        return None
    return _interp(grid, values, progress)


def _interval_points(trace: Samples, start: float, end: float) -> list[float]:
    grid = trace.get("progress") or []
    if not grid or start < grid[0] or end > grid[-1] or end < start:
        return []
    return [start, *(point for point in grid if start < point < end), end]


def corner_line_metrics(
    path: ReferencePath,
    trajectory: ProjectedTrajectory,
    corners: list[dict[str, Any]],
) -> list[dict[str, float | int | None]]:
    trace = resample_projected(path, trajectory, INTERNAL_STEP_M)
    rows: list[dict[str, float | int | None]] = []
    for corner in corners:
        entry = progress_at_source_distance(path, float(corner["entry_dist"]))
        apex = progress_at_source_distance(path, float(corner["apex_dist"]))
        exit_ = progress_at_source_distance(path, float(corner["exit_dist"]))
        intervals = [(entry, exit_)] if entry <= exit_ else [(entry, path.total), (0.0, exit_)]
        interval_points = [_interval_points(trace, start, end) for start, end in intervals]
        if not all(interval_points):
            continue
        metric_points = [
            point
            for start, end in intervals
            for point in trace["progress"]
            if start <= point <= end
        ]
        if not metric_points:
            continue
        offsets = [_at(trace, "lateral_offset", point) for point in metric_points]
        projections = [_at(trace, "projection_distance", point) for point in metric_points]
        curvatures = [_at(trace, "curvature", point) for point in metric_points]
        if any(value is None for value in (*offsets, *projections, *curvatures)):
            continue
        offset_values = [float(value) for value in offsets if value is not None]
        projection_values = [float(value) for value in projections if value is not None]
        curvature_values = [float(value) for value in curvatures if value is not None]
        path_length = 0.0
        for values in interval_points:
            for left, right in zip(values, values[1:], strict=False):
                x0, x1 = _at(trace, "x", left), _at(trace, "x", right)
                z0, z1 = _at(trace, "z", left), _at(trace, "z", right)
                y0, y1 = _at(trace, "y", left), _at(trace, "y", right)
                if x0 is None or x1 is None or z0 is None or z1 is None:
                    continue
                path_length += _distance(x0, y0, z0, x1, y1, z1, use_y=y0 is not None)
        peak_index = max(range(len(curvature_values)), key=lambda i: abs(curvature_values[i]))
        rows.append(
            {
                "corner": int(corner["n"]),
                "entry_lateral_offset": _at(trace, "lateral_offset", entry),
                "apex_lateral_offset": _at(trace, "lateral_offset", apex),
                "exit_lateral_offset": _at(trace, "lateral_offset", exit_),
                "entry_heading_error": _at(trace, "heading_error", entry),
                "apex_heading_error": _at(trace, "heading_error", apex),
                "exit_heading_error": _at(trace, "heading_error", exit_),
                "line_rms_offset": math.sqrt(
                    sum(value * value for value in offset_values) / len(offset_values)
                ),
                "line_peak_offset": max(offset_values, key=abs),
                "projection_distance_rms": math.sqrt(
                    sum(value * value for value in projection_values) / len(projection_values)
                ),
                "projection_distance_peak": max(projection_values),
                "corner_path_length": path_length,
                "mean_abs_curvature": sum(abs(value) for value in curvature_values)
                / len(curvature_values),
                "peak_abs_curvature": abs(curvature_values[peak_index]),
                "peak_curvature_progress": metric_points[peak_index],
            }
        )
    return rows
