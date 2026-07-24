// OBS / stream overlay: transparent page with a single compact telemetry
// strip. Add http://<host>:8000/#overlay as an OBS browser source.

import { useEffect, useRef, useState } from "react";
import { formatDelta, formatLapTime, speedUnit, speedValue } from "@/lib/format";
import type { LiveFrame } from "@/lib/types";
import { useSettings } from "@/store/settings";
import { liveFrameRef } from "@/store/telemetry";

export function OverlayView() {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const raf = useRef(0);

  useEffect(() => {
    document.body.classList.add("overlay");
    const tick = () => {
      setFrame(liveFrameRef.current);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      document.body.classList.remove("overlay");
      cancelAnimationFrame(raf.current);
    };
  }, []);

  if (!frame) return null;
  return <OverlayStrip frame={frame} />;
}

function OverlayStrip({ frame }: { frame: LiveFrame }) {
  const units = useSettings((s) => s.units);
  const rpmPct = Math.min(100, (frame.rpm / Math.max(1, frame.rpm_alert)) * 100);
  const nearLimit = frame.rpm >= frame.rpm_alert * 0.95;
  const fuelPct = (frame.fuel_level / Math.max(1, frame.fuel_capacity)) * 100;
  const delta =
    frame.last_lap_ms > 0 && frame.session_best_ms > 0
      ? frame.last_lap_ms - frame.session_best_ms
      : null;

  return (
    <div className="flex h-full items-end justify-center pb-4">
      <div className="flex items-stretch gap-4 rounded-2xl border border-white/10 bg-black/70 px-5 py-3 font-tabular backdrop-blur-sm">
        {/* Gear + speed */}
        <div className="flex items-center gap-3">
          <span className="text-6xl font-bold leading-none text-accent">
            {frame.gear === 0 ? "R" : frame.gear === 15 ? "N" : frame.gear}
          </span>
          <div>
            <div className="text-4xl font-bold leading-none">
              {Math.round(speedValue(frame.speed_kmh, units))}
            </div>
            <div className="text-[10px] uppercase tracking-widest text-ink-dim">
              {speedUnit(units)}
            </div>
          </div>
        </div>

        {/* RPM + inputs */}
        <div className="flex w-44 flex-col justify-center gap-1.5">
          <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full ${nearLimit ? "bg-brake" : "bg-accent"}`}
              style={{ width: `${rpmPct}%` }}
            />
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div className="h-full bg-throttle" style={{ width: `${frame.throttle}%` }} />
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
            <div className="h-full bg-brake" style={{ width: `${frame.brake}%` }} />
          </div>
        </div>

        {/* Laps */}
        <div className="flex flex-col justify-center text-xs leading-5">
          <div>
            <span className="text-ink-dim">LAP </span>
            {frame.current_lap}
            {frame.total_laps > 0 ? `/${frame.total_laps}` : ""}
          </div>
          <div>
            <span className="text-ink-dim">BEST </span>
            <span className="text-accent">{formatLapTime(frame.best_lap_ms)}</span>
          </div>
          <div>
            <span className="text-ink-dim">LAST </span>
            {formatLapTime(frame.last_lap_ms)}
            {delta !== null && (
              <span className={delta <= 0 ? "text-throttle" : "text-brake"}>
                {" "}{formatDelta(delta)}
              </span>
            )}
          </div>
        </div>

        {/* Tires */}
        <div className="grid grid-cols-2 content-center gap-1">
          {frame.tire_temps.map((t, i) => (
            <div
              key={i}
              className={`h-4 w-7 rounded-sm text-center text-[9px] leading-4 ${
                t < 55 ? "bg-coast/40" : t < 95 ? "bg-throttle/40" : "bg-brake/50"
              }`}
            >
              {Math.round(t)}
            </div>
          ))}
        </div>

        {/* Fuel */}
        <div className="flex flex-col items-center justify-center">
          <div className={`text-lg font-semibold ${fuelPct < 15 ? "text-brake" : ""}`}>
            {fuelPct.toFixed(0)}%
          </div>
          <div className="text-[9px] uppercase tracking-widest text-ink-dim">fuel</div>
        </div>
      </div>
    </div>
  );
}
