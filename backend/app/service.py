"""Central service: telemetry source -> lap processing -> storage -> live clients."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from app.config import Settings
from app.models import TelemetryPacket
from app.notify import Notifier
from app.processing.analysis import Samples, time_delta_at
from app.processing.cars import CarDatabase
from app.processing.laps import CompletedLap, LapProcessor, SessionInfo
from app.processing.tracks import signature_from_samples
from app.storage.repository import Repository, lap_summary  # noqa: F401  (re-export)
from app.telemetry.listener import UdpTelemetrySource
from app.telemetry.simulator import SimTelemetrySource

log = logging.getLogger(__name__)


def _count_events(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        kind = str(e.get("type", ""))
        counts[kind] = counts.get(kind, 0) + 1
    return counts


class TelemetryService:
    def __init__(self, settings: Settings, repo: Repository, cars: CarDatabase) -> None:
        self.settings = settings
        self.repo = repo
        self.cars = cars
        self.started_at = time.time()
        self.processor = LapProcessor(on_lap=self._on_lap, on_session=self._on_session)
        self.source: UdpTelemetrySource | SimTelemetrySource
        if settings.source == "sim":
            self.source = SimTelemetrySource(self._on_packet)
        else:
            self.source = UdpTelemetrySource(settings, self._on_packet)

        self.recording = True
        self.session_id: int | None = None
        self.track_name: str = ""
        self.latest_packet: TelemetryPacket | None = None
        self.notifier = Notifier()
        self.notifier.url = settings.webhook_url
        self._session_best_ms: int | None = None
        self._prev_best_ms: int | None = None
        # (dist, t) trace of the session-best lap — the reference for the
        # live delta. Safe to hold by reference: the processor allocates a
        # fresh sample store at every lap boundary.
        self._best_ref: Samples | None = None
        self._clients: set[WebSocket] = set()
        self._last_ws_send = 0.0
        self._ws_interval = 1.0 / settings.ws_rate

    async def start(self) -> None:
        await self.source.start()

    async def stop(self) -> None:
        await self.source.stop()

    async def switch_source(self, kind: str) -> None:
        """Swap between the UDP and simulated source at runtime."""
        await self.source.stop()
        self.settings.source = kind
        if kind == "sim":
            self.source = SimTelemetrySource(self._on_packet)
        else:
            self.source = UdpTelemetrySource(self.settings, self._on_packet)
        await self.source.start()
        log.info("telemetry source switched to %s", kind)
        await self._broadcast({"type": "status", "data": await self.status()})

    async def set_ps_ip(self, ip: str) -> None:
        self.settings.ps_ip = ip
        if isinstance(self.source, UdpTelemetrySource):
            self.source.reset_discovery()
        log.info("console IP set to %s", ip or "<auto-discover>")
        await self._broadcast({"type": "status", "data": await self.status()})

    async def restart_source(self) -> None:
        await self.switch_source(self.settings.source)

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
        await self._close_previous_session()
        self.session_id = await self.repo.create_session(info, self.cars.name(info.car_id))
        self.track_name = ""
        self._session_best_ms = None
        self._prev_best_ms = None
        self._best_ref = None
        log.info("new session %s (car %s)", self.session_id, self.cars.name(info.car_id))
        await self._broadcast({"type": "session", "data": await self.status()})

    async def _close_previous_session(self) -> None:
        """Summarize a finished session, or drop it if it never got a lap.

        One aggregate query serves both paths — loading the lap rows would
        drag every samples_json blob out of the DB just for bookkeeping.
        """
        if self.session_id is None:
            return
        stats = await self.repo.session_lap_stats(self.session_id)
        if stats["count"] == 0:
            # Menu visits and race restarts open sessions that never get a
            # lap; drop them so they don't pile up.
            await self.repo.delete_session(self.session_id)
            log.info("dropped empty session %s", self.session_id)
            return
        self.notifier.session_summary(
            car=self.cars.name(stats["car_id"]),
            track=self.track_name,
            lap_count=stats["count"],
            best_ms=stats["best_ms"],
            fuel_used=stats["fuel_used"],
        )

    async def _on_lap(self, lap: CompletedLap) -> None:
        if self.session_id is None:
            return
        lap_id = await self.repo.save_lap(self.session_id, lap)
        log.info("lap %d saved (%d ms, id=%d)", lap.number, lap.time_ms, lap_id)

        # Remember the best BEFORE this lap: the live "Δ best" compares the
        # latest lap against it (comparing against a best that already
        # includes the latest lap can never show an improvement).
        self._prev_best_ms = self._session_best_ms

        # Personal best (only when beating an existing best, not on the first lap)
        if self._session_best_ms is not None and lap.time_ms < self._session_best_ms:
            self.notifier.personal_best(
                lap.time_ms,
                self._session_best_ms,
                lap.number,
                self.cars.name(lap.car_id),
                self.track_name,
            )
        if self._session_best_ms is None or lap.time_ms < self._session_best_ms:
            self._session_best_ms = lap.time_ms
            self._best_ref = {"dist": lap.samples["dist"], "t": lap.samples["t"]}

        # Track auto-identification from the first completed lap's geometry
        if not self.track_name:
            await self._identify_track(lap)
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
            "tcs_active_pct": round(lap.tcs_active_pct, 1),
            "asm_active_pct": round(lap.asm_active_pct, 1),
            "event_counts": _count_events(lap.events),
        }
        await self._broadcast({"type": "lap", "data": summary})

    async def _identify_track(self, lap: CompletedLap) -> None:
        sig = signature_from_samples(lap.samples)
        if sig is None or self.session_id is None:
            return
        name = await self.repo.find_track(sig)
        if name:
            self.track_name = name
            await self.repo.set_session_track(self.session_id, name)
            log.info("track identified: %s", name)
            await self._broadcast({"type": "session", "data": await self.status()})

    async def name_current_track(self, name: str, lap_samples: dict[str, list[float]]) -> None:
        """Save the current circuit under a name and tag the session with it."""
        sig = signature_from_samples(lap_samples)
        if sig is None:
            raise ValueError("lap has no position data")
        await self.repo.create_track(name, sig)
        self.track_name = name
        if self.session_id is not None:
            await self.repo.set_session_track(self.session_id, name)
        log.info("track saved: %s (%.0f m)", name, sig.length_m)
        await self._broadcast({"type": "session", "data": await self.status()})

    # --- live stream --------------------------------------------------------

    def _live_frame(self, p: TelemetryPacket) -> dict[str, Any]:
        """Compact frame for the live view (~30 Hz)."""
        session = self.processor.session
        live = self.processor.live_lap_samples
        elapsed_ms = round(live["t"][-1] * 1000) if live["t"] else -1
        delta_ms: float | None = None
        if self._best_ref is not None and live["t"] and p.is_on_track and not p.is_paused:
            delta_ms = time_delta_at(live["dist"][-1], live["t"][-1], self._best_ref)
            if delta_ms is not None:
                delta_ms = round(delta_ms)
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
            "oil_pressure": round(p.oil_pressure, 2),
            "aids": p.aids_bits,
            "car_id": p.car_id,
            "car_name": self.cars.name(p.car_id),
            "session_best_ms": session.best_lap_time_ms if session else -1,
            "prev_best_ms": self._prev_best_ms if self._prev_best_ms is not None else -1,
            "delta_ms": delta_ms,
            "lap_elapsed_ms": elapsed_ms,
            "pos_x": round(p.position_x, 2),
            "pos_z": round(p.position_z, 2),
            "tod_ms": p.day_progression_ms,
            "track_name": self.track_name,
        }

    async def status(self) -> dict[str, Any]:
        return {
            "source": self.settings.source,
            "recording": self.recording,
            "session_id": self.session_id,
            "track_name": self.track_name,
            **self.source.stats,
        }

    @property
    def client_count(self) -> int:
        return len(self._clients)

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
            finished_at=datetime.now(UTC).isoformat(),
            car_id=self.latest_packet.car_id if self.latest_packet else 0,
            samples={k: list(v) for k, v in samples.items()},
            fuel_start=samples["fuel"][0],
            fuel_end=samples["fuel"][-1],
        )
        lap.compute_metrics()
        lap_id = await self.repo.save_lap(self.session_id, lap)
        return {"id": lap_id, "number": lap.number, "time_ms": lap.time_ms}
