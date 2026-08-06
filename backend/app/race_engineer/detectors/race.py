"""Race-state callouts: final lap, halfway, position changes."""

from __future__ import annotations

from app.models import TelemetryPacket
from app.processing.live_events import LiveEvent
from app.race_engineer.detectors.base import Detector
from app.race_engineer.formatter import spoken_position
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext

# Below this a "halfway" call is noise — in a 3-lap sprint the midpoint and
# the final lap are the same moment.
MIN_LAPS_FOR_HALFWAY = 4


class RaceDetector(Detector):
    def __init__(self) -> None:
        self._final_done = False
        self._halfway_done = False

    def reset(self, ctx: EngineerContext) -> None:
        self._final_done = False
        self._halfway_done = False

    def on_packet(self, p: TelemetryPacket, ctx: EngineerContext) -> list[CalloutRequest]:
        if not p.is_on_track or p.is_paused or p.total_laps <= 0 or p.current_lap <= 0:
            return []
        out: list[CalloutRequest] = []
        if not self._final_done and p.current_lap == p.total_laps:
            self._final_done = True
            out.append(
                CalloutRequest(
                    event_type="final_lap",
                    text="Final lap.",
                    message_key="race.final_lap",
                    message_args={"lap": p.current_lap},
                    dedupe_key=f"final_lap:{ctx.session_seq}",
                    metadata={"lap": p.current_lap, "total_laps": p.total_laps},
                )
            )
        if (
            not self._halfway_done
            and p.total_laps >= MIN_LAPS_FOR_HALFWAY
            and p.current_lap > p.total_laps / 2
            # Joining (or restarting) late must not produce "halfway through
            # the race" one breath before "final lap".
            and p.current_lap < p.total_laps
        ):
            self._halfway_done = True
            out.append(
                CalloutRequest(
                    event_type="race_halfway",
                    text="Halfway through the race.",
                    message_key="race.halfway",
                    message_args={"lap": p.current_lap, "total_laps": p.total_laps},
                    dedupe_key=f"race_halfway:{ctx.session_seq}",
                    metadata={"lap": p.current_lap, "total_laps": p.total_laps},
                )
            )
        return out

    def on_live_event(self, event: LiveEvent, ctx: EngineerContext) -> list[CalloutRequest]:
        """Position changes, already debounced by the live event watcher.

        Reusing that watcher matters: GT7 flips the position field every few
        frames in side-by-side racing, and a second detector would have to
        re-learn the same 1 s stabilization (and could disagree with the
        webhook notifications about what happened).
        """
        if event.kind not in ("overtake", "position_lost"):
            return []
        gained = event.kind == "overtake"
        event_type = "position_gained" if gained else "position_lost"
        lead = "Position gained." if gained else "Position lost."
        return [
            CalloutRequest(
                event_type=event_type,
                text=f"{lead} You are now {spoken_position(event.position)}.",
                message_key=f"position.{'gained' if gained else 'lost'}",
                message_args={
                    "position": event.position,
                    "previous": event.previous_position,
                },
                dedupe_key=f"position:{ctx.session_seq}:{event.position}",
                metadata={
                    "position": event.position,
                    "previous_position": event.previous_position,
                    "total_positions": event.total_positions,
                },
            )
        ]
