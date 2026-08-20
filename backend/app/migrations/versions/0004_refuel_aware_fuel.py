"""Repair pit-lap fuel consumption stored as a net tank change.

Revision ID: 0004_refuel_aware_fuel
Revises: 0003_fork_telemetry_metrics
Create Date: 2026-08-20
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0004_refuel_aware_fuel"
down_revision: str | None = "0003_fork_telemetry_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _consumed(start: float, raw_samples: str, end: float) -> float:
    try:
        decoded: Any = json.loads(raw_samples)
        values = decoded.get("fuel") if isinstance(decoded, dict) else None
    except (TypeError, ValueError):
        return 0.0
    if not isinstance(values, list):
        return 0.0
    finite: list[float] = []
    for level in (start, *values, end):
        try:
            value = float(level)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            finite.append(value)
    return math.fsum(
        max(previous - current, 0.0)
        for previous, current in zip(finite, finite[1:], strict=False)
    )


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id,fuel_start,fuel_end,fuel_consumed,samples_json "
            "FROM laps WHERE fuel_end > fuel_start AND fuel_consumed <= 0"
        )
    ).mappings()
    for row in rows:
        consumed = _consumed(
            float(row["fuel_start"]),
            str(row["samples_json"]),
            float(row["fuel_end"]),
        )
        if consumed > float(row["fuel_consumed"]):
            bind.execute(
                sa.text("UPDATE laps SET fuel_consumed=:consumed WHERE id=:lap_id"),
                {"consumed": consumed, "lap_id": int(row["id"])},
            )


def downgrade() -> None:
    # Restoring a known-wrong aggregate would destroy information.
    pass
