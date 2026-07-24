"""Lap detection, session boundaries, and lap metrics."""

import pytest

from app.models import SimulatorFlags, TelemetryPacket
from app.processing.laps import CompletedLap, LapProcessor, SessionInfo
from app.telemetry.packet import build_packet, parse_packet

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


def make_packet(**kwargs) -> TelemetryPacket:
    kwargs.setdefault("flags", ON_TRACK)
    return parse_packet(build_packet(**kwargs))


class Collector:
    def __init__(self) -> None:
        self.laps: list[CompletedLap] = []
        self.sessions: list[SessionInfo] = []

    async def on_lap(self, lap: CompletedLap) -> None:
        self.laps.append(lap)

    async def on_session(self, info: SessionInfo) -> None:
        self.sessions.append(info)


@pytest.fixture
def setup() -> tuple[LapProcessor, Collector]:
    c = Collector()
    return LapProcessor(on_lap=c.on_lap, on_session=c.on_session), c


async def feed_lap(proc: LapProcessor, lap_number: int, ticks: int, **kw) -> None:
    for _ in range(ticks):
        await proc.feed(make_packet(current_lap=lap_number, **kw))


async def test_lap_completion(setup) -> None:
    proc, c = setup
    await feed_lap(proc, 1, 120, speed_mps=50.0, throttle=255, fuel_level=100.0)
    # Crossing the line: counter advances, game reports last lap time
    await proc.feed(
        make_packet(current_lap=2, last_lap_time_ms=61_500, fuel_level=98.0, speed_mps=50.0)
    )
    assert len(c.laps) == 1
    lap = c.laps[0]
    assert lap.number == 1
    assert lap.time_ms == 61_500
    assert lap.total_ticks == 120
    assert lap.fuel_consumed == pytest.approx(2.0)
    assert lap.full_throttle_pct == pytest.approx(100.0)
    assert lap.max_speed == pytest.approx(180.0)


async def test_no_lap_on_first_boundary(setup) -> None:
    """Going from menu (lap 0) onto track (lap 1) must not emit a lap."""
    proc, c = setup
    await feed_lap(proc, 0, 10)
    await feed_lap(proc, 1, 10)
    assert c.laps == []


async def test_session_starts_once(setup) -> None:
    proc, c = setup
    await feed_lap(proc, 1, 10)
    await feed_lap(proc, 2, 10, last_lap_time_ms=60_000)
    assert len(c.sessions) == 1


async def test_new_session_on_car_change(setup) -> None:
    proc, c = setup
    await feed_lap(proc, 1, 10, car_id=100)
    await feed_lap(proc, 1, 10, car_id=200)
    assert len(c.sessions) == 2
    assert c.sessions[1].car_id == 200


async def test_new_session_on_lap_reset(setup) -> None:
    """Race restart: lap counter drops back to 1."""
    proc, c = setup
    await feed_lap(proc, 3, 10)
    await feed_lap(proc, 1, 10)
    assert len(c.sessions) == 2


async def test_new_session_on_lap_reset_to_zero(setup) -> None:
    """Race restart: lap counter drops back to 0 (out-lap)."""
    proc, c = setup
    await feed_lap(proc, 3, 10)
    await feed_lap(proc, 0, 10)
    assert len(c.sessions) == 2


async def test_paused_samples_not_recorded(setup) -> None:
    proc, _ = setup
    await feed_lap(proc, 1, 10)
    await feed_lap(proc, 1, 10, flags=ON_TRACK | int(SimulatorFlags.PAUSED))
    assert len(proc.live_lap_samples["t"]) == 10


async def test_coasting_and_metrics(setup) -> None:
    proc, c = setup
    # 50 ticks full throttle, 30 full brake, 20 coasting
    await feed_lap(proc, 1, 50, throttle=255, brake=0)
    await feed_lap(proc, 1, 30, throttle=0, brake=255)
    await feed_lap(proc, 1, 20, throttle=0, brake=0)
    await proc.feed(make_packet(current_lap=2, last_lap_time_ms=30_000))
    lap = c.laps[0]
    assert lap.full_throttle_pct == pytest.approx(50.0)
    assert lap.full_brake_pct == pytest.approx(30.0)
    assert lap.coasting_pct == pytest.approx(20.0)


async def test_distance_integration(setup) -> None:
    proc, _ = setup
    # 60 ticks at 60 m/s = 1 second = 60 m
    await feed_lap(proc, 1, 60, speed_mps=60.0)
    assert proc.live_lap_samples["dist"][-1] == pytest.approx(60.0, abs=0.1)


async def test_no_duplicate_laps_while_save_is_slow() -> None:
    """Regression: with a real console, packets keep arriving while a
    completed lap is being persisted. A stale lap counter during that await
    used to re-trigger the boundary once per packet (dozens of identical
    lap rows saved within milliseconds)."""
    import asyncio

    collector = Collector()

    async def slow_on_lap(lap: CompletedLap) -> None:
        await asyncio.sleep(0.05)  # simulate the DB write
        collector.laps.append(lap)

    proc = LapProcessor(on_lap=slow_on_lap, on_session=collector.on_session)
    await feed_lap(proc, 1, 30, speed_mps=50.0)

    # The boundary packet plus a burst of following packets, processed
    # concurrently the way the UDP path used to dispatch them.
    tasks = [
        asyncio.create_task(
            proc.feed(make_packet(current_lap=2, last_lap_time_ms=61_000, speed_mps=50.0))
        )
        for _ in range(10)
    ]
    await asyncio.gather(*tasks)
    assert len(collector.laps) == 1
    assert collector.laps[0].number == 1


async def test_no_samples_recorded_after_race_finish(setup) -> None:
    """After the checkered flag GT7 reports current_lap = total_laps + 1;
    the cool-down driving must not be recorded as a lap in progress."""
    proc, c = setup
    await feed_lap(proc, 5, 10, total_laps=5)
    await proc.feed(make_packet(current_lap=6, total_laps=5, last_lap_time_ms=59_000))
    assert len(c.laps) == 1  # final lap still completes
    await feed_lap(proc, 6, 20, total_laps=5, speed_mps=30.0)
    assert len(proc.live_lap_samples["t"]) == 0
