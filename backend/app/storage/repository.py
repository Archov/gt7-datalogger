"""Persistence for sessions and laps, plus JSON import/export."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.processing.laps import CompletedLap, SessionInfo
from app.storage.db import LapRow, SessionRow

EXPORT_VERSION = 1


def lap_summary(row: LapRow) -> dict[str, Any]:
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
    }


class Repository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_session(self, info: SessionInfo, car_name: str) -> int:
        async with self._sf() as db:
            row = SessionRow(started_at=info.started_at, car_id=info.car_id, car_name=car_name)
            db.add(row)
            await db.commit()
            return row.id

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
                samples_json=json.dumps(lap.samples, separators=(",", ":")),
            )
            db.add(row)
            await db.commit()
            return row.id

    async def list_sessions(self) -> list[dict[str, Any]]:
        async with self._sf() as db:
            rows = (await db.execute(select(SessionRow).order_by(SessionRow.id.desc()))).scalars()
            out = []
            for s in rows:
                laps = (
                    await db.execute(select(LapRow.time_ms).where(LapRow.session_id == s.id))
                ).scalars().all()
                out.append(
                    {
                        "id": s.id,
                        "started_at": s.started_at,
                        "car_id": s.car_id,
                        "car_name": s.car_name,
                        "note": s.note,
                        "lap_count": len(laps),
                        "best_lap_time_ms": min(laps) if laps else None,
                    }
                )
            return out

    async def list_laps(self, session_id: int | None = None) -> list[dict[str, Any]]:
        async with self._sf() as db:
            q = select(LapRow).order_by(LapRow.id.desc())
            if session_id is not None:
                q = q.where(LapRow.session_id == session_id)
            rows = (await db.execute(q)).scalars()
            return [lap_summary(r) for r in rows]

    async def get_lap(self, lap_id: int, with_samples: bool = True) -> dict[str, Any] | None:
        async with self._sf() as db:
            row = (await db.execute(select(LapRow).where(LapRow.id == lap_id))).scalar_one_or_none()
            if row is None:
                return None
            data = lap_summary(row)
            if with_samples:
                data["samples"] = json.loads(row.samples_json)
            return data

    async def get_laps_samples(self, lap_ids: list[int]) -> dict[int, dict[str, list[float]]]:
        async with self._sf() as db:
            rows = (await db.execute(select(LapRow).where(LapRow.id.in_(lap_ids)))).scalars()
            return {r.id: json.loads(r.samples_json) for r in rows}

    async def delete_session(self, session_id: int) -> None:
        async with self._sf() as db:
            await db.execute(delete(LapRow).where(LapRow.session_id == session_id))
            await db.execute(delete(SessionRow).where(SessionRow.id == session_id))
            await db.commit()

    async def delete_lap(self, lap_id: int) -> None:
        async with self._sf() as db:
            await db.execute(delete(LapRow).where(LapRow.id == lap_id))
            await db.commit()

    async def export_lap(self, lap_id: int) -> dict[str, Any] | None:
        lap = await self.get_lap(lap_id, with_samples=True)
        if lap is None:
            return None
        return {"format": "gt7-datalogger-lap", "version": EXPORT_VERSION, "lap": lap}

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
        )
        completed.compute_metrics()
        return await self.save_lap(session_id, completed)
