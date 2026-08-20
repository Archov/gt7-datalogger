"""Fixture-gated restart-to-HTTP acceptance for historical session 17."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.processing.orientation import ORIENTATION_CHANNELS
from app.telemetry.raw_archive import ArchiveRecord
from tests.llm_guide_contract import assert_standard_document_matches_guide

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REAL_DATABASE = BACKEND_ROOT / "data" / "gt7.db"
REAL_ARCHIVE = BACKEND_ROOT / "data" / "raw" / "session-17.gt7r.zip"
HAS_SESSION_17_FIXTURE = REAL_DATABASE.is_file() and REAL_ARCHIVE.is_file()


def _session_sample_blobs(database: Path) -> dict[int, bytes]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id, CAST(samples_json AS BLOB) FROM laps WHERE session_id = 17 ORDER BY id"
        ).fetchall()
    return {int(lap_id): bytes(blob) for lap_id, blob in rows}


@pytest.mark.skipif(
    not HAS_SESSION_17_FIXTURE,
    reason="local historical session-17 database/archive fixtures are absent",
)
async def test_session_17_hydrates_orientation_on_standard_http_export_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    archive_root = data_root / "raw"
    archive_root.mkdir(parents=True)
    database = data_root / "gt7.db"
    with sqlite3.connect(REAL_DATABASE) as source, sqlite3.connect(database) as target:
        source.backup(target)
    shutil.copy2(REAL_ARCHIVE, archive_root / REAL_ARCHIVE.name)

    # This acceptance test exercises hydration of a historical session. The
    # ignored developer fixture may itself have been hydrated by a newer local
    # run, so recreate the original missing-channel state in the disposable
    # copy without touching the user's database.
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT id, samples_json FROM laps WHERE session_id = 17"
        ).fetchall()
        for lap_id, raw in rows:
            samples = json.loads(raw)
            for channel in ORIENTATION_CHANNELS:
                samples.pop(channel, None)
            connection.execute(
                "UPDATE laps SET samples_json = ? WHERE id = ?",
                (json.dumps(samples, separators=(",", ":")), lap_id),
            )
        connection.commit()

    before = _session_sample_blobs(database)
    assert before
    for blob in before.values():
        samples = json.loads(blob)
        assert not set(ORIENTATION_CHANNELS).intersection(samples)

    from app import main
    from app.processing import laps, telemetry_hydration, telemetry_resolution
    from app.telemetry import packet, raw_archive, simulator
    from app.telemetry.listener import UdpTelemetrySource

    settings = Settings(
        source="udp",
        db_path=database,
        cars_csv=BACKEND_ROOT / "data" / "cars.csv",
        raw_archive=True,
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    async def no_source_start(_source: Any) -> None:
        return None

    async def no_source_stop(_source: Any) -> None:
        return None

    monkeypatch.setattr(UdpTelemetrySource, "start", no_source_start)
    monkeypatch.setattr(UdpTelemetrySource, "stop", no_source_stop)
    monkeypatch.setattr(simulator.SimTelemetrySource, "start", no_source_start)
    monkeypatch.setattr(simulator.SimTelemetrySource, "stop", no_source_stop)

    counts = {"archive_open": 0, "parse": 0, "lap_feed": 0, "resolution": 0}
    original_iter = raw_archive.RawArchiveReader.__iter__
    original_parse = packet.parse_packet
    original_feed = laps.LapProcessor.feed
    original_resolution = telemetry_resolution.resolve_session_telemetry

    def counted_iter(reader: raw_archive.RawArchiveReader) -> Iterator[ArchiveRecord]:
        counts["archive_open"] += 1
        yield from original_iter(reader)

    def counted_parse(payload: bytes) -> Any:
        counts["parse"] += 1
        return original_parse(payload)

    async def counted_feed(processor: laps.LapProcessor, parsed: Any) -> None:
        counts["lap_feed"] += 1
        await original_feed(processor, parsed)

    async def counted_resolution(
        bundle: dict[str, Any], requested: set[str], root: Path
    ) -> dict[str, Any]:
        counts["resolution"] += 1
        return await original_resolution(bundle, requested, root)

    monkeypatch.setattr(raw_archive.RawArchiveReader, "__iter__", counted_iter)
    monkeypatch.setattr(packet, "parse_packet", counted_parse)
    monkeypatch.setattr(laps.LapProcessor, "feed", counted_feed)
    monkeypatch.setattr(telemetry_resolution, "resolve_session_telemetry", counted_resolution)
    monkeypatch.setattr(telemetry_hydration, "resolve_session_telemetry", counted_resolution)

    application = main.create_app()
    lifespan = application.router.lifespan_context(application)
    async with lifespan:
        assert counts == {"archive_open": 0, "parse": 0, "lap_feed": 0, "resolution": 0}
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get(
                "/api/sessions/17/export.llm.json?detail=standard&segment_m=100"
            )
            assert first.status_code == 200
            assert counts["archive_open"] == 1
            assert counts["parse"] > 0
            assert counts["lap_feed"] == counts["parse"]
            assert counts["resolution"] == 1

            document = first.json()
            assert_standard_document_matches_guide(document)
            provenance_rows = {
                row[0]: dict(zip(document["channel_provenance"]["columns"], row, strict=True))
                for row in document["channel_provenance"]["rows"]
            }
            expected_laps = set(before)
            assert set(provenance_rows) == expected_laps
            for state in provenance_rows.values():
                assert set(ORIENTATION_CHANNELS).issubset(state["persisted"])
                assert state["archive_replay"] == []

            traces = {row[0]: (row[1], row[2]) for row in document["line_traces"]["rows"]}
            assert set(traces) == expected_laps
            for columns, rows in traces.values():
                chassis = columns.index("chassis_heading_error_deg")
                slip = columns.index("body_slip_angle_deg")
                assert any(row[chassis] is not None for row in rows)
                assert any(row[slip] is not None for row in rows)

            after_first = _session_sample_blobs(database)
            assert after_first != before
            for lap_id, blob in after_first.items():
                samples = json.loads(blob)
                assert set(ORIENTATION_CHANNELS).issubset(samples)
                original = json.loads(before[lap_id])
                for channel, values in original.items():
                    assert samples[channel] == values
            second = await client.get(
                "/api/sessions/17/export.llm.json?detail=standard&segment_m=100"
            )
            assert second.status_code == 200
            assert second.content == first.content
            assert counts["archive_open"] == 1
            assert counts["resolution"] == 1
            assert _session_sample_blobs(database) == after_first
