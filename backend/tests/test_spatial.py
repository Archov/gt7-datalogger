"""Continuity-aware physical racing-line projection and metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from app.processing import spatial


def make_samples(
    points: Sequence[tuple[float, float | None, float]],
    *,
    dist_scale: float = 1.0,
    speed_kmh: float = 120.0,
) -> dict[str, list[float]]:
    distance = [0.0]
    for previous, current in zip(points, points[1:], strict=False):
        previous_y = previous[1]
        current_y = current[1]
        dy = (
            current_y - previous_y
            if previous_y is not None and current_y is not None
            else 0.0
        )
        segment = math.sqrt(
            (current[0] - previous[0]) ** 2 + dy**2 + (current[2] - previous[2]) ** 2
        )
        distance.append(distance[-1] + segment * dist_scale)
    samples = {
        "t": [i / 60 for i in range(len(points))],
        "dist": distance,
        "pos_x": [point[0] for point in points],
        "pos_z": [point[2] for point in points],
        "speed": [speed_kmh] * len(points),
        "throttle": [70.0] * len(points),
        "brake": [0.0] * len(points),
        "gear": [4.0] * len(points),
        "yaw_rate_signed": [0.1] * len(points),
    }
    if all(point[1] is not None for point in points):
        pos_y: list[float] = []
        for _, value, _ in points:
            assert value is not None
            pos_y.append(value)
        samples["pos_y"] = pos_y
    return samples


def straight_points(length: int, lateral: float = 0.0) -> list[tuple[float, float, float]]:
    return [(float(x), 0.0, lateral) for x in range(length + 1)]


def test_spatial_grid_retains_final_partial_interval() -> None:
    assert spatial.spatial_grid(25.3, 10.0) == [0.0, 10.0, 20.0, 25.3]


def arc_points(radius: float, count: int = 181) -> list[tuple[float, float, float]]:
    return [
        (
            radius * math.cos((math.pi / 2) * i / (count - 1)),
            0.0,
            radius * math.sin((math.pi / 2) * i / (count - 1)),
        )
        for i in range(count)
    ]


def timed_samples(
    points: Sequence[tuple[float, float | None, float]],
    times: Sequence[float],
    *,
    speed_kmh: float = 36.0,
) -> dict[str, list[float]]:
    assert len(points) == len(times)
    samples = make_samples(points, speed_kmh=speed_kmh)
    samples["t"] = list(times)
    return samples


def test_same_physical_line_aligns_independently_of_speed_and_driven_distance() -> None:
    reference = make_samples(straight_points(200), speed_kmh=150.0)
    comparison = make_samples(straight_points(200), dist_scale=1.3, speed_kmh=90.0)
    path = spatial.build_reference_path(reference)
    assert path is not None
    projected = spatial.project_lap(path, comparison)
    assert projected is not None
    trace = spatial.resample_projected(path, projected, 10.0)
    assert max(abs(value) for value in trace["lateral_offset"]) < 1e-6
    assert max(trace["projection_distance"]) < 1e-6
    assert trace["speed"] == [90.0] * len(trace["progress"])


def test_chassis_heading_and_body_slip_use_distinct_orientation_and_travel() -> None:
    half = math.sqrt(0.5)
    reference = make_samples(straight_points(100))
    path = spatial.build_reference_path(reference)
    assert path is not None

    aligned = make_samples(straight_points(100))
    for channel, value in zip(
        ("orientation_x", "orientation_y", "orientation_z", "orientation_w"),
        (0.0, -half, 0.0, half),
        strict=True,
    ):
        aligned[channel] = [value] * len(aligned["t"])
    projected = spatial.project_lap(path, aligned)
    assert projected is not None
    trace = spatial.resample_projected(path, projected, 10.0)
    assert max(abs(value) for value in trace["chassis_heading_error"]) < 1e-5
    assert max(abs(value) for value in trace["body_slip_angle"]) < 1e-5

    sideways = make_samples(straight_points(100))
    sideways["orientation_x"] = [0.0] * len(sideways["t"])
    sideways["orientation_y"] = [0.0] * len(sideways["t"])
    sideways["orientation_z"] = [0.0] * len(sideways["t"])
    sideways["orientation_w"] = [1.0] * len(sideways["t"])
    projected_sideways = spatial.project_lap(path, sideways)
    assert projected_sideways is not None
    sideways_trace = spatial.resample_projected(path, projected_sideways, 10.0)
    assert sideways_trace["chassis_heading_error"] == pytest.approx([-90.0] * 11)
    assert sideways_trace["body_slip_angle"] == pytest.approx([90.0] * 11)


def test_wider_and_tighter_arcs_have_signed_offsets_and_physical_curvature() -> None:
    reference = make_samples(arc_points(50.0))
    path = spatial.build_reference_path(reference)
    assert path is not None
    wider = spatial.project_lap(path, make_samples(arc_points(55.0), dist_scale=1.2))
    tighter = spatial.project_lap(path, make_samples(arc_points(45.0), dist_scale=0.8))
    assert wider is not None and tighter is not None
    wide_trace = spatial.resample_projected(path, wider, 2.0)
    tight_trace = spatial.resample_projected(path, tighter, 2.0)
    middle = slice(5, -5)
    assert sum(wide_trace["lateral_offset"][middle]) / len(
        wide_trace["lateral_offset"][middle]
    ) < -4.0
    assert sum(tight_trace["lateral_offset"][middle]) / len(
        tight_trace["lateral_offset"][middle]
    ) > 4.0
    assert max(wide_trace["projection_distance"]) == pytest.approx(5.0, abs=0.2)
    wide_curvature = sum(abs(value) for value in wide_trace["curvature"][middle])
    tight_curvature = sum(abs(value) for value in tight_trace["curvature"][middle])
    assert wide_curvature < tight_curvature


def test_projection_distance_distinguishes_normal_line_from_large_excursion() -> None:
    path = spatial.build_reference_path(make_samples(straight_points(200)))
    assert path is not None
    alternate = spatial.project_lap(path, make_samples(straight_points(200, lateral=2.0)))
    excursion_points = [
        (float(x), 0.0, 30.0 if 80 <= x <= 120 else 0.0) for x in range(201)
    ]
    excursion = spatial.project_lap(path, make_samples(excursion_points))
    assert alternate is not None and excursion is not None
    alternate_trace = spatial.resample_projected(path, alternate, 10.0)
    excursion_trace = spatial.resample_projected(path, excursion, 10.0)
    assert max(alternate_trace["projection_distance"]) == pytest.approx(2.0, abs=0.1)
    assert max(excursion_trace["projection_distance"]) >= 29.0
    assert excursion.progress == sorted(excursion.progress)


def test_corner_boundaries_produce_deterministic_line_and_projection_metrics() -> None:
    path = spatial.build_reference_path(make_samples(straight_points(200)))
    assert path is not None
    points = []
    for x in range(201):
        if x <= 100:
            lateral = -1.0 + 0.04 * x
        else:
            lateral = 3.0 - 0.04 * (x - 100)
        points.append((float(x), 0.0, lateral))
    projected = spatial.project_lap(path, make_samples(points))
    assert projected is not None
    corners = [
        {
            "n": 1,
            "entry_dist": 50.0,
            "apex_dist": 100.0,
            "exit_dist": 150.0,
        }
    ]
    metrics = spatial.corner_line_metrics(path, projected, corners)[0]
    assert metrics["entry_lateral_offset"] == pytest.approx(1.0, abs=0.1)
    assert metrics["apex_lateral_offset"] == pytest.approx(3.0, abs=0.1)
    assert metrics["exit_lateral_offset"] == pytest.approx(1.0, abs=0.1)
    assert metrics["projection_distance_peak"] == pytest.approx(3.0, abs=0.1)
    assert 1.0 < float(metrics["projection_distance_rms"] or 0.0) < 3.0


def test_continuity_prevents_excursion_from_jumping_to_parallel_section() -> None:
    reference_points = [
        *( (float(x), 0.0, 0.0) for x in range(101) ),
        *( (100.0 - i, 0.0, 5.0 * i / 10) for i in range(1, 11) ),
        *( (float(x), 0.0, 5.0) for x in range(89, -1, -1) ),
    ]
    path = spatial.build_reference_path(make_samples(reference_points))
    assert path is not None
    outbound = [(float(x), 0.0, 4.0 if 45 <= x <= 55 else 0.0) for x in range(101)]
    projected = spatial.project_lap(path, make_samples(outbound))
    assert projected is not None
    excursion_index = max(
        range(len(projected.channels["projection_distance"])),
        key=projected.channels["projection_distance"].__getitem__,
    )
    assert projected.progress[excursion_index] < 70.0
    assert projected.channels["projection_distance"][excursion_index] == pytest.approx(
        4.0, abs=0.2
    )


def test_y_disambiguates_vertically_overlapping_xz_sections() -> None:
    reference = make_samples(
        [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (10.0, 20.0, 0.0),
            (0.0, 20.0, 0.0),
        ]
    )
    path = spatial.build_reference_path(reference)
    assert path is not None
    elevated = spatial.project_lap(
        path, make_samples([(5.0, 22.0, 0.0), (4.0, 22.0, 0.0)])
    )
    legacy_xz = spatial.project_lap(path, make_samples([(5.0, None, 0.0), (6.0, None, 0.0)]))
    assert elevated is not None and legacy_xz is not None
    assert elevated.progress[0] > 30.0
    assert elevated.channels["projection_distance"][0] == pytest.approx(2.0)
    assert legacy_xz.progress[0] < 10.0
    assert legacy_xz.channels["projection_distance"][0] == pytest.approx(0.0)
    assert "y" not in legacy_xz.channels


def test_wrapping_corner_combines_both_sides_of_start_finish() -> None:
    path = spatial.build_reference_path(make_samples(straight_points(200)))
    assert path is not None
    projected = spatial.project_lap(
        path, make_samples(straight_points(200, lateral=2.0))
    )
    assert projected is not None
    metrics = spatial.corner_line_metrics(
        path,
        projected,
        [{"n": 9, "entry_dist": 150.0, "apex_dist": 190.0, "exit_dist": 50.0}],
    )[0]
    assert metrics["corner_path_length"] == pytest.approx(100.0, abs=0.2)
    assert metrics["projection_distance_rms"] == pytest.approx(2.0, abs=0.1)
    assert metrics["projection_distance_peak"] == pytest.approx(2.0, abs=0.1)


def test_spatial_time_interpolation_differs_by_speed_on_identical_geometry() -> None:
    points = straight_points(100)
    reference = timed_samples(points, [x / 10 for x in range(101)])
    path = spatial.build_reference_path(reference)
    assert path is not None
    fast = spatial.project_lap(
        path,
        timed_samples(points, [x / 20 for x in range(101)], speed_kmh=72.0),
        completed_time_ms=5000,
    )
    slow = spatial.project_lap(
        path,
        timed_samples(points, [x / 10 for x in range(101)]),
        completed_time_ms=10_000,
    )
    assert fast is not None and slow is not None
    fast_trace = spatial.resample_projected(path, fast, 10.0)
    slow_trace = spatial.resample_projected(path, slow, 10.0)
    assert fast_trace["x"] == slow_trace["x"]
    assert fast_trace["time_ms"] == pytest.approx([x * 500 for x in range(11)])
    assert slow_trace["time_ms"] == pytest.approx([x * 1000 for x in range(11)])
    assert slow_trace["time_ms"] == sorted(slow_trace["time_ms"])


def test_duplicate_progress_keeps_dwell_and_reverse_time_loss() -> None:
    reference_samples = timed_samples(
        straight_points(100), [x / 10 for x in range(101)]
    )
    path = spatial.build_reference_path(reference_samples)
    assert path is not None

    stopped_points = [*straight_points(50), *([(50.0, 0.0, 0.0)] * 30)]
    stopped_points += [(float(x), 0.0, 0.0) for x in range(51, 101)]
    stopped = spatial.project_lap(
        path,
        timed_samples(stopped_points, [i / 10 for i in range(len(stopped_points))]),
        completed_time_ms=13_000,
    )

    reverse_points = [*straight_points(50)]
    reverse_points += [(float(x), 0.0, 0.0) for x in range(49, 39, -1)]
    reverse_points += [(float(x), 0.0, 0.0) for x in range(41, 101)]
    reverse = spatial.project_lap(
        path,
        timed_samples(reverse_points, [i / 10 for i in range(len(reverse_points))]),
        completed_time_ms=12_000,
    )
    assert stopped is not None and reverse is not None
    stopped_trace = spatial.resample_projected(path, stopped, 10.0)
    reverse_trace = spatial.resample_projected(path, reverse, 10.0)
    index_50 = stopped_trace["progress"].index(50.0)
    assert stopped_trace["time_ms"][index_50] == pytest.approx(8000.0)
    assert stopped_trace["time_ms"][-1] == pytest.approx(13_000.0)
    reverse_index_50 = reverse_trace["progress"].index(50.0)
    assert reverse_trace["time_ms"][reverse_index_50] >= 7000.0
    assert reverse_trace["along_track_speed_kmh"][reverse_index_50] < 0
    assert reverse.dense["progress"] == sorted(reverse.dense["progress"])


def test_completed_time_only_replaces_reached_finish_endpoint() -> None:
    points = straight_points(100)
    path = spatial.build_reference_path(
        timed_samples(points, [x * 0.098 for x in range(101)])
    )
    assert path is not None
    projected = spatial.project_lap(
        path,
        timed_samples(points, [x * 0.098 for x in range(101)]),
        completed_time_ms=10_000,
    )
    assert projected is not None
    trace = spatial.resample_projected(path, projected, 10.0)
    assert trace["time_ms"][5] == pytest.approx(4900.0)
    assert trace["time_ms"][-1] == pytest.approx(10_000.0)


def test_signed_motion_uses_dense_world_displacement_before_progress_clamp() -> None:
    path = spatial.build_reference_path(
        timed_samples(straight_points(100), [x / 10 for x in range(101)])
    )
    assert path is not None
    points = [*straight_points(50)]
    points += [(float(x), 0.0, 0.0) for x in range(49, 39, -1)]
    points += [(float(x), 0.0, 0.0) for x in range(41, 101)]
    projected = spatial.project_lap(
        path, timed_samples(points, [i / 10 for i in range(len(points))])
    )
    assert projected is not None
    speeds = projected.dense["along_track_speed_kmh"]
    assert max(speeds[5:40]) == pytest.approx(36.0, abs=0.1)
    assert min(speeds) == pytest.approx(-36.0, abs=0.1)
    assert projected.dense["progress"] == sorted(projected.dense["progress"])


def test_signed_motion_handles_stationary_lateral_xyz_and_xz_cases() -> None:
    straight_path = spatial.build_reference_path(
        timed_samples(straight_points(100), [x / 10 for x in range(101)])
    )
    assert straight_path is not None
    mixed_points = [*straight_points(50)]
    mixed_points += [(50.0, 0.0, float(z)) for z in range(1, 11)]
    mixed_points += [(50.0, 0.0, 10.0)] * 8
    mixed_points += [(float(x), 0.0, 10.0) for x in range(51, 101)]
    mixed = spatial.project_lap(
        straight_path,
        timed_samples(mixed_points, [i / 10 for i in range(len(mixed_points))]),
    )
    assert mixed is not None
    assert abs(mixed.dense["along_track_speed_kmh"][55]) < 0.1
    assert abs(mixed.dense["along_track_speed_kmh"][65]) < 0.1

    uphill_points = [(float(x), float(x), 0.0) for x in range(101)]
    uphill_path = spatial.build_reference_path(
        timed_samples(uphill_points, [x / 10 for x in range(101)])
    )
    assert uphill_path is not None
    uphill = spatial.project_lap(
        uphill_path,
        timed_samples(uphill_points, [x / 10 for x in range(101)]),
    )
    assert uphill is not None
    assert uphill.dense["along_track_speed_kmh"][50] == pytest.approx(50.9, abs=0.1)

    legacy_points = [(float(x), None, 0.0) for x in range(101)]
    legacy = spatial.project_lap(
        straight_path,
        timed_samples(legacy_points, [x / 10 for x in range(101)]),
    )
    assert legacy is not None
    assert legacy.dense["along_track_speed_kmh"][50] == pytest.approx(36.0, abs=0.1)
