"""The disposable Grafana mirror retains native values and atomic lap rows."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.metrics import MetricsDatabase


def sample_lap() -> dict[str, object]:
    return {
        "id": 11,
        "session_id": 7,
        "number": 2,
        "time_ms": 1000,
        "finished_at": "2026-01-01T00:00:01+00:00",
        "car_id": 42,
        "fuel_start": 10.0,
        "fuel_end": 9.0,
        "fuel_consumed": 1.0,
        "counts_for_best": True,
        "metrics_revision": 4,
        "samples": {"t": [0.0, 0.5], "speed": [100.0, 101.0], "dist": [0.0, 14.0]},
        "events": [
            {
                "type": "wheelspin",
                "start_dist": 1.0,
                "end_dist": 2.0,
                "severity": 0.4,
                "wheels": ["rl", "rr"],
            }
        ],
    }


async def test_metrics_database_keeps_native_unknowns_and_nulls(tmp_path: Path) -> None:
    path = tmp_path / "gt7-metrics.db"
    database = MetricsDatabase(path)
    await database.initialize()
    session = {
        "id": 7,
        "started_at": "2026-01-01T00:00:00+00:00",
        "car_id": 42,
        "car_name": "Test Car",
        "track_name": "Test Track",
        "note": "",
        "metrics_revision": 3,
    }
    native = {
        "packet_size": [368, 368],
        "packet_format": ["C", "C"],
        "received_unix_ns": [1_767_225_600_000_000_000, 1_767_225_600_500_000_000],
        "received_monotonic_ns": [10, 20],
        "receiver_order": [1, 2],
        "source": ["udp", "udp"],
        "unknown_0x154_f32": [7.25, -0.0],
        "speed_mps": [27.77777862548828, 28.05555534362793],
        "flags_raw": [0x8001, 0x0002],
    }
    await database.replace_lap(session, sample_lap(), native, "live_capture")

    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT native_unknown_0x154_f32,native_speed_mps,flag_bit_15,"
            "native_energy_recovery,speed FROM samples ORDER BY sample_index"
        ).fetchall()
        assert [row["native_unknown_0x154_f32"] for row in rows] == [7.25, 0.0]
        assert rows[0]["native_speed_mps"] == 27.77777862548828
        assert [row["flag_bit_15"] for row in rows] == [1, 0]
        assert rows[0]["native_energy_recovery"] is None
        assert [row["speed"] for row in rows] == [100.0, 101.0]
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT source FROM lap_channel_provenance "
                "WHERE lap_id=11 AND channel_name='native_unknown_0x154_f32'"
            ).fetchone()[0]
            == "live_capture"
        )

    # An upsert must replace one lap atomically without REPLACE cascading through its session.
    lap = sample_lap()
    lap["metrics_revision"] = 5
    await database.replace_lap(session, lap, native, "archive_replay")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM laps").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 2
        assert db.execute("SELECT mirror_revision FROM laps").fetchone()[0] == 5
