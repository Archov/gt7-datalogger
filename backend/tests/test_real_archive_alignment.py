"""Fixture-gated alignment evidence from real historical archives."""

from __future__ import annotations

import math
from pathlib import Path
from statistics import median

import pytest

from app.processing.laps import CompletedLap, LapProcessor, SessionInfo
from app.processing.orientation import ORIENTATION_CHANNELS, chassis_forward, wrap_angle
from app.processing.telemetry_resolution import resolve_session_telemetry
from app.storage.db import make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.raw_archive import replay_archive

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATABASE = BACKEND_ROOT / "data" / "gt7.db"
OVERLAP_CHANNELS = (
    "speed",
    "gear",
    "throttle",
    "brake",
    "steering_wheel_rad",
    "pos_x",
    "pos_y",
    "pos_z",
    "yaw_rate_signed",
)


@pytest.mark.parametrize("session_id", [15, 17])
async def test_real_archive_replay_aligns_and_recovers_orientation(session_id: int) -> None:
    archive = BACKEND_ROOT / "data" / "raw" / f"session-{session_id}.gt7r.zip"
    if not DATABASE.is_file() or not archive.is_file():
        pytest.skip(f"local historical session-{session_id} fixtures are absent")

    engine = make_engine(DATABASE)
    repository = Repository(make_session_factory(engine))
    bundle = await repository.get_session_analysis_data(session_id)
    assert bundle is not None
    persisted_orientation = {
        lap["id"]: set(ORIENTATION_CHANNELS).issubset(lap["samples"])
        for lap in bundle["laps"]
    }

    completed: list[CompletedLap] = []
    sessions: list[SessionInfo] = []

    async def on_lap(lap: CompletedLap) -> None:
        completed.append(lap)

    async def on_session(session: SessionInfo) -> None:
        sessions.append(session)

    processor = LapProcessor(on_lap=on_lap, on_session=on_session)
    await replay_archive(archive, processor.feed, strict_truncation=True)
    assert len(sessions) == 1
    replayed = {
        (lap.car_id, lap.number, lap.time_ms): lap
        for lap in completed
    }
    assert len(replayed) == len(bundle["laps"])
    for persisted in bundle["laps"]:
        key = (persisted["car_id"], persisted["number"], persisted["time_ms"])
        reconstructed = replayed[key]
        assert reconstructed.samples["t"] == persisted["samples"]["t"]
        for channel in OVERLAP_CHANNELS:
            assert reconstructed.samples[channel] == persisted["samples"][channel]
        if persisted_orientation[persisted["id"]]:
            for channel in ORIENTATION_CHANNELS:
                assert reconstructed.samples[channel] == persisted["samples"][channel]

    resolved = await resolve_session_telemetry(
        bundle, set(ORIENTATION_CHANNELS), DATABASE.parent
    )
    for lap in resolved["laps"]:
        samples: dict[str, list[float]] = lap["samples"]
        assert all(channel in samples for channel in ORIENTATION_CHANNELS)
        provenance = resolved["channel_provenance"][lap["id"]]
        source = "persisted" if persisted_orientation[lap["id"]] else "archive_replay"
        assert set(ORIENTATION_CHANNELS).issubset(provenance[source])
        norms = [
            math.sqrt(sum(samples[channel][i] ** 2 for channel in ORIENTATION_CHANNELS))
            for i in range(len(samples["t"]))
        ]
        assert max(abs(value - 1.0) for value in norms) < 1e-4

    dots: list[float] = []
    spin_angles: list[float] = []
    for lap in resolved["laps"]:
        samples = lap["samples"]
        for i in range(1, len(samples["t"]) - 1):
            dx = samples["pos_x"][i + 1] - samples["pos_x"][i - 1]
            dz = samples["pos_z"][i + 1] - samples["pos_z"][i - 1]
            travel_norm = math.hypot(dx, dz)
            quaternion = tuple(samples[channel][i] for channel in ORIENTATION_CHANNELS)
            forward = chassis_forward(quaternion)
            assert forward is not None
            forward_norm = math.hypot(forward[0], forward[2])
            if travel_norm > 0.1 and forward_norm > 0.1:
                dot = (dx * forward[0] + dz * forward[2]) / (travel_norm * forward_norm)
                dots.append(dot)
                if session_id == 15 and lap["number"] == 2:
                    travel_heading = math.atan2(dz, dx)
                    chassis_heading = math.atan2(forward[2], forward[0])
                    spin_angles.append(
                        abs(math.degrees(wrap_angle(travel_heading - chassis_heading)))
                    )
    assert median(dots) > 0.99
    if session_id == 15:
        assert max(spin_angles) > 45.0
    await engine.dispose()
