"""Pure compact session export analytics."""

import json
from typing import Any

import pytest

from app.processing import analysis, llm_export


def make_samples(speed_mps: float, total_m: float = 250.0, n: int = 51) -> dict[str, list[float]]:
    samples: dict[str, list[float]] = {
        key: []
        for key in (
            "t",
            "dist",
            "speed",
            "throttle",
            "brake",
            "gear",
            "rpm",
            "body_height",
            "yaw_rate",
            "yaw_rate_signed",
            "aids",
            "surface",
            "steer_fl_rad",
            "steer_fr_rad",
            "steering_wheel_rad",
            "steering_angular_velocity",
            "sway",
            "heave",
            "surge",
            "throttle_filtered",
            "brake_filtered",
            "slip_fl",
            "slip_fr",
            "slip_rl",
            "slip_rr",
            "sus_fl",
            "sus_fr",
            "sus_rl",
            "sus_rr",
            "tt_fl",
            "tt_fr",
            "tt_rl",
            "tt_rr",
            "pos_x",
            "pos_z",
        )
    }
    for i in range(n):
        distance = total_m * i / (n - 1)
        samples["t"].append(distance / speed_mps)
        samples["dist"].append(distance)
        samples["speed"].append(speed_mps * 3.6)
        samples["throttle"].append(80.0)
        samples["brake"].append(0.0)
        samples["gear"].append(4.0)
        samples["rpm"].append(6000.0)
        samples["body_height"].append(80.0)
        samples["yaw_rate"].append(0.1)
        samples["yaw_rate_signed"].append(-0.1)
        samples["aids"].append(1.0)
        samples["surface"].append(float(0x1111))
        samples["steer_fl_rad"].append(0.05)
        samples["steer_fr_rad"].append(0.04)
        samples["steering_wheel_rad"].append(0.2)
        samples["steering_angular_velocity"].append(0.3)
        samples["sway"].append(1.0)
        samples["heave"].append(0.2)
        samples["surge"].append(0.4)
        samples["throttle_filtered"].append(78.0)
        samples["brake_filtered"].append(0.0)
        for wheel in ("fl", "fr", "rl", "rr"):
            samples[f"slip_{wheel}"].append(1.02)
            samples[f"sus_{wheel}"].append(30.0 + i % 3)
            samples[f"tt_{wheel}"].append(75.0 + i % 2)
        samples["pos_x"].append(distance)
        samples["pos_z"].append(0.0)
    return samples


def make_lap(
    lap_id: int,
    speed_mps: float,
    *,
    clean: bool | None = True,
    full: bool = True,
    events: list[dict[str, object]] | None = None,
    total_m: float = 250.0,
    sample_count: int = 51,
    time_ms: int | None = None,
) -> dict[str, Any]:
    samples = make_samples(speed_mps, total_m=total_m, n=sample_count)
    return {
        "id": lap_id,
        "session_id": 1,
        "number": lap_id,
        "time_ms": time_ms if time_ms is not None else round(total_m / speed_mps * 1000),
        "finished_at": f"2026-01-01T00:00:0{lap_id}Z",
        "car_id": 7,
        "fuel_start": 50.0,
        "fuel_end": 48.0,
        "fuel_consumed": 2.0,
        "full_throttle_pct": 80.0,
        "full_brake_pct": 0.0,
        "coasting_pct": 0.0,
        "tire_spin_pct": 0.0,
        "max_speed": speed_mps * 3.6,
        "min_body_height": 80.0,
        "tcs_active_pct": 100.0,
        "asm_active_pct": 0.0,
        "counts_for_best": full,
        "off_track_count": 0 if clean is not None else -1,
        "clean_lap": clean,
        "event_counts": {},
        "events": events or [],
        "gearing": {"ratios": [3.0, 2.0], "top_speed": 280.0, "rpm_alert": 8000},
        "telemetry_meta": {
            "packet_format": "C",
            "wheelbase_m": 2.7,
            "car_category": "GR3",
            "fuel_capacity": 80.0,
        },
        "samples": samples,
    }


def bundle(laps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "session": {
            "id": 1,
            "started_at": "2026-01-01T00:00:00Z",
            "car_id": 7,
            "car_name": "Test Car",
            "track_name": "Test Track",
            "note": "",
        },
        "laps": laps,
    }


def range_candidate(
    start: float,
    end: float,
    reason: str,
    *,
    lap_id: int = 1,
    priority: int = 1,
    corner: int | None = None,
    corner_source: str | None = None,
) -> dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "reasons": [reason],
        "lap_ids": [lap_id],
        "priority": priority,
        "corner": corner,
        "corner_source": corner_source,
    }


def test_reference_selection_precedence_and_validation() -> None:
    dirty_fast = make_lap(1, 60.0, clean=False)
    unknown = make_lap(2, 55.0, clean=None)
    clean = make_lap(3, 50.0, clean=True)
    partial = make_lap(4, 80.0, full=False)
    selected, reason = llm_export.select_reference([dirty_fast, unknown, clean, partial])
    assert selected["id"] == 3
    assert reason == "fastest_clean_full_lap"
    selected, reason = llm_export.select_reference([dirty_fast, unknown])
    assert selected["id"] == 2
    assert reason == "fastest_full_lap_cleanliness_unknown"
    assert llm_export.select_reference([dirty_fast], explicit_ref=1)[1] == "explicit"
    with pytest.raises(llm_export.ExportInputError):
        llm_export.select_reference([partial], explicit_ref=4)
    with pytest.raises(llm_export.ReferenceNotFoundError):
        llm_export.select_reference([clean], explicit_ref=99)


def test_fixed_segments_and_partial_final_segment() -> None:
    reference = make_lap(1, 50.0)
    slower = make_lap(2, 40.0)
    result = llm_export.build_export(bundle([reference, slower]), detail="compact")
    timing = result["timing_segments"]
    columns = timing["columns"]
    rows = [dict(zip(columns, row, strict=True)) for row in timing["rows"]]
    slow_rows = [row for row in rows if row["lap_id"] == 2]
    assert [(row["start_m"], row["end_m"]) for row in slow_rows] == [
        (0.0, 100.0),
        (100.0, 200.0),
        (200.0, 250.0),
    ]
    assert [row["segment_delta_vs_reference_ms"] for row in slow_rows] == [500, 500, 250]
    assert slow_rows[-1]["cumulative_delta_vs_reference_ms"] == 1250


def test_corner_rows_use_reference_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    corner = {
        "n": 7,
        "direction": "R",
        "entry_dist": 50.0,
        "apex_dist": 100.0,
        "exit_dist": 150.0,
        "angle_deg": 60.0,
        "min_speed": 120.0,
    }
    monkeypatch.setattr(analysis, "detect_corners", lambda _samples: [corner])
    result = llm_export.build_export(bundle([make_lap(1, 50.0), make_lap(2, 45.0)]))
    definitions = result["reference_corners"]
    assert definitions["rows"][0][definitions["columns"].index("corner")] == 7
    analysis_rows = result["corner_analysis"]
    assert {row[analysis_rows["columns"].index("corner")] for row in analysis_rows["rows"]} == {7}


def test_recurring_events_merge_ranges_and_detail_modes() -> None:
    event = {
        "type": "bottoming",
        "start_dist": 100.0,
        "end_dist": 105.0,
        "wheels": ["fl"],
        "severity": 0.99,
    }
    laps = [make_lap(i, 50.0 - i, events=[event]) for i in range(1, 4)]
    compact = llm_export.build_export(bundle(laps), detail="compact")
    assert "detail_traces" not in compact
    assert len(compact["recurring_events"]["rows"]) == 1

    standard = llm_export.build_export(bundle(laps), detail="standard")
    assert len(standard["interesting_ranges"]["rows"]) == 1
    assert standard["detail_traces"]["rows"]
    assert "source_traces" not in standard

    deep = llm_export.build_export(bundle(laps), detail="deep")
    assert deep["source_traces"]["rows"]
    for _range_id, lap_id, _columns, rows in deep["source_traces"]["rows"]:
        source_n = len(next(lap for lap in laps if lap["id"] == lap_id)["samples"]["t"])
        assert len(rows) < source_n


def test_output_is_deterministic_strict_and_partial_delta_is_null() -> None:
    reference = make_lap(1, 50.0)
    partial = make_lap(2, 80.0, full=False)
    first = llm_export.build_export(bundle([partial, reference]), detail="compact")
    second = llm_export.build_export(bundle([partial, reference]), detail="compact")
    assert first == second
    json.dumps(first, allow_nan=False, separators=(",", ":"))
    laps = first["laps"]
    rows = [dict(zip(laps["columns"], row, strict=True)) for row in laps["rows"]]
    assert next(row for row in rows if row["lap_id"] == 2)["delta_to_reference_ms"] is None


def test_standard_trace_channels_are_reason_aware() -> None:
    samples = make_samples(50.0)
    n = len(samples["t"])
    for wheel in ("fl", "fr", "rl", "rr"):
        samples[f"torque_{wheel}"] = [100.0] * n
    samples["road_plane_distance"] = [1.0] * n

    bottoming = llm_export._standard_trace_columns(samples, ["bottoming"])
    assert {"speed", "throttle", "brake", "gear"} <= set(bottoming)
    assert {"body_height", "sus_fl", "sus_fr", "sus_rl", "sus_rr", "heave"} <= set(
        bottoming
    )
    assert "road_plane_distance" in bottoming
    assert not {"torque_fl", "tt_fl", "steer_fl_rad"} & set(bottoming)

    steering = llm_export._standard_trace_columns(samples, ["front-steering-anomaly"])
    assert {
        "steer_fl_rad",
        "steer_fr_rad",
        "steering_wheel_rad",
        "steering_angular_velocity",
        "yaw_rate_signed",
        "sway",
    } <= set(steering)
    assert "torque_fl" not in steering

    reasons = ["recurring-bottoming", "wheelspin", "segment_loss_250ms"]
    first = llm_export._standard_trace_columns(samples, reasons)
    second = llm_export._standard_trace_columns(samples, list(reversed(reasons)))
    assert first == second
    assert {"body_height", "throttle_filtered", "torque_fl", "yaw_rate_signed", "aids"} <= set(
        first
    )
    assert first == [column for column in llm_export.TRACE_CHANNELS if column in first]

    samples.pop("heave")
    assert "heave" not in llm_export._standard_trace_columns(samples, ["bottoming"])


def test_deep_trace_retains_full_available_channel_set() -> None:
    samples = make_samples(50.0)
    n = len(samples["t"])
    samples["torque_fl"] = [100.0] * n
    standard_columns, _ = llm_export._distance_trace(
        samples, 75.0, 125.0, ["bottoming"]
    )
    deep_columns, deep_rows = llm_export._source_trace(samples, 75.0, 125.0)
    assert "torque_fl" not in standard_columns
    assert "tt_fl" not in standard_columns
    assert "torque_fl" in deep_columns
    assert "tt_fl" in deep_columns
    assert "steer_fl_rad" in deep_columns
    assert deep_rows


def test_bottoming_only_export_uses_sparse_standard_but_rich_deep_trace() -> None:
    event = {
        "type": "bottoming",
        "start_dist": 100.0,
        "end_dist": 105.0,
        "wheels": ["fl"],
        "severity": 0.99,
    }
    lap = make_lap(1, 50.0, events=[event])
    samples = lap["samples"]
    for wheel in ("fl", "fr", "rl", "rr"):
        samples[f"torque_{wheel}"] = [100.0] * len(samples["t"])

    standard = llm_export.build_export(bundle([lap]), detail="standard")
    standard_columns = standard["detail_traces"]["rows"][0][2]
    assert "body_height" in standard_columns
    assert not {"torque_fl", "tt_fl", "steer_fl_rad"} & set(standard_columns)

    deep = llm_export.build_export(bundle([lap]), detail="deep")
    deep_columns = deep["source_traces"]["rows"][0][2]
    assert {"torque_fl", "tt_fl", "steer_fl_rad"} <= set(deep_columns)


def test_range_finalization_merges_splits_caps_and_is_deterministic() -> None:
    within_limit = [
        range_candidate(100.0, 180.0, "first"),
        range_candidate(200.0, 250.0, "second"),
    ]
    merged = llm_export._finalize_ranges(within_limit, 1000.0, [])
    assert len(merged) == 1
    assert merged[0]["reasons"] == ["first", "second"]

    over_limit = [
        range_candidate(100.0, 350.0, "first"),
        range_candidate(340.0, 500.0, "second"),
    ]
    first = llm_export._finalize_ranges(over_limit, 1000.0, [])
    second = llm_export._finalize_ranges(list(reversed(over_limit)), 1000.0, [])
    assert first == second
    assert len(first) == 2
    assert all(float(item["end"]) - float(item["start"]) <= 300.0 for item in first)
    by_distance = sorted(first, key=lambda item: float(item["start"]))
    assert float(by_distance[0]["end"]) <= float(by_distance[1]["start"])

    exact_gap = [
        range_candidate(100.0, 150.0, "left"),
        range_candidate(225.0, 250.0, "right"),
    ]
    assert len(llm_export._finalize_ranges(exact_gap, 1000.0, [])) == 1

    disconnected = [
        range_candidate(float(index * 100 + 50), float(index * 100 + 55), str(index))
        for index in range(13)
    ]
    capped = llm_export._finalize_ranges(disconnected, 1400.0, [])
    assert len(capped) == 12
    ordered = sorted(capped, key=lambda item: float(item["start"]))
    assert all(
        float(left["end"]) <= float(right["start"])
        for left, right in zip(ordered, ordered[1:], strict=False)
    )


def test_split_range_traces_do_not_duplicate_seam_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranges = llm_export._finalize_ranges(
        [
            range_candidate(100.0, 350.0, "bottoming"),
            range_candidate(340.0, 500.0, "bottoming"),
        ],
        600.0,
        [],
    )
    lap = make_lap(1, 50.0, total_m=600.0, sample_count=121)
    standard = llm_export._standard_traces(ranges, [lap], 1)
    standard_distances = [
        row[0]
        for _range_id, _lap_id, _columns, rows in standard["rows"]
        for row in rows
    ]
    assert len(standard_distances) == len(set(standard_distances))

    monkeypatch.setattr(llm_export, "MAX_DEEP_LAP_FRACTION", 1.0)
    deep = llm_export._deep_traces(ranges, [lap], 1)
    deep_distances = [row[0] for _range_id, _lap_id, _columns, rows in deep["rows"] for row in rows]
    assert len(deep_distances) == len(set(deep_distances))


def test_range_corner_evidence_survives_merge_and_split() -> None:
    corners = [
        {
            "n": 8,
            "entry_dist": 2650.0,
            "apex_dist": 2680.0,
            "exit_dist": 2720.0,
        },
        {
            "n": 9,
            "entry_dist": 2800.0,
            "apex_dist": 2830.0,
            "exit_dist": 2880.0,
        },
    ]
    candidates = [
        range_candidate(
            2681.0,
            2681.0,
            "recurring_bottoming",
            priority=3,
            corner=8,
            corner_source="recurring",
        ),
        range_candidate(2500.0, 2900.0, "suspension_anomaly"),
        range_candidate(
            2690.0,
            2700.0,
            "bottoming",
            priority=2,
            corner=9,
            corner_source="event",
        ),
    ]
    ranges = llm_export._finalize_ranges(candidates, 3500.0, corners)
    recurring_range = next(item for item in ranges if "recurring_bottoming" in item["reasons"])
    assert recurring_range["corner"] == 8

    event_and_anomaly = [
        range_candidate(
            2660.0,
            2670.0,
            "bottoming",
            priority=2,
            corner=8,
            corner_source="event",
        ),
        range_candidate(2670.0, 2690.0, "body_height_anomaly"),
    ]
    assert llm_export._finalize_ranges(event_and_anomaly, 3500.0, corners)[0]["corner"] == 8

    crossing = llm_export._finalize_ranges(
        [range_candidate(2640.0, 2860.0, "unknown")], 3500.0, corners
    )
    assert crossing[0]["corner"] == 9
    no_corner = llm_export._finalize_ranges(
        [range_candidate(1000.0, 1050.0, "unknown")], 3500.0, corners
    )
    assert no_corner[0]["corner"] is None


def test_finish_segment_reconciles_shorter_and_longer_full_laps() -> None:
    reference = make_lap(
        1, 40.0, total_m=3553.5, sample_count=712, time_ms=90_000
    )
    shorter = make_lap(2, 40.0, total_m=3548.0, sample_count=711, time_ms=90_395)
    longer = make_lap(3, 40.0, total_m=3560.0, sample_count=713, time_ms=90_330)
    partial = make_lap(
        4, 40.0, full=False, total_m=3548.0, sample_count=711, time_ms=89_000
    )
    result = llm_export.build_export(
        bundle([reference, shorter, longer, partial]), detail="compact", segment_m=100.0
    )
    timing = result["timing_segments"]
    rows = [dict(zip(timing["columns"], row, strict=True)) for row in timing["rows"]]

    assert not [row for row in rows if row["lap_id"] == 4]
    for lap_id, expected_delta in ((1, 0), (2, 395), (3, 330)):
        lap_rows = [row for row in rows if row["lap_id"] == lap_id]
        final = lap_rows[-1]
        assert (final["start_m"], final["end_m"]) == (3500.0, 3553.5)
        assert final["cumulative_delta_vs_reference_ms"] == expected_delta
        segment_sum = sum(row["segment_delta_vs_reference_ms"] for row in lap_rows)
        assert segment_sum == pytest.approx(expected_delta, abs=len(lap_rows))
