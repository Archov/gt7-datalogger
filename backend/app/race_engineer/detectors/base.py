"""Detector protocol and the shared threshold helper."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import TelemetryPacket
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext, LapRecord


class Detector:
    """Base class: override the hooks a detector actually needs.

    `on_packet` runs at 60 Hz — keep it to comparisons and counters. Anything
    that walks a lap's samples belongs in `on_lap`, which runs once per lap.
    """

    def reset(self, ctx: EngineerContext) -> None:
        """New session, car change or race restart."""

    def on_packet(self, p: TelemetryPacket, ctx: EngineerContext) -> list[CalloutRequest]:
        return []

    def on_lap(self, lap: LapRecord, ctx: EngineerContext) -> list[CalloutRequest]:
        return []


@dataclass(slots=True)
class Sustained:
    """A threshold that must hold for a while, and clears at a lower value.

    Reports the *state* of the condition rather than an edge: while it is
    held the detector keeps asking for its callout and the manager's cooldown
    decides how often the driver actually hears it (an engine that stays hot
    should be mentioned again, not once and never).
    """

    trigger: float
    clear: float
    hold_s: float
    above: bool = True  # False: fires when the value drops BELOW trigger
    _since: float | None = None
    _active: bool = False

    @property
    def active(self) -> bool:
        return self._active

    def reset(self) -> None:
        self._since = None
        self._active = False

    def update(self, value: float, now: float) -> bool:
        if self._active:
            cleared = value < self.clear if self.above else value > self.clear
            if cleared:
                self.reset()
            return self._active
        over = value >= self.trigger if self.above else value <= self.trigger
        if not over:
            self._since = None
            return False
        if self._since is None:
            self._since = now
        if now - self._since >= self.hold_s:
            self._active = True
        return self._active
