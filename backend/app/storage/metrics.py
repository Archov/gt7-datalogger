"""Disposable, Grafana-oriented mirror of comprehensive completed-lap telemetry."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.processing.laps import (
    CAPTURE_SAMPLE_COLUMNS,
    NATIVE_SAMPLE_COLUMNS,
    SAMPLE_COLUMNS,
    CompletedLap,
    LapProcessor,
    SessionInfo,
)
from app.processing.telemetry_hydration import archive_fingerprint
from app.storage.repository import Repository
from app.telemetry.diagnostics import decoder_diagnostics
from app.telemetry.packet_catalog import FORMAT_SIZES, catalog_rows
from app.telemetry.raw_archive import ArchiveError, replay_archive

log = logging.getLogger(__name__)

METRICS_SCHEMA_VERSION = 1
DECODER_SCHEMA_VERSION = 1
SQLITE_BATCH_ROWS = 250

_SAMPLE_META: tuple[tuple[str, str], ...] = (
    ("session_id", "INTEGER NOT NULL"),
    ("lap_id", "INTEGER NOT NULL"),
    ("sample_index", "INTEGER NOT NULL"),
    ("sample_time_unix_s", "REAL"),
    ("packet_size", "INTEGER"),
    ("packet_format", "TEXT"),
    ("received_unix_ns", "INTEGER"),
    ("received_monotonic_ns", "INTEGER"),
    ("receiver_order", "INTEGER"),
    ("source", "TEXT"),
    ("decoder_schema_version", "INTEGER NOT NULL"),
    ("row_provenance", "TEXT NOT NULL"),
)
_DERIVED_COLUMNS = tuple(dict.fromkeys(SAMPLE_COLUMNS))
_NATIVE_COLUMNS = tuple(f"native_{name}" for name in NATIVE_SAMPLE_COLUMNS)
_FLAG_COLUMNS = tuple(f"flag_bit_{bit}" for bit in range(16))
SAMPLE_DB_COLUMNS = (
    tuple(name for name, _ in _SAMPLE_META) + _DERIVED_COLUMNS + _NATIVE_COLUMNS + _FLAG_COLUMNS
)
_LAP_DB_COLUMNS = (
    "id",
    "session_id",
    "number",
    "time_ms",
    "finished_at",
    "finished_at_unix_s",
    "car_id",
    "fuel_start",
    "fuel_end",
    "fuel_consumed",
    "full_throttle_pct",
    "full_brake_pct",
    "coasting_pct",
    "tire_spin_pct",
    "max_speed",
    "min_body_height",
    "total_ticks",
    "tod_ms",
    "tcs_active_pct",
    "asm_active_pct",
    "max_water_temp",
    "max_oil_temp",
    "min_oil_pressure",
    "counts_for_best",
    "off_track_count",
    "clean_lap",
    "packet_format",
    "wheelbase_m",
    "car_category",
    "fuel_capacity",
    "transmission_top_speed",
    "rpm_alert",
    "gear_ratio_1",
    "gear_ratio_2",
    "gear_ratio_3",
    "gear_ratio_4",
    "gear_ratio_5",
    "gear_ratio_6",
    "gear_ratio_7",
    "gear_ratio_8",
    "native_provenance",
    "mirror_revision",
)


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _chunks(values: list[tuple[Any, ...]], size: int) -> Iterable[list[tuple[Any, ...]]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _finite(value: object) -> float | int | str | None:
    if value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _unix_seconds(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class MetricsDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=DELETE")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA busy_timeout=5000")
            await self._ensure_schema(db)
            await db.commit()

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = await (
            await db.execute("SELECT value FROM schema_metadata WHERE key='metrics_schema_version'")
        ).fetchone()
        if row is not None and int(row[0]) != METRICS_SCHEMA_VERSION:
            for table in (
                "samples",
                "events",
                "lap_channel_provenance",
                "laps",
                "sessions",
                "channel_catalog",
                "decoder_status",
                "mirror_status",
            ):
                await db.execute(f"DROP TABLE IF EXISTS {_q(table)}")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                started_at_unix_s REAL,
                car_id INTEGER NOT NULL,
                car_name TEXT NOT NULL,
                track_name TEXT NOT NULL,
                note TEXT NOT NULL,
                archive_fingerprint TEXT,
                parser_version INTEGER NOT NULL,
                mirror_revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS laps (
                id INTEGER PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                number INTEGER NOT NULL,
                time_ms INTEGER NOT NULL,
                finished_at TEXT NOT NULL,
                finished_at_unix_s REAL,
                car_id INTEGER NOT NULL,
                fuel_start REAL, fuel_end REAL, fuel_consumed REAL,
                full_throttle_pct REAL, full_brake_pct REAL, coasting_pct REAL,
                tire_spin_pct REAL, max_speed REAL, min_body_height REAL,
                total_ticks INTEGER, tod_ms INTEGER,
                tcs_active_pct REAL, asm_active_pct REAL,
                max_water_temp REAL, max_oil_temp REAL, min_oil_pressure REAL,
                counts_for_best INTEGER, off_track_count INTEGER, clean_lap INTEGER,
                packet_format TEXT, wheelbase_m REAL, car_category TEXT,
                fuel_capacity REAL, transmission_top_speed REAL, rpm_alert REAL,
                gear_ratio_1 REAL, gear_ratio_2 REAL, gear_ratio_3 REAL,
                gear_ratio_4 REAL, gear_ratio_5 REAL, gear_ratio_6 REAL,
                gear_ratio_7 REAL, gear_ratio_8 REAL,
                native_provenance TEXT NOT NULL,
                mirror_revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS ix_metrics_laps_session
                ON laps(session_id, number);
            CREATE TABLE IF NOT EXISTS events (
                lap_id INTEGER NOT NULL REFERENCES laps(id) ON DELETE CASCADE,
                event_index INTEGER NOT NULL,
                type TEXT NOT NULL,
                start_dist REAL, end_dist REAL, severity REAL,
                wheel_fl INTEGER NOT NULL, wheel_fr INTEGER NOT NULL,
                wheel_rl INTEGER NOT NULL, wheel_rr INTEGER NOT NULL,
                PRIMARY KEY(lap_id, event_index)
            );
            CREATE TABLE IF NOT EXISTS channel_catalog (
                name TEXT PRIMARY KEY,
                layer TEXT NOT NULL,
                source_offset INTEGER,
                storage_type TEXT NOT NULL,
                introduced_format TEXT,
                unit TEXT NOT NULL,
                confidence TEXT NOT NULL,
                classification TEXT NOT NULL,
                formula TEXT NOT NULL,
                description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lap_channel_provenance (
                lap_id INTEGER NOT NULL REFERENCES laps(id) ON DELETE CASCADE,
                channel_name TEXT NOT NULL REFERENCES channel_catalog(name),
                source TEXT NOT NULL,
                available INTEGER NOT NULL,
                diagnostic TEXT,
                PRIMARY KEY(lap_id, channel_name)
            );
            CREATE TABLE IF NOT EXISTS decoder_status (
                id INTEGER PRIMARY KEY CHECK(id=1),
                decoder_schema_version INTEGER NOT NULL,
                supported_sizes TEXT NOT NULL,
                byte_coverage_complete INTEGER NOT NULL,
                decode_errors INTEGER NOT NULL DEFAULT 0,
                unsupported_lengths INTEGER NOT NULL DEFAULT 0,
                latest_diagnostic TEXT
            );
            CREATE TABLE IF NOT EXISTS mirror_status (
                id INTEGER PRIMARY KEY CHECK(id=1),
                state TEXT NOT NULL,
                total_sessions INTEGER NOT NULL DEFAULT 0,
                processed_sessions INTEGER NOT NULL DEFAULT 0,
                pending_records INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                latest_error TEXT
            );
            """
        )
        column_sql = [f"{_q(name)} {ddl}" for name, ddl in _SAMPLE_META]
        column_sql.extend(f"{_q(name)} REAL" for name in _DERIVED_COLUMNS)
        native_types = {
            f"native_{row['name']}": (
                "TEXT"
                if row["scalar_type"] == "char"
                else "INTEGER"
                if row["scalar_type"] in {"u8", "i16", "u16", "i32", "u32"}
                else "REAL"
            )
            for row in catalog_rows()
            if row["name"] != "magic"
        }
        column_sql.extend(f"{_q(name)} {native_types[name]}" for name in _NATIVE_COLUMNS)
        column_sql.extend(f"{_q(name)} INTEGER" for name in _FLAG_COLUMNS)
        column_sql.append("PRIMARY KEY(lap_id, sample_index)")
        column_sql.append("FOREIGN KEY(lap_id) REFERENCES laps(id) ON DELETE CASCADE")
        await db.execute("CREATE TABLE IF NOT EXISTS samples (" + ",".join(column_sql) + ")")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS ix_metrics_samples_session "
            "ON samples(session_id, lap_id, sample_index)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS ix_metrics_samples_time ON samples(sample_time_unix_s)"
        )
        await db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key,value) VALUES(?,?)",
            ("metrics_schema_version", str(METRICS_SCHEMA_VERSION)),
        )
        await db.execute(
            "INSERT INTO decoder_status"
            "(id,decoder_schema_version,supported_sizes,byte_coverage_complete) VALUES(1,?,?,1)"
            " ON CONFLICT(id) DO UPDATE SET decoder_schema_version=excluded.decoder_schema_version,"
            "supported_sizes=excluded.supported_sizes,"
            "byte_coverage_complete=excluded.byte_coverage_complete",
            (DECODER_SCHEMA_VERSION, json.dumps(FORMAT_SIZES, separators=(",", ":"))),
        )
        await db.execute("INSERT OR IGNORE INTO mirror_status(id,state) VALUES(1,'idle')")
        await self._populate_catalog(db)

    async def _populate_catalog(self, db: aiosqlite.Connection) -> None:
        rows: list[tuple[Any, ...]] = []
        for row in catalog_rows():
            if row["name"] == "magic":
                continue
            name = f"native_{row['name']}"
            storage = (
                "text"
                if row["scalar_type"] == "char"
                else "integer"
                if row["scalar_type"] in {"u8", "i16", "u16", "i32", "u32"}
                else "real"
            )
            rows.append(
                (
                    name,
                    "native",
                    row["offset"],
                    storage,
                    row["introduced"],
                    row["unit"],
                    row["confidence"],
                    row["classification"],
                    "",
                    row["interpretation"],
                )
            )
        for name in _DERIVED_COLUMNS:
            rows.append(
                (
                    name,
                    "derived",
                    None,
                    "real",
                    None,
                    "see documentation",
                    "verified",
                    "derived",
                    "capture-time transform",
                    "Compatibility SAMPLE_COLUMNS channel",
                )
            )
        for name in _FLAG_COLUMNS:
            rows.append(
                (
                    name,
                    "derived",
                    0x08E,
                    "integer",
                    "A",
                    "boolean",
                    "verified" if int(name.rsplit("_", 1)[1]) < 12 else "unknown",
                    "derived",
                    "(flags_raw >> bit) & 1",
                    "Decoded native flag bit",
                )
            )
        await db.executemany(
            "INSERT OR REPLACE INTO channel_catalog"
            "(name,layer,source_offset,storage_type,introduced_format,unit,confidence,classification,formula,description)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            rows,
        )

    async def set_status(
        self,
        state: str,
        *,
        total: int | None = None,
        processed: int | None = None,
        pending: int | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, object] = {"state": state, "latest_error": error}
        if total is not None:
            values["total_sessions"] = total
        if processed is not None:
            values["processed_sessions"] = processed
        if pending is not None:
            values["pending_records"] = pending
        if state == "idle" and error is None:
            values["last_success_at"] = datetime.now().astimezone().isoformat()
        assignments = ",".join(f"{_q(key)}=?" for key in values)
        async with aiosqlite.connect(self.path) as db:
            await self._update_decoder_status(db)
            await db.execute(
                f"UPDATE mirror_status SET {assignments} WHERE id=1", tuple(values.values())
            )
            await db.commit()

    async def reconciliation_manifest(
        self,
    ) -> tuple[
        dict[int, tuple[int, int, str | None]],
        dict[int, tuple[int, int]],
    ]:
        """Return mirror identities without touching the wide samples table."""
        async with aiosqlite.connect(self.path) as db:
            session_rows = await (
                await db.execute(
                    "SELECT id,mirror_revision,parser_version,archive_fingerprint FROM sessions"
                )
            ).fetchall()
            lap_rows = await (
                await db.execute("SELECT id,session_id,mirror_revision FROM laps")
            ).fetchall()
        sessions = {
            int(row[0]): (int(row[1]), int(row[2]), row[3]) for row in session_rows
        }
        laps = {int(row[0]): (int(row[1]), int(row[2])) for row in lap_rows}
        return sessions, laps

    @staticmethod
    async def _update_decoder_status(db: aiosqlite.Connection) -> None:
        diagnostics = decoder_diagnostics()
        await db.execute(
            "UPDATE decoder_status SET decode_errors=?,unsupported_lengths=?,"
            "latest_diagnostic=? WHERE id=1",
            (
                diagnostics.decode_errors,
                diagnostics.unsupported_lengths,
                diagnostics.latest_diagnostic,
            ),
        )

    async def replace_lap(
        self,
        session: dict[str, Any],
        lap: dict[str, Any],
        native_samples: dict[str, list[float | int | str | None]] | None,
        provenance: str,
        archive_fingerprint: str | None = None,
    ) -> None:
        samples_value = lap.get("samples")
        samples: dict[str, Any] = samples_value if isinstance(samples_value, dict) else {}
        times_value = samples.get("t")
        times: list[Any] = times_value if isinstance(times_value, list) else []
        n = len(times)
        native = native_samples or {}
        meta_value = lap.get("telemetry_meta")
        meta: dict[str, Any] = meta_value if isinstance(meta_value, dict) else {}
        gearing_value = lap.get("gearing")
        gearing: dict[str, Any] = gearing_value if isinstance(gearing_value, dict) else {}
        ratios = list(gearing.get("ratios") or [])[:8]
        ratios.extend([None] * (8 - len(ratios)))
        finish_unix = _unix_seconds(lap.get("finished_at"))
        start_unix = (
            finish_unix - float(lap.get("time_ms") or 0) / 1000 if finish_unix is not None else None
        )
        rows: list[tuple[Any, ...]] = []
        for index in range(n):
            elapsed = _finite(times[index])
            receive_values = native.get("received_unix_ns") or []
            receive_ns = receive_values[index] if len(receive_values) == n else None
            sample_time: float | None
            if isinstance(receive_ns, (int, float)) and math.isfinite(float(receive_ns)):
                sample_time = float(receive_ns) / 1e9
            else:
                sample_time = (
                    start_unix + float(elapsed)
                    if start_unix is not None and isinstance(elapsed, (int, float))
                    else None
                )
            capture = [
                session["id"],
                lap["id"],
                index,
                sample_time,
                *(
                    _finite((native.get(name) or [None] * n)[index])
                    if len(native.get(name) or []) == n
                    else None
                    for name in CAPTURE_SAMPLE_COLUMNS
                ),
                DECODER_SCHEMA_VERSION,
                provenance,
            ]
            derived = [
                _finite(values[index]) if isinstance(values, list) and len(values) == n else None
                for name in _DERIVED_COLUMNS
                for values in (samples.get(name),)
            ]
            native_values = [
                _finite(values[index]) if len(values) == n else None
                for name in NATIVE_SAMPLE_COLUMNS
                for values in (native.get(name) or [],)
            ]
            flags = native.get("flags_raw") or []
            flag_value = flags[index] if len(flags) == n else None
            raw_flags = int(flag_value) if isinstance(flag_value, (int, float)) else None
            flag_values = [
                int(bool(raw_flags & (1 << bit))) if raw_flags is not None else None
                for bit in range(16)
            ]
            rows.append(tuple([*capture, *derived, *native_values, *flag_values]))
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("BEGIN IMMEDIATE")
            await self._update_decoder_status(db)
            await db.execute(
                "INSERT INTO sessions"
                "(id,started_at,started_at_unix_s,car_id,car_name,track_name,note,archive_fingerprint,parser_version,mirror_revision)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET "
                "started_at=excluded.started_at,started_at_unix_s=excluded.started_at_unix_s,"
                "car_id=excluded.car_id,car_name=excluded.car_name,track_name=excluded.track_name,"
                "note=excluded.note,archive_fingerprint=excluded.archive_fingerprint,"
                "parser_version=excluded.parser_version,mirror_revision=excluded.mirror_revision",
                (
                    session["id"],
                    session.get("started_at", ""),
                    _unix_seconds(session.get("started_at")),
                    session.get("car_id", 0),
                    session.get("car_name", ""),
                    session.get("track_name", ""),
                    session.get("note", ""),
                    archive_fingerprint,
                    DECODER_SCHEMA_VERSION,
                    session.get("metrics_revision", 1),
                ),
            )
            lap_values = (
                lap["id"],
                session["id"],
                lap.get("number", 0),
                lap.get("time_ms", 0),
                lap.get("finished_at", ""),
                finish_unix,
                lap.get("car_id", 0),
                lap.get("fuel_start"),
                lap.get("fuel_end"),
                lap.get("fuel_consumed"),
                lap.get("full_throttle_pct"),
                lap.get("full_brake_pct"),
                lap.get("coasting_pct"),
                lap.get("tire_spin_pct"),
                lap.get("max_speed"),
                lap.get("min_body_height"),
                lap.get("total_ticks"),
                lap.get("tod_ms"),
                lap.get("tcs_active_pct"),
                lap.get("asm_active_pct"),
                lap.get("max_water_temp"),
                lap.get("max_oil_temp"),
                lap.get("min_oil_pressure"),
                int(bool(lap.get("counts_for_best", True))),
                lap.get("off_track_count"),
                None if lap.get("clean_lap") is None else int(bool(lap["clean_lap"])),
                meta.get("packet_format"),
                meta.get("wheelbase_m"),
                meta.get("car_category"),
                meta.get("fuel_capacity"),
                gearing.get("top_speed"),
                gearing.get("rpm_alert"),
                *ratios,
                provenance,
                lap.get("metrics_revision", 1),
            )
            lap_columns = ",".join(_q(name) for name in _LAP_DB_COLUMNS)
            lap_updates = ",".join(
                f"{_q(name)}=excluded.{_q(name)}" for name in _LAP_DB_COLUMNS if name != "id"
            )
            await db.execute(
                f"INSERT INTO laps({lap_columns}) VALUES("
                + ",".join("?" for _ in _LAP_DB_COLUMNS)
                + f") ON CONFLICT(id) DO UPDATE SET {lap_updates}",
                lap_values,
            )
            await db.execute("DELETE FROM samples WHERE lap_id=?", (lap["id"],))
            await db.execute("DELETE FROM events WHERE lap_id=?", (lap["id"],))
            await db.execute("DELETE FROM lap_channel_provenance WHERE lap_id=?", (lap["id"],))
            placeholders = ",".join("?" for _ in SAMPLE_DB_COLUMNS)
            columns = ",".join(_q(name) for name in SAMPLE_DB_COLUMNS)
            for batch in _chunks(rows, SQLITE_BATCH_ROWS):
                await db.executemany(
                    f"INSERT INTO samples({columns}) VALUES({placeholders})", batch
                )
            event_rows = []
            for index, event in enumerate(lap.get("events") or []):
                wheels = set(event.get("wheels") or [])
                event_rows.append(
                    (
                        lap["id"],
                        index,
                        event.get("type", "unknown"),
                        event.get("start_dist"),
                        event.get("end_dist"),
                        event.get("severity"),
                        int("fl" in wheels),
                        int("fr" in wheels),
                        int("rl" in wheels),
                        int("rr" in wheels),
                    )
                )
            if event_rows:
                await db.executemany("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)", event_rows)
            provenance_rows = []
            for name in (*_DERIVED_COLUMNS, *_NATIVE_COLUMNS, *_FLAG_COLUMNS):
                source_name = name.removeprefix("native_")
                values = samples.get(name) if name in samples else native.get(source_name)
                available = isinstance(values, list) and len(values) == n
                if name in _FLAG_COLUMNS:
                    available = len(native.get("flags_raw") or []) == n
                provenance_rows.append(
                    (
                        lap["id"],
                        name,
                        provenance if available else "unavailable",
                        int(available),
                        None if available else "source channel absent or unaligned",
                    )
                )
            await db.executemany(
                "INSERT INTO lap_channel_provenance VALUES(?,?,?,?,?)", provenance_rows
            )
            await db.commit()

    async def replace_session(
        self, session: dict[str, Any], archive_fingerprint: str | None = None
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                "INSERT INTO sessions"
                "(id,started_at,started_at_unix_s,car_id,car_name,track_name,note,"
                "archive_fingerprint,parser_version,mirror_revision) VALUES(?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET started_at=excluded.started_at,"
                "started_at_unix_s=excluded.started_at_unix_s,car_id=excluded.car_id,"
                "car_name=excluded.car_name,track_name=excluded.track_name,note=excluded.note,"
                "archive_fingerprint=excluded.archive_fingerprint,"
                "parser_version=excluded.parser_version,mirror_revision=excluded.mirror_revision",
                (
                    session["id"],
                    session.get("started_at", ""),
                    _unix_seconds(session.get("started_at")),
                    session.get("car_id", 0),
                    session.get("car_name", ""),
                    session.get("track_name", ""),
                    session.get("note", ""),
                    archive_fingerprint,
                    DECODER_SCHEMA_VERSION,
                    session.get("metrics_revision", 1),
                ),
            )
            await db.commit()

    async def prune_laps(self, session_id: int, retained_ids: set[int]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            if retained_ids:
                placeholders = ",".join("?" for _ in retained_ids)
                await db.execute(
                    f"DELETE FROM laps WHERE session_id=? AND id NOT IN ({placeholders})",
                    (session_id, *sorted(retained_ids)),
                )
            else:
                await db.execute("DELETE FROM laps WHERE session_id=?", (session_id,))
            await db.commit()

    async def delete_lap(self, lap_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("DELETE FROM laps WHERE id=?", (lap_id,))
            await db.commit()

    async def delete_session(self, session_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            await db.commit()

    async def clear(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("DELETE FROM sessions")
            await db.commit()

    async def prune_sessions(self, retained_ids: set[int]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            if retained_ids:
                placeholders = ",".join("?" for _ in retained_ids)
                await db.execute(
                    f"DELETE FROM sessions WHERE id NOT IN ({placeholders})",
                    tuple(sorted(retained_ids)),
                )
            else:
                await db.execute("DELETE FROM sessions")
            await db.commit()


class MetricsMirror:
    """Background mirror; secondary failures never affect primary persistence."""

    def __init__(self, repo: Repository, path: Path, data_root: Path) -> None:
        self.repo = repo
        self.database = MetricsDatabase(path)
        self.data_root = data_root.resolve()
        self._queue: asyncio.Queue[tuple[str, int, CompletedLap | None, int]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._pending_keys: set[tuple[str, int]] = set()
        self._latest_laps: dict[int, CompletedLap | None] = {}

    async def start(self) -> None:
        await self.database.initialize()
        self._task = asyncio.create_task(self._run(), name="metrics-mirror")
        self.enqueue("reconcile", 0)

    async def stop(self) -> None:
        if self._task is None:
            return
        await self._queue.join()
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def enqueue(self, operation: str, identifier: int, lap: CompletedLap | None = None) -> None:
        key = (operation, identifier)
        if operation == "lap":
            self._latest_laps[identifier] = lap
        if key in self._pending_keys:
            return
        self._pending_keys.add(key)
        self._queue.put_nowait((operation, identifier, lap, 0))

    async def _run(self) -> None:
        while True:
            operation, identifier, completed, attempt = await self._queue.get()
            key = (operation, identifier)
            self._pending_keys.discard(key)
            if operation == "lap":
                completed = self._latest_laps.pop(identifier, completed)
            try:
                if operation == "reconcile":
                    await self._reconcile()
                elif operation == "lap":
                    await self._sync_lap(identifier, completed)
                elif operation == "delete_lap":
                    await self.database.delete_lap(identifier)
                elif operation == "delete_session":
                    await self.database.delete_session(identifier)
                elif operation == "clear":
                    await self.database.clear()
                if operation != "reconcile":
                    await self.database.set_status("idle", pending=self._queue.qsize())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("metrics mirror %s failed for %s", operation, identifier)
                try:
                    await self.database.set_status(
                        "error",
                        pending=self._queue.qsize() + int(attempt < 2),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                except Exception:  # noqa: BLE001
                    log.exception("could not persist metrics mirror failure status")
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
                    if key not in self._pending_keys:
                        self._pending_keys.add(key)
                        self._queue.put_nowait((operation, identifier, completed, attempt + 1))
            finally:
                self._queue.task_done()

    async def _sync_lap(self, lap_id: int, completed: CompletedLap | None) -> None:
        lap = await self.repo.get_lap(lap_id, with_samples=True)
        if lap is None:
            await self.database.delete_lap(lap_id)
            return
        session = await self.repo.get_session_metadata(int(lap["session_id"]))
        if session is None:
            return
        native = completed.native_samples if completed is not None else None
        await self.database.replace_lap(
            session, lap, native, "live_capture" if native else "primary_fallback"
        )

    async def _reconcile(self) -> None:
        primary = await self.repo.metrics_manifest()
        mirrored_sessions, mirrored_laps = await self.database.reconciliation_manifest()
        fingerprints: dict[int, tuple[str | None, str | None]] = {}
        expected_sessions: dict[int, tuple[int, int, str | None]] = {}
        expected_laps: dict[int, tuple[int, int]] = {}
        for session_id, source in primary.items():
            metadata = source.get("raw_archive_meta")
            fingerprint = (
                archive_fingerprint(self.data_root, metadata)
                if isinstance(metadata, dict) and metadata
                else None
            )
            legacy_fingerprint = (
                json.dumps(metadata, sort_keys=True, default=str)
                if isinstance(metadata, dict) and metadata
                else None
            )
            fingerprints[session_id] = (fingerprint, legacy_fingerprint)
            session = source["session"]
            expected_sessions[session_id] = (
                int(session.get("metrics_revision", 1)),
                DECODER_SCHEMA_VERSION,
                fingerprint,
            )
            expected_laps.update(
                {
                    int(lap_id): (session_id, int(revision))
                    for lap_id, revision in source.get("laps", {}).items()
                }
            )

        total = len(primary)
        if mirrored_sessions == expected_sessions and mirrored_laps == expected_laps:
            await self.database.set_status("idle", total=total, processed=total)
            log.info(
                "metrics reconciliation complete: 0 laps refreshed, %d unchanged",
                len(expected_laps),
            )
            return

        primary_session_ids = set(primary)
        if set(mirrored_sessions) != primary_session_ids:
            await self.database.prune_sessions(primary_session_ids)

        refreshed_laps = 0
        skipped_laps = 0
        await self.database.set_status("backfilling", total=total, processed=0)
        for index, session_id in enumerate(sorted(primary), start=1):
            source = primary[session_id]
            session = source["session"]
            metadata = source.get("raw_archive_meta")
            fingerprint, legacy_fingerprint = fingerprints[session_id]
            source_laps = {
                int(lap_id): int(revision)
                for lap_id, revision in source.get("laps", {}).items()
            }
            mirrored_session = mirrored_sessions.get(session_id)
            parser_changed = (
                mirrored_session is not None
                and mirrored_session[1] != DECODER_SCHEMA_VERSION
            )
            archive_changed = (
                mirrored_session is not None and mirrored_session[2] != fingerprint
            )
            archive_content_changed = bool(
                mirrored_session is not None
                and archive_changed
                and mirrored_session[2] != legacy_fingerprint
            )
            archive_is_complete = (
                isinstance(metadata, dict) and metadata.get("complete") is True
            )
            rebuild_all_laps = parser_changed or (
                archive_content_changed and archive_is_complete
            )
            stale_lap_ids = {
                lap_id
                for lap_id, revision in source_laps.items()
                if rebuild_all_laps
                or mirrored_laps.get(lap_id) != (session_id, revision)
            }
            mirrored_for_session = {
                lap_id
                for lap_id, (mirrored_session_id, _revision) in mirrored_laps.items()
                if mirrored_session_id == session_id
            }
            if not mirrored_for_session.issubset(source_laps):
                await self.database.prune_laps(session_id, set(source_laps))

            session_changed = (
                mirrored_session is None
                or mirrored_session[0] != int(session.get("metrics_revision", 1))
                or parser_changed
                or archive_changed
            )
            if session_changed:
                await self.database.replace_session(session, fingerprint)

            if stale_lap_ids:
                bundles = await self.repo.get_lap_analysis_bundles(sorted(stale_lap_ids))
                bundle = bundles.get(session_id)
                if bundle is not None:
                    replayed = await self._replay_native(bundle)
                    for lap in bundle.get("laps") or []:
                        key = (
                            int(lap["car_id"]),
                            int(lap["number"]),
                            int(lap["time_ms"]),
                        )
                        native = replayed.get(key)
                        await self.database.replace_lap(
                            session,
                            lap,
                            native,
                            "archive_replay" if native else "primary_fallback",
                            fingerprint,
                        )
                        refreshed_laps += 1
            skipped_laps += len(source_laps) - len(stale_lap_ids)
            await self.database.set_status("backfilling", total=total, processed=index)
            await asyncio.sleep(0)
        await self.database.set_status("idle", total=total, processed=total)
        log.info(
            "metrics reconciliation complete: %d laps refreshed, %d unchanged",
            refreshed_laps,
            skipped_laps,
        )

    async def _replay_native(
        self, bundle: dict[str, Any]
    ) -> dict[tuple[int, int, int], dict[str, list[float | int | str | None]]]:
        metadata = bundle.get("raw_archive_meta")
        if not isinstance(metadata, dict) or metadata.get("complete") is not True:
            return {}
        value = metadata.get("path")
        if not isinstance(value, str):
            return {}
        path = (self.data_root / value).resolve()
        if not path.is_relative_to(self.data_root) or not path.is_file():
            return {}
        laps: list[CompletedLap] = []
        sessions: list[SessionInfo] = []

        async def on_lap(lap: CompletedLap) -> None:
            laps.append(lap)

        async def on_session(session: SessionInfo) -> None:
            sessions.append(session)

        try:
            await replay_archive(
                path,
                LapProcessor(on_lap=on_lap, on_session=on_session).feed,
                strict_truncation=True,
            )
        except (ArchiveError, OSError, ValueError):
            log.warning("metrics archive replay failed for session %s", bundle["session"]["id"])
            return {}
        expected_car = int(bundle["session"]["car_id"])
        if len(sessions) != 1 or sessions[0].car_id != expected_car:
            return {}
        result: dict[tuple[int, int, int], dict[str, list[float | int | str | None]]] = {}
        duplicates: set[tuple[int, int, int]] = set()
        targets = {
            (int(lap["car_id"]), int(lap["number"]), int(lap["time_ms"])): lap
            for lap in bundle.get("laps") or []
        }
        for lap in laps:
            key = (lap.car_id, lap.number, lap.time_ms)
            target = targets.get(key)
            target_samples = target.get("samples") if isinstance(target, dict) else None
            target_t = target_samples.get("t") if isinstance(target_samples, dict) else None
            replay_t = lap.samples.get("t")
            packet_ids = lap.native_samples.get("packet_id") or []
            aligned = (
                isinstance(target_t, list)
                and isinstance(replay_t, list)
                and len(target_t) == len(replay_t)
                and all(
                    isinstance(left, (int, float))
                    and isinstance(right, (int, float))
                    and abs(float(left) - float(right)) <= 1e-6
                    for left, right in zip(target_t, replay_t, strict=True)
                )
                and len(packet_ids) == len(target_t)
                and len({int(value) for value in packet_ids if value is not None})
                == len(packet_ids)
            )
            if not aligned:
                continue
            if key in result:
                duplicates.add(key)
            result[key] = lap.native_samples
        for key in duplicates:
            result.pop(key, None)
        return result
