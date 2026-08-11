"""Filesystem-safe metadata-rich export names."""

from datetime import timedelta, timezone
from typing import Any, cast

import pytest

from app.export_filenames import (
    MAX_COMPONENT_LENGTH,
    filename_timestamp,
    lap_export_filename,
    safe_component,
    session_export_filename,
)

HOST_TIMEZONE = timezone(timedelta(hours=-5))


def test_session_filename_uses_host_local_time_and_lap_count() -> None:
    session = {
        "id": 8,
        "started_at": "2026-08-10T19:32:05Z",
        "car_name": "Porsche 911 GT3",
        "track_name": "Laguna Seca",
    }
    assert session_export_filename(session, 5, timezone=HOST_TIMEZONE) == (
        "8-2026-08-10_14-32-05-Porsche-911-GT3-Laguna-Seca-5-Laps-llm.json"
    )


def test_lap_filename_uses_finish_then_session_timestamp_and_extension() -> None:
    session = {
        "id": 8,
        "started_at": "2026-08-10T19:32:05Z",
        "car_name": "Porsche 911 GT3",
        "track_name": "Laguna Seca",
    }
    lap = {
        "id": 42,
        "session_id": 8,
        "number": 4,
        "finished_at": "2026-08-10T19:38:12+00:00",
    }
    expected = "42-Session-8-2026-08-10_14-38-12-Porsche-911-GT3-Laguna-Seca-Lap-4"
    assert lap_export_filename(lap, session, "json", timezone=HOST_TIMEZONE) == (
        f"{expected}.json"
    )
    assert lap_export_filename(lap, session, "csv", timezone=HOST_TIMEZONE) == (
        f"{expected}.csv"
    )

    lap["finished_at"] = "not-a-date"
    assert "2026-08-10_14-32-05" in lap_export_filename(
        lap, session, "json", timezone=HOST_TIMEZONE
    )


def test_filename_components_are_ascii_bounded_and_have_explicit_fallbacks() -> None:
    assert safe_component("  Mazda RX-7 / Café?!  ", "Unknown-Car") == "Mazda-RX-7-Caf"
    assert len(safe_component("A" * 100, "fallback")) == MAX_COMPONENT_LENGTH
    assert safe_component("東京", "Unknown-Track") == "Unknown-Track"
    assert filename_timestamp("bad", None, timezone=HOST_TIMEZONE) == "Unknown-Date-Time"

    lap = {"id": 3, "session_id": 2, "number": 1, "finished_at": ""}
    assert lap_export_filename(lap, None, "json", timezone=HOST_TIMEZONE) == (
        "3-Session-2-Unknown-Date-Time-Unknown-Car-Unknown-Track-Lap-1.json"
    )


def test_lap_filename_rejects_unknown_extension() -> None:
    lap: dict[str, Any] = {"id": 1, "session_id": 1, "number": 1}
    with pytest.raises(ValueError):
        lap_export_filename(lap, None, cast(Any, "txt"), timezone=HOST_TIMEZONE)
