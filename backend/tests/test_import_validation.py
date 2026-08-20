"""Lap import validation: malformed files get a 400, never a stored 500-bomb."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import routes
from app.config import Settings
from app.main import create_app
from app.processing.cars import CarCatalog
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from tests.test_api import drive_laps


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        source="udp", db_path=tmp_path / "test.db", ws_rate=1000, telemetry_port=43743
    )
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    service = TelemetryService(settings, repo, CarCatalog(repo))
    service.processor.min_lap_ticks = 1

    app = create_app()
    app.router.lifespan_context = None  # type: ignore[assignment]
    app.state.service = service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, service
    await service.stop()
    await engine.dispose()


async def exported_lap(c, service) -> dict:
    await drive_laps(service)
    lap_id = (await c.get("/api/laps")).json()[0]["id"]
    return (await c.get(f"/api/laps/{lap_id}/export")).json()


async def test_missing_required_column_400(client) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    del payload["lap"]["samples"]["dist"]
    resp = await c.post("/api/laps/import", json=payload)
    assert resp.status_code == 400
    assert "dist" in resp.json()["detail"]


async def test_ragged_column_lengths_400(client) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    payload["lap"]["samples"]["speed"] = payload["lap"]["samples"]["speed"][:-5]
    resp = await c.post("/api/laps/import", json=payload)
    assert resp.status_code == 400
    assert "unequal" in resp.json()["detail"]


async def test_string_sample_values_400(client) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    n = len(payload["lap"]["samples"]["t"])
    payload["lap"]["samples"]["speed"] = ["fast"] * n
    resp = await c.post("/api/laps/import", json=payload)
    assert resp.status_code == 400


@pytest.mark.parametrize("version", [1, 2, 3])
async def test_legacy_import_without_native_velocity_remains_valid(client, version: int) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    payload["version"] = version
    for channel in ("velocity_x", "velocity_y", "velocity_z"):
        payload["lap"]["samples"].pop(channel)

    response = await c.post("/api/laps/import", json=payload)

    assert response.status_code == 200
    imported = (await c.get(f"/api/laps/{response.json()['id']}")).json()
    assert "velocity_x" not in imported["samples"]


async def test_non_finite_values_400(client) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    payload["lap"]["samples"]["speed"][0] = float("inf")
    # json.dumps would refuse Infinity in strict mode; send it the way a
    # hostile client would (python's default json allows it).
    body = json.dumps(payload)
    resp = await c.post(
        "/api/laps/import", content=body, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400
    assert "non-finite" in resp.json()["detail"]


async def test_oversized_import_400(client, monkeypatch) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    monkeypatch.setattr(routes, "MAX_IMPORT_SAMPLES", 10)
    resp = await c.post("/api/laps/import", json=payload)
    assert resp.status_code == 400
    assert "sample count" in resp.json()["detail"]


async def test_samples_not_a_dict_400(client) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    payload["lap"]["samples"] = [1, 2, 3]
    resp = await c.post("/api/laps/import", json=payload)
    assert resp.status_code == 400


async def test_unknown_extra_column_is_dropped(client) -> None:
    c, service = client
    payload = await exported_lap(c, service)
    n = len(payload["lap"]["samples"]["t"])
    payload["lap"]["samples"]["future_channel"] = [0.0] * n
    resp = await c.post("/api/laps/import", json=payload)
    assert resp.status_code == 200
    lap = (await c.get(f"/api/laps/{resp.json()['id']}")).json()
    assert "future_channel" not in lap["samples"]


async def test_rejected_import_creates_no_session(client) -> None:
    c, _service = client
    bad = {"format": "gt7-datalogger-lap", "version": 2, "lap": {"samples": {}}}
    resp = await c.post("/api/laps/import", json=bad)
    assert resp.status_code == 400
    assert (await c.get("/api/sessions")).json() == []
