import { computeAlerts, type AlertSeverity } from "@/lib/alerts";
import type { WidgetRenderProps } from "@/lib/widgetMeta";

const BANNER_CLASS: Record<AlertSeverity, string> = {
  critical: "bg-brake/85 text-white animate-pulse",
  warn: "bg-warn/80 text-black",
  info: "bg-accent/70 text-black",
};

const TEXT_CLASS: Record<AlertSeverity, string> = {
  critical: "text-brake animate-pulse",
  warn: "text-warn",
  info: "text-accent",
};

// Renders nothing when all is well, so the cell stays transparent in OBS.
export function AlertsWidget({ frame, laps, variant }: WidgetRenderProps) {
  const alerts = computeAlerts(frame, laps);
  if (alerts.length === 0) return null;

  if (variant === "list") {
    return (
      <div className="flex flex-col justify-center gap-0.5 text-xs font-semibold leading-4">
        {alerts.map((a) => (
          <div key={a.id} className={TEXT_CLASS[a.severity]}>
            {a.message}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col justify-center gap-1">
      {alerts.map((a) => (
        <div
          key={a.id}
          className={`rounded-lg px-3 py-1 text-center text-sm font-bold uppercase tracking-wider ${BANNER_CLASS[a.severity]}`}
        >
          {a.message}
        </div>
      ))}
    </div>
  );
}
