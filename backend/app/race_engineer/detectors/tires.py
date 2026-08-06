"""Tire callouts: sustained high temperature, front/rear and left/right balance."""

from __future__ import annotations

from app.models import TelemetryPacket
from app.race_engineer.detectors.base import Detector, Sustained
from app.race_engineer.formatter import plural, spoken_int
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext, LapRecord
from app.race_engineer.thresholds import (
    TIRE_IMBALANCE_C,
    TIRE_PERSISTENCE_S,
    TIRE_TEMP_CLEAR,
    TIRE_TEMP_WARN,
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class TireDetector(Detector):
    def __init__(self) -> None:
        self._hot = Sustained(TIRE_TEMP_WARN, TIRE_TEMP_CLEAR, TIRE_PERSISTENCE_S)

    def reset(self, ctx: EngineerContext) -> None:
        self._hot.reset()

    def on_packet(self, p: TelemetryPacket, ctx: EngineerContext) -> list[CalloutRequest]:
        if not p.is_on_track or p.is_paused:
            self._hot.reset()
            return []
        hottest = max(p.tire_temp_fl, p.tire_temp_fr, p.tire_temp_rl, p.tire_temp_rr)
        if not self._hot.update(hottest, ctx.now):
            return []
        return [
            CalloutRequest(
                event_type="tire_temp_high",
                text="Tire temperatures high.",
                message_key="tires.temp_high",
                message_args={"celsius": round(hottest)},
                dedupe_key=f"tire_temp:{ctx.session_seq}",
                metadata={"celsius": round(hottest, 1)},
            )
        ]

    def on_lap(self, lap: LapRecord, ctx: EngineerContext) -> list[CalloutRequest]:
        """Balance is a lap-average question — one corner proves nothing."""
        s = lap.samples
        cols = [s.get(f"tt_{w}") or [] for w in ("fl", "fr", "rl", "rr")]
        if not all(cols):
            return []
        fl, fr, rl, rr = (_mean(c) for c in cols)
        front, rear = (fl + fr) / 2, (rl + rr) / 2
        left, right = (fl + rl) / 2, (fr + rr) / 2
        # Report the bigger of the two imbalances; two callouts about the same
        # set of four temperatures is one too many.
        axis_gap, side_gap = rear - front, left - right
        if max(abs(axis_gap), abs(side_gap)) < TIRE_IMBALANCE_C:
            return []
        if abs(axis_gap) >= abs(side_gap):
            hot, cold = ("Rear", "fronts") if axis_gap > 0 else ("Front", "rears")
            gap, axis = abs(axis_gap), "front_rear"
        else:
            hot, cold = ("Left", "rights") if side_gap > 0 else ("Right", "lefts")
            gap, axis = abs(side_gap), "left_right"
        degrees = round(gap)
        return [
            CalloutRequest(
                event_type="tire_imbalance",
                text=(
                    f"{hot} tires are running {spoken_int(degrees)} "
                    f"{plural(degrees, 'degree')} hotter than the {cold}."
                ),
                message_key="tires.imbalance",
                message_args={"axis": axis, "hotter": hot.lower(), "degrees": degrees},
                dedupe_key=f"tire_imbalance:{ctx.session_seq}:{lap.number}",
                metadata={
                    "front": round(front, 1),
                    "rear": round(rear, 1),
                    "left": round(left, 1),
                    "right": round(right, 1),
                },
            )
        ]
