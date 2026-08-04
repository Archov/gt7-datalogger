"""Telemetry source lifecycle: restarts and source switches release cleanly."""

import pytest

from app.config import Settings
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.listener import UdpTelemetrySource
from app.telemetry.simulator import SimTelemetrySource


@pytest.fixture
async def service(tmp_path):
    # High port so tests never collide with a live server on 33740.
    settings = Settings(
        source="udp", db_path=tmp_path / "test.db", ws_rate=1000, telemetry_port=43741
    )
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    svc = TelemetryService(settings, repo, CarDatabase())
    yield svc
    await svc.stop()
    await engine.dispose()


async def test_switch_source_rebinds_udp_port_cleanly(service) -> None:
    await service.start()
    # Each switch stops the old source (releasing the UDP port) and binds a
    # new one on the same port — any lingering task/socket raises OSError.
    for _ in range(5):
        await service.switch_source("udp")
    assert isinstance(service.source, UdpTelemetrySource)
    assert service.source._transport is not None


async def test_switch_between_sim_and_udp_repeatedly(service) -> None:
    await service.start()
    for _ in range(3):
        await service.switch_source("sim")
        assert isinstance(service.source, SimTelemetrySource)
        assert service.source.stats["console_ip"] == "simulated"
        await service.switch_source("udp")
        assert isinstance(service.source, UdpTelemetrySource)
        assert "packet_format" in service.source.stats


async def test_stop_clears_source_tasks(service) -> None:
    await service.start()
    assert service.source._tasks
    await service.source.stop()
    assert service.source._tasks == []
    assert service.source._transport is None

    await service.switch_source("sim")
    await service.source.stop()
    assert service.source._task is None


async def test_stop_without_start_is_safe(service) -> None:
    # test fixtures routinely stop never-started services
    await service.stop()
