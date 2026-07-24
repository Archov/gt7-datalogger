"""In-memory ring buffer of recent log records, served by the admin API."""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

_BUFFER: deque[dict[str, Any]] = deque(maxlen=2000)


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging raise
            message = str(record.msg)
        _BUFFER.append(
            {
                "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
        )


def install() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, RingBufferHandler) for h in root.handlers):
        root.addHandler(RingBufferHandler())


def records(limit: int = 500, level: str | None = None) -> list[dict[str, Any]]:
    """Most recent records, oldest first. `level` filters to that severity and above."""
    items: list[dict[str, Any]] = list(_BUFFER)
    if level:
        threshold = logging.getLevelNamesMapping().get(level.upper(), 0)
        items = [r for r in items if logging.getLevelNamesMapping().get(r["level"], 0) >= threshold]
    return items[-limit:]


def clear() -> None:
    _BUFFER.clear()
