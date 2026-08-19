"""Persistence for sessions and laps, plus JSON import/export."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.processing.laps import CompletedLap, SessionInfo
from app.processing.tracks import TrackSignature, matches
from app.storage.db import (
    CarDrivetrainRow,
    LapRow,
    LayoutRow,
    SessionRow,
    SettingRow,
    TrackRow,
)

# v3: extended packet channels plus per-lap static telemetry metadata.
# v1/v2 files import fine — missing fields stay absent and consumers skip them.
EXPORT_VERSION = 3


def lap_summary(row: LapRow, metrics_revision: int | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "number": row.number,
        "time_ms": row.time_ms,
        "finished_at": row.finished_at,
        "car_id": row.car_id,
        "fuel_start": row.fuel_start,
        "fuel_end": row.fuel_end,
        "fuel_consumed": row.fuel_consumed,
        "full_throttle_pct": row.full_throttle_pct,
        "full_brake_pct": row.full_brake_pct,
        "coasting_pct": row.coasting_pct,
        "tire_spin_pct": row.tire_spin_pct,
        "max_speed": row.max_speed,
        "min_body_height": row.min_body_height,
        "total_ticks": row.total_ticks,
        "tod_ms": row.tod_ms,
        "tcs_active_pct": row.tcs_active_pct,
        "asm_active_pct": row.asm_active_pct,
        "max_water_temp": row.max_water_temp,
        "max_oil_temp": row.max_oil_temp,
        "min_oil_pressure": row.min_oil_pressure,
        "counts_for_best": row.counts_for_best,
        "off_track_count": row.off_track_count,
        "clean_lap": row.clean_lap,
        "metrics_revision": metrics_revision or row.__dict__.get("metrics_revision", 1),
        "event_counts": _event_counts(row.events_json),
        "telemetry_meta": (
            json.loads(row.telemetry_meta_json) if row.telemetry_meta_json else None
        ),
    }


def _event_counts(events_json: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        for e in json.loads(events_json or "[]"):
            counts[e["type"]] = counts.get(e["type"], 0) + 1
    except (ValueError, KeyError, TypeError):
        pass
    return counts


def _json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def _hydration_metadata(
    db: AsyncSession, session_ids: list[int]
) -> dict[int, dict[str, Any] | None]:
    """Read additive hydration metadata, tolerating an unmigrated read-only DB."""
    if not session_ids:
        return {}
    try:
        rows = (
            await db.execute(
                select(SessionRow.id, SessionRow.telemetry_hydration_meta_json).where(
                    SessionRow.id.in_(session_ids)
                )
            )
        ).all()
    except OperationalError:
        return {session_id: None for session_id in session_ids}
    return {session_id: _json_object(raw) for session_id, raw in rows}


async def _session_revisions(db: AsyncSession, session_ids: list[int]) -> dict[int, int]:
    if not session_ids:
        return {}
    try:
        rows = (
            await db.execute(
                select(SessionRow.id, SessionRow.metrics_revision).where(
                    SessionRow.id.in_(session_ids)
                )
            )
        ).all()
    except OperationalError:
        return {session_id: 1 for session_id in session_ids}
    return {int(row_id): int(revision) for row_id, revision in rows}


async def _lap_revisions(db: AsyncSession, lap_ids: list[int]) -> dict[int, int]:
    if not lap_ids:
        return {}
    try:
        rows = (
            await db.execute(
                select(LapRow.id, LapRow.metrics_revision).where(LapRow.id.in_(lap_ids))
            )
        ).all()
    except OperationalError:
        return {lap_id: 1 for lap_id in lap_ids}
    return {int(row_id): int(revision) for row_id, revision in rows}


class Repository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._mutation_callback: Callable[[str, int, CompletedLap | None], None] | None = None

    def set_mutation_callback(
        self, callback: Callable[[str, int, CompletedLap | None], None] | None
    ) -> None:
        self._mutation_callback = callback

    def _notify_metrics(
        self, operation: str, identifier: int = 0, lap: CompletedLap | None = None
    ) -> None:
        if self._mutation_callback is not None:
            self._mutation_callback(operation, identifier, lap)

    async def create_session(self, info: SessionInfo, car_name: str) -> int:
        async with self._sf() as db:
            row = SessionRow(started_at=info.started_at, car_id=info.car_id, car_name=car_name)
            db.add(row)
            await db.commit()
            return row.id

    async def set_session_archive_metadata(
        self, session_id: int, metadata: dict[str, object]
    ) -> None:
        async with self._sf() as db:
            row = await db.get(SessionRow, session_id)
            if row is not None:
                row.raw_archive_meta_json = json.dumps(metadata, separators=(",", ":"))
                await db.execute(
                    update(SessionRow)
                    .where(SessionRow.id == session_id)
                    .values(metrics_revision=SessionRow.metrics_revision + 1)
                )
                await db.commit()
                self._notify_metrics("reconcile")

    async def get_session_archive_metadata(self, session_id: int) -> dict[str, object] | None:
        async with self._sf() as db:
            row = await db.get(SessionRow, session_id)
            if row is None or not row.raw_archive_meta_json:
                return None
            value = json.loads(row.raw_archive_meta_json)
            return value if isinstance(value, dict) else None

    async def get_session_hydration_metadata(self, session_id: int) -> dict[str, object] | None:
        async with self._sf() as db:
            return (await _hydration_metadata(db, [session_id])).get(session_id)

    async def persist_session_hydration(
        self,
        session_id: int,
        updates: dict[int, dict[str, list[float]]],
        expected: dict[int, tuple[int, int, int, list[float]]],
        metadata: dict[str, object],
        *,
        replace_channels: set[str] | None = None,
    ) -> tuple[bool, int]:
        """Atomically merge recovered channels and record the hydration outcome.

        Existing aligned channels remain authoritative unless a caller explicitly
        identifies a semantically-invalid group (for example an invalid quaternion).
        The persisted lap identity and time grid are revalidated inside the write
        transaction so a concurrent import/delete cannot receive replayed data.
        """
        replace = replace_channels or set()
        async with self._sf() as db:
            session = await db.get(SessionRow, session_id)
            if session is None:
                return False, 0
            rows = (
                (
                    await db.execute(
                        select(LapRow).where(LapRow.session_id == session_id).order_by(LapRow.id)
                    )
                )
                .scalars()
                .all()
            )
            by_id = {row.id: row for row in rows}
            changed = 0
            for lap_id, channels in updates.items():
                row = by_id.get(lap_id)
                identity = expected.get(lap_id)
                if row is None or identity is None:
                    await db.rollback()
                    return False, 0
                car_id, number, time_ms, target_t = identity
                if (row.car_id, row.number, row.time_ms) != (car_id, number, time_ms):
                    await db.rollback()
                    return False, 0
                samples = json.loads(row.samples_json)
                current_t = samples.get("t") if isinstance(samples, dict) else None
                if current_t != target_t:
                    await db.rollback()
                    return False, 0
                size = len(target_t)
                for channel, values in sorted(channels.items()):
                    if len(values) != size or any(
                        not isinstance(value, (int, float)) or not math.isfinite(float(value))
                        for value in values
                    ):
                        continue
                    current = samples.get(channel)
                    if (
                        channel not in replace
                        and isinstance(current, list)
                        and len(current) == size
                    ):
                        continue
                    samples[channel] = values
                    changed += 1
                row.samples_json = json.dumps(
                    samples,
                    separators=(",", ":"),
                    allow_nan=False,
                    ensure_ascii=False,
                )
                await db.execute(
                    update(LapRow)
                    .where(LapRow.id == row.id)
                    .values(metrics_revision=LapRow.metrics_revision + 1)
                )
            session.telemetry_hydration_meta_json = json.dumps(
                metadata,
                separators=(",", ":"),
                allow_nan=False,
                ensure_ascii=False,
            )
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(metrics_revision=SessionRow.metrics_revision + 1)
            )
            await db.commit()
            if changed:
                self._notify_metrics("reconcile")
            return True, changed

    async def list_recording_archive_metadata(self) -> list[tuple[int, dict[str, object]]]:
        async with self._sf() as db:
            rows = (
                await db.execute(
                    select(SessionRow.id, SessionRow.raw_archive_meta_json).where(
                        SessionRow.raw_archive_meta_json != ""
                    )
                )
            ).all()
        result: list[tuple[int, dict[str, object]]] = []
        for session_id, raw in rows:
            try:
                metadata = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(metadata, dict) and metadata.get("status") == "recording":
                result.append((session_id, metadata))
        return result

    async def list_session_archive_metadata(self) -> list[tuple[int, dict[str, object]]]:
        async with self._sf() as db:
            rows = (
                await db.execute(
                    select(SessionRow.id, SessionRow.raw_archive_meta_json).where(
                        SessionRow.raw_archive_meta_json != ""
                    )
                )
            ).all()
        result: list[tuple[int, dict[str, object]]] = []
        for session_id, raw in rows:
            try:
                metadata = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(metadata, dict):
                result.append((session_id, metadata))
        return result

    async def save_lap(self, session_id: int, lap: CompletedLap) -> int:
        async with self._sf() as db:
            row = LapRow(
                session_id=session_id,
                number=lap.number,
                time_ms=lap.time_ms,
                finished_at=lap.finished_at,
                car_id=lap.car_id,
                fuel_start=lap.fuel_start,
                fuel_end=lap.fuel_end,
                fuel_consumed=lap.fuel_consumed,
                full_throttle_pct=lap.full_throttle_pct,
                full_brake_pct=lap.full_brake_pct,
                coasting_pct=lap.coasting_pct,
                tire_spin_pct=lap.tire_spin_pct,
                max_speed=lap.max_speed,
                min_body_height=lap.min_body_height,
                total_ticks=lap.total_ticks,
                tod_ms=lap.tod_ms,
                tcs_active_pct=lap.tcs_active_pct,
                asm_active_pct=lap.asm_active_pct,
                counts_for_best=lap.counts_for_best,
                off_track_count=lap.off_track_count,
                clean_lap=lap.clean_lap,
                max_water_temp=lap.max_water_temp,
                max_oil_temp=lap.max_oil_temp,
                min_oil_pressure=lap.min_oil_pressure,
                events_json=json.dumps(lap.events, separators=(",", ":")),
                gearing_json=json.dumps(lap.gearing, separators=(",", ":")) if lap.gearing else "",
                telemetry_meta_json=(
                    json.dumps(lap.telemetry_meta, separators=(",", ":"))
                    if lap.telemetry_meta
                    else ""
                ),
                samples_json=json.dumps(lap.samples, separators=(",", ":")),
            )
            db.add(row)
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(metrics_revision=SessionRow.metrics_revision + 1)
            )
            await db.commit()
            self._notify_metrics("lap", row.id, lap)
            return row.id

    async def list_sessions(self) -> list[dict[str, Any]]:
        # One aggregate query for all sessions; the outer join keeps lap-less
        # sessions and only touches LapRow ids/times (never samples_json).
        async with self._sf() as db:
            # Best excludes partial laps (pit out-laps, counts_for_best=0):
            # their GT7-reported "times" aren't full-lap times.
            best_expr = func.min(case((LapRow.counts_for_best, LapRow.time_ms)))
            rows = (
                await db.execute(
                    select(SessionRow, func.count(LapRow.id), best_expr)
                    .outerjoin(LapRow, LapRow.session_id == SessionRow.id)
                    .group_by(SessionRow.id)
                    .order_by(SessionRow.id.desc())
                )
            ).all()
            try:
                overrides = dict(
                    (await db.execute(select(CarDrivetrainRow.car_id, CarDrivetrainRow.drivetrain)))
                    .tuples()
                    .all()
                )
            except OperationalError:
                # Direct readers of an old database may not have run init_db yet.
                overrides = {}
            revisions = await _session_revisions(db, [s.id for s, _count, _best in rows])
            return [
                {
                    "id": s.id,
                    "started_at": s.started_at,
                    "car_id": s.car_id,
                    "car_name": s.car_name,
                    "note": s.note,
                    "track_name": s.track_name,
                    "lap_count": count,
                    "best_lap_time_ms": best,
                    "drivetrain_override": overrides.get(s.car_id),
                    "metrics_revision": revisions.get(s.id, 1),
                }
                for s, count, best in rows
            ]

    async def get_session_metadata(self, session_id: int) -> dict[str, Any] | None:
        """Load lightweight session fields without materializing any lap samples."""
        async with self._sf() as db:
            row = await db.get(SessionRow, session_id)
            if row is None:
                return None
            revision = (await _session_revisions(db, [session_id])).get(session_id, 1)
            return {
                "id": row.id,
                "started_at": row.started_at,
                "car_id": row.car_id,
                "car_name": row.car_name,
                "track_name": row.track_name,
                "note": row.note,
                "metrics_revision": revision,
            }

    async def session_lap_stats(self, session_id: int) -> dict[str, Any]:
        """Aggregates for a session without materializing lap rows.

        Loading LapRow objects pulls the (large) samples_json column along;
        session-boundary bookkeeping only needs these numbers.
        """
        async with self._sf() as db:
            count, best_ms, fuel_used, car_id = (
                await db.execute(
                    select(
                        func.count(LapRow.id),
                        # partial out-laps don't own the session best
                        func.min(case((LapRow.counts_for_best, LapRow.time_ms))),
                        func.coalesce(func.sum(LapRow.fuel_consumed), 0.0),
                        func.min(LapRow.car_id),
                    ).where(LapRow.session_id == session_id)
                )
            ).one()
            return {
                "count": count,
                "best_ms": best_ms if best_ms is not None else -1,
                "fuel_used": fuel_used,
                "car_id": car_id if car_id is not None else 0,
            }

    async def mark_session_laps_partial(self, session_id: int, numbers: list[int]) -> None:
        """Set which laps of a session are partial — and which are not.

        Called when later laps change the verdict on an earlier one. The whole
        session is rewritten rather than only the newly-condemned laps, because
        the yardstick moves in both directions: the lap that looked short next
        to one wide lap is full again once a third lap settles the distance.
        """
        async with self._sf() as db:
            await db.execute(
                update(LapRow)
                .where(LapRow.session_id == session_id)
                .values(
                    counts_for_best=LapRow.number.notin_(numbers) if numbers else True,
                    metrics_revision=LapRow.metrics_revision + 1,
                )
            )
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == session_id)
                .values(metrics_revision=SessionRow.metrics_revision + 1)
            )
            await db.commit()
        self._notify_metrics("reconcile")

    async def list_laps(self, session_id: int | None = None) -> list[dict[str, Any]]:
        async with self._sf() as db:
            q = select(LapRow).order_by(LapRow.id.desc())
            if session_id is not None:
                q = q.where(LapRow.session_id == session_id)
            rows = list((await db.execute(q)).scalars())
            revisions = await _lap_revisions(db, [row.id for row in rows])
            return [lap_summary(row, revisions.get(row.id, 1)) for row in rows]

    async def get_lap(self, lap_id: int, with_samples: bool = True) -> dict[str, Any] | None:
        async with self._sf() as db:
            row = (await db.execute(select(LapRow).where(LapRow.id == lap_id))).scalar_one_or_none()
            if row is None:
                return None
            revision = (await _lap_revisions(db, [lap_id])).get(lap_id, 1)
            data = lap_summary(row, revision)
            data["events"] = json.loads(row.events_json or "[]")
            data["gearing"] = json.loads(row.gearing_json) if row.gearing_json else None
            if with_samples:
                data["samples"] = json.loads(row.samples_json)
            return data

    async def get_laps_samples(self, lap_ids: list[int]) -> dict[int, dict[str, list[float]]]:
        async with self._sf() as db:
            rows = (await db.execute(select(LapRow).where(LapRow.id.in_(lap_ids)))).scalars()
            return {r.id: json.loads(r.samples_json) for r in rows}

    async def get_laps_events(self, lap_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        async with self._sf() as db:
            rows = (
                await db.execute(
                    select(LapRow.id, LapRow.events_json).where(LapRow.id.in_(lap_ids))
                )
            ).all()
            return {lap_id: json.loads(ev or "[]") for lap_id, ev in rows}

    async def get_lap_analysis_bundles(self, lap_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Load selected laps grouped with the archive metadata for their sessions."""
        async with self._sf() as db:
            lap_rows = (
                (await db.execute(select(LapRow).where(LapRow.id.in_(lap_ids)).order_by(LapRow.id)))
                .scalars()
                .all()
            )
            session_ids = sorted({row.session_id for row in lap_rows})
            session_rows = (
                (
                    await db.execute(
                        select(SessionRow)
                        .where(SessionRow.id.in_(session_ids))
                        .order_by(SessionRow.id)
                    )
                )
                .scalars()
                .all()
                if session_ids
                else []
            )
            hydration_by_id = await _hydration_metadata(db, session_ids)
            session_revisions = await _session_revisions(db, session_ids)
            lap_revisions = await _lap_revisions(db, [row.id for row in lap_rows])
            bundles: dict[int, dict[str, Any]] = {}
            for session in session_rows:
                bundles[session.id] = {
                    "session": {
                        "id": session.id,
                        "started_at": session.started_at,
                        "car_id": session.car_id,
                        "car_name": session.car_name,
                        "note": session.note,
                        "track_name": session.track_name,
                        "metrics_revision": session_revisions.get(session.id, 1),
                    },
                    "laps": [],
                    "raw_archive_meta": _json_object(session.raw_archive_meta_json),
                    "telemetry_hydration_meta": hydration_by_id.get(session.id),
                }
            for row in lap_rows:
                bundle = bundles.get(row.session_id)
                if bundle is None:
                    continue
                lap = lap_summary(row, lap_revisions.get(row.id, 1))
                lap["events"] = json.loads(row.events_json or "[]")
                lap["gearing"] = json.loads(row.gearing_json) if row.gearing_json else None
                lap["samples"] = json.loads(row.samples_json)
                bundle["laps"].append(lap)
            return bundles

    async def get_session_analysis_data(self, session_id: int) -> dict[str, Any] | None:
        """Load one session and all persisted lap analysis inputs.

        The endpoint intentionally needs the sample blobs, but the number of
        database round trips stays constant rather than growing per lap.
        """
        async with self._sf() as db:
            session = await db.get(SessionRow, session_id)
            if session is None:
                return None
            rows = list(
                (
                    await db.execute(
                        select(LapRow).where(LapRow.session_id == session_id).order_by(LapRow.id)
                    )
                ).scalars()
            )
            hydration_meta = (await _hydration_metadata(db, [session_id])).get(session_id)
            session_revision = (await _session_revisions(db, [session_id])).get(session_id, 1)
            lap_revisions = await _lap_revisions(db, [row.id for row in rows])
            laps: list[dict[str, Any]] = []
            for row in rows:
                lap = lap_summary(row, lap_revisions.get(row.id, 1))
                lap["events"] = json.loads(row.events_json or "[]")
                lap["gearing"] = json.loads(row.gearing_json) if row.gearing_json else None
                lap["samples"] = json.loads(row.samples_json)
                laps.append(lap)
            try:
                drivetrain_override = await db.get(CarDrivetrainRow, session.car_id)
            except OperationalError:
                drivetrain_override = None
            return {
                "session": {
                    "id": session.id,
                    "started_at": session.started_at,
                    "car_id": session.car_id,
                    "car_name": session.car_name,
                    "note": session.note,
                    "track_name": session.track_name,
                    "metrics_revision": session_revision,
                },
                "laps": laps,
                "raw_archive_meta": _json_object(session.raw_archive_meta_json),
                "telemetry_hydration_meta": hydration_meta,
                "drivetrain_override": (
                    drivetrain_override.drivetrain if drivetrain_override is not None else None
                ),
            }

    async def set_car_drivetrain(self, car_id: int, drivetrain: str | None) -> None:
        """Set a per-car override, or delete it to restore automatic inference."""
        async with self._sf() as db:
            row = await db.get(CarDrivetrainRow, car_id)
            if drivetrain is None:
                if row is not None:
                    await db.delete(row)
            elif row is None:
                db.add(CarDrivetrainRow(car_id=car_id, drivetrain=drivetrain))
            else:
                row.drivetrain = drivetrain
            await db.commit()

    async def get_car_drivetrain(self, car_id: int) -> str | None:
        async with self._sf() as db:
            try:
                row = await db.get(CarDrivetrainRow, car_id)
            except OperationalError:
                return None
            return row.drivetrain if row is not None else None

    async def delete_session(self, session_id: int) -> None:
        async with self._sf() as db:
            await db.execute(delete(LapRow).where(LapRow.session_id == session_id))
            await db.execute(delete(SessionRow).where(SessionRow.id == session_id))
            await db.commit()
        self._notify_metrics("delete_session", session_id)

    async def delete_lap(self, lap_id: int) -> None:
        async with self._sf() as db:
            await db.execute(delete(LapRow).where(LapRow.id == lap_id))
            await db.commit()
        self._notify_metrics("delete_lap", lap_id)

    async def export_lap(self, lap_id: int) -> dict[str, Any] | None:
        lap = await self.get_lap(lap_id, with_samples=True)
        if lap is None:
            return None
        return {"format": "gt7-datalogger-lap", "version": EXPORT_VERSION, "lap": lap}

    # --- tracks -------------------------------------------------------------

    async def list_tracks(self) -> list[dict[str, Any]]:
        async with self._sf() as db:
            rows = (await db.execute(select(TrackRow).order_by(TrackRow.name))).scalars()
            return [
                {
                    "id": t.id,
                    "name": t.name,
                    "length_m": t.length_m,
                    "created_at": t.created_at,
                }
                for t in rows
            ]

    async def find_track(self, sig: TrackSignature) -> str | None:
        """Name of the stored track matching this signature, if any."""
        async with self._sf() as db:
            rows = (await db.execute(select(TrackRow))).scalars()
            for track in rows:
                if matches(sig, track):
                    return track.name
        return None

    async def create_track(self, name: str, sig: TrackSignature) -> int:
        async with self._sf() as db:
            row = TrackRow(
                name=name,
                length_m=sig.length_m,
                min_x=sig.min_x,
                max_x=sig.max_x,
                min_z=sig.min_z,
                max_z=sig.max_z,
                created_at=datetime.now(UTC).isoformat(),
            )
            db.add(row)
            await db.commit()
            return row.id

    async def delete_track(self, track_id: int) -> None:
        async with self._sf() as db:
            await db.execute(delete(TrackRow).where(TrackRow.id == track_id))
            await db.commit()

    async def set_session_track(self, session_id: int, track_name: str) -> None:
        async with self._sf() as db:
            row = await db.get(SessionRow, session_id)
            if row is not None:
                row.track_name = track_name
                await db.execute(
                    update(SessionRow)
                    .where(SessionRow.id == session_id)
                    .values(metrics_revision=SessionRow.metrics_revision + 1)
                )
                await db.commit()
                self._notify_metrics("reconcile")

    # --- overlay/dashboard layouts ------------------------------------------

    @staticmethod
    def _layout_dict(row: LayoutRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "config": json.loads(row.config_json),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def list_layouts(self) -> list[dict[str, Any]]:
        async with self._sf() as db:
            rows = (await db.execute(select(LayoutRow).order_by(LayoutRow.name))).scalars()
            return [self._layout_dict(r) for r in rows]

    async def get_layout(self, ref: str) -> dict[str, Any] | None:
        """Look up by numeric id first, falling back to name (URLs carry either)."""
        async with self._sf() as db:
            row = None
            if ref.isdigit():
                row = await db.get(LayoutRow, int(ref))
            if row is None:
                row = (
                    await db.execute(select(LayoutRow).where(LayoutRow.name == ref))
                ).scalar_one_or_none()
            return self._layout_dict(row) if row else None

    async def get_layout_by_name(self, name: str) -> dict[str, Any] | None:
        async with self._sf() as db:
            row = (
                await db.execute(select(LayoutRow).where(LayoutRow.name == name))
            ).scalar_one_or_none()
            return self._layout_dict(row) if row else None

    async def create_layout(self, name: str, kind: str, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        async with self._sf() as db:
            row = LayoutRow(
                name=name,
                kind=kind,
                config_json=json.dumps(config, separators=(",", ":")),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()
            return self._layout_dict(row)

    async def update_layout(
        self,
        layout_id: int,
        name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        async with self._sf() as db:
            row = await db.get(LayoutRow, layout_id)
            if row is None:
                return None
            if name is not None:
                row.name = name
            if config is not None:
                row.config_json = json.dumps(config, separators=(",", ":"))
            row.updated_at = datetime.now(UTC).isoformat()
            await db.commit()
            return self._layout_dict(row)

    async def delete_layout(self, layout_id: int) -> None:
        async with self._sf() as db:
            await db.execute(delete(LayoutRow).where(LayoutRow.id == layout_id))
            await db.commit()

    # --- runtime settings ---------------------------------------------------

    async def get_settings(self) -> dict[str, str]:
        async with self._sf() as db:
            rows = (await db.execute(select(SettingRow))).scalars()
            return {r.key: r.value for r in rows}

    async def set_setting(self, key: str, value: str) -> None:
        async with self._sf() as db:
            row = await db.get(SettingRow, key)
            if row is None:
                db.add(SettingRow(key=key, value=value))
            else:
                row.value = value
            await db.commit()

    # --- admin --------------------------------------------------------------

    async def stats(self) -> dict[str, int]:
        async with self._sf() as db:
            sessions = (await db.execute(select(func.count(SessionRow.id)))).scalar_one()
            laps = (await db.execute(select(func.count(LapRow.id)))).scalar_one()
            return {"sessions": sessions, "laps": laps}

    async def clear_all(self) -> None:
        """Delete all recorded sessions and laps (settings are kept)."""
        async with self._sf() as db:
            await db.execute(delete(LapRow))
            await db.execute(delete(SessionRow))
            await db.commit()
        self._notify_metrics("clear")

    async def vacuum(self) -> None:
        async with self._sf() as db:
            await db.execute(text("VACUUM"))

    async def import_lap(self, payload: dict[str, Any], session_id: int) -> int:
        if payload.get("format") != "gt7-datalogger-lap":
            raise ValueError("unrecognized lap export format")
        lap = payload["lap"]
        completed = CompletedLap(
            number=int(lap["number"]),
            time_ms=int(lap["time_ms"]),
            finished_at=str(lap.get("finished_at", "")),
            car_id=int(lap.get("car_id", 0)),
            samples=lap["samples"],
            fuel_start=float(lap.get("fuel_start", 0)),
            fuel_end=float(lap.get("fuel_end", 0)),
            tod_ms=int(lap.get("tod_ms", -1)),
            counts_for_best=bool(lap.get("counts_for_best", True)),
        )
        # Aid metrics and events are recomputed from samples; engine-health
        # aggregates and gearing aren't derivable, so carry them from v2 files
        # (v1 files simply keep the "unknown" defaults).
        completed.max_water_temp = float(lap.get("max_water_temp", 0.0))
        completed.max_oil_temp = float(lap.get("max_oil_temp", 0.0))
        completed.min_oil_pressure = float(lap.get("min_oil_pressure", -1.0))
        gearing = lap.get("gearing")
        completed.gearing = gearing if isinstance(gearing, dict) else None
        telemetry_meta = lap.get("telemetry_meta")
        completed.telemetry_meta = telemetry_meta if isinstance(telemetry_meta, dict) else None
        completed.compute_metrics()
        return await self.save_lap(session_id, completed)
