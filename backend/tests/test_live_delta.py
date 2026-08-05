"""Live delta-to-best: the mid-lap gap vs the session-best lap's trace."""

import pytest

from app.config import Settings
from app.models import SimulatorFlags
from app.processing.analysis import time_delta_at
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.packet import build_packet, parse_packet

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


# --- pure helper ------------------------------------------------------------


def test_time_delta_at_sign_and_interpolation() -> None:
    # Reference: 1 m/s — t == dist numerically.
    ref = {"dist": [0.0, 10.0, 20.0], "t": [0.0, 10.0, 20.0]}
    # On pace at the same point
    assert time_delta_at(10.0, 10.0, ref) == 0.0
    # 2 s behind, halfway between samples (interpolated ref t = 15)
    assert time_delta_at(15.0, 17.0, ref) == pytest.approx(2000.0)
    # 3 s ahead
    assert time_delta_at(5.0, 2.0, ref) == pytest.approx(-3000.0)


def test_time_delta_at_edges() -> None:
    assert time_delta_at(5.0, 5.0, {"dist": [], "t": []}) is None
    # Past the reference's final sample: no comparison, not a clamped one
    ref = {"dist": [0.0, 10.0], "t": [0.0, 10.0]}
    assert time_delta_at(10.5, 11.0, ref) is None
    assert time_delta_at(10.0, 12.0, ref) == pytest.approx(2000.0)


# --- through the service ----------------------------------------------------


@pytest.fixture
async def service(tmp_path):
    settings = Settings(source="udp", db_path=tmp_path / "test.db", ws_rate=1000)
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    svc = TelemetryService(settings, repo, CarDatabase())
    svc.processor.min_lap_ticks = 1
    yield svc
    await engine.dispose()


def packet(lap: int, speed: float, last_ms: int = -1):
    return parse_packet(
        build_packet(
            current_lap=lap,
            speed_mps=speed,
            last_lap_time_ms=last_ms,
            flags=ON_TRACK,
            car_id=7,
        )
    )


async def drive(service: TelemetryService, lap: int, speed: float, ticks: int):
    p = None
    for _ in range(ticks):
        p = packet(lap, speed)
        await service._on_packet(p)
    return p


async def test_live_delta_null_without_reference(service) -> None:
    p = await drive(service, lap=1, speed=40.0, ticks=30)
    frame = service._live_frame(p)
    assert frame["delta_ms"] is None
    assert frame["lap_elapsed_ms"] > 0


async def test_live_delta_tracks_pace_vs_session_best(service) -> None:
    # Lap 1 at 40 m/s becomes the session best (and the delta reference)
    await drive(service, lap=1, speed=40.0, ticks=60)
    await service._on_packet(packet(lap=2, speed=40.0, last_ms=59_000))
    assert service._best_ref is not None

    # Faster than the reference: gaining time, delta negative
    p = await drive(service, lap=2, speed=50.0, ticks=20)
    fast = service._live_frame(p)["delta_ms"]
    assert fast is not None and fast < 0

    # Complete lap 2 (slower time keeps lap 1 as the reference)
    await service._on_packet(packet(lap=3, speed=40.0, last_ms=60_000))

    # Slower than the reference: losing time, delta positive
    p = await drive(service, lap=3, speed=30.0, ticks=20)
    slow = service._live_frame(p)["delta_ms"]
    assert slow is not None and slow > 0


async def test_live_delta_null_past_reference_distance(service) -> None:
    # Reference covers 60 ticks * 40/60 = 40 m
    await drive(service, lap=1, speed=40.0, ticks=60)
    await service._on_packet(packet(lap=2, speed=40.0, last_ms=59_000))
    # 60 ticks at 50 m/s = 50 m > the reference's 40 m
    p = await drive(service, lap=2, speed=50.0, ticks=60)
    assert service._live_frame(p)["delta_ms"] is None


async def test_live_delta_reference_resets_with_session(service) -> None:
    await drive(service, lap=1, speed=40.0, ticks=60)
    await service._on_packet(packet(lap=2, speed=40.0, last_ms=59_000))
    assert service._best_ref is not None
    # Car change starts a new session — the old trace must not leak into it
    await service._on_packet(
        parse_packet(build_packet(current_lap=1, speed_mps=40.0, flags=ON_TRACK, car_id=42))
    )
    assert service._best_ref is None


async def test_partial_outlap_never_stays_the_reference(service) -> None:
    """A short pit out-lap gets a GT7 lap time but covers a fraction of the
    track with a pit-exit-anchored distance axis — the first full lap must
    replace it as session best / delta reference even though it's slower."""
    await drive(service, lap=1, speed=40.0, ticks=30)  # out-lap: ~20 m span
    await service._on_packet(packet(lap=2, speed=40.0, last_ms=60_500))
    assert service._best_ref is not None  # baseline until proven partial

    await drive(service, lap=2, speed=40.0, ticks=300)  # full lap: ~200 m
    await service._on_packet(packet(lap=3, speed=40.0, last_ms=118_900))

    assert service._session_best_ms == 118_900  # slower but real
    assert service.processor.session is not None
    assert service.processor.session.best_lap_time_ms == 118_900
    ref = service._best_ref
    assert ref is not None
    assert ref["dist"][-1] == pytest.approx(300 * 40 / 60, rel=0.05)

    p = await drive(service, lap=3, speed=40.0, ticks=5)
    frame = service._live_frame(p)
    assert frame["session_best_ms"] == 118_900
    # prev_best must not point at the phantom out-lap time — the delta
    # widget's end-of-lap fallback would otherwise show last-lap minus
    # out-lap (~+58 s, frozen for the rest of the lap).
    assert frame["prev_best_ms"] == -1


async def test_later_pit_outlap_does_not_steal_best(service) -> None:
    await drive(service, lap=1, speed=40.0, ticks=300)
    await service._on_packet(packet(lap=2, speed=40.0, last_ms=118_900))
    assert service._session_best_ms == 118_900

    # Mid-race pit stop: short lap with a meaninglessly low reported time
    await drive(service, lap=2, speed=40.0, ticks=30)
    await service._on_packet(packet(lap=3, speed=40.0, last_ms=45_000))

    assert service._session_best_ms == 118_900
    assert service.processor.session is not None
    assert service.processor.session.best_lap_time_ms == 118_900
    ref = service._best_ref
    assert ref is not None
    assert ref["dist"][-1] == pytest.approx(300 * 40 / 60, rel=0.05)
