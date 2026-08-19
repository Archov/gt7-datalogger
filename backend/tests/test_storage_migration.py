"""Backward-compatible SQLite schema migration coverage."""

import json
import sqlite3

from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository


async def test_old_lap_row_without_telemetry_metadata_is_readable(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, started_at VARCHAR NOT NULL, car_id INTEGER NOT NULL,
            car_name VARCHAR NOT NULL, note VARCHAR NOT NULL DEFAULT '',
            track_name VARCHAR NOT NULL DEFAULT ''
        );
        CREATE TABLE laps (
            id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, number INTEGER NOT NULL,
            time_ms INTEGER NOT NULL, finished_at VARCHAR NOT NULL, car_id INTEGER NOT NULL,
            fuel_start FLOAT NOT NULL, fuel_end FLOAT NOT NULL, fuel_consumed FLOAT NOT NULL,
            full_throttle_pct FLOAT NOT NULL, full_brake_pct FLOAT NOT NULL,
            coasting_pct FLOAT NOT NULL, tire_spin_pct FLOAT NOT NULL, max_speed FLOAT NOT NULL,
            min_body_height FLOAT NOT NULL, total_ticks INTEGER NOT NULL,
            tod_ms INTEGER NOT NULL DEFAULT -1, tcs_active_pct FLOAT NOT NULL DEFAULT 0,
            asm_active_pct FLOAT NOT NULL DEFAULT 0, max_water_temp FLOAT NOT NULL DEFAULT 0,
            max_oil_temp FLOAT NOT NULL DEFAULT 0, min_oil_pressure FLOAT NOT NULL DEFAULT -1,
            counts_for_best BOOLEAN NOT NULL DEFAULT 1,
            off_track_count INTEGER NOT NULL DEFAULT -1, clean_lap BOOLEAN,
            events_json TEXT NOT NULL DEFAULT '[]', gearing_json TEXT NOT NULL DEFAULT '',
            samples_json TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE INDEX ix_laps_session ON laps(session_id);
        """
    )
    samples = {
        "t": [0.0, 1.0],
        "dist": [0.0, 50.0],
        "speed": [180.0, 180.0],
        "throttle": [100.0, 100.0],
        "brake": [0.0, 0.0],
        "coast": [0.0, 0.0],
        "tire_slip": [1.0, 1.0],
        "body_height": [80.0, 80.0],
        "pos_x": [0.0, 50.0],
        "pos_z": [0.0, 0.0],
    }
    db.execute(
        "INSERT INTO sessions (id, started_at, car_id, car_name) VALUES (1, 'old', 7, 'Car')"
    )
    db.execute(
        """
        INSERT INTO laps (
            id, session_id, number, time_ms, finished_at, car_id, fuel_start, fuel_end,
            fuel_consumed, full_throttle_pct, full_brake_pct, coasting_pct, tire_spin_pct,
            max_speed, min_body_height, total_ticks, samples_json
        ) VALUES (1, 1, 1, 1000, 'old', 7, 10, 9, 1, 100, 0, 0, 0, 180, 80, 2, ?)
        """,
        (json.dumps(samples),),
    )
    db.commit()
    db.close()

    engine = make_engine(path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    lap = await repo.get_lap(1)
    assert lap is not None
    assert lap["telemetry_meta"] is None
    assert await repo.get_session_archive_metadata(1) is None
    assert await repo.get_session_hydration_metadata(1) is None
    await engine.dispose()
