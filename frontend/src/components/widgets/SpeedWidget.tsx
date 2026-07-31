import { speedUnit, speedValue } from "@/lib/format";
import type { WidgetRenderProps } from "@/lib/widgetMeta";
import { useSettings } from "@/store/settings";
import { Caption, Gauge, isBig } from "./shared";

// Fraction-of-scale used by the bar and gauge variants; GT7 road cars rarely
// exceed this, so the needle spends the useful range in motion.
const SPEED_SCALE_KMH = 320;

export function SpeedWidget(props: WidgetRenderProps) {
  const { frame, variant } = props;
  const units = useSettings((s) => s.units);
  const value = Math.round(speedValue(frame.speed_kmh, units));
  const big = isBig(props);

  if (variant === "gauge") {
    return (
      <div className="flex flex-col items-center justify-center">
        <Gauge
          value={frame.speed_kmh / SPEED_SCALE_KMH}
          text={String(value)}
          caption={speedUnit(units)}
        />
      </div>
    );
  }

  if (variant === "bar") {
    const pct = Math.min(100, (frame.speed_kmh / SPEED_SCALE_KMH) * 100);
    return (
      <div className="flex w-full min-w-36 flex-col justify-center gap-1">
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-bold leading-none">{value}</span>
          <Caption>{speedUnit(units)}</Caption>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
          <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center">
      <div className={`${big ? "text-6xl" : "text-4xl"} font-bold leading-none`}>{value}</div>
      <Caption>{speedUnit(units)}</Caption>
    </div>
  );
}
