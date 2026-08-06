"""Lap-time and personal-best callouts."""

from __future__ import annotations

from app.race_engineer.detectors.base import Detector
from app.race_engineer.formatter import spoken_gap, spoken_lap_time
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext, LapRecord

# Gaps below this are noise to a driver — "no tenths" is not worth saying.
MIN_GAP_MS = 50


class LapDetector(Detector):
    def on_lap(self, lap: LapRecord, ctx: EngineerContext) -> list[CalloutRequest]:
        # A pit out-lap gets a real GT7 lap time but covers a fraction of the
        # track; announcing it as a lap (let alone a best) is worse than
        # silence. Same flag the session best and the live delta respect.
        if not lap.counts_for_best or lap.time_ms <= 0:
            return []
        prev = ctx.prev_best_ms
        spoken = spoken_lap_time(lap.time_ms)
        key = f"{ctx.session_seq}:{lap.number}"

        if prev is not None and lap.time_ms < prev:
            gain = prev - lap.time_ms
            text = f"New personal best, {spoken}."
            if gain >= MIN_GAP_MS:
                text += f" {spoken_gap(gain).capitalize()} faster."
            return [
                CalloutRequest(
                    event_type="personal_best",
                    text=text,
                    message_key="lap.personal_best",
                    message_args={"time_ms": lap.time_ms, "gain_ms": gain},
                    dedupe_key=f"personal_best:{key}",
                    metadata={"lap": lap.number, "time_ms": lap.time_ms, "gain_ms": gain},
                )
            ]

        text = f"Lap time, {spoken}."
        diff = lap.time_ms - prev if prev is not None else 0
        if prev is not None and abs(diff) >= MIN_GAP_MS:
            text += f" {spoken_gap(diff).capitalize()} {'slower' if diff > 0 else 'faster'}."
        return [
            CalloutRequest(
                event_type="lap_time",
                text=text,
                message_key="lap.time",
                message_args={"time_ms": lap.time_ms, "delta_ms": diff},
                dedupe_key=f"lap_time:{key}",
                metadata={"lap": lap.number, "time_ms": lap.time_ms, "delta_ms": diff},
            )
        ]
