"""Reference-dependent reverse-motion event detection."""

from __future__ import annotations

import pytest

from app.processing import events


def dense_motion(
    speeds: list[float], *, step_ms: float = 100.0
) -> dict[str, list[float]]:
    times = [index * step_ms for index in range(len(speeds))]
    distance = [0.0]
    progress = [50.0]
    for index in range(1, len(speeds)):
        dt_s = (times[index] - times[index - 1]) / 1000
        distance.append(
            distance[-1]
            + (abs(speeds[index - 1]) + abs(speeds[index])) * 0.5 / 3.6 * dt_s
        )
        progress.append(max(progress[-1], progress[-1] + speeds[index] / 3.6 * dt_s))
    return {
        "time_ms": times,
        "dist": distance,
        "progress": progress,
        "along_track_speed_kmh": speeds,
    }


def test_sustained_reverse_reports_time_peak_distance_and_null_severity() -> None:
    detected = events.detect_reverse_motion(dense_motion([-5.0] * 7))
    assert len(detected) == 1
    event = detected[0]
    assert event["type"] == "reverse_motion"
    assert event["severity"] is None
    assert event["wheels"] == []
    assert event["start_time_ms"] == 0
    assert event["end_time_ms"] == 600
    assert event["duration_ms"] == 600
    assert event["peak_along_track_speed_kmh"] == -5.0
    assert event["backward_distance_m"] == pytest.approx(0.833, abs=0.001)
    assert event["start_progress_m"] == event["end_progress_m"] == 50.0


def test_stationary_jitter_and_short_reverse_do_not_create_events() -> None:
    jitter = [-0.4, 0.2, -0.3, 0.1, -0.2, 0.0, -0.4, 0.2]
    assert events.detect_reverse_motion(dense_motion(jitter)) == []
    assert events.detect_reverse_motion(dense_motion([-5.0] * 5)) == []


def test_brief_near_zero_interruption_does_not_fragment_reversal() -> None:
    speeds = [-5.0] * 5 + [0.0] * 2 + [-6.0] * 5
    detected = events.detect_reverse_motion(dense_motion(speeds))
    assert len(detected) == 1
    event = detected[0]
    assert event["start_time_ms"] == 0
    assert event["end_time_ms"] == 1100
    assert event["duration_ms"] == 1100
    assert event["peak_along_track_speed_kmh"] == -6.0


def test_forward_motion_breaks_reversal_into_separate_events() -> None:
    speeds = [-5.0] * 7 + [2.0] + [-6.0] * 7
    detected = events.detect_reverse_motion(dense_motion(speeds))
    assert len(detected) == 2
    assert [event["peak_along_track_speed_kmh"] for event in detected] == [-5.0, -6.0]


def test_reverse_event_count_is_bounded() -> None:
    speeds: list[float] = []
    for _ in range(events.MAX_EVENTS_PER_TYPE + 2):
        speeds += [-5.0] * 7 + [2.0]
    detected = events.detect_reverse_motion(dense_motion(speeds))
    assert len(detected) == events.MAX_EVENTS_PER_TYPE
