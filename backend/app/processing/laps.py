"""Lap detection and per-lap sample series derived from the 60 Hz stream."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models import TelemetryPacket

log = logging.getLogger(__name__)

TICK_SECONDS = 1 / 60
FULL_INPUT = 250  # of 255; GT7 rarely reports exactly 255 with analog triggers
TIRE_SPIN_THRESHOLD = 1.1
# A "completed lap" with almost no samples is a phantom: GT7's lap counter
# flickers through old values in menus/replays and re-reports a stale
# last_lap_time. No real lap is shorter than this many ticks (~10 s).
MIN_LAP_TICKS = 600

# Columnar per-tick series kept for each lap. Column order matters for the
# frontend; keep in sync with frontend/src/lib/types.ts.
SAMPLE_COLUMNS = (
    "t", "dist", "speed", "throttle", "brake", "coast", "gear", "rpm",
    "boost", "tire_slip", "yaw_rate", "pos_x", "pos_z", "body_height", "fuel",
    # Tier 1 per-corner channels (FL FR RL RR)
    "slip_fl", "slip_fr", "slip_rl", "slip_rr",
    "tt_fl", "tt_fr", "tt_rl", "tt_rr",
    "sus_fl", "sus_fr", "sus_rl", "sus_rr",  # suspension compression, mm
    "aids",  # AidsBits mask: TCS | ASM | handbrake | rev limiter
)


def new_sample_store() -> dict[str, list[float]]:
    return {c: [] for c in SAMPLE_COLUMNS}


@dataclass(slots=True)
class CompletedLap:
    number: int
    time_ms: int
    finished_at: str
    car_id: int
    samples: dict[str, list[float]]
    fuel_start: float
    fuel_end: float
    tod_ms: int = -1  # in-game time of day when the lap completed
    # metrics
    fuel_consumed: float = 0.0
    full_throttle_pct: float = 0.0
    full_brake_pct: float = 0.0
    coasting_pct: float = 0.0
    tire_spin_pct: float = 0.0
    max_speed: float = 0.0
    min_body_height: float = 0.0
    total_ticks: int = 0
    tcs_active_pct: float = 0.0
    asm_active_pct: float = 0.0
    # Engine health — per-lap aggregates only (these drift over minutes, not
    # corners), tracked by the processor rather than sampled per tick.
    max_water_temp: float = 0.0
    max_oil_temp: float = 0.0
    min_oil_pressure: float = -1.0  # sampled above idle rpm only; -1 = unknown
    # Static per lap: {"ratios": [...], "top_speed": float, "rpm_alert": float}
    gearing: dict[str, object] | None = None
    events: list[dict[str, object]] = field(default_factory=list)

    def compute_metrics(self) -> None:
        # Imported laps from older export versions may lack the newer columns;
        # every metric guards with .get so they degrade to 0 rather than raise.
        from app.models import AidsBits
        from app.processing.events import detect_events

        s = self.samples
        n = len(s["t"])
        self.total_ticks = n
        if n == 0:
            return
        self.fuel_consumed = max(0.0, self.fuel_start - self.fuel_end)
        self.full_throttle_pct = 100.0 * sum(1 for v in s["throttle"] if v >= 98.0) / n
        self.full_brake_pct = 100.0 * sum(1 for v in s["brake"] if v >= 98.0) / n
        self.coasting_pct = 100.0 * sum(1 for v in s["coast"] if v > 0) / n
        self.tire_spin_pct = 100.0 * sum(
            1 for v in s["tire_slip"] if v >= TIRE_SPIN_THRESHOLD
        ) / n
        self.max_speed = max(s["speed"])
        self.min_body_height = min(s["body_height"])
        aids = s.get("aids") or []
        if aids:
            self.tcs_active_pct = 100.0 * sum(1 for v in aids if int(v) & AidsBits.TCS) / n
            self.asm_active_pct = 100.0 * sum(1 for v in aids if int(v) & AidsBits.ASM) / n
        self.events = detect_events(s)


@dataclass(slots=True)
class SessionInfo:
    car_id: int
    started_at: str
    lap_count: int = 0
    best_lap_time_ms: int = -1


LapCallback = Callable[[CompletedLap], Awaitable[None]]
SessionCallback = Callable[[SessionInfo], Awaitable[None]]


@dataclass
class LapProcessor:
    """Consumes packets, emits completed laps and session boundaries.

    A new session starts when the car changes, or when the lap counter resets
    (race restart / return to track). Time-trial "lap 0" out-laps are ignored.
    """

    on_lap: LapCallback
    on_session: SessionCallback
    min_lap_ticks: int = MIN_LAP_TICKS

    _session: SessionInfo | None = None
    _current_lap: int = -1
    _samples: dict[str, list[float]] = field(default_factory=new_sample_store)
    _distance: float = 0.0
    _ticks: int = 0
    _fuel_start: float = 0.0
    _last_packet: TelemetryPacket | None = None
    # Engine-health aggregates for the lap in progress (not per-tick columns)
    _max_water: float = 0.0
    _max_oil: float = 0.0
    _min_oil_pressure: float = -1.0

    @property
    def session(self) -> SessionInfo | None:
        return self._session

    @property
    def live_lap_samples(self) -> dict[str, list[float]]:
        return self._samples

    async def feed(self, p: TelemetryPacket) -> None:
        if p.is_loading:
            return

        if self._session is not None and p.car_id != self._session.car_id:
            log.info("car changed (%d -> %d): starting new session", self._session.car_id, p.car_id)
            self._session = None

        lap_reset = (
            self._current_lap > 0 and 0 <= p.current_lap < self._current_lap
        )
        if self._session is None or lap_reset:
            self._session = SessionInfo(
                car_id=p.car_id,
                started_at=datetime.now(UTC).isoformat(),
            )
            self._current_lap = -1
            await self.on_session(self._session)

        if p.current_lap != self._current_lap:
            await self._handle_lap_boundary(p)

        # After the checkered flag GT7 reports current_lap = total_laps + 1;
        # the cool-down lap is not real driving, so don't record it.
        past_finish = 0 < p.total_laps < p.current_lap
        if p.is_on_track and not p.is_paused and p.current_lap > 0 and not past_finish:
            self._append_sample(p)
        self._last_packet = p

    async def _handle_lap_boundary(self, p: TelemetryPacket) -> None:
        prev = self._current_lap
        completing = (
            prev > 0
            and p.current_lap == prev + 1
            and p.last_lap_time_ms > 0
            and len(self._samples["t"]) >= self.min_lap_ticks
        )
        finished_samples = self._samples
        fuel_start = self._fuel_start
        engine = (self._max_water, self._max_oil, self._min_oil_pressure)

        # Commit all state BEFORE any await: packets keep arriving while the
        # lap is persisted, and a stale _current_lap would re-trigger this
        # boundary once per packet (duplicate laps at ~60 Hz).
        self._current_lap = p.current_lap
        self._samples = new_sample_store()
        self._distance = 0.0
        self._ticks = 0
        self._fuel_start = p.fuel_level
        self._max_water = 0.0
        self._max_oil = 0.0
        self._min_oil_pressure = -1.0

        if completing:
            lap = CompletedLap(
                number=prev,
                time_ms=p.last_lap_time_ms,
                finished_at=datetime.now(UTC).isoformat(),
                car_id=p.car_id,
                samples=finished_samples,
                fuel_start=fuel_start,
                fuel_end=p.fuel_level,
                tod_ms=p.day_progression_ms,
            )
            lap.max_water_temp = round(engine[0], 1)
            lap.max_oil_temp = round(engine[1], 1)
            lap.min_oil_pressure = round(engine[2], 3)
            lap.gearing = {
                "ratios": [round(r, 4) for r in p.gear_ratios if r > 0],
                "top_speed": round(p.transmission_top_speed, 1),
                "rpm_alert": p.rpm_alert_max,
            }
            lap.compute_metrics()
            assert self._session is not None
            self._session.lap_count += 1
            if self._session.best_lap_time_ms < 0 or lap.time_ms < self._session.best_lap_time_ms:
                self._session.best_lap_time_ms = lap.time_ms
            await self.on_lap(lap)

    def _append_sample(self, p: TelemetryPacket) -> None:
        self._distance += p.speed_mps * TICK_SECONDS
        s = self._samples
        throttle = round(p.throttle_pct, 1)
        brake = round(p.brake_pct, 1)
        s["t"].append(round(self._ticks * TICK_SECONDS, 4))
        s["dist"].append(round(self._distance, 2))
        s["speed"].append(round(p.speed_kmh, 2))
        s["throttle"].append(throttle)
        s["brake"].append(brake)
        s["coast"].append(1.0 if throttle < 1 and brake < 1 else 0.0)
        s["gear"].append(float(p.current_gear))
        s["rpm"].append(round(p.engine_rpm, 1))
        s["boost"].append(round(p.boost, 3))
        s["tire_slip"].append(round(p.tire_slip_ratio, 4))
        s["yaw_rate"].append(round(abs(p.angular_velocity_y), 4))
        s["pos_x"].append(round(p.position_x, 2))
        s["pos_z"].append(round(p.position_z, 2))
        s["body_height"].append(round(p.body_height * 1000, 1))  # mm
        s["fuel"].append(round(p.fuel_level, 3))
        slips = p.wheel_slips
        for i, w in enumerate(("fl", "fr", "rl", "rr")):
            s[f"slip_{w}"].append(round(slips[i], 4))
        s["tt_fl"].append(round(p.tire_temp_fl, 1))
        s["tt_fr"].append(round(p.tire_temp_fr, 1))
        s["tt_rl"].append(round(p.tire_temp_rl, 1))
        s["tt_rr"].append(round(p.tire_temp_rr, 1))
        s["sus_fl"].append(round(p.suspension_fl * 1000, 1))  # mm
        s["sus_fr"].append(round(p.suspension_fr * 1000, 1))
        s["sus_rl"].append(round(p.suspension_rl * 1000, 1))
        s["sus_rr"].append(round(p.suspension_rr * 1000, 1))
        s["aids"].append(float(p.aids_bits))
        # Engine-health aggregates (per-lap, not per-tick)
        self._max_water = max(self._max_water, p.water_temp)
        self._max_oil = max(self._max_oil, p.oil_temp)
        if p.engine_rpm > 1200:  # ignore idle — pressure at idle is meaningless
            self._min_oil_pressure = (
                p.oil_pressure
                if self._min_oil_pressure < 0
                else min(self._min_oil_pressure, p.oil_pressure)
            )
        self._ticks += 1
