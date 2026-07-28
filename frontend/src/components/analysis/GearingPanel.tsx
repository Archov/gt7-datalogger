// Gearing panel: per-lap transmission metadata (captured once per lap).
// Ratio table with estimated speed at redline per gear — real shift points
// vs redline and ratio gaps at a glance.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { speedUnit, speedValue, type Units } from "@/lib/format";
import type { LapGearing } from "@/lib/types";

export function GearingPanel({ lapId, units }: { lapId: number; units: Units }) {
  const [gearing, setGearing] = useState<LapGearing | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    api.lapDetail(lapId, false)
      .then((lap) => {
        if (!cancelled) setGearing((lap.gearing as LapGearing | null) ?? null);
      })
      .catch(() => {
        if (!cancelled) setGearing(null);
      });
    return () => {
      cancelled = true;
    };
  }, [lapId]);

  if (gearing === undefined) return <div className="skeleton m-3 h-16" />;
  if (gearing === null || gearing.ratios.length === 0) {
    return (
      <div className="p-3 text-xs text-ink-dim">
        No gearing data for this lap (recorded before Tier 1).
      </div>
    );
  }

  const last = gearing.ratios[gearing.ratios.length - 1];
  return (
    <div className="p-3">
      <table className="w-full font-tabular text-xs">
        <thead>
          <tr className="text-left text-ink-dim">
            <th className="pb-1 font-normal">Gear</th>
            <th className="pb-1 font-normal">Ratio</th>
            <th className="pb-1 text-right font-normal">est. @ redline</th>
          </tr>
        </thead>
        <tbody>
          {gearing.ratios.map((ratio, i) => (
            <tr key={i} className="border-t border-edge/50">
              <td className="py-1 text-ink-dim">{i + 1}</td>
              <td className="py-1">{ratio.toFixed(3)}</td>
              <td className="py-1 text-right">
                {Math.round(speedValue((gearing.top_speed * last) / ratio, units))}{" "}
                {speedUnit(units)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex justify-between font-tabular text-[11px] text-ink-dim">
        <span>Top speed (tune) {Math.round(speedValue(gearing.top_speed, units))} {speedUnit(units)}</span>
        <span>Redline {Math.round(gearing.rpm_alert).toLocaleString()} rpm</span>
      </div>
    </div>
  );
}
