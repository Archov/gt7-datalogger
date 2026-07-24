// Sessions view: browse historical sessions, inspect and manage laps,
// export/import laps as JSON, manual "log lap now".

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formatLapTime, formatSpeed, formatTime } from "@/lib/format";
import type { LapSummary, SessionSummary } from "@/lib/types";
import { useSettings } from "@/store/settings";
import { useTelemetry } from "@/store/telemetry";

export function SessionsView() {
  const units = useSettings((s) => s.units);
  const lapEpoch = useTelemetry((s) => s.lapEpoch);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [laps, setLaps] = useState<Record<number, LapSummary[]>>({});
  const [message, setMessage] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    api.sessions().then(setSessions).catch(() => {});
  }, []);

  useEffect(refresh, [refresh, lapEpoch]);

  useEffect(() => {
    if (expanded == null) return;
    api.sessionLaps(expanded).then((ls) => setLaps((cur) => ({ ...cur, [expanded]: ls })));
  }, [expanded, lapEpoch]);

  const flash = (text: string) => {
    setMessage(text);
    window.setTimeout(() => setMessage(null), 3000);
  };

  async function exportLap(id: number) {
    const data = await api.exportLap(id);
    const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gt7-lap-${id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function importLap(file: File) {
    try {
      const payload = JSON.parse(await file.text());
      await api.importLap(payload);
      flash(`Imported ${file.name}`);
      refresh();
    } catch {
      flash("Import failed — not a valid lap file");
    }
  }

  async function logLapNow() {
    try {
      const res = await api.logLapNow();
      flash(`Saved in-progress lap #${res.id}`);
      refresh();
    } catch {
      flash("No lap in progress");
    }
  }

  return (
    <div className="mx-auto max-w-6xl p-3">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-lg font-semibold">Sessions</h2>
        <div className="ml-auto flex gap-2">
          <button onClick={logLapNow} className="btn">Log lap now</button>
          <button onClick={() => fileInput.current?.click()} className="btn">Import lap…</button>
          <input
            ref={fileInput}
            type="file"
            accept=".json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) importLap(f);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      {message && (
        <div className="mb-3 rounded-md bg-accent/10 px-3 py-2 text-sm text-accent">{message}</div>
      )}

      {sessions.length === 0 && (
        <div className="rounded-xl bg-panel p-8 text-center text-ink-dim">
          No sessions recorded yet.
        </div>
      )}

      <div className="space-y-2">
        {sessions.map((s) => (
          <div key={s.id} className="rounded-xl bg-panel">
            <button
              onClick={() => setExpanded(expanded === s.id ? null : s.id)}
              className="flex w-full items-center gap-4 px-4 py-3 text-left"
            >
              <span className="font-tabular text-sm text-ink-dim">#{s.id}</span>
              <span className="font-medium">{s.car_name}</span>
              <span className="text-xs text-ink-dim">{formatTime(s.started_at)}</span>
              <span className="ml-auto font-tabular text-sm">
                {s.lap_count} laps
                {s.best_lap_time_ms != null && (
                  <span className="ml-3 text-accent">{formatLapTime(s.best_lap_time_ms)}</span>
                )}
              </span>
              <span className="text-ink-dim">{expanded === s.id ? "▾" : "▸"}</span>
            </button>

            {expanded === s.id && (
              <div className="border-t border-edge px-2 pb-2">
                <LapTable
                  laps={laps[s.id] ?? []}
                  units={units}
                  bestMs={s.best_lap_time_ms}
                  onExport={exportLap}
                  onDelete={async (id) => {
                    await api.deleteLap(id);
                    setLaps((cur) => ({
                      ...cur,
                      [s.id]: (cur[s.id] ?? []).filter((l) => l.id !== id),
                    }));
                    refresh();
                  }}
                />
                <div className="flex justify-end px-2 pt-2">
                  <button
                    className="btn-danger"
                    onClick={async () => {
                      if (!confirm(`Delete session #${s.id} and all its laps?`)) return;
                      await api.deleteSession(s.id);
                      setExpanded(null);
                      refresh();
                    }}
                  >
                    Delete session
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function LapTable({
  laps,
  units,
  bestMs,
  onExport,
  onDelete,
}: {
  laps: LapSummary[];
  units: "metric" | "imperial";
  bestMs: number | null;
  onExport: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  if (laps.length === 0) return <div className="p-4 text-sm text-ink-dim">No laps.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full font-tabular text-xs">
        <thead>
          <tr className="text-left text-ink-dim">
            {["Lap", "Time", "Δ best", "Fuel", "Full thr.", "Full brake", "Coast", "Spin", "Max spd", ""].map(
              (h) => (
                <th key={h} className="px-2 py-2 font-normal">{h}</th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {laps.map((lap) => {
            const isBest = bestMs != null && lap.time_ms === bestMs;
            const diff = bestMs != null ? lap.time_ms - bestMs : null;
            return (
              <tr key={lap.id} className="border-t border-edge/50 hover:bg-panel-2/50">
                <td className="px-2 py-1.5 text-ink-dim">{lap.number}</td>
                <td className={`px-2 py-1.5 ${isBest ? "text-accent" : ""}`}>
                  {formatLapTime(lap.time_ms)}
                </td>
                <td className="px-2 py-1.5 text-ink-dim">
                  {diff == null || diff === 0 ? "–" : `+${(diff / 1000).toFixed(3)}`}
                </td>
                <td className="px-2 py-1.5">{lap.fuel_consumed.toFixed(2)} L</td>
                <td className="px-2 py-1.5">{lap.full_throttle_pct.toFixed(0)}%</td>
                <td className="px-2 py-1.5">{lap.full_brake_pct.toFixed(0)}%</td>
                <td className="px-2 py-1.5">{lap.coasting_pct.toFixed(0)}%</td>
                <td className="px-2 py-1.5">{lap.tire_spin_pct.toFixed(0)}%</td>
                <td className="px-2 py-1.5">{formatSpeed(lap.max_speed, units)}</td>
                <td className="px-2 py-1.5 text-right whitespace-nowrap">
                  <button className="mr-2 text-ink-dim hover:text-ink" onClick={() => onExport(lap.id)}>
                    export
                  </button>
                  <button className="text-ink-dim hover:text-brake" onClick={() => onDelete(lap.id)}>
                    delete
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
