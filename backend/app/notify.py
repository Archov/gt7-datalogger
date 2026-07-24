"""Outbound webhook notifications (personal bests, session summaries).

Discord webhook URLs get a rich embed; any other URL receives plain JSON with
an `event` field, so generic automations (n8n, Home Assistant, ...) work too.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


def format_lap_time(ms: int) -> str:
    return f"{ms // 60000}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"


class Notifier:
    """Sends webhook events fire-and-forget; failures only log."""

    def __init__(self) -> None:
        self.url: str = ""

    @property
    def _is_discord(self) -> bool:
        return "discord.com/api/webhooks" in self.url or "discordapp.com/api/webhooks" in self.url

    def notify(self, event: str, title: str, fields: list[tuple[str, str]]) -> None:
        if not self.url:
            return
        asyncio.get_running_loop().create_task(self._send(event, title, fields))

    async def send(self, event: str, title: str, fields: list[tuple[str, str]]) -> None:
        """Awaitable variant (used by the admin test endpoint)."""
        await self._send(event, title, fields, raise_errors=True)

    async def _send(
        self,
        event: str,
        title: str,
        fields: list[tuple[str, str]],
        raise_errors: bool = False,
    ) -> None:
        payload: dict[str, Any]
        if self._is_discord:
            payload = {
                "username": "GT7 Datalogger",
                "embeds": [
                    {
                        "title": title,
                        "color": 0x38BDF8,
                        "fields": [
                            {"name": k, "value": v, "inline": True} for k, v in fields
                        ],
                    }
                ],
            }
        else:
            extra = {k.lower().replace(" ", "_"): v for k, v in fields}
            payload = {"event": event, "title": title, **extra}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.url, json=payload)
                resp.raise_for_status()
            log.info("webhook sent: %s", event)
        except httpx.HTTPError as exc:
            log.warning("webhook %s failed: %s", event, exc)
            if raise_errors:
                raise

    # --- event helpers ------------------------------------------------------

    def personal_best(
        self, lap_time_ms: int, previous_ms: int, lap_number: int, car: str, track: str
    ) -> None:
        gain = (previous_ms - lap_time_ms) / 1000
        self.notify(
            "personal_best",
            f"🏁 New personal best: {format_lap_time(lap_time_ms)}",
            [
                ("Lap", str(lap_number)),
                ("Improvement", f"-{gain:.3f}s"),
                ("Car", car),
                ("Track", track or "unknown"),
            ],
        )

    def session_summary(
        self, car: str, track: str, lap_count: int, best_ms: int, fuel_used: float
    ) -> None:
        self.notify(
            "session_summary",
            "📋 Session complete",
            [
                ("Car", car),
                ("Track", track or "unknown"),
                ("Laps", str(lap_count)),
                ("Best lap", format_lap_time(best_ms) if best_ms > 0 else "–"),
                ("Fuel used", f"{fuel_used:.1f} L"),
            ],
        )
