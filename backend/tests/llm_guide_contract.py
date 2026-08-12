"""Assertions shared by synthetic and fixture-gated LLM guide checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.processing.laps import SAMPLE_COLUMNS

GUIDE_PATH = Path(__file__).resolve().parents[2] / "LLM-Parsing-Guide.md"
OPTIMIZED_GUIDE_PATH = Path(__file__).resolve().parents[2] / "LLM-Parsing-Guide-Optimized.md"
GUIDE_PATHS = (GUIDE_PATH, OPTIMIZED_GUIDE_PATH)

STANDARD_KEYS = {
    "format",
    "version",
    "options",
    "schema",
    "session",
    "channel_availability",
    "channel_provenance",
    "reference",
    "laps",
    "whole_lap_chassis",
    "timing_segments",
    "reference_corners",
    "events",
    "recurring_events",
    "corner_line_analysis",
    "corner_analysis",
    "interesting_ranges",
    "detail_traces",
    "spatial_reference",
    "line_traces",
    "drivetrain_characterization",
    "wheelspin_characterization",
}


def guide_text(path: Path = GUIDE_PATH) -> str:
    return path.read_text(encoding="utf-8")


def documented_sample_channels(text: str) -> tuple[str, ...]:
    match = re.search(
        r"<!-- canonical-sample-channels:start -->\s*```text\s*(.*?)\s*```\s*"
        r"<!-- canonical-sample-channels:end -->",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return tuple(re.findall(r"[a-z][a-z0-9_]*", match.group(1)))


def assert_standard_document_matches_guide(document: dict[str, Any]) -> None:
    """Check a representative geometry-bearing Standard export against the guide."""
    assert set(document) == STANDARD_KEYS
    assert document["format"] == "gt7-datalogger-llm-session"
    assert document["version"] == 1
    assert document["options"]["detail"] == "standard"
    assert document["channel_provenance"]["columns"] == [
        "lap_id",
        "persisted",
        "archive_replay",
        "unavailable",
    ]

    canonical = set(SAMPLE_COLUMNS)
    for _lap_id, channels in document["channel_availability"]["rows"]:
        assert set(channels) <= canonical
    for _lap_id, persisted, archive_replay, unavailable in document["channel_provenance"]["rows"]:
        assert set(persisted) <= canonical
        assert set(archive_replay) <= canonical
        assert set(unavailable) <= canonical

    for path in GUIDE_PATHS:
        text = guide_text(path)
        for key in STANDARD_KEYS:
            assert re.search(rf"\b{re.escape(key)}\b", text)
        for _lap_id, columns, _rows in document["line_traces"]["rows"]:
            for column in columns:
                assert re.search(rf"\b{re.escape(column)}\b", text)

    # The guide promises strict finite JSON and the representative output must satisfy it.
    json.dumps(document, allow_nan=False)
