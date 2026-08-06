"""Fuel range, shortage prediction and pit-window callouts."""

from __future__ import annotations

from app.models import TelemetryPacket
from app.processing.strategy import project_strategy
from app.race_engineer.detectors.base import Detector, Sustained
from app.race_engineer.formatter import plural, spoken_decimal, spoken_laps
from app.race_engineer.models import CalloutRequest
from app.race_engineer.state import EngineerContext, LapRecord
from app.race_engineer.thresholds import (
    FUEL_LAPS_CRITICAL,
    FUEL_LAPS_WARN,
    FUEL_SHORTFALL_ESCALATION_LAPS,
    FUEL_SHORTFALL_MARGIN_LAPS,
    FUEL_SHORTFALL_MIN_LAPS,
)

# Laps of consumption history before any fuel number is spoken. One lap is
# enough for a number but not for a trustworthy one — an out-lap or a
# safety-car lap would set the whole projection wrong.
MIN_HISTORY_LAPS = 2
LIVE_HOLD_S = 2.0
# Range worth mentioning unconditionally — below this the tank is a decision.
RANGE_ALWAYS_BELOW_LAPS = 15.0
# ...or when it is within this many laps of the race distance left to run.
RANGE_RACE_MARGIN_LAPS = 3.0


class FuelDetector(Detector):
    """Per-lap projections plus a cheap live range check between them.

    Everything expensive (averaging laps, race-distance arithmetic) happens on
    lap completion. Between laps only one division runs per packet, so a tank
    draining faster than the lap-based model predicted is still caught before
    the car coasts to a stop.
    """

    def __init__(self) -> None:
        self._avg_per_lap: float | None = None
        self._short_laps = 0
        self._last_shortfall = 0.0
        self._pit_state = ""  # "" | "next" | "open"
        self._low = Sustained(FUEL_LAPS_WARN, FUEL_LAPS_WARN + 0.5, LIVE_HOLD_S, above=False)
        self._critical = Sustained(
            FUEL_LAPS_CRITICAL, FUEL_LAPS_CRITICAL + 0.3, LIVE_HOLD_S, above=False
        )

    def reset(self, ctx: EngineerContext) -> None:
        # `_avg_per_lap` deliberately survives: a race restart opens a new
        # session but the car and its consumption are unchanged, and dropping
        # the model would leave the first lap of the restart unguarded.
        self._short_laps = 0
        self._last_shortfall = 0.0
        self._pit_state = ""
        self._low.reset()
        self._critical.reset()

    # --- per lap ------------------------------------------------------------

    def on_lap(self, lap: LapRecord, ctx: EngineerContext) -> list[CalloutRequest]:
        p = ctx.packet
        if p is None or p.fuel_capacity <= 0:
            return []  # fuel consumption is off in this event
        proj = project_strategy(
            p.fuel_level, p.current_lap, p.car_id, "", [rec.as_fuel() for rec in ctx.laps]
        )
        if proj is None:
            return []
        self._avg_per_lap = proj.avg_fuel_per_lap
        usable = sum(1 for rec in ctx.laps if rec.fuel_consumed > 0.01)
        if usable < MIN_HISTORY_LAPS:
            return []

        out: list[CalloutRequest] = []
        if self._range_is_worth_saying(p, proj.laps_to_empty):
            out.append(
                CalloutRequest(
                    event_type="fuel_remaining",
                    text=f"Fuel remaining, {spoken_laps(proj.laps_to_empty)}.",
                    message_key="fuel.remaining",
                    message_args={"laps": round(proj.laps_to_empty, 1)},
                    dedupe_key=f"fuel_remaining:{ctx.session_seq}:{p.current_lap}",
                    metadata={
                        "laps_to_empty": round(proj.laps_to_empty, 2),
                        "fuel_per_lap": round(proj.avg_fuel_per_lap, 3),
                        "fuel_level": round(p.fuel_level, 2),
                    },
                )
            )
        out += self._race_distance_calls(p, proj.laps_to_empty, proj.pit_before_lap, ctx)
        return out

    @staticmethod
    def _range_is_worth_saying(p: TelemetryPacket, laps_to_empty: float) -> bool:
        """Skip the number when the tank cannot decide anything.

        "Fuel remaining, fifty-three point six laps" every lap of a practice
        stint is noise. It matters when the tank is genuinely finite, or when
        it is close to the race distance still to run.
        """
        if laps_to_empty <= RANGE_ALWAYS_BELOW_LAPS:
            return True
        if p.total_laps <= 0:
            return False
        remaining = p.total_laps - p.current_lap + 1
        return laps_to_empty <= remaining + RANGE_RACE_MARGIN_LAPS

    def _race_distance_calls(
        self, p: TelemetryPacket, laps_to_empty: float, pit_before_lap: int, ctx: EngineerContext
    ) -> list[CalloutRequest]:
        """Shortage and pit-window calls; only meaningful in a lapped race."""
        if p.total_laps <= 0:
            return []
        remaining = p.total_laps - p.current_lap + 1  # including the lap just started
        out: list[CalloutRequest] = []

        shortfall = remaining - laps_to_empty
        if shortfall > FUEL_SHORTFALL_MARGIN_LAPS:
            self._short_laps += 1
            # One lap's projection is easy to get wrong (a slow lap behind
            # traffic burns less); two in a row is a real shortfall.
            escalated = (
                shortfall - self._last_shortfall >= FUEL_SHORTFALL_ESCALATION_LAPS
                if self._last_shortfall
                else False
            )
            if self._short_laps >= FUEL_SHORTFALL_MIN_LAPS and (
                self._last_shortfall == 0.0 or escalated
            ):
                self._last_shortfall = shortfall
                out.append(
                    CalloutRequest(
                        event_type="fuel_short",
                        text=(
                            f"Fuel will be short by {spoken_decimal(shortfall)} "
                            f"{plural(round(shortfall, 1), 'lap')}."
                        ),
                        message_key="fuel.shortfall",
                        message_args={"laps": round(shortfall, 1)},
                        dedupe_key=f"fuel_short:{ctx.session_seq}",
                        metadata={
                            "shortfall_laps": round(shortfall, 2),
                            "fuel_laps_remaining": round(laps_to_empty, 2),
                            "race_laps_remaining": remaining,
                        },
                        severity=int(shortfall / FUEL_SHORTFALL_ESCALATION_LAPS) + 1,
                    )
                )
        else:
            self._short_laps = 0
            self._last_shortfall = 0.0

        # Pit window: the lap by which the tank runs out, while the race is
        # still running. Announced once per transition, not once per lap.
        if pit_before_lap < p.total_laps:
            if pit_before_lap <= p.current_lap:
                state, event, text = "open", "pit_window_open", "Pit window is open."
            elif pit_before_lap == p.current_lap + 1:
                state, event, text = "next", "pit_window_next", "Pit window opens next lap."
            else:
                state, event, text = "", "", ""
            if state and state != self._pit_state:
                self._pit_state = state
                out.append(
                    CalloutRequest(
                        event_type=event,
                        text=text,
                        message_key=f"strategy.{event}",
                        message_args={"lap": pit_before_lap},
                        dedupe_key=f"{event}:{ctx.session_seq}:{pit_before_lap}",
                        metadata={"pit_before_lap": pit_before_lap},
                    )
                )
        return out

    # --- between laps -------------------------------------------------------

    def on_packet(self, p: TelemetryPacket, ctx: EngineerContext) -> list[CalloutRequest]:
        if self._avg_per_lap is None or self._avg_per_lap <= 0:
            return []
        if not p.is_on_track or p.is_paused or p.fuel_capacity <= 0:
            self._low.reset()
            self._critical.reset()
            return []
        laps_left = p.fuel_level / self._avg_per_lap
        critical = self._critical.update(laps_left, ctx.now)
        low = self._low.update(laps_left, ctx.now)
        if not critical and not low:
            return []
        event = "fuel_critical" if critical else "fuel_low"
        lead = "Fuel critical" if critical else "Fuel low"
        return [
            CalloutRequest(
                event_type=event,
                text=f"{lead}, {spoken_laps(laps_left)} remaining.",
                message_key=f"fuel.{'critical' if critical else 'low'}",
                message_args={"laps": round(laps_left, 1)},
                dedupe_key=f"fuel_level:{ctx.session_seq}",
                metadata={"laps_to_empty": round(laps_left, 2)},
                severity=2 if critical else 1,
            )
        ]
