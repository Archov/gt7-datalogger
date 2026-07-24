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
  const recent = laps.slice(0, 3).filter((lap) => lap.fuel_consumed > 0.01);
  if (recent.length === 0) return null;
  const avgFuelPerLap = recent.reduce((a, lap) => a + lap.fuel_consumed, 0) / recent.length;
  const avgLapMs = recent.reduce((a, lap) => a + lap.time_ms, 0) / recent.length;
  const lapsToEmpty = frame.fuel_level / avgFuelPerLap;
  return {
    avgFuelPerLap,
    avgLapMs,
    lapsToEmpty,
    pitBeforeLap: frame.current_lap + Math.floor(lapsToEmpty),
  };
}
