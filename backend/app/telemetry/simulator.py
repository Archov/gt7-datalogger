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
from collections.abc import Awaitable, Callable

from app.models import SimulatorFlags, TelemetryPacket
from app.telemetry.packet import build_packet, parse_packet

log = logging.getLogger(__name__)

TICK = 1 / 60
TRACK_LENGTH = 3200.0  # meters
CAR_ID = 3298  # Shelby GT350R '16 in the bundled cars.csv
FUEL_PER_LAP = 1.8


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
    def __init__(self, on_packet: Callable[[TelemetryPacket], Awaitable[None]]) -> None:
        self._on_packet = on_packet
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
        }

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        log.info("simulated telemetry source started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        rng = random.Random(42)
        distance = 0.0
        lap = 1
        lap_start_tick = 0
        tick = 0
        speed = 40.0
        fuel = 100.0
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
            fuel -= FUEL_PER_LAP * (speed * TICK) / TRACK_LENGTH
            if fuel <= 0:
                fuel = 100.0

            new_lap = int(distance // TRACK_LENGTH) + 1
            if new_lap != lap:
                last_ms = int((tick - lap_start_tick) * TICK * 1000)
                best_ms = last_ms if best_ms < 0 else min(best_ms, last_ms)
                lap = new_lap
                lap_start_tick = tick
                lap_jitter = rng.uniform(-1.5, 1.5)

            # Position on a rounded-rectangle circuit
            angle = s * 2 * math.pi
            px = 500 * math.cos(angle) + 80 * math.cos(3 * angle)
            pz = 300 * math.sin(angle) + 40 * math.sin(2 * angle)

            gear = min(6, max(1, int(speed / 11) + 1))
            rpm = 2000 + (speed * 3.6 % 60) / 60 * 5500 + gear * 100
            slipping = brake > 200 or (throttle == 255 and speed < 25)
            wheel_speed_factor = 1.12 if slipping else 1.0
            wheel_rps = speed * wheel_speed_factor / 0.33

            plain = build_packet(
                packet_id=tick,
                position=(px, 10.0, pz),
                velocity=(speed, 0.0, 0.0),
                angular_velocity=(0.0, math.sin(angle * 2) * 0.3, 0.0),
                body_height=0.08 + rng.uniform(0, 0.01),
                engine_rpm=rpm,
                fuel_level=fuel,
                fuel_capacity=100.0,
                speed_mps=speed,
                boost=0.0,
                tire_temps=(70 + speed / 4, 71 + speed / 4, 68 + speed / 5, 69 + speed / 5),
                current_lap=lap,
                total_laps=0,
                best_lap_time_ms=best_ms,
                last_lap_time_ms=last_ms,
                day_progression_ms=int(tick * TICK * 1000),
                flags=int(SimulatorFlags.CAR_ON_TRACK | SimulatorFlags.IN_GEAR),
                current_gear=gear,
                suggested_gear=15,
                throttle=throttle,
                brake=brake,
                wheel_rps=(wheel_rps, wheel_rps, wheel_rps, wheel_rps),
                car_id=CAR_ID,
            )
            self._packet_count += 1
            await self._on_packet(parse_packet(plain))
            tick += 1
            await asyncio.sleep(TICK)
