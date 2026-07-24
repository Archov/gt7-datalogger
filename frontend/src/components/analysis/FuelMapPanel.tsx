// Relative fuel-map strategy table: laps/time remaining per fuel setting.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { FuelMapResult } from "@/lib/types";

export function FuelMapPanel({ lapId }: { lapId: number }) {
  const [data, setData] = useState<FuelMapResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .fuelMap(lapId)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch(() => setError("No fuel data for this lap"));
  }, [lapId]);

  if (error) return <div className="p-3 text-xs text-ink-dim">{error}</div>;
  if (!data) return <div className="p-3 text-xs text-ink-dim">Loading…</div>;
  if (data.rows.length === 0)
    return (
      <div className="p-3 text-xs text-ink-dim">
        No fuel consumption on the reference lap — fuel map unavailable.
      </div>
    );

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-tabular text-xs">
        <thead>
          <tr className="text-left text-ink-dim">
            <th className="px-2 py-1 font-normal">Setting</th>
            <th className="px-2 py-1 font-normal">Fuel/lap</th>
            <th className="px-2 py-1 font-normal">Laps rem.</th>
            <th className="px-2 py-1 font-normal">Time rem.</th>
            <th className="px-2 py-1 font-normal">Lap Δ</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr
              key={r.setting}
              className={r.setting === 0 ? "bg-panel-2 text-accent" : "text-ink"}
            >
              <td className="px-2 py-0.5">{r.setting > 0 ? `+${r.setting}` : r.setting}</td>
              <td className="px-2 py-0.5">{r.fuel_per_lap.toFixed(2)}</td>
              <td className="px-2 py-0.5">{r.laps_remaining.toFixed(1)}</td>
              <td className="px-2 py-0.5">{formatDuration(r.time_remaining_ms)}</td>
              <td className="px-2 py-0.5">
                {r.lap_time_delta_ms > 0 ? "+" : ""}
                {(r.lap_time_delta_ms / 1000).toFixed(2)}s
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-2 py-1.5 text-[10px] text-ink-dim">
        Fuel {data.fuel_level.toFixed(1)} L · base {data.base_fuel_per_lap.toFixed(2)} L/lap
      </div>
    </div>
  );
}
