"""Sustained pace loss: the stint is drifting away from the best lap.

Distinct from the per-lap "one point one seconds slower" comparison, which is
about a single lap. This watches the trend — tires going away, fuel-saving,
concentration — and only speaks when several laps in a row are off the pace.
"""

from __future__ import annotations

from app.race_engineer.detectors.base import Detector
from app.race_engineer.formatter import spoken_gap
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext, LapRecord
from app.race_engineer.thresholds import (
    PACE_CLEAR_MS,
    PACE_DROP_MS,
    PACE_ESCALATION_MS,
    PACE_MIN_LAPS,
    PACE_WINDOW_LAPS,
)


class PaceDetector(Detector):
    """Rolling average of recent laps against the session best.

    The best lap is the reference on purpose: it is the pace the driver has
    already proven on this track, in this car, this session — a threshold on
    lap-to-lap variation would fire on traffic instead of on a real drop.
    """

    def __init__(self) -> None:
        self._dropped = False
        # Incremented every time the pace recovers, so a second slump later in
        # the stint gets a fresh dedupe key instead of counting as a repeat.
        self._spell = 0

    def reset(self, ctx: EngineerContext) -> None:
        self._dropped = False
        self._spell = 0

    def on_lap(self, lap: LapRecord, ctx: EngineerContext) -> list[CalloutRequest]:
        best = ctx.best_lap_ms if ctx.best_lap_ms is not None else ctx.prev_best_ms
        if best is None or not lap.counts_for_best:
            return []
        recent = [rec.time_ms for rec in ctx.laps if rec.counts_for_best][:PACE_WINDOW_LAPS]
        counted = sum(1 for rec in ctx.laps if rec.counts_for_best)
        if counted < PACE_MIN_LAPS or len(recent) < PACE_WINDOW_LAPS:
            return []

        average = sum(recent) / len(recent)
        drop = average - best
        # A window containing a lap at (or near) the best is not a slump, even
        # if the average is dragged up by one bad lap — and saying "your pace
        # is dropping" moments after a personal best reads as a bug.
        on_pace = min(recent) - best < PACE_CLEAR_MS
        if on_pace or drop < PACE_CLEAR_MS:
            # Back on the pace: arm the detector for a later slump.
            if self._dropped:
                self._dropped = False
                self._spell += 1
            return []
        if drop < PACE_DROP_MS:
            return []  # inside the hysteresis band; neither drop nor recovery

        self._dropped = True
        return [
            CalloutRequest(
                event_type="pace_drop",
                text=f"Your pace is dropping, {spoken_gap(drop)} off your best.",
                message_key="pace.drop",
                message_args={"gap_ms": round(drop), "laps": len(recent)},
                # The spell keeps a recovered-then-lost pace speakable again,
                # while a still-slipping stint escalates instead of repeating.
                dedupe_key=f"pace_drop:{ctx.session_seq}:{self._spell}",
                metadata={
                    "average_ms": round(average),
                    "best_ms": best,
                    "gap_ms": round(drop),
                    "laps": len(recent),
                },
                severity=int(drop / PACE_ESCALATION_MS),
            )
        ]
