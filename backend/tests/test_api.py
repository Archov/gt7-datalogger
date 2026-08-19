"""API integration tests against an in-memory pipeline (no UDP, no network)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.export_filenames import attachment_header, lap_export_filename, session_export_filename
from app.main import create_app
from app.models import SimulatorFlags
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.packet import build_packet, parse_packet

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


@pytest.fixture
async def client(tmp_path):
    settings = Settings(source="udp", db_path=tmp_path / "test.db", ws_rate=1000)
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
    await engine.dispose()


async def drive_laps(service: TelemetryService, laps: int = 2, car_id: int = 7) -> None:
    # GT7 keeps last_lap_time_ms set to the previous lap's time on every packet.
    for lap in range(1, laps + 1):
        for tick in range(60):
            await service._on_packet(
                parse_packet(
                    build_packet(
                        packet_id=lap * 100 + tick,
                        current_lap=lap,
                        last_lap_time_ms=59_000 if lap > 1 else -1,
                        speed_mps=40.0 + lap,
                        throttle=255,
                        fuel_level=100.0 - lap,
                        flags=ON_TRACK,
                        car_id=car_id,
                    )
                )
            )
    # Final boundary completes the last lap
    await service._on_packet(
        parse_packet(
            build_packet(
                current_lap=laps + 1,
                last_lap_time_ms=59_000,
                fuel_level=100.0 - laps - 1.5,
                flags=ON_TRACK,
                car_id=car_id,
            )
        )
    )


async def test_empty_sessions_are_dropped(client) -> None:
    """Menu bounces open sessions that never see a lap; when a new session
    starts, the previous empty one is deleted instead of piling up."""
    c, service = client
    # Session A: one real lap
    await drive_laps(service, laps=1)
    # Session B: car change, no laps driven
    await service._on_packet(parse_packet(build_packet(current_lap=1, flags=ON_TRACK, car_id=42)))
    # Session C: another car change — session B was empty and must vanish
    await service._on_packet(parse_packet(build_packet(current_lap=1, flags=ON_TRACK, car_id=43)))
    sessions = (await c.get("/api/sessions")).json()
    lap_counts = [s["lap_count"] for s in sessions]
    assert len(sessions) == 2  # A (1 lap) + C (current, still empty)
    assert sorted(lap_counts) == [0, 1]


async def test_health(client) -> None:
    c, _ = client
    resp = await c.get("/api/health")
    assert resp.status_code == 200


async def test_car_drivetrain_override_is_shared_and_auto_deletes(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)

    response = await c.put("/api/cars/7/drivetrain", json={"drivetrain": "rwd"})
    assert response.status_code == 200
    assert response.json() == {"car_id": 7, "drivetrain_override": "rwd"}
    sessions = (await c.get("/api/sessions")).json()
    assert all(row["drivetrain_override"] == "rwd" for row in sessions)

    await c.post("/api/admin/clear-data")
    assert await service.repo.get_car_drivetrain(7) == "rwd"

    response = await c.put("/api/cars/7/drivetrain", json={"drivetrain": "auto"})
    assert response.status_code == 200
    assert response.json()["drivetrain_override"] is None
    assert await service.repo.get_car_drivetrain(7) is None


async def test_pipeline_persists_sessions_and_laps(client) -> None:
    c, service = client
    await drive_laps(service, laps=2)

    sessions = (await c.get("/api/sessions")).json()
    assert len(sessions) == 1
    assert sessions[0]["lap_count"] == 2

    laps = (await c.get(f"/api/sessions/{sessions[0]['id']}/laps")).json()
    assert len(laps) == 2
    assert all(lap["time_ms"] == 59_000 or lap["time_ms"] > 0 for lap in laps)

    detail = (await c.get(f"/api/laps/{laps[0]['id']}")).json()
    assert "samples" in detail
    assert len(detail["samples"]["speed"]) == 60


async def test_compare_endpoint(client) -> None:
    c, service = client
    await drive_laps(service, laps=2)
    laps = (await c.get("/api/laps")).json()
    ids = [lap["id"] for lap in laps]
    resp = await c.get(
        f"/api/analysis/compare?laps={ids[0]},{ids[1]}&ref={ids[1]}"
        "&channels=speed,orientation_x,orientation_y,orientation_z,orientation_w,"
        "velocity_x,velocity_y,velocity_z"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert str(ids[0]) in data["laps"]
    assert "delta" in data["laps"][str(ids[0])]
    assert "pos_x" in data["laps"][str(ids[1])]["series"]
    assert "orientation_w" in data["laps"][str(ids[1])]["series"]
    assert "velocity_x" in data["laps"][str(ids[1])]["series"]
    assert "peaks_valleys" in data["laps"][str(ids[1])]


async def test_compare_endpoint_preserves_cross_session_selection(client) -> None:
    c, service = client
    await drive_laps(service, laps=1, car_id=7)
    await drive_laps(service, laps=1, car_id=8)
    laps = (await c.get("/api/laps")).json()
    assert {lap["session_id"] for lap in laps} == {1, 2}
    ids = [lap["id"] for lap in laps]

    response = await c.get(
        f"/api/analysis/compare?laps={ids[0]},{ids[1]}&ref={ids[1]}"
        "&channels=orientation_x,orientation_y,orientation_z,orientation_w,"
        "velocity_x,velocity_y,velocity_z"
    )

    assert response.status_code == 200
    assert set(response.json()["laps"]) == {str(ids[0]), str(ids[1])}


async def test_export_import_roundtrip(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)
    laps = (await c.get("/api/laps")).json()
    sessions = (await c.get("/api/sessions")).json()
    export_response = await c.get(f"/api/laps/{laps[0]['id']}/export")
    assert export_response.headers["content-disposition"] == attachment_header(
        lap_export_filename(laps[0], sessions[0], "json")
    )
    exported = export_response.json()
    assert exported["format"] == "gt7-datalogger-lap"
    assert "orientation_w" in exported["lap"]["samples"]
    assert "velocity_x" in exported["lap"]["samples"]

    csv_response = await c.get(f"/api/laps/{laps[0]['id']}/export.csv")
    assert csv_response.headers["content-disposition"] == attachment_header(
        lap_export_filename(laps[0], sessions[0], "csv")
    )
    assert "Orientation X" in csv_response.text
    assert "Velocity X" in csv_response.text

    resp = await c.post("/api/laps/import", json=exported)
    assert resp.status_code == 200
    assert len((await c.get("/api/laps")).json()) == 2


async def test_llm_session_export_and_validation(client) -> None:
    c, service = client
    await drive_laps(service, laps=2)
    sessions = (await c.get("/api/sessions")).json()
    session_id = sessions[0]["id"]
    laps = (await c.get(f"/api/sessions/{session_id}/laps")).json()
    response = await c.get(f"/api/sessions/{session_id}/export.llm.json")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == attachment_header(
        session_export_filename(sessions[0], len(laps))
    )
    data = response.json()
    assert data["format"] == "gt7-datalogger-llm-session"
    assert data["version"] == 1
    assert data["options"]["detail"] == "standard"

    explicit = await c.get(
        f"/api/sessions/{session_id}/export.llm.json?detail=compact"
        f"&segment_m=50&ref={laps[0]['id']}"
    )
    assert explicit.status_code == 200
    assert explicit.json()["reference"]["reason"] == "explicit"
    assert "detail_traces" not in explicit.json()

    assert (await c.get("/api/sessions/999/export.llm.json")).status_code == 404
    assert (await c.get(f"/api/sessions/{session_id}/export.llm.json?ref=999")).status_code == 404
    for query in ("detail=huge", "segment_m=10", "segment_m=not-a-number", "ref=nope"):
        assert (
            await c.get(f"/api/sessions/{session_id}/export.llm.json?{query}")
        ).status_code == 400

    partial = await service.log_lap_now()
    assert partial is not None
    assert (
        await c.get(f"/api/sessions/{session_id}/export.llm.json?ref={partial['id']}")
    ).status_code == 400


async def test_import_rejects_bad_format(client) -> None:
    c, _ = client
    resp = await c.post("/api/laps/import", json={"format": "nope", "version": 1, "lap": {}})
    assert resp.status_code == 400


async def test_fuel_endpoint(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)
    laps = (await c.get("/api/laps")).json()
    resp = await c.get(f"/api/analysis/fuel?lap_id={laps[0]['id']}")
    assert resp.status_code == 200
    assert len(resp.json()["rows"]) == 11
