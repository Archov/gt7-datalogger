"""Race Engineer WebSocket protocol: capabilities, active speaker, callouts."""

import asyncio
import json

import pytest

from app.api.ws import _handle_client_message
from app.config import Settings
from app.models import SimulatorFlags
from app.processing.cars import CarDatabase
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.packet import build_packet, parse_packet
from tests.test_ws_broadcast import FakeWS

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


@pytest.fixture
async def service(tmp_path):
    settings = Settings(
        source="udp", db_path=tmp_path / "test.db", ws_rate=1000, telemetry_port=43744
    )
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    svc = TelemetryService(settings, repo, CarDatabase())
    svc.processor.min_lap_ticks = 1
    yield svc
    await svc.stop()
    await engine.dispose()


def send(service: TelemetryService, ws, kind: str, **data: object) -> None:
    _handle_client_message(service, ws, json.dumps({"type": kind, "data": data}))


async def register(service: TelemetryService, ws, client_id: str, page: str = "dash",
                   voice_enabled: bool = True) -> None:
    await service.register(ws)
    send(
        service,
        ws,
        "client_capabilities",
        client_id=client_id,
        page=page,
        voice_supported=True,
        voice_enabled=voice_enabled,
    )


async def test_capabilities_and_claim(service) -> None:
    ws = FakeWS()
    await register(service, ws, "client-a")
    assert service.voice_clients[0]["client_id"] == "client-a"
    assert service.engineer_active is True

    send(service, ws, "claim_voice_output", client_id="client-a")
    assert service.engineer_status()["active_client_id"] == "client-a"
    await asyncio.sleep(0.01)
    status = ws.messages("voice_output_status")[-1]
    assert status["data"]["active_client_id"] == "client-a"


async def test_only_one_active_speaker(service) -> None:
    a, b = FakeWS(), FakeWS()
    await register(service, a, "client-a")
    await register(service, b, "client-b")
    send(service, a, "claim_voice_output", client_id="client-a")
    send(service, b, "claim_voice_output", client_id="client-b")
    assert service.engineer_status()["active_client_id"] == "client-b"
    flags = {c["client_id"]: c["is_active_speaker"] for c in service.voice_clients}
    assert flags == {"client-a": False, "client-b": True}


async def test_overlay_pages_may_not_claim_voice(service) -> None:
    """Several open OBS sources would otherwise all speak at once."""
    ws = FakeWS()
    await register(service, ws, "obs-1", page="overlay")
    send(service, ws, "claim_voice_output", client_id="obs-1")
    assert service.engineer_status()["active_client_id"] == ""


async def test_a_client_cannot_claim_on_behalf_of_another(service) -> None:
    a, b = FakeWS(), FakeWS()
    await register(service, a, "client-a")
    await register(service, b, "client-b")
    send(service, a, "claim_voice_output", client_id="client-b")
    assert service.engineer_status()["active_client_id"] == ""


async def test_release_and_disconnect_clear_the_claim(service) -> None:
    ws = FakeWS()
    await register(service, ws, "client-a")
    send(service, ws, "claim_voice_output", client_id="client-a")
    send(service, ws, "release_voice_output", client_id="client-a")
    assert service.engineer_status()["active_client_id"] == ""

    send(service, ws, "claim_voice_output", client_id="client-a")
    await service.unregister(ws)
    assert service.engineer_status()["active_client_id"] == ""


async def test_refresh_restores_the_previous_claim(service) -> None:
    ws = FakeWS()
    await register(service, ws, "client-a")
    send(service, ws, "claim_voice_output", client_id="client-a")
    await service.unregister(ws)

    again = FakeWS()
    await register(service, again, "client-a")
    assert service.engineer_status()["active_client_id"] == "client-a"


async def test_unparseable_client_messages_are_ignored(service) -> None:
    """Older pages send pings; a garbage frame must not disturb anything."""
    ws = FakeWS()
    await register(service, ws, "client-a")
    for raw in ("ping", "", "[]", '{"type": 5}', '{"type": "claim_voice_output"}'):
        _handle_client_message(service, ws, raw)
    assert service.engineer_status()["active_client_id"] == ""
    assert service.client_count == 1


async def test_detection_is_off_until_a_browser_enables_voice(service) -> None:
    ws = FakeWS()
    await service.register(ws)
    assert service.engineer_active is False
    for i in range(120):
        await service._on_packet(
            parse_packet(build_packet(fmt="C", packet_id=i, current_lap=3, total_laps=3,
                                      speed_mps=40.0, flags=ON_TRACK))
        )
    await asyncio.sleep(0.01)
    assert ws.messages("voice_callout") == []
    assert service.engineer.stats["evaluated"] == 0


async def test_callouts_reach_every_client_on_the_event_lane(service) -> None:
    """Non-speaking pages still get callouts — for captions and diagnostics."""
    driver, viewer = FakeWS(), FakeWS()
    await register(service, driver, "client-a")
    await service.register(viewer)
    send(service, driver, "claim_voice_output", client_id="client-a")

    for i in range(120):
        await service._on_packet(
            parse_packet(build_packet(fmt="C", packet_id=i, current_lap=3, total_laps=3,
                                      speed_mps=40.0, flags=ON_TRACK))
        )
    await asyncio.sleep(0.01)
    for ws in (driver, viewer):
        callouts = ws.messages("voice_callout")
        assert [c["data"]["event_type"] for c in callouts] == ["final_lap"]
        assert callouts[0]["data"]["ttl_ms"] > 0


async def test_acks_are_recorded_but_never_gate_anything(service) -> None:
    ws = FakeWS()
    await register(service, ws, "client-a")
    send(
        service,
        ws,
        "voice_callout_ack",
        callout_id="final_lap-1-1",
        client_id="client-a",
        status="spoken",
        spoken_at_ms=1,
    )
    assert service.engineer.ack_counts == {"spoken": 1}


async def test_new_clients_get_status_but_never_past_callouts(service) -> None:
    first = FakeWS()
    await register(service, first, "client-a")
    send(service, first, "claim_voice_output", client_id="client-a")
    for i in range(120):
        await service._on_packet(
            parse_packet(build_packet(fmt="C", packet_id=i, current_lap=3, total_laps=3,
                                      speed_mps=40.0, flags=ON_TRACK))
        )
    late = FakeWS()
    await service.register(late)
    await asyncio.sleep(0.01)
    assert late.messages("voice_callout") == []
    assert late.messages("race_engineer_status")[0]["data"]["active_client_id"] == "client-a"
