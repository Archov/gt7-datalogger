// Configurable overlay / dashboard. Widgets, layout, and appearance come from
// the URL hash (see lib/overlay.ts). Used as an OBS browser source (strip or
// stack on a transparent page) or as a phone dashboard (grid on a dark page).

import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  formatDelta,
  formatLapTime,
  formatTimeOfDay,
  speedUnit,
  speedValue,
} from "@/lib/format";
import type { OverlayConfig, WidgetId } from "@/lib/overlay";
import { projectStrategy } from "@/lib/strategy";
import type { LapSummary, LiveFrame } from "@/lib/types";
import { useSettings } from "@/store/settings";
import { liveFrameRef, useTelemetry } from "@/store/telemetry";

export function OverlayView({ config }: { config: OverlayConfig }) {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const recentLaps = useTelemetry((s) => s.recentLaps);
  const raf = useRef(0);
  const gridPage = config.layout === "grid";

  useEffect(() => {
    document.body.classList.add(gridPage ? "overlay-page" : "overlay");
    const tick = () => {
      setFrame(liveFrameRef.current);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      document.body.classList.remove("overlay", "overlay-page");
      cancelAnimationFrame(raf.current);
    };
  }, [gridPage]);

  if (!frame) {
    return gridPage ? (
      <div className="flex h-full items-center justify-center text-sm text-ink-dim">
        Waiting for telemetry…
      </div>
    ) : null;
  }

  const card: CSSProperties = { backgroundColor: `rgba(8, 10, 14, ${config.bg / 100})` };
  const widgets = config.widgets.map((id) => (
    <Widget key={id} id={id} frame={frame} laps={recentLaps} card={card} layout={config.layout} />
  ));

  if (config.layout === "grid") {
    return (
      <div className="min-h-full p-3" style={{ zoom: config.scale }}>
        <div className="mx-auto grid max-w-md grid-cols-2 gap-2 font-tabular">{widgets}</div>
      </div>
    );
  }

  const justify =
    config.align === "top" ? "items-start" : config.align === "center" ? "items-center" : "items-end";
  if (config.layout === "stack") {
    return (
      <div className={`flex h-full justify-start p-4 ${justify}`} style={{ zoom: config.scale }}>
        <div className="flex w-56 flex-col gap-2 font-tabular">{widgets}</div>
      </div>
    );
  }
  return (
    <div className={`flex h-full justify-center p-4 ${justify}`} style={{ zoom: config.scale }}>
      <div
        className="flex items-stretch gap-3 rounded-2xl border border-white/10 px-4 py-3 font-tabular backdrop-blur-sm"
        style={card}
      >
        {config.widgets.map((id) => (
          <Widget key={id} id={id} frame={frame} laps={recentLaps} card={{}} layout="strip" />
        ))}
      </div>
    </div>
  );
}

// --- widgets ----------------------------------------------------------------

interface WidgetProps {
  id: WidgetId;
  frame: LiveFrame;
  laps: LapSummary[];
  card: CSSProperties;
  layout: OverlayConfig["layout"];
}

function Widget({ id, frame, laps, card, layout }: WidgetProps) {
  const inStrip = layout === "strip";
  const body = pickWidget(id, frame, laps, inStrip);
  if (body === null) return null;
  if (inStrip) return body;
  return (
    <div
      className={`rounded-xl border border-white/10 p-3 ${id === "speed" || id === "gear" ? "" : ""}`}
      style={card}
    >
      {body}
    </div>
  );
}

function pickWidget(
  id: WidgetId,
  frame: LiveFrame,
  laps: LapSummary[],
  inStrip: boolean,
): React.ReactNode {
  switch (id) {
    case "gear":
      return <GearWidget frame={frame} big={!inStrip} />;
    case "speed":
      return <SpeedWidget frame={frame} big={!inStrip} />;
    case "rpm":
      return <RpmWidget frame={frame} />;
    case "inputs":
      return <InputsWidget frame={frame} />;
    case "times":
      return <TimesWidget frame={frame} />;
    case "delta":
      return <DeltaWidget frame={frame} />;
    case "position":
      return <PositionWidget frame={frame} />;
    case "tires":
      return <TiresWidget frame={frame} />;
    case "fuel":
      return <FuelWidget frame={frame} />;
    case "strategy":
      return <StrategyWidget frame={frame} laps={laps} />;
    case "clock":
      return <ClockWidget frame={frame} />;
  }
}

function Caption({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9px] uppercase tracking-widest text-ink-dim">{children}</div>
  );
}

function GearWidget({ frame, big }: { frame: LiveFrame; big: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center">
      <span className={`${big ? "text-7xl" : "text-6xl"} font-bold leading-none text-accent`}>
        {frame.gear === 0 ? "R" : frame.gear === 15 ? "N" : frame.gear}
      </span>
      <Caption>
        gear{frame.suggested_gear !== 15 ? ` → ${frame.suggested_gear}` : ""}
      </Caption>
    </div>
  );
}

function SpeedWidget({ frame, big }: { frame: LiveFrame; big: boolean }) {
  const units = useSettings((s) => s.units);
  return (
    <div className="flex flex-col items-center justify-center">
      <div className={`${big ? "text-6xl" : "text-4xl"} font-bold leading-none`}>
        {Math.round(speedValue(frame.speed_kmh, units))}
      </div>
      <Caption>{speedUnit(units)}</Caption>
    </div>
  );
}

function RpmWidget({ frame }: { frame: LiveFrame }) {
  const pct = Math.min(100, (frame.rpm / Math.max(1, frame.rpm_alert)) * 100);
  const nearLimit = frame.rpm >= frame.rpm_alert * 0.95;
  return (
    <div className="flex w-full min-w-40 flex-col justify-center gap-1">
      <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full ${nearLimit ? "bg-brake" : "bg-accent"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-ink-dim">
        <span>{frame.rpm.toLocaleString()} rpm</span>
        {nearLimit && <span className="text-brake">SHIFT</span>}
      </div>
    </div>
  );
}

function InputsWidget({ frame }: { frame: LiveFrame }) {
  return (
    <div className="flex w-full min-w-36 flex-col justify-center gap-1.5">
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full bg-throttle" style={{ width: `${frame.throttle}%` }} />
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-white/10">
        <div className="h-full bg-brake" style={{ width: `${frame.brake}%` }} />
      </div>
    </div>
  );
}

function lastVsPrevBest(frame: LiveFrame): number | null {
  return frame.last_lap_ms > 0 && frame.prev_best_ms > 0
    ? frame.last_lap_ms - frame.prev_best_ms
    : null;
}

function lapLabel(frame: LiveFrame): string {
  if (frame.total_laps > 0 && frame.current_lap > frame.total_laps) return "FIN";
  return `${frame.current_lap}${frame.total_laps > 0 ? `/${frame.total_laps}` : ""}`;
}

function TimesWidget({ frame }: { frame: LiveFrame }) {
  const delta = lastVsPrevBest(frame);
  return (
    <div className="flex flex-col justify-center text-xs leading-5">
      <div>
        <span className="text-ink-dim">LAP </span>
        {lapLabel(frame)}
      </div>
      <div>
        <span className="text-ink-dim">BEST </span>
        <span className="text-accent">{formatLapTime(frame.best_lap_ms)}</span>
      </div>
      <div>
        <span className="text-ink-dim">LAST </span>
        {formatLapTime(frame.last_lap_ms)}
        {delta !== null && (
          <span className={delta <= 0 ? "text-throttle" : "text-brake"}> {formatDelta(delta)}</span>
        )}
      </div>
    </div>
  );
}

function DeltaWidget({ frame }: { frame: LiveFrame }) {
  const delta = lastVsPrevBest(frame);
  return (
    <div className="flex flex-col items-center justify-center">
      <div
        className={`text-3xl font-bold leading-none ${
          delta == null ? "text-ink-dim" : delta <= 0 ? "text-throttle" : "text-brake"
        }`}
      >
        {delta == null ? "–" : formatDelta(delta)}
      </div>
      <Caption>Δ best</Caption>
    </div>
  );
}

function PositionWidget({ frame }: { frame: LiveFrame }) {
  return (
    <div className="flex flex-col items-center justify-center">
      <div className="text-3xl font-bold leading-none">
        P{frame.position}
        <span className="text-lg text-ink-dim">/{frame.total_positions}</span>
      </div>
      <Caption>position</Caption>
    </div>
  );
}

function TiresWidget({ frame }: { frame: LiveFrame }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1">
      <div className="grid grid-cols-2 gap-1">
        {frame.tire_temps.map((t, i) => (
          <div
            key={i}
            className={`h-4 w-8 rounded-sm text-center text-[9px] leading-4 ${
              t < 55 ? "bg-coast/40" : t < 95 ? "bg-throttle/40" : "bg-brake/50"
            }`}
          >
            {Math.round(t)}
          </div>
        ))}
      </div>
      <Caption>tires °C</Caption>
    </div>
  );
}

function FuelWidget({ frame }: { frame: LiveFrame }) {
  const pct = (frame.fuel_level / Math.max(1, frame.fuel_capacity)) * 100;
  return (
    <div className="flex flex-col items-center justify-center">
      <div className={`text-2xl font-semibold leading-none ${pct < 15 ? "text-brake" : ""}`}>
        {pct.toFixed(0)}%
      </div>
      <div className="mt-1 h-1.5 w-14 overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full ${pct < 15 ? "bg-brake" : "bg-warn"}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <Caption>fuel</Caption>
    </div>
  );
}

function StrategyWidget({ frame, laps }: { frame: LiveFrame; laps: LapSummary[] }) {
  const proj = projectStrategy(frame, laps);
  return (
    <div className="flex flex-col justify-center text-xs leading-5">
      {proj == null ? (
        <span className="text-ink-dim">fuel: need a lap</span>
      ) : (
        <>
          <div>
            <span className="text-ink-dim">FUEL </span>
            <span className={proj.lapsToEmpty < 2 ? "text-brake" : proj.lapsToEmpty < 4 ? "text-warn" : ""}>
              {proj.lapsToEmpty.toFixed(1)} laps
            </span>
          </div>
          <div>
            <span className="text-ink-dim">PIT ≤ L</span>
            {proj.pitBeforeLap}
          </div>
        </>
      )}
    </div>
  );
}

function ClockWidget({ frame }: { frame: LiveFrame }) {
  return (
    <div className="flex flex-col items-center justify-center">
      <div className="text-2xl font-semibold leading-none">{formatTimeOfDay(frame.tod_ms)}</div>
      <Caption>in-game</Caption>
    </div>
  );
}
