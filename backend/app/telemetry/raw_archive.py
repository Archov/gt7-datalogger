"""Lossless append-only archives of decrypted GT7 telemetry payloads.

The container deliberately knows nothing about packet fields.  It stores the
complete plaintext supplied to :func:`parse_packet` so a newer parser can be
run over an old capture without changing the archive.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import uuid
import zipfile
import zlib
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, BinaryIO, Literal

from app.models import TelemetryPacket

log = logging.getLogger(__name__)

MAGIC = b"GT7RAW\x00\x00"
RECORD_MAGIC = b"PKT1"
FORMAT_VERSION = 1
MAX_PAYLOAD_SIZE = 1024 * 1024
FILE_HEADER = struct.Struct("<8sHHQ")
RECORD_HEADER = struct.Struct("<4sHHQQIiiBBHI")
FLUSH_INTERVAL_NS = 1_000_000_000

SourceName = Literal["udp", "sim"]
_SOURCE_CODES: dict[SourceName, int] = {"udp": 1, "sim": 2}
_SOURCE_NAMES = {value: key for key, value in _SOURCE_CODES.items()}
_FORMAT_CODES = {"A": 1, "B": 2, "~": 3, "C": 4}
_FORMAT_NAMES = {value: key for key, value in _FORMAT_CODES.items()}


class ArchiveError(ValueError):
    """Base class for malformed or unsupported raw archives."""


class UnsupportedArchiveVersion(ArchiveError):
    """The archive uses a container version this reader does not understand."""


class TruncatedArchiveError(ArchiveError):
    """The archive ends part-way through its final header or payload."""


@dataclass(slots=True, frozen=True)
class CapturedPayload:
    """Immutable receive-boundary data retained independently of parsing."""

    payload: bytes
    received_monotonic_ns: int
    received_unix_ns: int
    receiver_order: int
    source: SourceName
    packet: TelemetryPacket | None = None


RawPacketCallback = Callable[[CapturedPayload], str | None]


@dataclass(slots=True, frozen=True)
class ArchiveRecord:
    monotonic_offset_ns: int
    order: int
    payload: bytes
    packet_id: int | None
    lap_number: int | None
    source: str
    packet_format: str | None
    approximate_unix_ns: int

    @property
    def payload_length(self) -> int:
        return len(self.payload)


@dataclass(slots=True)
class _Writer:
    path: Path
    created_unix_ns: int
    base_monotonic_ns: int
    file: BinaryIO
    packet_count: int = 0
    payload_bytes: int = 0
    last_offset_ns: int = 0
    last_flush_ns: int = 0
    sources: set[str] = field(default_factory=set)
    packet_formats: set[str] = field(default_factory=set)
    failed: str | None = None

    @classmethod
    def create(cls, path: Path, first: CapturedPayload) -> _Writer:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("w+b", buffering=256 * 1024)
        stream.write(
            FILE_HEADER.pack(
                MAGIC,
                FORMAT_VERSION,
                FILE_HEADER.size,
                first.received_unix_ns,
            )
        )
        stream.flush()
        return cls(
            path=path,
            created_unix_ns=first.received_unix_ns,
            base_monotonic_ns=first.received_monotonic_ns,
            file=stream,
            last_flush_ns=first.received_monotonic_ns,
        )

    def append(self, capture: CapturedPayload) -> None:
        if self.failed is not None:
            return
        try:
            payload_len = len(capture.payload)
            if payload_len > MAX_PAYLOAD_SIZE:
                raise OSError(f"payload is larger than {MAX_PAYLOAD_SIZE} bytes")
            offset = max(0, capture.received_monotonic_ns - self.base_monotonic_ns)
            packet = capture.packet
            packet_id = packet.packet_id if packet is not None else -1
            lap = packet.current_lap if packet is not None else -1
            packet_format = packet.packet_format if packet is not None else None
            self.file.write(
                RECORD_HEADER.pack(
                    RECORD_MAGIC,
                    RECORD_HEADER.size,
                    0,
                    offset,
                    capture.receiver_order,
                    payload_len,
                    packet_id,
                    lap,
                    _SOURCE_CODES[capture.source],
                    _FORMAT_CODES.get(packet_format or "", 0),
                    0,
                    zlib.crc32(capture.payload),
                )
            )
            self.file.write(capture.payload)
            self.packet_count += 1
            self.payload_bytes += payload_len
            self.last_offset_ns = offset
            self.sources.add(capture.source)
            if packet_format:
                self.packet_formats.add(packet_format)
            if capture.received_monotonic_ns - self.last_flush_ns >= FLUSH_INTERVAL_NS:
                self.file.flush()
                self.last_flush_ns = capture.received_monotonic_ns
        except OSError as exc:
            self.failed = str(exc)
            try:
                self.file.close()
            except OSError:
                pass
            raise

    def close(self) -> None:
        if self.file.closed:
            return
        self.file.flush()
        self.file.close()

    def rename(self, path: Path) -> None:
        was_open = not self.file.closed
        self.close()
        os.replace(self.path, path)
        self.path = path
        if was_open and self.failed is None:
            self.file = path.open("r+b", buffering=256 * 1024)
            self.file.seek(0, io.SEEK_END)


@dataclass(slots=True)
class _ArchiveSession:
    token: str
    writer: _Writer
    session_id: int | None = None
    status: str = "recording"
    complete: bool = False
    stored_bytes: int = 0
    container_bytes: int = 0
    compressed_bytes: int = 0
    finalized_at: str | None = None


class RawArchiveManager:
    """Synchronous capture plus asynchronous session finalization."""

    def __init__(self, data_root: Path, *, enabled: bool = True) -> None:
        self.data_root = data_root.resolve()
        self.archive_dir = self.data_root / "raw"
        self.enabled = enabled
        self._next_enabled = enabled
        self._sessions: dict[str, _ArchiveSession] = {}
        self._current_token: str | None = None
        self._car_id: int | None = None
        self._lap_number = -1
        self._dirty: set[str] = set()
        self._suppressed_until_boundary = False

    def capture(self, capture: CapturedPayload, *, recording: bool) -> str | None:
        """Append before the normalized queue and return the logical-session token."""
        if not recording:
            return None
        packet = capture.packet
        boundary = False
        if packet is not None and not packet.is_loading:
            if self._car_id is None:
                self._car_id = packet.car_id
                self._lap_number = packet.current_lap
            else:
                boundary = packet.car_id != self._car_id or (
                    self._lap_number > 0 and 0 <= packet.current_lap < self._lap_number
                )
                if boundary:
                    self._car_id = packet.car_id
                self._lap_number = packet.current_lap

        if boundary:
            self.enabled = self._next_enabled
            self._suppressed_until_boundary = False
        if self._suppressed_until_boundary:
            return None
        if self._current_token is None or boundary:
            self._start(capture)
        if self._current_token is None:
            return None
        session = self._sessions[self._current_token]
        try:
            session.writer.append(capture)
        except OSError as exc:
            session.status = "write_failed"
            session.complete = False
            self._dirty.add(session.token)
            log.error("raw telemetry archive disabled after write failure: %s", exc)
        return session.token

    def _start(self, capture: CapturedPayload) -> None:
        if self._current_token is not None:
            previous = self._sessions[self._current_token]
            try:
                previous.writer.close()
            except OSError as exc:
                previous.writer.failed = str(exc)
                previous.status = "write_failed"
                self._dirty.add(previous.token)
        if not self.enabled:
            self._current_token = None
            return
        token = uuid.uuid4().hex
        path = self.archive_dir / f".pending-{token}.gt7r"
        try:
            writer = _Writer.create(path, capture)
        except OSError as exc:
            log.error("could not open raw telemetry archive %s: %s", path, exc)
            self._current_token = None
            self._suppressed_until_boundary = True
            return
        self._sessions[token] = _ArchiveSession(token=token, writer=writer)
        self._current_token = token

    def bind(self, token: str | None, session_id: int) -> dict[str, object] | None:
        if token is None or token not in self._sessions:
            return None
        session = self._sessions[token]
        target = self.archive_dir / f"session-{session_id}.gt7r"
        try:
            session.writer.rename(target)
        except OSError as exc:
            session.writer.failed = str(exc)
            session.status = "write_failed"
            log.error("could not bind raw archive to session %d: %s", session_id, exc)
        session.session_id = session_id
        self._dirty.discard(token)
        return self.metadata(token)

    async def finalize(self, token: str | None) -> dict[str, object] | None:
        if token is None or token not in self._sessions:
            return None
        session = self._sessions[token]
        writer = session.writer
        try:
            writer.close()
        except OSError as exc:
            writer.failed = str(exc)
            session.status = "write_failed"
        try:
            session.container_bytes = writer.path.stat().st_size
        except OSError:
            session.container_bytes = 0
        if writer.failed is None and session.session_id is not None:
            zip_path = writer.path.with_suffix(writer.path.suffix + ".zip")
            try:
                await asyncio.to_thread(_compress_archive, writer.path, zip_path)
                session.compressed_bytes = zip_path.stat().st_size
                session.stored_bytes = session.compressed_bytes
                writer.path.unlink()
                writer.path = zip_path
                session.status = "complete"
                session.complete = True
            except OSError as exc:
                writer.failed = str(exc)
                session.status = "compression_failed"
                session.complete = True
                session.stored_bytes = session.container_bytes
                log.error("could not compress raw archive %s: %s", writer.path, exc)
        else:
            session.stored_bytes = session.container_bytes
        session.finalized_at = _utc_now()
        self._dirty.discard(token)
        return self.metadata(token)

    def metadata(self, token: str) -> dict[str, object]:
        session = self._sessions[token]
        writer = session.writer
        relative = writer.path.resolve().relative_to(self.data_root).as_posix()
        source = next(iter(writer.sources)) if len(writer.sources) == 1 else "mixed"
        return {
            "version": FORMAT_VERSION,
            "path": relative,
            "status": session.status,
            "complete": session.complete,
            "packet_count": writer.packet_count,
            "payload_bytes": writer.payload_bytes,
            "container_bytes": session.container_bytes,
            "compressed_bytes": session.compressed_bytes,
            "stored_bytes": session.stored_bytes,
            "created_unix_ns": writer.created_unix_ns,
            "first_monotonic_offset_ns": 0 if writer.packet_count else None,
            "last_monotonic_offset_ns": writer.last_offset_ns if writer.packet_count else None,
            "source": source,
            "packet_formats": sorted(writer.packet_formats),
            "finalized_at": session.finalized_at,
            "error": writer.failed,
        }

    def dirty_metadata(self) -> list[tuple[int, dict[str, object]]]:
        result: list[tuple[int, dict[str, object]]] = []
        for token in tuple(self._dirty):
            session = self._sessions[token]
            if session.session_id is not None:
                result.append((session.session_id, self.metadata(token)))
                self._dirty.discard(token)
        return result

    def detach(self, token: str | None) -> list[Path]:
        if token is None or token not in self._sessions:
            return []
        session = self._sessions.pop(token)
        try:
            session.writer.close()
        except OSError:
            pass
        if self._current_token == token:
            self._current_token = None
            self._suppressed_until_boundary = True
        return [session.writer.path]

    def reset_boundary(self) -> None:
        self._car_id = None
        self._lap_number = -1

    def schedule_enabled(self, enabled: bool) -> None:
        """Apply a setting change when capture next observes a session boundary."""
        self._next_enabled = enabled


def _compress_archive(source: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            archive.write(source, arcname=source.name)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


class RawArchiveReader:
    def __init__(self, path: Path, *, strict_truncation: bool = False) -> None:
        self.path = path
        self.strict_truncation = strict_truncation
        self.truncated_tail = False
        self.version: int | None = None
        self.created_unix_ns: int | None = None

    def __iter__(self) -> Iterator[ArchiveRecord]:
        self.truncated_tail = False
        with _open_archive_stream(self.path) as stream:
            prefix = stream.read(FILE_HEADER.size)
            if len(prefix) != FILE_HEADER.size:
                raise ArchiveError("truncated archive header")
            magic, version, header_size, created_ns = FILE_HEADER.unpack(prefix)
            if magic != MAGIC:
                raise ArchiveError("invalid archive magic")
            if version != FORMAT_VERSION:
                raise UnsupportedArchiveVersion(f"unsupported archive version {version}")
            if header_size < FILE_HEADER.size:
                raise ArchiveError("archive header is smaller than the v1 minimum")
            _read_exact(stream, header_size - FILE_HEADER.size, "archive header extension")
            self.version = version
            self.created_unix_ns = created_ns
            while True:
                first = stream.read(1)
                if not first:
                    break
                rest = stream.read(RECORD_HEADER.size - 1)
                if len(rest) != RECORD_HEADER.size - 1:
                    self._truncated("record header")
                    break
                values = RECORD_HEADER.unpack(first + rest)
                (
                    record_magic,
                    record_header_size,
                    _flags,
                    offset_ns,
                    order,
                    payload_length,
                    packet_id,
                    lap_number,
                    source_code,
                    format_code,
                    _reserved,
                    checksum,
                ) = values
                if record_magic != RECORD_MAGIC:
                    raise ArchiveError(f"invalid record magic at record {order}")
                if record_header_size < RECORD_HEADER.size:
                    raise ArchiveError(f"record {order} header is too small")
                if payload_length > MAX_PAYLOAD_SIZE:
                    raise ArchiveError(f"record {order} payload length is unreasonable")
                extension = record_header_size - RECORD_HEADER.size
                try:
                    _read_exact(stream, extension, f"record {order} header extension")
                except TruncatedArchiveError:
                    self._truncated(f"record {order} header extension")
                    break
                payload = stream.read(payload_length)
                if len(payload) != payload_length:
                    self._truncated(f"record {order} payload")
                    break
                if zlib.crc32(payload) != checksum:
                    raise ArchiveError(f"record {order} payload checksum mismatch")
                yield ArchiveRecord(
                    monotonic_offset_ns=offset_ns,
                    order=order,
                    payload=payload,
                    packet_id=packet_id if packet_id >= 0 else None,
                    lap_number=lap_number if lap_number >= 0 else None,
                    source=_SOURCE_NAMES.get(source_code, "unknown"),
                    packet_format=_FORMAT_NAMES.get(format_code),
                    approximate_unix_ns=created_ns + offset_ns,
                )

    def _truncated(self, part: str) -> None:
        self.truncated_tail = True
        if self.strict_truncation:
            raise TruncatedArchiveError(f"truncated final {part}")


class _ArchiveStream:
    def __init__(self, stream: IO[bytes], archive: zipfile.ZipFile | None = None) -> None:
        self.stream = stream
        self.archive = archive

    def __enter__(self) -> IO[bytes]:
        return self.stream

    def __exit__(self, *_args: object) -> None:
        self.stream.close()
        if self.archive is not None:
            self.archive.close()


def _open_archive_stream(path: Path) -> _ArchiveStream:
    if path.suffix == ".zip":
        archive = zipfile.ZipFile(path, "r")
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1 or not members[0].filename.endswith(".gt7r"):
            archive.close()
            raise ArchiveError("archive zip must contain exactly one .gt7r member")
        return _ArchiveStream(archive.open(members[0], "r"), archive)
    return _ArchiveStream(path.open("rb"))


def _read_exact(stream: IO[bytes], length: int, description: str) -> bytes:
    data = stream.read(length)
    if len(data) != length:
        raise TruncatedArchiveError(f"truncated {description}")
    return data


async def replay_archive(
    path: Path,
    callback: Callable[[TelemetryPacket], Awaitable[None]],
    *,
    preserve_timing: bool = False,
    speed: float = 1.0,
    strict_truncation: bool = False,
) -> None:
    """Parse archived payloads and deliver them without a UDP transport."""
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    from app.telemetry.packet import parse_packet

    previous_ns: int | None = None
    for record in RawArchiveReader(path, strict_truncation=strict_truncation):
        if preserve_timing and previous_ns is not None:
            delay = max(0, record.monotonic_offset_ns - previous_ns) / 1e9 / speed
            if delay:
                await asyncio.sleep(delay)
        try:
            packet = parse_packet(record.payload)
        except ValueError as exc:
            raise ArchiveError(f"record {record.order} cannot be parsed: {exc}") from exc
        await callback(packet)
        previous_ns = record.monotonic_offset_ns


def scan_archive(path: Path) -> tuple[int, int, int, bool]:
    """Return packet count, payload bytes, final offset, and truncated-tail state."""
    reader = RawArchiveReader(path)
    count = payload_bytes = last_offset = 0
    for record in reader:
        count += 1
        payload_bytes += record.payload_length
        last_offset = record.monotonic_offset_ns
    return count, payload_bytes, last_offset, reader.truncated_tail


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
