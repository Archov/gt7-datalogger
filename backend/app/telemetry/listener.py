"""UDP telemetry capture from a PlayStation running GT7.

Sends a heartbeat ("A") to the console every ~1.6 s (GT7 stops sending after
100 packets without one) and receives ~60 Hz encrypted packets. If no console
IP is configured, the heartbeat is broadcast so the console is auto-discovered
from the first packet's source address.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.config import Settings
from app.models import TelemetryPacket
from app.telemetry.crypto import decrypt_packet
from app.telemetry.packet import parse_packet

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 1.6
STALE_AFTER = 5.0  # seconds without packets -> report disconnected

PacketCallback = Callable[[TelemetryPacket], Awaitable[None]]


class UdpTelemetrySource:
    """Async UDP source. Calls `on_packet` for every decoded packet."""

    def __init__(self, settings: Settings, on_packet: PacketCallback) -> None:
        self._settings = settings
        self._on_packet = on_packet
        self._transport: asyncio.DatagramTransport | None = None
        self._console_addr: tuple[str, int] | None = None
        self._last_packet_at: float = 0.0
        self._packet_count = 0
        self._decode_errors = 0
        self._dropped = 0
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
        # Packets are consumed by ONE task so processing stays strictly
        # ordered and never overlaps — overlapping feeds corrupt lap
        # detection (duplicate lap saves while a DB write is in flight).
        self._queue: asyncio.Queue[TelemetryPacket] = asyncio.Queue(maxsize=600)

    @property
    def connected(self) -> bool:
        return self._last_packet_at > 0 and (time.monotonic() - self._last_packet_at) < STALE_AFTER

    @property
    def stats(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "console_ip": self._console_addr[0] if self._console_addr else self._settings.ps_ip,
            "packets_received": self._packet_count,
            "decode_errors": self._decode_errors,
            "packets_dropped": self._dropped,
        }

    def reset_discovery(self) -> None:
        """Forget the discovered console (after the configured IP changes)."""
        self._console_addr = None
        self._last_packet_at = 0.0

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        source = self

        class _Protocol(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                source._handle_datagram(data, addr)

        self._transport, _ = await loop.create_datagram_endpoint(
            _Protocol,
            local_addr=("0.0.0.0", self._settings.telemetry_port),
            allow_broadcast=True,
        )
        self._running = True
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._consume_loop()))
        target = self._settings.ps_ip or "<broadcast>"
        log.info(
            "UDP telemetry listening on :%d, heartbeat to %s:%d",
            self._settings.telemetry_port, target, self._settings.heartbeat_port,
        )

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._transport:
            self._transport.close()

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._console_addr is None or self._console_addr[0] != addr[0]:
            log.info("telemetry source discovered at %s", addr[0])
        self._console_addr = addr
        self._last_packet_at = time.monotonic()
        plain = decrypt_packet(data)
        if plain is None:
            self._decode_errors += 1
            if self._decode_errors in (1, 100):
                log.warning("failed to decrypt packet from %s (bad key/format?)", addr[0])
            return
        try:
            packet = parse_packet(plain)
        except ValueError:
            self._decode_errors += 1
            return
        self._packet_count += 1
        try:
            self._queue.put_nowait(packet)
        except asyncio.QueueFull:
            # Consumer is behind (e.g. slow disk); drop the oldest to keep live.
            self._dropped += 1
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(packet)

    async def _consume_loop(self) -> None:
        while True:
            packet = await self._queue.get()
            try:
                await self._on_packet(packet)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "error processing telemetry packet %d: %s",
                    packet.packet_id,
                    exc,
                    exc_info=True,
                )

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self._send_heartbeat()
            except OSError as exc:
                log.warning("heartbeat send failed: %s", exc)
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    def _send_heartbeat(self) -> None:
        if self._transport is None:
            return
        if self._settings.ps_ip:
            target = (self._settings.ps_ip, self._settings.heartbeat_port)
        elif self._console_addr:
            target = (self._console_addr[0], self._settings.heartbeat_port)
        else:
            target = ("255.255.255.255", self._settings.heartbeat_port)
        self._transport.sendto(b"A", target)
