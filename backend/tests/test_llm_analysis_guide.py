"""Keep the canonical LLM parsing guide aligned with representative exports."""

from __future__ import annotations

import re
from typing import Any

from app.processing import llm_export
from app.processing.laps import SAMPLE_COLUMNS
from tests.llm_guide_contract import (
    GUIDE_PATH,
    GUIDE_PATHS,
    OPTIMIZED_GUIDE_PATH,
    assert_standard_document_matches_guide,
    documented_sample_channels,
    guide_text,
)


def _native_orientation_bundle() -> dict[str, Any]:
    sample_count = 31
    samples: dict[str, list[float]] = {
        "t": [],
        "dist": [],
        "speed": [],
        "throttle": [],
        "brake": [],
        "gear": [],
        "pos_x": [],
        "pos_y": [],
        "pos_z": [],
        "orientation_x": [],
        "orientation_y": [],
        "orientation_z": [],
        "orientation_w": [],
    }
    for index in range(sample_count):
        samples["t"].append(index * 0.5)
        samples["dist"].append(index * 10.0)
        samples["speed"].append(72.0)
        samples["throttle"].append(80.0)
        samples["brake"].append(0.0)
        samples["gear"].append(3.0)
        samples["pos_x"].append(index * 10.0)
        samples["pos_y"].append(0.0)
        samples["pos_z"].append(0.0)
        # Valid native quaternion; local -Z points along world +X.
        samples["orientation_x"].append(0.0)
        samples["orientation_y"].append(-(0.5**0.5))
        samples["orientation_z"].append(0.0)
        samples["orientation_w"].append(0.5**0.5)
    lap = {
        "id": 101,
        "session_id": 10,
        "number": 1,
        "time_ms": 15_000,
        "finished_at": "2026-08-11T12:00:15Z",
        "car_id": 7,
        "counts_for_best": True,
        "clean_lap": True,
        "off_track_count": 0,
        "event_counts": {},
        "events": [],
        "telemetry_meta": {"packet_format": "A"},
        "samples": samples,
    }
    return {
        "session": {
            "id": 10,
            "started_at": "2026-08-11T12:00:00Z",
            "car_id": 7,
            "car_name": "Guide Test Car",
            "track_name": "Guide Test Track",
            "note": "",
        },
        "laps": [lap],
    }


def test_documented_normalized_channels_equal_canonical_registry() -> None:
    for path in GUIDE_PATHS:
        text = guide_text(path)
        assert documented_sample_channels(text) == SAMPLE_COLUMNS
        for stale_name in (
            "filtered_throttle",
            "filtered_brake",
            "steering_fl",
            "steering_fr",
        ):
            assert stale_name not in text


def test_optimized_guide_preserves_canonical_field_names() -> None:
    field_pattern = r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"
    canonical_fields = set(re.findall(field_pattern, guide_text(GUIDE_PATH)))
    optimized_fields = set(re.findall(field_pattern, guide_text(OPTIMIZED_GUIDE_PATH)))
    assert canonical_fields <= optimized_fields


def test_current_native_orientation_standard_export_matches_guide() -> None:
    document = llm_export.build_export(
        _native_orientation_bundle(), detail="standard", segment_m=100.0
    )
    assert_standard_document_matches_guide(document)

    availability = dict(document["channel_availability"]["rows"])[101]
    assert {"orientation_x", "orientation_y", "orientation_z", "orientation_w"} <= set(
        availability
    )
    provenance = document["channel_provenance"]["rows"][0]
    assert {"orientation_x", "orientation_y", "orientation_z", "orientation_w"} <= set(
        provenance[1]
    )
    assert provenance[2] == []
    line_columns = document["line_traces"]["rows"][0][1]
    assert "chassis_heading_error_deg" in line_columns
    assert "body_slip_angle_deg" in line_columns
