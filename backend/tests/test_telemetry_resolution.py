"""Generic persisted-first archive telemetry hydration."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import SimulatorFlags
from app.processing.cars import CarDatabase
from app.processing.laps import VELOCITY_CHANNELS, CompletedLap, LapProcessor, SessionInfo
from app.processing.orientation import ORIENTATION_CHANNELS
from app.processing.telemetry_resolution import resolve_session_telemetry
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry import raw_archive
from app.telemetry.packet import build_packet, parse_packet
from app.telemetry.raw_archive import CapturedPayload, RawArchiveManager

ON_TRACK = int(SimulatorFlags.CAR_ON_TRACK)


async def _fixture_bundle(tmp_path: Path) -> dict[str, Any]:
    payloads = [
        build_packet(
            fmt="C",
            packet_id=index,
            current_lap=1,
            flags=ON_TRACK,
            car_id=7,
            speed_mps=30.0 + index / 1000,
            velocity=(20.0, 0.5, 5.0),
            orientation=(0.0, -0.70710678, 0.0, 0.70710678),
        )
        for index in range(605)
    ]
    payloads.append(
        build_packet(
            fmt="C",
            packet_id=605,
            current_lap=2,
            last_lap_time_ms=10_000,
            flags=ON_TRACK,
            car_id=7,
        )
    )
    completed: list[CompletedLap] = []
    sessions: list[SessionInfo] = []

    async def on_lap(lap: CompletedLap) -> None:
        completed.append(lap)

    async def on_session(session: SessionInfo) -> None:
        sessions.append(session)

    processor = LapProcessor(on_lap=on_lap, on_session=on_session)
    manager = RawArchiveManager(tmp_path)
    token: str | None = None
    for index, payload in enumerate(payloads):
        packet = parse_packet(payload)
        await processor.feed(packet)
        token = manager.capture(
            CapturedPayload(
                payload=payload,
                received_monotonic_ns=index * 16_666_667,
                received_unix_ns=1_800_000_000_000_000_000 + index * 16_666_667,
                receiver_order=index,
                source="udp",
                packet=packet,
            ),
            recording=True,
        )
    assert token is not None and len(completed) == 1 and len(sessions) == 1
    metadata = manager.bind(token, 9)
    assert metadata is not None
    metadata = await manager.finalize(token)
    assert metadata is not None
    lap = completed[0]
    return {
        "session": {
            "id": 9,
            "started_at": "2026-01-01T00:00:00Z",
            "car_id": 7,
            "car_name": "Test Car",
            "track_name": "Test Track",
            "note": "",
        },
        "laps": [
            {
                "id": 42,
                "session_id": 9,
                "number": lap.number,
                "time_ms": lap.time_ms,
                "car_id": lap.car_id,
                "counts_for_best": True,
                "samples": copy.deepcopy(lap.samples),
            }
        ],
        "raw_archive_meta": metadata,
    }


async def test_recovers_orientation_and_an_ordinary_channel_in_one_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = await _fixture_bundle(tmp_path)
    original = copy.deepcopy(bundle)
    samples = bundle["laps"][0]["samples"]
    for channel in (*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS, "speed"):
        samples.pop(channel)
    before_resolution = copy.deepcopy(bundle)

    calls = 0
    replay = raw_archive.replay_archive

    async def counted_replay(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        await replay(*args, **kwargs)

    monkeypatch.setattr(raw_archive, "replay_archive", counted_replay)
    resolved = await resolve_session_telemetry(
        bundle, {*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS, "speed"}, tmp_path
    )
    assert calls == 1
    resolved_samples = resolved["laps"][0]["samples"]
    assert all(
        channel in resolved_samples
        for channel in (*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS, "speed")
    )
    lengths = {
        len(resolved_samples[channel])
        for channel in (*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS, "speed")
    }
    assert len(lengths) == 1
    state = resolved["channel_provenance"][42]
    assert state["archive_replay"] == sorted((*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS, "speed"))
    assert bundle == before_resolution
    assert original["laps"][0]["samples"] != samples


async def test_persisted_channel_wins_without_opening_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = await _fixture_bundle(tmp_path)
    speed = bundle["laps"][0]["samples"]["speed"]

    def unexpected_reader(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("archive should not be opened")

    monkeypatch.setattr(raw_archive, "replay_archive", unexpected_reader)
    resolved = await resolve_session_telemetry(bundle, {"speed"}, tmp_path)
    assert resolved["laps"][0]["samples"]["speed"] == speed
    assert "speed" in resolved["channel_provenance"][42]["persisted"]


async def test_unusable_archive_degrades_to_unavailable(tmp_path: Path) -> None:
    bundle = await _fixture_bundle(tmp_path)
    for channel in ORIENTATION_CHANNELS:
        bundle["laps"][0]["samples"].pop(channel)
    bundle["raw_archive_meta"]["status"] = "interrupted"
    bundle["raw_archive_meta"]["complete"] = False
    resolved = await resolve_session_telemetry(bundle, set(ORIENTATION_CHANNELS), tmp_path)
    state = resolved["channel_provenance"][42]
    assert state["archive_replay"] == []
    assert state["unavailable"] == sorted(ORIENTATION_CHANNELS)


async def test_corrupt_archive_does_not_fail_resolution(tmp_path: Path) -> None:
    bundle = await _fixture_bundle(tmp_path)
    for channel in ORIENTATION_CHANNELS:
        bundle["laps"][0]["samples"].pop(channel)
    archive = tmp_path / str(bundle["raw_archive_meta"]["path"])
    archive.write_bytes(b"not an archive")
    resolved = await resolve_session_telemetry(bundle, set(ORIENTATION_CHANNELS), tmp_path)
    assert resolved["channel_provenance"][42]["archive_replay"] == []
    assert resolved["channel_provenance"][42]["unavailable"] == sorted(ORIENTATION_CHANNELS)


async def test_mismatched_lap_identity_cannot_receive_archive_channels(tmp_path: Path) -> None:
    bundle = await _fixture_bundle(tmp_path)
    bundle["laps"][0]["number"] = 99
    for channel in ORIENTATION_CHANNELS:
        bundle["laps"][0]["samples"].pop(channel)
    resolved = await resolve_session_telemetry(bundle, set(ORIENTATION_CHANNELS), tmp_path)
    assert resolved["channel_provenance"][42]["archive_replay"] == []
    assert resolved["channel_provenance"][42]["unavailable"] == sorted(ORIENTATION_CHANNELS)


async def test_compare_request_persists_map_channels_and_replays_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = await _fixture_bundle(tmp_path)
    source = fixture["laps"][0]
    persisted_samples = copy.deepcopy(source["samples"])
    for channel in (*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS):
        persisted_samples.pop(channel)

    settings = Settings(source="udp", db_path=tmp_path / "compare.db", ws_rate=1000)
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    session_id = await repo.create_session(
        SessionInfo(car_id=7, started_at="2026-01-01T00:00:00Z"), "Test Car"
    )
    completed = CompletedLap(
        number=int(source["number"]),
        time_ms=int(source["time_ms"]),
        finished_at="2026-01-01T00:00:10Z",
        car_id=7,
        samples=persisted_samples,
        fuel_start=100.0,
        fuel_end=99.0,
        total_ticks=len(persisted_samples["t"]),
    )
    lap_id = await repo.save_lap(session_id, completed)
    await repo.set_session_archive_metadata(session_id, fixture["raw_archive_meta"])

    replay_calls = 0
    replay = raw_archive.replay_archive

    async def counted_replay(*args: Any, **kwargs: Any) -> None:
        nonlocal replay_calls
        replay_calls += 1
        await replay(*args, **kwargs)

    monkeypatch.setattr(raw_archive, "replay_archive", counted_replay)
    service = TelemetryService(settings, repo, CarDatabase())
    app = create_app()
    app.router.lifespan_context = None  # type: ignore[assignment]
    app.state.service = service
    url = (
        f"/api/analysis/compare?laps={lap_id}&ref={lap_id}"
        "&channels=orientation_x,orientation_y,orientation_z,orientation_w,"
        "velocity_x,velocity_y,velocity_z"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get(url)
        second = await client.get(url)

    assert first.status_code == 200
    assert first.content == second.content
    assert replay_calls == 1
    series = first.json()["laps"][str(lap_id)]["series"]
    assert all(channel in series for channel in (*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS))
    persisted = await repo.get_lap(lap_id)
    assert persisted is not None
    assert all(
        channel in persisted["samples"] for channel in (*ORIENTATION_CHANNELS, *VELOCITY_CHANNELS)
    )
    for channel, values in persisted_samples.items():
        assert persisted["samples"][channel] == values
    hydration = await repo.get_session_hydration_metadata(session_id)
    assert hydration is not None
    assert hydration["status"] == "complete"
    await engine.dispose()
