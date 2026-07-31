import { formatTimeOfDay } from "@/lib/format";
import type { WidgetRenderProps } from "@/lib/widgetMeta";
import { Caption } from "./shared";

export function ClockWidget({ frame }: WidgetRenderProps) {
  return (
    <div className="flex flex-col items-center justify-center">
      <div className="text-2xl font-semibold leading-none">{formatTimeOfDay(frame.tod_ms)}</div>
      <Caption>in-game</Caption>
    </div>
  );
}
