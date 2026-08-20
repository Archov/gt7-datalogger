"""Fixture-gated Session 20 characterization and performance acceptance."""

from __future__ import annotations

import gc
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from app.processing.llm_export import build_export
from app.storage.db import make_engine, make_session_factory
from app.storage.repository import Repository

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATABASE = BACKEND_ROOT / "data" / "gt7.db"


def _has_session_20() -> bool:
    if not DATABASE.is_file():
        return False
    with sqlite3.connect(DATABASE) as connection:
        return connection.execute("SELECT 1 FROM sessions WHERE id = 20").fetchone() is not None


@pytest.mark.skipif(not _has_session_20(), reason="local historical session-20 fixture is absent")
async def test_session_20_standard_characterization_acceptance() -> None:
    engine = make_engine(DATABASE)
    bundle = await Repository(make_session_factory(engine)).get_session_analysis_data(20)
    assert bundle is not None

    started = time.perf_counter()
    first = build_export(bundle, detail="standard", segment_m=100.0)
    first_seconds = time.perf_counter() - started
    first_bytes = json.dumps(first, separators=(",", ":"), allow_nan=False).encode()
    del first
    gc.collect()
    started = time.perf_counter()
    second = build_export(bundle, detail="standard", segment_m=100.0)
    second_seconds = time.perf_counter() - started
    await engine.dispose()

    second_bytes = json.dumps(second, separators=(",", ":"), allow_nan=False).encode()
    assert first_bytes == second_bytes
    assert max(first_seconds, second_seconds) <= 15.0

    table: dict[str, Any] = second["wheelspin_characterization"]
    assert len(table["rows"]) == 152
    assert len(json.dumps(table, separators=(",", ":")).encode()) <= 250_000

    outer = table["columns"]
    quality_columns = table["comparator_quality_columns"]
    quality_index = outer.index("comparator_quality")
    comparator_index = outer.index("comparators")
    observed_index = outer.index("observed")
    lap_index = outer.index("lap_id")
    qualities = [
        dict(zip(quality_columns, row[quality_index], strict=True)) for row in table["rows"]
    ]
    assert any(item["quality"] in {"moderate", "strong"} for item in qualities)
    assert any(
        comparator[1] == "relative"
        for row in table["rows"]
        for comparator in row[comparator_index]
    )

    observed_columns = table["observed_columns"]
    travel_index = observed_columns.index("travel_heading_deg_at_onset")
    body_index = observed_columns.index("body_slip_angle_deg_at_onset")
    for lap_id in (80, 84, 86, 92):
        rows = [row for row in table["rows"] if row[lap_index] == lap_id]
        assert rows
        assert any(
            row[observed_index][travel_index] is not None
            and row[observed_index][body_index] is not None
            for row in rows
        )

    assert any(row[lap_index] == 89 for row in table["rows"])
