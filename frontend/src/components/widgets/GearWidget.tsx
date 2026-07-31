import type { WidgetRenderProps } from "@/lib/widgetMeta";
import { Caption, isBig } from "./shared";

export function GearWidget(props: WidgetRenderProps) {
  const { frame, variant } = props;
  const big = isBig(props);
  return (
    <div className="flex flex-col items-center justify-center">
      <span className={`${big ? "text-7xl" : "text-6xl"} font-bold leading-none text-accent`}>
        {frame.gear === 0 ? "R" : frame.gear === 15 ? "N" : frame.gear}
      </span>
      <Caption>
        gear
        {variant !== "plain" && frame.suggested_gear !== 15 ? ` → ${frame.suggested_gear}` : ""}
      </Caption>
    </div>
  );
}
