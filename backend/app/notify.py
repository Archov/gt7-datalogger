"""Outbound webhook notifications (personal bests, race events, summaries).

Discord webhook URLs get a rich embed; any other URL receives plain JSON with
an `event` field, so generic automations (n8n, Home Assistant, ...) work too.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Every webhook event type, in display order. Kept in sync with the Admin UI
# toggle list (frontend AdminView) and the docs.
ALL_EVENTS = (
    "personal_best",
    "session_summary",
    "overtake",
    "position_lost",
    "off_road",
)


def parse_events(spec: str) -> set[str]:
    """Parse a comma-separated event list, dropping unknown names."""
    return {e.strip() for e in spec.split(",") if e.strip() in ALL_EVENTS}


def format_lap_time(ms: int) -> str:
    return f"{ms // 60000}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}"


class Notifier:
    """Sends webhook events fire-and-forget; failures only log.

    Only events in `enabled` are sent (the admin "test" event always goes
    through so the Test button works regardless of toggles).
    """

    def __init__(self) -> None:
        self.url: str = ""
        self.enabled: set[str] = set(ALL_EVENTS)

    @property
    def _is_discord(self) -> bool:
        return "discord.com/api/webhooks" in self.url or "discordapp.com/api/webhooks" in self.url

    def notify(self, event: str, title: str, fields: list[tuple[str, str]]) -> None:
        if not self.url or (event in ALL_EVENTS and event not in self.enabled):
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

    def overtake(self, new_pos: int, old_pos: int, total: int, car: str, track: str) -> None:
        self.notify(
            "overtake",
            f"🟢 Overtake! P{old_pos} → P{new_pos}",
            [
                ("Position", f"P{new_pos} of {total}"),
                ("Car", car),
                ("Track", track or "unknown"),
            ],
        )

    def position_lost(self, new_pos: int, old_pos: int, total: int, car: str, track: str) -> None:
        self.notify(
            "position_lost",
            f"🔻 Position lost: P{old_pos} → P{new_pos}",
            [
                ("Position", f"P{new_pos} of {total}"),
                ("Car", car),
                ("Track", track or "unknown"),
            ],
        )

    def off_road(self, lap: int, car: str, track: str) -> None:
        self.notify(
            "off_road",
            "🌿 Off-road excursion",
            [
                ("Lap", str(lap) if lap > 0 else "–"),
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
