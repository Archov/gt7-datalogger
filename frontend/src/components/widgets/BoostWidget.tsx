import type { WidgetRenderProps } from "@/lib/widgetMeta";
import { Caption, Gauge } from "./shared";

// Gauge full-scale, in bar.
const BOOST_SCALE = 2;

export function BoostWidget({ frame, variant }: WidgetRenderProps) {
  if (variant === "gauge") {
    return (
      <div className="flex flex-col items-center justify-center">
        <Gauge
          value={Math.max(0, frame.boost) / BOOST_SCALE}
          text={frame.boost.toFixed(2)}
          caption="boost bar"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center">
      <div className="text-2xl font-semibold leading-none">{frame.boost.toFixed(2)}</div>
      <Caption>boost bar</Caption>
    </div>
  );
}
