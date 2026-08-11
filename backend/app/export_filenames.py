"""Deterministic, filesystem-safe names for telemetry downloads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from typing import Any, Literal

MAX_COMPONENT_LENGTH = 60
UNKNOWN_TIMESTAMP = "Unknown-Date-Time"


def safe_component(value: object, fallback: str) -> str:
    """Convert user/catalog text to one bounded ASCII filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "")).strip("-")
    cleaned = cleaned[:MAX_COMPONENT_LENGTH].rstrip("-")
    return cleaned or fallback


def filename_timestamp(
    primary: object,
    fallback: object = None,
    *,
    timezone: tzinfo | None = None,
) -> str:
    """Format the first valid timestamp in the app host's local timezone."""
    for value in (primary, fallback):
        if not isinstance(value, str) or not value:
            continue
        normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        localized = parsed.astimezone(timezone) if timezone is not None else parsed.astimezone()
        return localized.strftime("%Y-%m-%d_%H-%M-%S")
    return UNKNOWN_TIMESTAMP


def session_export_filename(
    session: Mapping[str, Any], lap_count: int, *, timezone: tzinfo | None = None
) -> str:
    """Filename for the whole-session LLM export."""
    timestamp = filename_timestamp(session.get("started_at"), timezone=timezone)
    car = safe_component(session.get("car_name"), "Unknown-Car")
    track = safe_component(session.get("track_name"), "Unknown-Track")
    return f"{session['id']}-{timestamp}-{car}-{track}-{lap_count}-Laps-llm.json"


def lap_export_filename(
    lap: Mapping[str, Any],
    session: Mapping[str, Any] | None,
    extension: Literal["json", "csv"],
    *,
    timezone: tzinfo | None = None,
) -> str:
    """Filename shared by raw JSON and MoTeC CSV lap exports."""
    if extension not in ("json", "csv"):
        raise ValueError("lap export extension must be json or csv")
    session = session or {}
    timestamp = filename_timestamp(
        lap.get("finished_at"), session.get("started_at"), timezone=timezone
    )
    car = safe_component(session.get("car_name"), "Unknown-Car")
    track = safe_component(session.get("track_name"), "Unknown-Track")
    session_id = lap.get("session_id", session.get("id"))
    return (
        f"{lap['id']}-Session-{session_id}-{timestamp}-{car}-{track}"
        f"-Lap-{lap['number']}.{extension}"
    )


def attachment_header(filename: str) -> str:
    """Content-Disposition value for an ASCII-safe generated filename."""
    return f'attachment; filename="{filename}"'
