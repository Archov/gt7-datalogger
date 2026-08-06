"""Rolling fuel-strategy projection.

Backend port of `frontend/src/lib/strategy.ts` (`projectStrategy`), used by the
Race Engineer callouts. The frontend keeps its own copy so the widgets stay
pure functions of the live frame; both must agree, so the constants below are
duplicated deliberately — change one, change the other (and the docs table in
docs/internals/fuel-strategy.md).
"""

from __future__ import annotations

from dataclasses import dataclass

WINDOW_LAPS = 3  # laps averaged for consumption/pace
MIN_FUEL_PER_LAP = 0.01  # L — below this the lap burned nothing usable
PARTIAL_LAP_RATIO = 0.5  # drop laps burning < this fraction of the window max


@dataclass(slots=True)
class LapFuel:
    """The per-lap fields the projection needs (mirrors LapSummary)."""

    number: int
    time_ms: int
    fuel_consumed: float
    car_id: int | None = None
    car_name: str = ""


@dataclass(slots=True)
class StrategyProjection:
    avg_fuel_per_lap: float
    avg_lap_ms: float
    laps_to_empty: float
    pit_before_lap: int


def project_strategy(
    fuel_level: float,
    current_lap: int,
    car_id: int | None,
    car_name: str,
    laps: list[LapFuel],
) -> StrategyProjection | None:
    """Project remaining range from the last few laps of the same car.

    `laps` is newest-first. Same car only (a race restart keeps the stint's
    laps, but a car swap must not inherit another car's consumption), and only
    laps that actually burned fuel.
    """

    def same_car(lap: LapFuel) -> bool:
        if lap.car_id is not None and car_id is not None:
            return lap.car_id == car_id
        if lap.car_name and car_name:
            return lap.car_name == car_name
        return True

    recent = [
        lap for lap in laps if lap.fuel_consumed > MIN_FUEL_PER_LAP and same_car(lap)
    ][:WINDOW_LAPS]
    if not recent:
        return None
    # Drop partial laps (a pit out-lap burns a fraction of a normal lap and
    # would inflate the projected range — dangerous with aggressive fuel use).
    max_fuel = max(lap.fuel_consumed for lap in recent)
    usable = [lap for lap in recent if lap.fuel_consumed >= PARTIAL_LAP_RATIO * max_fuel]
    avg_fuel = sum(lap.fuel_consumed for lap in usable) / len(usable)
    avg_lap_ms = sum(lap.time_ms for lap in usable) / len(usable)
    laps_to_empty = fuel_level / avg_fuel
    return StrategyProjection(
        avg_fuel_per_lap=avg_fuel,
        avg_lap_ms=avg_lap_ms,
        laps_to_empty=laps_to_empty,
        pit_before_lap=current_lap + int(laps_to_empty),
    )
