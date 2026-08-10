"""Pure compact session export analytics."""

import json

import pytest

from app.processing import llm_export


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
) -> dict[str, object]:
    samples = make_samples(speed_mps)
    return {
        "id": lap_id,
        "session_id": 1,
        "number": lap_id,
        "time_ms": round(250 / speed_mps * 1000),
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


def bundle(laps: list[dict[str, object]]) -> dict[str, object]:
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
    monkeypatch.setattr(llm_export.analysis, "detect_corners", lambda _samples: [corner])
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
