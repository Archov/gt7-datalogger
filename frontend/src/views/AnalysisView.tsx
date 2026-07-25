// Analysis view: multi-lap comparison with synced cursors, race line map,
// consistency (deviation), fuel strategy, and tuning info.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DeviationChart } from "@/components/analysis/DeviationChart";
import { FuelMapPanel } from "@/components/analysis/FuelMapPanel";
import { RaceLineMap, type MapLap } from "@/components/analysis/RaceLineMap";
import { CHART_COLORS } from "@/components/EChart";
import { StackedCharts } from "@/components/analysis/StackedCharts";
import { api } from "@/lib/api";
import { formatLapTime, formatSpeed } from "@/lib/format";
import type { CompareResult, DeviationResult, LapSummary, SessionSummary } from "@/lib/types";
import { useSettings } from "@/store/settings";
import { useTelemetry } from "@/store/telemetry";

export function AnalysisView() {
  const units = useSettings((s) => s.units);
  const lapEpoch = useTelemetry((s) => s.lapEpoch);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [laps, setLaps] = useState<LapSummary[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [refLap, setRefLap] = useState<number | null>(null);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [deviation, setDeviation] = useState<DeviationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load sessions (refreshed when a new lap arrives live)
  useEffect(() => {
    api.sessions().then((s) => {
      setSessions(s);
      setSessionId((cur) => cur ?? s[0]?.id ?? null);
    }).catch(() => setError("Could not load sessions"));
  }, [lapEpoch]);

  // Load laps for the chosen session. Until the user picks laps manually,
  // selection follows "latest vs best" as new laps arrive live.
  const manualSelection = useRef(false);
  useEffect(() => {
    if (sessionId == null) return;
    api.sessionLaps(sessionId).then((ls) => {
      setLaps(ls);
      if (ls.length === 0) return;
      const best = [...ls].sort((a, b) => a.time_ms - b.time_ms)[0];
      const latest = ls[0]; // list is newest-first
      setSelected((cur) => {
        const stillValid = cur.filter((id) => ls.some((l) => l.id === id));
        return manualSelection.current && stillValid.length > 0
          ? stillValid
          : [...new Set([latest.id, best.id])];
      });
      setRefLap((cur) =>
        manualSelection.current && cur && ls.some((l) => l.id === cur) ? cur : best.id,
      );
    }).catch(() => setError("Could not load laps"));
  }, [sessionId, lapEpoch]);

  // Fetch comparison + deviation when the selection changes
  useEffect(() => {
    if (refLap == null || selected.length === 0) {
      setCompare(null);
      return;
    }
    setLoading(true);
    api.compare(selected, refLap)
      .then((c) => {
        setCompare(c);
        setError(null);
      })
      .catch(() => setError("Comparison failed"))
      .finally(() => setLoading(false));
  }, [selected, refLap]);

  useEffect(() => {
    if (sessionId == null) return;
    api.deviation(sessionId).then(setDeviation).catch(() => setDeviation(null));
  }, [sessionId, lapEpoch]);

  // Cursor sync (rAF-throttled to keep hover smooth)
  const [cursorDist, setCursorDist] = useState<number | null>(null);
  const pendingCursor = useRef<number | null>(null);
  const rafId = useRef(0);
  const onCursorDist = useCallback((d: number | null) => {
    pendingCursor.current = d;
    if (!rafId.current) {
      rafId.current = requestAnimationFrame(() => {
        rafId.current = 0;
        setCursorDist(pendingCursor.current);
      });
    }
  }, []);

  const lapLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const lap of laps) {
      labels[String(lap.id)] = `L${lap.number} · ${formatLapTime(lap.time_ms)}${
        lap.id === refLap ? " (ref)" : ""
      }`;
    }
    return labels;
  }, [laps, refLap]);

  const refEntry = compare?.laps[String(refLap)];
  const refSummary = laps.find((l) => l.id === refLap);

  // Laps for the track map, colored exactly like the chart series (both use
  // the same key order over compare.laps).
  const mapLaps = useMemo<MapLap[]>(() => {
    if (!compare) return [];
    return Object.keys(compare.laps).map((id, i) => ({
      id,
      entry: compare.laps[id],
      color: CHART_COLORS.series[i % CHART_COLORS.series.length],
      label: lapLabels[id] ?? `Lap ${id}`,
      isRef: id === String(refLap),
    }));
  }, [compare, lapLabels, refLap]);

  if (sessions.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-ink-dim">
        No sessions yet — drive some laps first.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 p-3 xl:grid-cols-[1fr_360px]">
      {/* Left: selector + stacked charts */}
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl bg-panel p-3">
          <select
            value={sessionId ?? ""}
            onChange={(e) => {
              manualSelection.current = false;
              setSessionId(Number(e.target.value));
            }}
            className="rounded-md border border-edge bg-panel-2 px-2 py-1.5 text-sm"
          >
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                #{s.id} · {s.car_name} · {s.lap_count} laps
              </option>
            ))}
          </select>
          <div className="flex flex-wrap gap-1.5">
            {laps.map((lap) => {
              const active = selected.includes(lap.id);
              const isRef = lap.id === refLap;
              return (
                <button
                  key={lap.id}
                  onClick={() => {
                    manualSelection.current = true;
                    setSelected((cur) =>
                      active ? cur.filter((id) => id !== lap.id) : [...cur, lap.id],
                    );
                  }}
                  onDoubleClick={() => {
                    manualSelection.current = true;
                    setRefLap(lap.id);
                  }}
                  title="Click to toggle, double-click to set as reference"
                  className={`rounded-md border px-2 py-1 font-tabular text-xs transition-colors ${
                    isRef
                      ? "border-accent bg-accent/15 text-accent"
                      : active
                        ? "border-edge bg-panel-2 text-ink"
                        : "border-edge text-ink-dim hover:text-ink"
                  }`}
                >
                  L{lap.number} {formatLapTime(lap.time_ms)}
                </button>
              );
            })}
          </div>
          {refLap != null && (
            <select
              value={refLap}
              onChange={(e) => {
                manualSelection.current = true;
                setRefLap(Number(e.target.value));
              }}
              className="ml-auto rounded-md border border-edge bg-panel-2 px-2 py-1.5 text-xs"
              title="Reference lap"
            >
              {laps.map((lap) => (
                <option key={lap.id} value={lap.id}>
                  ref: L{lap.number} {formatLapTime(lap.time_ms)}
                </option>
              ))}
            </select>
          )}
        </div>

        {error && <div className="mb-3 rounded-md bg-brake/10 p-2 text-sm text-brake">{error}</div>}
        {loading && !compare && <div className="p-8 text-center text-ink-dim">Loading…</div>}
        {compare && (
          <div className="rounded-xl bg-panel p-2">
            <StackedCharts
              data={compare}
              lapLabels={lapLabels}
              units={units}
              onCursorDist={onCursorDist}
            />
          </div>
        )}
      </div>

      {/* Right: race line, deviation, fuel, tuning */}
      <div className="flex min-w-0 flex-col gap-3">
        {refEntry && (
          <SidePanel
            title={mapLaps.length > 1 ? "Race lines — selected laps" : "Race line (reference lap)"}
          >
            <RaceLineMap laps={mapLaps} cursorDist={cursorDist} step={compare!.step} />
          </SidePanel>
        )}
        {deviation && deviation.dist.length > 0 && (
          <SidePanel title={`Consistency — best ${deviation.lap_ids.length} laps`}>
            <DeviationChart data={deviation} units={units} />
          </SidePanel>
        )}
        {refLap != null && (
          <SidePanel title="Fuel strategy">
            <FuelMapPanel lapId={refLap} />
          </SidePanel>
        )}
        {refSummary && (
          <SidePanel title="Tuning info (reference lap)">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 p-3 font-tabular text-xs">
              <Info k="Max speed" v={formatSpeed(refSummary.max_speed, units)} />
              <Info k="Min body height" v={`${refSummary.min_body_height.toFixed(0)} mm`} />
              <Info k="Full throttle" v={`${refSummary.full_throttle_pct.toFixed(1)}%`} />
              <Info k="Full brake" v={`${refSummary.full_brake_pct.toFixed(1)}%`} />
              <Info k="Coasting" v={`${refSummary.coasting_pct.toFixed(1)}%`} />
              <Info k="Tire spin" v={`${refSummary.tire_spin_pct.toFixed(1)}%`} />
              <Info k="Fuel used" v={`${refSummary.fuel_consumed.toFixed(2)} L`} />
              <Info k="Car" v={refSummary.car_name ?? "–"} />
            </div>
          </SidePanel>
        )}
      </div>
    </div>
  );
}

function SidePanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-panel">
      <div className="border-b border-edge px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-ink-dim">
        {title}
      </div>
      {children}
    </div>
  );
}

function Info({ k, v }: { k: string; v: string }) {
  return (
    <>
      <span className="text-ink-dim">{k}</span>
      <span className="text-right">{v}</span>
    </>
  );
}
