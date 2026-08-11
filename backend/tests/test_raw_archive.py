"""Lossless raw telemetry container, replay, and lifecycle regressions."""

from __future__ import annotations

import asyncio
import os
import struct
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.models import SimulatorFlags, TelemetryPacket
from app.processing.cars import CarDatabase
from app.processing.laps import SessionInfo
from app.service import TelemetryService
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.repository import Repository
from app.telemetry.crypto import decrypt_packet, encrypt_packet
from app.telemetry.listener import UdpTelemetrySource
from app.telemetry.packet import build_packet, parse_packet
from app.telemetry.raw_archive import (
    FILE_HEADER,
    FORMAT_VERSION,
    MAX_PAYLOAD_SIZE,
    RECORD_HEADER,
    ArchiveError,
    CapturedPayload,
    RawArchiveManager,
    RawArchiveReader,
    TruncatedArchiveError,
    UnsupportedArchiveVersion,
    replay_archive,
)


def capture(
    payload: bytes,
    order: int,
    *,
    offset_ns: int = 0,
    parsed: bool = True,
) -> CapturedPayload:
    packet = parse_packet(payload) if parsed else None
    return CapturedPayload(
        payload=payload,
        received_monotonic_ns=10_000_000_000 + offset_ns,
        received_unix_ns=1_800_000_000_000_000_000 + offset_ns,
        receiver_order=order,
        source="udp",
        packet=packet,
    )


def packet_payload(fmt: str = "A", packet_id: int = 1, lap: int = 1) -> bytes:
    return build_packet(
        fmt=fmt,
        packet_id=packet_id,
        current_lap=lap,
        flags=int(SimulatorFlags.CAR_ON_TRACK),
    )


async def completed_archive(tmp_path: Path, payloads: list[bytes]) -> Path:
    manager = RawArchiveManager(tmp_path)
    token = None
    for index, payload in enumerate(payloads):
        token = manager.capture(
            capture(payload, index, offset_ns=index * 17_000_000), recording=True
        )
    assert token is not None
    metadata = manager.bind(token, 7)
    assert metadata is not None
    metadata = await manager.finalize(token)
    assert metadata is not None
    assert metadata["status"] == "complete"
    return tmp_path / str(metadata["path"])


async def test_exact_round_trip_known_unknown_and_mixed_lengths(tmp_path: Path) -> None:
    packet_a = packet_payload("A", 10)
    packet_c = packet_payload("C", 11)
    unknown = packet_c + os.urandom(517)
    path = await completed_archive(tmp_path, [packet_a, packet_c, unknown])

    records = list(RawArchiveReader(path))
    assert [record.payload for record in records] == [packet_a, packet_c, unknown]
    assert [record.payload_length for record in records] == [296, 368, 885]
    assert [record.order for record in records] == [0, 1, 2]


async def test_timing_and_approximate_absolute_time_round_trip(tmp_path: Path) -> None:
    path = await completed_archive(
        tmp_path, [packet_payload(packet_id=1), packet_payload(packet_id=2)]
    )
    reader = RawArchiveReader(path)
    records = list(reader)
    assert [record.monotonic_offset_ns for record in records] == [0, 17_000_000]
    assert reader.created_unix_ns == 1_800_000_000_000_000_000
    assert records[1].approximate_unix_ns == reader.created_unix_ns + 17_000_000


def _uncompressed_archive(tmp_path: Path) -> Path:
    manager = RawArchiveManager(tmp_path)
    token = manager.capture(capture(packet_payload(), 0), recording=True)
    assert token is not None
    metadata = manager.bind(token, 9)
    assert metadata is not None
    paths = manager.detach(token)
    assert paths == [tmp_path / "raw" / "session-9.gt7r"]
    return paths[0]


def test_reader_skips_forward_header_extensions(tmp_path: Path) -> None:
    path = _uncompressed_archive(tmp_path)
    original = path.read_bytes()
    magic, version, header_size, created_ns = FILE_HEADER.unpack_from(original)
    extension = b"future-file"
    file_header = FILE_HEADER.pack(magic, version, header_size + len(extension), created_ns)
    extended = file_header + extension + original[FILE_HEADER.size :]

    record_at = header_size + len(extension)
    values = list(RECORD_HEADER.unpack_from(extended, record_at))
    record_extension = b"future-record"
    values[1] = int(values[1]) + len(record_extension)
    record_header = RECORD_HEADER.pack(*values)
    payload_at = record_at + RECORD_HEADER.size
    path.write_bytes(
        extended[:record_at]
        + record_header
        + record_extension
        + extended[payload_at:]
    )
    assert list(RawArchiveReader(path))[0].payload == packet_payload()


def test_reader_rejects_version_crc_and_unreasonable_length(tmp_path: Path) -> None:
    path = _uncompressed_archive(tmp_path)
    original = bytearray(path.read_bytes())

    struct.pack_into("<H", original, 8, FORMAT_VERSION + 1)
    path.write_bytes(original)
    with pytest.raises(UnsupportedArchiveVersion):
        list(RawArchiveReader(path))

    path = _uncompressed_archive(tmp_path / "crc")
    original = bytearray(path.read_bytes())
    original[-1] ^= 0xFF
    path.write_bytes(original)
    with pytest.raises(ArchiveError, match="checksum"):
        list(RawArchiveReader(path))

    path = _uncompressed_archive(tmp_path / "length")
    original = bytearray(path.read_bytes())
    values = list(RECORD_HEADER.unpack_from(original, FILE_HEADER.size))
    values[5] = MAX_PAYLOAD_SIZE + 1
    original[FILE_HEADER.size : FILE_HEADER.size + RECORD_HEADER.size] = RECORD_HEADER.pack(
        *values
    )
    path.write_bytes(original)
    with pytest.raises(ArchiveError, match="unreasonable"):
        list(RawArchiveReader(path))


def test_truncated_final_record_is_reported_or_strictly_rejected(tmp_path: Path) -> None:
    path = _uncompressed_archive(tmp_path)
    raw = path.read_bytes()
    path.write_bytes(raw[:-10])

    reader = RawArchiveReader(path)
    assert list(reader) == []
    assert reader.truncated_tail is True
    with pytest.raises(TruncatedArchiveError):
        list(RawArchiveReader(path, strict_truncation=True))


async def test_replay_parses_without_udp_and_can_preserve_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = await completed_archive(
        tmp_path, [packet_payload(packet_id=41), packet_payload(packet_id=42)]
    )
    seen: list[int] = []
    sleeps: list[float] = []

    async def accept(packet: TelemetryPacket) -> None:
        seen.append(packet.packet_id)

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await replay_archive(path, accept, preserve_timing=True, speed=2.0)
    assert seen == [41, 42]
    assert sleeps == pytest.approx([0.0085])


def test_disabled_archive_starts_only_at_next_boundary(tmp_path: Path) -> None:
    manager = RawArchiveManager(tmp_path, enabled=False)
    assert manager.capture(capture(packet_payload(lap=1), 0), recording=True) is None
    manager.schedule_enabled(True)
    assert manager.capture(capture(packet_payload(lap=2), 1), recording=True) is None
    token = manager.capture(capture(packet_payload(lap=1), 2), recording=True)
    assert token is not None


def test_parser_unusable_payload_is_still_archived_in_active_session(tmp_path: Path) -> None:
    manager = RawArchiveManager(tmp_path)
    token = manager.capture(capture(packet_payload(), 0), recording=True)
    assert token is not None
    unknown = b"G7S0" + os.urandom(92)
    same = manager.capture(capture(unknown, 1, parsed=False), recording=True)
    assert same == token
    manager.bind(token, 5)
    path = manager.detach(token)[0]
    assert [record.payload for record in RawArchiveReader(path)] == [packet_payload(), unknown]


def test_udp_archives_before_the_lossy_processing_queue(tmp_path: Path) -> None:
    manager = RawArchiveManager(tmp_path)
    tokens: list[str] = []

    async def consume(_packet: Any, _token: str | None) -> None:
        pass

    def archive(captured: CapturedPayload) -> str | None:
        token = manager.capture(captured, recording=True)
        if token is not None:
            tokens.append(token)
        return token

    source = UdpTelemetrySource(Settings(), consume, archive)
    for packet_id in range(605):
        source._handle_datagram(
            encrypt_packet(packet_payload(packet_id=packet_id)), ("192.0.2.10", 33740)
        )
    assert source.stats["packets_dropped"] == 5
    path = manager.detach(tokens[-1])[0]
    records = list(RawArchiveReader(path))
    assert len(records) == 605
    expected = decrypt_packet(encrypt_packet(packet_payload(packet_id=604)))
    assert expected is not None
    assert records[-1].payload == expected


def test_archive_open_failure_does_not_break_udp_parsing(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw"
    raw_path.write_text("not a directory", encoding="utf-8")
    manager = RawArchiveManager(tmp_path)

    async def consume(_packet: Any, _token: str | None) -> None:
        pass

    source = UdpTelemetrySource(
        Settings(),
        consume,
        lambda captured: manager.capture(captured, recording=True),
    )
    source._handle_datagram(
        encrypt_packet(packet_payload(packet_id=99)), ("192.0.2.10", 33740)
    )
    assert source._queue.qsize() == 1
    assert source.stats["packets_received"] == 1


async def test_service_finalizes_and_deletes_session_archive(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", telemetry_port=43801)
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    service = TelemetryService(settings, repo, CarDatabase())

    payload = packet_payload(packet_id=1)
    captured = capture(payload, 0)
    token = service._on_raw_packet(captured)
    assert captured.packet is not None
    await service._on_packet(captured.packet, token)
    assert service.session_id is not None
    session_id = service.session_id
    await service.stop()

    metadata = await repo.get_session_archive_metadata(session_id)
    assert metadata is not None
    assert metadata["status"] == "complete"
    path = tmp_path / str(metadata["path"])
    assert path.name == f"session-{session_id}.gt7r.zip"
    assert path.exists()
    assert list(RawArchiveReader(path))[0].payload == payload

    await service.delete_session(session_id)
    assert not path.exists()
    assert await repo.get_session_metadata(session_id) is None

    second_id = await repo.create_session(SessionInfo(car_id=2, started_at="later"), "Car 2")
    second_path = tmp_path / "raw" / f"session-{second_id}.gt7r"
    second_path.write_bytes(b"archive")
    await repo.set_session_archive_metadata(
        second_id,
        {"path": f"raw/session-{second_id}.gt7r", "status": "interrupted"},
    )
    await service.clear_recorded_data()
    assert not second_path.exists()
    assert await repo.get_session_metadata(second_id) is None
    await engine.dispose()


async def test_startup_marks_unfinished_archive_interrupted(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", telemetry_port=43802)
    engine = make_engine(settings.db_path)
    await init_db(engine)
    repo = Repository(make_session_factory(engine))
    session_id = await repo.create_session(SessionInfo(car_id=1, started_at="now"), "Car")

    manager = RawArchiveManager(tmp_path)
    token = manager.capture(capture(packet_payload(), 0), recording=True)
    assert token is not None
    metadata = manager.bind(token, session_id)
    assert metadata is not None
    path = manager.detach(token)[0]
    await repo.set_session_archive_metadata(session_id, metadata)

    service = TelemetryService(settings, repo, CarDatabase())
    await service._recover_interrupted_archives()
    recovered = await repo.get_session_archive_metadata(session_id)
    assert recovered is not None
    assert recovered["status"] == "interrupted"
    assert recovered["packet_count"] == 1
    assert path.exists()
    await service.stop()
    await engine.dispose()
