"""Simulated telemetry source: drives laps around a synthetic circuit at 60 Hz.

Lets the whole stack (lap detection, storage, live dashboard) run without a
PlayStation. The track is a rounded-rectangle circuit with two hard braking
zones; laps vary slightly so comparison/deviation charts have real content.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from app.models import SimulatorFlags, TelemetryPacket
from app.telemetry.packet import build_packet, parse_packet
from app.telemetry.raw_archive import CapturedPayload, RawPacketCallback

log = logging.getLogger(__name__)

TICK = 1 / 60
TRACK_LENGTH = 3200.0  # meters
CAR_ID = 3298  # Shelby GT350R '16 in the bundled cars.csv
FUEL_PER_LAP = 1.8


@dataclass(slots=True, frozen=True)
class SimScenario:
    """Optional overrides that stage a situation worth talking about.

    The defaults reproduce the original free-practice simulation exactly —
    many tests depend on it, so a scenario only ever adds to that behavior.
    Selected with GT7_SIM_SCENARIO; see SCENARIOS below.
    """

    race_laps: int = 0  # 0 = open practice (no race distance)
    fuel_start: float = 100.0
    fuel_rate: float = 1.0  # multiplier on FUEL_PER_LAP
    temp_offset: float = 0.0  # °C added to water and oil
    oil_pressure_scale: float = 1.0
    race_positions: int = 0  # 0 = no position reporting (GT7 sends -1)


# Scenarios for exercising Race Engineer callouts without a console.
SCENARIOS: dict[str, SimScenario] = {
    "practice": SimScenario(),
    # A short race: final lap, halfway, and positions changing under you.
    "race": SimScenario(race_laps=6, race_positions=8),
    # Not enough fuel to finish: pit window, then the shortage warning.
    "fuel_shortage": SimScenario(race_laps=10, fuel_start=9.0, fuel_rate=2.5),
    "overheating": SimScenario(race_laps=6, temp_offset=35.0),
    "oil_pressure": SimScenario(race_laps=6, oil_pressure_scale=0.2),
}


def scenario_for(name: str) -> SimScenario:
    return SCENARIOS.get(name, SCENARIOS["practice"])


def _speed_profile(s: float, jitter: float) -> float:
    """Target speed (m/s) at track position s in [0, 1).

    Corner speeds are flat steps so the driver must actually brake into them
    (a gradual profile would let partial throttle track it with zero braking).
    """
    base = 62.0  # ~223 km/h baseline
    # Two corners: heavy at 20%, medium at 65%
    for center, width, depth in ((0.20, 0.05, 38.0), (0.65, 0.045, 26.0)):
        d = min(abs(s - center), 1 - abs(s - center))
        if d < width:
            base -= depth
    return max(14.0, base + jitter)


class SimTelemetrySource:
    def __init__(
        self,
        on_packet: Callable[[TelemetryPacket, str | None], Awaitable[None]],
        scenario: SimScenario | None = None,
        on_raw_packet: RawPacketCallback | None = None,
    ) -> None:
        self._on_packet = on_packet
        self._on_raw_packet = on_raw_packet
        self._scenario = scenario or SCENARIOS["practice"]
        self._task: asyncio.Task[None] | None = None
        self._packet_count = 0

    @property
    def connected(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def stats(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "console_ip": "simulated",
            "packets_received": self._packet_count,
            "decode_errors": 0,
            "packet_format": "C",
        }

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        log.info("simulated telemetry source started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        rng = random.Random(42)
        sim = self._scenario
        distance = 0.0
        lap = 1
        lap_start_tick = 0
        tick = 0
        speed = 40.0
        fuel = sim.fuel_start
        # Mid-pack start, gaining a place every other lap: enough for the
        # position detector to have something to stabilize on.
        position = max(1, sim.race_positions // 2) if sim.race_positions else -1
        best_ms = -1
        last_ms = -1
        lap_jitter = rng.uniform(-1.5, 1.5)

        while True:
            s = (distance % TRACK_LENGTH) / TRACK_LENGTH
            target = _speed_profile(s, lap_jitter)
            ahead = _speed_profile((s + 0.006) % 1.0, lap_jitter)
            # Driver model: brake into corners, lift-and-coast just before the
            # brake point, full throttle on straights, hold speed otherwise.
            if target < speed - 2.0:
                throttle, brake = 0, int(min(255, (speed - target) * 22))
                speed = max(target, speed - 22.0 * TICK)
            elif ahead < speed - 5.0:
                throttle, brake = 0, 0
                speed = max(14.0, speed - 2.5 * TICK)
            elif target > speed + 0.5:
                throttle, brake = 255, 0
                speed = min(target, speed + 9.0 * TICK)
            else:
                throttle = 255 if target > 55 else int(140 + rng.uniform(-30, 30))
                brake = 0
                speed = target
            distance += speed * TICK
            fuel -= FUEL_PER_LAP * sim.fuel_rate * (speed * TICK) / TRACK_LENGTH
            if fuel <= 0:
                fuel = sim.fuel_start

            new_lap = int(distance // TRACK_LENGTH) + 1
            if new_lap != lap:
                last_ms = int((tick - lap_start_tick) * TICK * 1000)
                best_ms = last_ms if best_ms < 0 else min(best_ms, last_ms)
                if sim.race_laps and new_lap > sim.race_laps:
                    # Checkered flag: start the race again rather than driving
                    # cool-down laps forever. The lap counter reset is exactly
                    # what a real race restart looks like to the pipeline.
                    distance, new_lap, fuel, best_ms = 0.0, 1, sim.fuel_start, -1
                    position = sim.race_positions // 2 if sim.race_positions else -1
                lap = new_lap
                lap_start_tick = tick
                lap_jitter = rng.uniform(-1.5, 1.5)
                if position > 1 and lap % 2 == 0:
                    position -= 1

            # Position on a rounded-rectangle circuit
            angle = s * 2 * math.pi
            px = 500 * math.cos(angle) + 80 * math.cos(3 * angle)
            pz = 300 * math.sin(angle) + 40 * math.sin(2 * angle)

            gear = min(6, max(1, int(speed / 11) + 1))
            rpm = 2000 + (speed * 3.6 % 60) / 60 * 5500 + gear * 100

            # Per-wheel slip: hard braking locks the fronts, hard launches spin
            # the rears — gives the lockup/wheelspin detectors real events.
            locking = brake > 200
            spinning = throttle == 255 and speed < 25
            base_rps = speed / 0.33
            factor = [1.0, 1.0, 1.0, 1.0]  # FL FR RL RR
            if locking:
                factor[0] = 0.72 + rng.uniform(0, 0.08)
                factor[1] = 0.86 + rng.uniform(0, 0.08)
            if spinning:
                factor[2] = factor[3] = 1.18 + rng.uniform(0, 0.1)
            rps = (
                base_rps * factor[0],
                base_rps * factor[1],
                base_rps * factor[2],
                base_rps * factor[3],
            )

            # Suspension compression (m): braking loads the front axle,
            # cornering loads the outside; corner 1 apex adds a kerb strike.
            lat = math.sin(angle * 2) * 0.3  # matches angular velocity below
            front = 0.030 + (0.028 if brake > 100 else 0.0)
            rear = 0.030 + (0.012 if throttle > 200 else 0.0)
            roll = lat * 0.02
            kerb = 0.05 if abs(s - 0.21) < 0.0008 else 0.0
            suspension = (
                front + max(0, -roll) + kerb + rng.uniform(0, 0.002),
                front + max(0, roll) + rng.uniform(0, 0.002),
                rear + max(0, -roll) + rng.uniform(0, 0.002),
                rear + max(0, roll) + rng.uniform(0, 0.002),
            )

            flags = SimulatorFlags.CAR_ON_TRACK | SimulatorFlags.IN_GEAR
            if spinning:
                flags |= SimulatorFlags.TCS_ACTIVE
            if locking:
                flags |= SimulatorFlags.ASM_ACTIVE
            if rpm > 8600:
                flags |= SimulatorFlags.REV_LIMITER

            plain = build_packet(
                packet_id=tick,
                position=(px, 10.0, pz),
                velocity=(speed, 0.0, 0.0),
                angular_velocity=(0.0, lat, 0.0),
                body_height=0.08 + rng.uniform(0, 0.01),
                engine_rpm=rpm,
                fuel_level=fuel,
                fuel_capacity=100.0,
                speed_mps=speed,
                boost=0.0,
                tire_temps=(70 + speed / 4, 71 + speed / 4, 68 + speed / 5, 69 + speed / 5),
                current_lap=lap,
                total_laps=sim.race_laps,
                best_lap_time_ms=best_ms,
                last_lap_time_ms=last_ms,
                day_progression_ms=int(tick * TICK * 1000),
                race_position=position,
                total_positions=sim.race_positions,
                flags=int(flags),
                current_gear=gear,
                suggested_gear=15,
                throttle=throttle,
                brake=brake,
                wheel_rps=rps,
                suspension=suspension,
                oil_pressure=(6.5 - rpm / 9000 * 1.5) * sim.oil_pressure_scale,
                water_temp=84.0 + (tick % 36000) / 36000 * 8 + sim.temp_offset,
                oil_temp=88.0 + (tick % 36000) / 36000 * 12 + sim.temp_offset,
                gear_ratios=(3.2, 2.3, 1.8, 1.4, 1.15, 0.95),
                transmission_top_speed=290.0,
                car_id=CAR_ID,
                # Packet C extension: exercises the full parse path in dev.
                fmt="C",
                wheel_rotation=lat * 1.2,
                sway=lat * 6.0,
                surge=(throttle - brake) / 255 * 5.0,
                throttle_filtered=throttle,
                brake_filtered=brake,
                surface_types="CTTT" if kerb else "TTTT",
                lap_time_ms=int((tick - lap_start_tick) * TICK * 1000),
                wheel_steering_rad=(lat * 0.3, lat * 0.3),
                wheelbase_m=2.7,
                car_category="GRX",
            )
            capture = CapturedPayload(
                payload=plain,
                received_monotonic_ns=time.monotonic_ns(),
                received_unix_ns=time.time_ns(),
                receiver_order=self._packet_count,
                source="sim",
            )
            packet = parse_packet(plain)
            token = None
            if self._on_raw_packet is not None:
                token = self._on_raw_packet(replace(capture, packet=packet))
            self._packet_count += 1
            await self._on_packet(packet, token)
            tick += 1
            await asyncio.sleep(TICK)
