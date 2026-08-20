"""Admin API: runtime settings, logs, stats, data management."""

import asyncio
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app import logbuffer
from app.config import Settings
from app.main import create_app
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from tests.test_api import drive_laps


@pytest.fixture
async def client(tmp_path):
    # High port so tests never collide with a live server on 33740.
    settings = Settings(
        source="udp", db_path=tmp_path / "test.db", ws_rate=1000, telemetry_port=43740
    )
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    service = TelemetryService(settings, repo, CarDatabase())
    service.processor.min_lap_ticks = 1

    app = create_app()
    app.router.lifespan_context = None  # type: ignore[assignment]
    app.state.service = service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, service
    await service.stop()
    await engine.dispose()


async def test_get_settings(client) -> None:
    c, _ = client
    data = (await c.get("/api/admin/settings")).json()
    assert data["source"] == "udp"
    assert data["telemetry_port"] == 43740  # fixture overrides the default


async def test_set_ps_ip_applies_and_persists(client) -> None:
    c, service = client
    resp = await c.put("/api/admin/settings", json={"ps_ip": "192.168.1.50"})
    assert resp.status_code == 200
    assert resp.json()["ps_ip"] == "192.168.1.50"
    assert service.settings.ps_ip == "192.168.1.50"
    stored = await service.repo.get_settings()
    assert stored["ps_ip"] == "192.168.1.50"


async def test_set_ps_ip_rejects_garbage(client) -> None:
    c, _ = client
    resp = await c.put("/api/admin/settings", json={"ps_ip": "not an ip !!"})
    assert resp.status_code == 400


async def test_clear_ps_ip_allowed(client) -> None:
    c, service = client
    await c.put("/api/admin/settings", json={"ps_ip": "192.168.1.50"})
    resp = await c.put("/api/admin/settings", json={"ps_ip": ""})
    assert resp.status_code == 200
    assert service.settings.ps_ip == ""


async def test_switch_source(client) -> None:
    c, service = client
    resp = await c.put("/api/admin/settings", json={"source": "sim"})
    assert resp.status_code == 200
    assert service.settings.source == "sim"
    assert type(service.source).__name__ == "SimTelemetrySource"
    resp = await c.put("/api/admin/settings", json={"source": "udp"})
    assert type(service.source).__name__ == "UdpTelemetrySource"


async def test_logs_endpoint(client) -> None:
    c, _ = client
    logbuffer.install()
    logging.getLogger("test.admin").warning("something happened")
    logs = (await c.get("/api/admin/logs")).json()
    assert any(r["message"] == "something happened" for r in logs)
    # level filter
    logs = (await c.get("/api/admin/logs?level=ERROR")).json()
    assert not any(r["message"] == "something happened" for r in logs)
    await c.delete("/api/admin/logs")
    assert (await c.get("/api/admin/logs")).json() == []


async def test_stats(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)
    data = (await c.get("/api/admin/stats")).json()
    assert data["db"]["sessions"] == 1
    assert data["db"]["laps"] == 1
    assert "uptime_s" in data


async def test_clear_data(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)
    resp = await c.post("/api/admin/clear-data")
    assert resp.status_code == 200
    data = (await c.get("/api/admin/stats")).json()
    assert data["db"]["laps"] == 0
    assert service.session_id is None


async def test_archive_hydration_job_reports_progress_and_rejects_duplicate(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, service = client
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_archives() -> list[tuple[int, dict[str, object]]]:
        entered.set()
        await release.wait()
        return []

    monkeypatch.setattr(service.repo, "list_session_archive_metadata", delayed_archives)
    started = await c.post("/api/admin/archive-hydration", json={"mode": "retry_incomplete"})
    assert started.status_code == 202
    assert started.json()["state"] == "running"
    await entered.wait()
    duplicate = await c.post("/api/admin/archive-hydration", json={"mode": "force_all"})
    assert duplicate.status_code == 409
    assert (await c.get("/api/admin/archive-hydration")).json()["state"] == "running"
    assert (await c.post("/api/admin/vacuum")).status_code == 409
    release.set()
    for _ in range(20):
        status = (await c.get("/api/admin/archive-hydration")).json()
        if status["state"] == "completed":
            break
        await asyncio.sleep(0)
    assert status["state"] == "completed"
    assert status["mode"] == "retry_incomplete"


async def test_archive_hydration_rejects_unknown_mode(client) -> None:
    c, _ = client
    response = await c.post("/api/admin/archive-hydration", json={"mode": "unexpected"})
    assert response.status_code == 422


async def test_log_level_change(client) -> None:
    c, _ = client
    resp = await c.put("/api/admin/settings", json={"log_level": "DEBUG"})
    assert resp.status_code == 200
    assert logging.getLogger().level == logging.DEBUG
    await c.put("/api/admin/settings", json={"log_level": "INFO"})


async def test_raw_archive_setting_applies_at_next_session_and_persists(client) -> None:
    c, service = client
    assert (await c.get("/api/admin/settings")).json()["raw_archive"] is True
    resp = await c.put("/api/admin/settings", json={"raw_archive": False})
    assert resp.status_code == 200
    assert resp.json()["raw_archive"] is False
    assert service.settings.raw_archive is False
    assert (await service.repo.get_settings())["raw_archive"] == "false"


async def test_race_engineer_settings_apply_and_persist(client) -> None:
    c, service = client
    resp = await c.put(
        "/api/admin/settings",
        json={
            "race_engineer_verbosity": "coach",
            "race_engineer_categories": ["engine", "strategy"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["race_engineer_verbosity"] == "coach"
    assert body["race_engineer_categories"] == ["strategy", "engine"]  # CATEGORIES order
    # Applied live, not just stored.
    assert service.engineer.verbosity == "coach"
    assert service.engineer.effective_categories == {"engine", "strategy"}
    stored = await service.repo.get_settings()
    assert stored["race_engineer_categories"] == "engine,strategy"


async def test_race_engineer_rejects_unknown_categories(client) -> None:
    c, _ = client
    resp = await c.put(
        "/api/admin/settings", json={"race_engineer_categories": ["engine", "nonsense"]}
    )
    assert resp.status_code == 400


async def test_race_engineer_diagnostics_and_test_callout(client) -> None:
    c, service = client
    data = (await c.get("/api/admin/race-engineer")).json()
    assert data["enabled"] is True
    assert data["active"] is False  # no browser has voice enabled
    assert data["stats"]["emitted"] == 0

    resp = await c.post("/api/admin/race-engineer/test", json={"text": "Radio check."})
    assert resp.status_code == 200
    assert resp.json()["text"] == "Radio check."
    assert service.engineer.diagnostics()["stats"]["emitted"] == 1


async def test_spoken_units_apply_live(client) -> None:
    c, service = client
    resp = await c.put("/api/admin/settings", json={"race_engineer_units": "imperial"})
    assert resp.status_code == 200
    assert resp.json()["race_engineer_units"] == "imperial"
    assert service.engineer.ctx.units == "imperial"
    stored = await service.repo.get_settings()
    assert stored["race_engineer_units"] == "imperial"
