// Rolling fuel-strategy projection shared by the Live view and the overlay.

import type { LapSummary, LiveFrame } from "./types";

export interface StrategyProjection {
  avgFuelPerLap: number;
  avgLapMs: number;
  lapsToEmpty: number;
  pitBeforeLap: number;
}

export function projectStrategy(
  frame: LiveFrame,
  laps: LapSummary[],
): StrategyProjection | null {
  // Same car only (a race restart keeps the stint's laps; a car swap must
  // not inherit another car's consumption), and only laps that actually
  // burned fuel. Prefer car_id (exact); fall back to car_name; only when a
  // lap carries neither (demo data, legacy rows) is it accepted as-is.
  const sameCar = (lap: LapSummary): boolean => {
    if (lap.car_id != null && frame.car_id != null) return lap.car_id === frame.car_id;
    if (lap.car_name && frame.car_name) return lap.car_name === frame.car_name;
    return true;
  };
  const recent = laps
    .filter((lap) => lap.fuel_consumed > 0.01 && sameCar(lap))
    .slice(0, 3);
  if (recent.length === 0) return null;
  // Drop partial laps (pit out-laps burn a fraction of a normal lap and
  // would inflate the projected range — dangerous with aggressive fuel use).
  const maxFuel = Math.max(...recent.map((lap) => lap.fuel_consumed));
  const usable = recent.filter((lap) => lap.fuel_consumed >= 0.5 * maxFuel);
  const avgFuelPerLap = usable.reduce((a, lap) => a + lap.fuel_consumed, 0) / usable.length;
  const avgLapMs = usable.reduce((a, lap) => a + lap.time_ms, 0) / usable.length;
  const lapsToEmpty = frame.fuel_level / avgFuelPerLap;
  return {
    avgFuelPerLap,
    avgLapMs,
    lapsToEmpty,
    pitBeforeLap: frame.current_lap + Math.floor(lapsToEmpty),
  };
}
