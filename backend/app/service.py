"""Central service: telemetry source -> lap processing -> storage -> live clients."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import WebSocket

from app.config import Settings
from app.models import TelemetryPacket
from app.processing.cars import CarDatabase
from app.processing.laps import CompletedLap, LapProcessor, SessionInfo
from app.storage.repository import Repository, lap_summary  # noqa: F401  (re-export)
from app.telemetry.listener import UdpTelemetrySource
from app.telemetry.simulator import SimTelemetrySource

log = logging.getLogger(__name__)


class TelemetryService:
    def __init__(self, settings: Settings, repo: Repository, cars: CarDatabase) -> None:
        self.settings = settings
        self.repo = repo
        self.cars = cars
        self.processor = LapProcessor(on_lap=self._on_lap, on_session=self._on_session)
        self.source: UdpTelemetrySource | SimTelemetrySource
        if settings.source == "sim":
            self.source = SimTelemetrySource(self._on_packet)
        else:
            self.source = UdpTelemetrySource(settings, self._on_packet)

        self.recording = True
        self.session_id: int | None = None
        self.latest_packet: TelemetryPacket | None = None
        self._clients: set[WebSocket] = set()
        self._last_ws_send = 0.0
        self._ws_interval = 1.0 / settings.ws_rate

    async def start(self) -> None:
        await self.source.start()

    async def stop(self) -> None:
        await self.source.stop()

    # --- pipeline callbacks -------------------------------------------------

    async def _on_packet(self, p: TelemetryPacket) -> None:
        self.latest_packet = p
        if self.recording:
            await self.processor.feed(p)
        now = time.monotonic()
        if now - self._last_ws_send >= self._ws_interval:
            self._last_ws_send = now
            await self._broadcast({"type": "telemetry", "data": self._live_frame(p)})

    async def _on_session(self, info: SessionInfo) -> None:
        self.session_id = await self.repo.create_session(info, self.cars.name(info.car_id))
        log.info("new session %s (car %s)", self.session_id, self.cars.name(info.car_id))
        await self._broadcast({"type": "session", "data": await self.status()})

    async def _on_lap(self, lap: CompletedLap) -> None:
        if self.session_id is None:
            return
        lap_id = await self.repo.save_lap(self.session_id, lap)
        log.info("lap %d saved (%d ms, id=%d)", lap.number, lap.time_ms, lap_id)
        summary = {
            "id": lap_id,
            "session_id": self.session_id,
            "number": lap.number,
            "time_ms": lap.time_ms,
            "car_name": self.cars.name(lap.car_id),
            "fuel_consumed": round(lap.fuel_consumed, 3),
            "full_throttle_pct": round(lap.full_throttle_pct, 1),
            "full_brake_pct": round(lap.full_brake_pct, 1),
            "coasting_pct": round(lap.coasting_pct, 1),
            "tire_spin_pct": round(lap.tire_spin_pct, 1),
            "max_speed": round(lap.max_speed, 1),
            "min_body_height": round(lap.min_body_height, 1),
        }
        await self._broadcast({"type": "lap", "data": summary})

    # --- live stream --------------------------------------------------------

    def _live_frame(self, p: TelemetryPacket) -> dict[str, Any]:
        """Compact frame for the live view (~30 Hz)."""
        session = self.processor.session
        return {
            "on_track": p.is_on_track,
            "paused": p.is_paused,
            "speed_kmh": round(p.speed_kmh, 1),
            "rpm": round(p.engine_rpm),
            "rpm_alert": p.rpm_alert_max,
            "gear": p.current_gear,
            "suggested_gear": p.suggested_gear,
            "throttle": round(p.throttle_pct, 1),
            "brake": round(p.brake_pct, 1),
            "boost": round(p.boost, 2),
            "fuel_level": round(p.fuel_level, 2),
            "fuel_capacity": p.fuel_capacity,
            "current_lap": p.current_lap,
            "total_laps": p.total_laps,
            "best_lap_ms": p.best_lap_time_ms,
            "last_lap_ms": p.last_lap_time_ms,
            "position": p.race_position,
            "total_positions": p.total_positions,
            "tire_temps": [
                round(p.tire_temp_fl, 1), round(p.tire_temp_fr, 1),
                round(p.tire_temp_rl, 1), round(p.tire_temp_rr, 1),
            ],
            "tire_slip": round(p.tire_slip_ratio, 3),
            "water_temp": round(p.water_temp, 1),
            "oil_temp": round(p.oil_temp, 1),
            "car_id": p.car_id,
            "car_name": self.cars.name(p.car_id),
            "session_best_ms": session.best_lap_time_ms if session else -1,
            "pos_x": round(p.position_x, 2),
            "pos_z": round(p.position_z, 2),
        }

    async def status(self) -> dict[str, Any]:
        return {
            "source": self.settings.source,
            "recording": self.recording,
            "session_id": self.session_id,
            **self.source.stats,
        }

    async def register(self, ws: WebSocket) -> None:
        self._clients.add(ws)
        await ws.send_text(json.dumps({"type": "status", "data": await self.status()}))

    def unregister(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        if not self._clients:
            return
        text = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # --- controls -----------------------------------------------------------

    async def log_lap_now(self) -> dict[str, Any] | None:
        """Persist the in-progress lap without waiting for the finish line."""
        samples = self.processor.live_lap_samples
        if self.session_id is None or not samples["t"]:
            return None
        lap = CompletedLap(
            number=self.processor._current_lap,
            time_ms=int(samples["t"][-1] * 1000),
            finished_at="",
            car_id=self.latest_packet.car_id if self.latest_packet else 0,
            samples={k: list(v) for k, v in samples.items()},
            fuel_start=samples["fuel"][0],
            fuel_end=samples["fuel"][-1],
        )
        lap.compute_metrics()
        lap_id = await self.repo.save_lap(self.session_id, lap)
        return {"id": lap_id, "number": lap.number, "time_ms": lap.time_ms}
