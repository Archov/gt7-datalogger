"""Per-client WebSocket queues: slow viewers can't stall telemetry capture."""

import asyncio
import json

import pytest

from app.config import Settings
from app.models import SimulatorFlags
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.packet import build_packet, parse_packet

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


class FakeWS:
    """Stands in for a WebSocket; optionally blocks until released."""

    def __init__(self, block: asyncio.Event | None = None) -> None:
        self.sent: list[str] = []
        self.block = block

    async def send_text(self, text: str) -> None:
        if self.block is not None:
            await self.block.wait()
        self.sent.append(text)

    def messages(self, kind: str) -> list[dict]:
        return [m for m in map(json.loads, self.sent) if m["type"] == kind]


@pytest.fixture
async def service(tmp_path):
    settings = Settings(
        source="udp", db_path=tmp_path / "test.db", ws_rate=1000, telemetry_port=43742
    )
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    svc = TelemetryService(settings, repo, CarDatabase())
    svc.processor.min_lap_ticks = 1
    yield svc
    await svc.stop()
    await engine.dispose()


def packet(i: int, lap: int = 1) -> object:
    return parse_packet(
        build_packet(packet_id=i, current_lap=lap, speed_mps=40.0, flags=ON_TRACK)
    )


async def test_slow_client_does_not_block_ingestion(service) -> None:
    release = asyncio.Event()
    slow, fast = FakeWS(block=release), FakeWS()
    await service.register(slow)  # type: ignore[arg-type]
    await service.register(fast)  # type: ignore[arg-type]

    async def feed() -> None:
        for i in range(50):
            await service._on_packet(packet(i))
            await asyncio.sleep(0)

    # The whole feed must complete while one client is fully stalled.
    await asyncio.wait_for(feed(), timeout=1.0)
    await asyncio.sleep(0.01)
    assert fast.messages("telemetry")
    assert service.client_count == 2  # slow frames never evict a client
    release.set()


async def test_slow_client_drops_frames_but_keeps_events(service) -> None:
    release = asyncio.Event()
    slow = FakeWS(block=release)
    await service.register(slow)  # type: ignore[arg-type]
    await asyncio.sleep(0.01)  # let the initial status flush attempt start

    for i in range(20):
        service._publish({"type": "telemetry", "data": {"i": i}})
    service._publish({"type": "lap", "data": {"number": 1}})
    service._publish({"type": "status", "data": {"ok": True}})

    release.set()
    await asyncio.sleep(0.05)
    frames = slow.messages("telemetry")
    assert len(frames) <= 1  # latest wins; intermediates dropped
    if frames:
        assert frames[0]["data"] == {"i": 19}
    assert len(slow.messages("lap")) == 1
    assert len(slow.messages("status")) >= 2  # initial status + published one


async def test_lap_event_delivered_exactly_once(service) -> None:
    ws = FakeWS()
    await service.register(ws)  # type: ignore[arg-type]
    # Lap 1 for a few ticks, then lap 2 with a valid last-lap time -> one lap
    for i in range(10):
        await service._on_packet(packet(i, lap=1))
    await service._on_packet(
        parse_packet(
            build_packet(
                packet_id=10, current_lap=2, last_lap_time_ms=61_000,
                speed_mps=40.0, flags=ON_TRACK,
            )
        )
    )
    await asyncio.sleep(0.05)
    assert len(ws.messages("lap")) == 1


async def test_unregister_cancels_sender(service) -> None:
    ws = FakeWS()
    await service.register(ws)  # type: ignore[arg-type]
    client = service._clients[ws]  # type: ignore[index]
    await service.unregister(ws)  # type: ignore[arg-type]
    assert service.client_count == 0
    assert client.task is not None and client.task.done()


async def test_event_queue_overflow_disconnects_client(service) -> None:
    release = asyncio.Event()
    slow = FakeWS(block=release)
    await service.register(slow)  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    for _ in range(300):  # events queue maxsize is 256
        service._publish({"type": "status", "data": {}})
    assert service.client_count == 0
    release.set()
