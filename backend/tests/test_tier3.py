"""Tier 3 features: track identification, CSV export, webhooks, time of day."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import SimulatorFlags
from app.notify import Notifier, format_lap_time
from app.processing.cars import CarDatabase
from app.processing.laps import new_sample_store
from app.processing.tracks import TrackSignature, matches, signature_from_samples
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.packet import build_packet, parse_packet
from tests.test_api import drive_laps

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


# --- track signatures -------------------------------------------------------


def make_samples(length: float = 4000.0, w: float = 800.0, h: float = 400.0):
    s = new_sample_store()
    n = 50
    for i in range(n):
        frac = i / (n - 1)
        s["dist"].append(length * frac)
        s["pos_x"].append(w * frac - w / 2)
        s["pos_z"].append(h * (frac % 0.5) - h / 4)
    return s


def test_signature_from_samples() -> None:
    sig = signature_from_samples(make_samples())
    assert sig is not None
    assert sig.length_m == 4000.0
    assert sig.max_x - sig.min_x == pytest.approx(800.0)


def test_signature_empty_samples() -> None:
    assert signature_from_samples(new_sample_store()) is None


def test_track_matching_tolerances() -> None:
    base = TrackSignature(4000, -400, 400, -100, 300)
    assert matches(TrackSignature(4050, -395, 405, -98, 305), base)  # small drift ok
    assert not matches(TrackSignature(5000, -400, 400, -100, 300), base)  # wrong length
    assert not matches(TrackSignature(4000, 600, 1400, -100, 300), base)  # elsewhere


async def test_track_auto_identification(tmp_path) -> None:
    settings = Settings(source="udp", db_path=tmp_path / "t.db", ws_rate=1000)
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))

    # Store a track whose signature matches the laps drive_laps produces
    service = TelemetryService(settings, repo, CarDatabase())
    service.processor.min_lap_ticks = 1
    await drive_laps(service, laps=1)
    laps = await repo.list_laps()
    samples = (await repo.get_lap(laps[0]["id"]))["samples"]
    real_sig = signature_from_samples(samples)
    assert real_sig is not None
    await repo.create_track("Test Ring", real_sig)

    # A fresh service on the same "track" should auto-identify it
    service2 = TelemetryService(settings, repo, CarDatabase())
    service2.processor.min_lap_ticks = 1
    await drive_laps(service2, laps=1)
    assert service2.track_name == "Test Ring"
    sessions = await repo.list_sessions()
    assert sessions[0]["track_name"] == "Test Ring"
    await engine.dispose()


# --- CSV export -------------------------------------------------------------


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


async def test_csv_export(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)
    laps = (await c.get("/api/laps")).json()
    resp = await c.get(f"/api/laps/{laps[0]['id']}/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == '"Format","MoTeC CSV File"'
    header_idx = next(i for i, line in enumerate(lines) if line.startswith('"Time"'))
    channels = lines[header_idx].count(",") + 1
    units = lines[header_idx + 1].count(",") + 1
    first_row = lines[header_idx + 2].count(",") + 1
    assert channels == units == first_row
    # 60 data rows for 60 sampled ticks
    assert len(lines) - (header_idx + 2) == 60


async def test_csv_export_missing_lap(client) -> None:
    c, _ = client
    assert (await c.get("/api/laps/9999/export.csv")).status_code == 404


# --- tracks API -------------------------------------------------------------


async def test_create_and_match_track_via_api(client) -> None:
    c, service = client
    await drive_laps(service, laps=1)
    laps = (await c.get("/api/laps")).json()
    resp = await c.post("/api/tracks", json={"name": "My Circuit", "lap_id": laps[0]["id"]})
    assert resp.status_code == 200
    assert service.track_name == "My Circuit"
    tracks = (await c.get("/api/tracks")).json()
    assert tracks[0]["name"] == "My Circuit"
    sessions = (await c.get("/api/sessions")).json()
    assert sessions[0]["track_name"] == "My Circuit"


# --- time of day ------------------------------------------------------------


async def test_lap_records_time_of_day(client) -> None:
    c, service = client
    for tick in range(30):
        await service._on_packet(
            parse_packet(
                build_packet(
                    packet_id=tick, current_lap=1, speed_mps=40.0,
                    day_progression_ms=50_000_000, flags=ON_TRACK,
                )
            )
        )
    await service._on_packet(
        parse_packet(
            build_packet(
                current_lap=2, last_lap_time_ms=59_000,
                day_progression_ms=50_100_000, flags=ON_TRACK,
            )
        )
    )
    laps = (await c.get("/api/laps")).json()
    assert laps[0]["tod_ms"] == 50_100_000


# --- webhooks ---------------------------------------------------------------


def test_format_lap_time() -> None:
    assert format_lap_time(61_500) == "1:01.500"


async def test_pb_notification_logic(client, monkeypatch) -> None:
    _, service = client
    events: list[str] = []
    monkeypatch.setattr(
        Notifier, "notify",
        lambda self, event, title, fields: events.append(event),
    )
    service.notifier.url = "https://example.invalid/hook"
    # lap 1 (no PB - first lap), lap 2 slower (no PB), lap 3 faster (PB)
    times = [60_000, 61_000, 58_000]
    for i, _t in enumerate(times, start=1):
        for tick in range(10):
            await service._on_packet(
                parse_packet(build_packet(
                    packet_id=i * 100 + tick, current_lap=i,
                    last_lap_time_ms=times[i - 2] if i > 1 else -1,
                    speed_mps=40.0, flags=ON_TRACK,
                ))
            )
    await service._on_packet(
        parse_packet(build_packet(current_lap=4, last_lap_time_ms=58_000, flags=ON_TRACK))
    )
    assert events.count("personal_best") == 1


async def test_session_summary_on_new_session(client, monkeypatch) -> None:
    _, service = client
    events: list[str] = []
    monkeypatch.setattr(
        Notifier, "notify",
        lambda self, event, title, fields: events.append(event),
    )
    service.notifier.url = "https://example.invalid/hook"
    await drive_laps(service, laps=1)
    # Car change starts a new session -> summary for the old one
    await service._on_packet(
        parse_packet(build_packet(current_lap=1, flags=ON_TRACK, car_id=99))
    )
    assert "session_summary" in events
