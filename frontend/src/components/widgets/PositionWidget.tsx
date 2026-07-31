import type { WidgetRenderProps } from "@/lib/widgetMeta";
import { Caption } from "./shared";

export function PositionWidget({ frame, variant }: WidgetRenderProps) {
  if (variant === "compact") {
    return (
      <div className="flex items-baseline justify-center gap-1">
        <span className="text-base font-bold leading-none">P{frame.position}</span>
        <span className="text-xs text-ink-dim">/{frame.total_positions}</span>
      </div>
    );
  }

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
