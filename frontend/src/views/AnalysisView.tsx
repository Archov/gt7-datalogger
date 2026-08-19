// Analysis view: multi-lap comparison with synced cursors, race line map,
// consistency (deviation), fuel strategy, and tuning info. The lap selection
// can arrive via deep link (#/analysis?session=…&laps=…&ref=…) from the
// Sessions or Live views, and is mirrored back into the URL for sharing.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { ChannelPicker } from "@/components/analysis/ChannelPicker";
import { CornerDetail, type CornerLap } from "@/components/analysis/CornerDetail";
import { DeviationChart } from "@/components/analysis/DeviationChart";
import { FuelMapPanel } from "@/components/analysis/FuelMapPanel";
import { GearingPanel } from "@/components/analysis/GearingPanel";
import { RaceLineMap, type MapLap } from "@/components/analysis/RaceLineMap";
import { StackedCharts } from "@/components/analysis/StackedCharts";
import { Select } from "@/components/ui/Select";
import { Tip } from "@/components/ui/Tooltip";
import { api } from "@/lib/api";
import {
  CHANNEL_BY_KEY,
  columnsForChannels,
  isDefaultChannelSet,
  loadChannelKeys,
  saveChannelKeys,
} from "@/lib/channels";
import { lapColor, lapColorMap } from "@/lib/colors";
import { formatLapTime, formatSpeed } from "@/lib/format";
import {
  clampWorkspacePreferences,
  defaultWorkspacePreferences,
  hasStoredWorkspacePreferences,
  loadWorkspacePreferences,
  MAP_SCALE_PRESETS,
  MAP_SCALE_STEP,
  MAX_MAP_METERS_PER_PIXEL,
  MIN_CENTER_WIDTH,
  MIN_INSPECTOR_WIDTH,
  MIN_MAP_HEIGHT,
  MIN_MAP_METERS_PER_PIXEL,
  MIN_TIMELINE_HEIGHT,
  normalizeMapMetersPerPixel,
  saveWorkspacePreferences,
  TIMELINE_PANEL_HEIGHTS,
  type AnalysisWorkspacePreferences,
  WORKSPACE_DIVIDER_SIZE,
} from "@/lib/analysisWorkspace";
import { reflectAnalysisSelection, type AnalysisRequest } from "@/lib/router";
import type { CompareResult, DeviationResult, LapSummary, SessionSummary } from "@/lib/types";
import { useAnalysisSelection } from "@/store/analysis";
import { useSettings } from "@/store/settings";
import { useTelemetry } from "@/store/telemetry";

// The Corner Detail widget always needs the per-corner columns, whatever the
// chart picker says.
const CORNER_COLUMNS = [
  "slip_fl", "slip_fr", "slip_rl", "slip_rr",
  "tt_fl", "tt_fr", "tt_rl", "tt_rr",
  "sus_fl", "sus_fr", "sus_rl", "sus_rr",
  "throttle", "brake",
];

// The race-line map shades where wheels touched kerb/grass/gravel whenever
// the lap carries the per-tick surface column (packet C recordings).
const MAP_COLUMNS = [
  "surface",
  "orientation_x",
  "orientation_y",
  "orientation_z",
  "orientation_w",
  "velocity_x",
  "velocity_y",
  "velocity_z",
];

type ResizeKind = "vertical" | "horizontal" | "diagonal";

interface ResizeGesture {
  kind: ResizeKind;
  pointerId: number;
  startX: number;
  startY: number;
  inspectorWidth: number;
  mapHeight: number;
  workspaceWidth: number;
  workspaceHeight: number;
}

export function AnalysisView({ request }: { request: AnalysisRequest }) {
  const units = useSettings((s) => s.units);
  const lapEpoch = useTelemetry((s) => s.lapEpoch);

  // Seed from the shared selection so switching tabs doesn't reset the view.
  const stored = useRef(useAnalysisSelection.getState()).current;
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [sessionId, setSessionId] = useState<number | null>(request.session ?? stored.sessionId);
  const [laps, setLaps] = useState<LapSummary[]>([]);
  const [selected, setSelected] = useState<number[]>(request.laps ?? stored.selectedLapIds);
  const [refLap, setRefLap] = useState<number | null>(request.ref ?? stored.refLapId);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [deviation, setDeviation] = useState<DeviationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [channelKeys, setChannelKeys] = useState<string[]>(
    () => request.channels?.filter((k) => k in CHANNEL_BY_KEY) ?? loadChannelKeys(),
  );
  useEffect(() => saveChannelKeys(channelKeys), [channelKeys]);
  const channelDefs = useMemo(
    () => channelKeys.map((k) => CHANNEL_BY_KEY[k]).filter(Boolean),
    [channelKeys],
  );

  // Until the user (or a deep link) picks laps, selection follows
  // "latest vs best" as new laps arrive live.
  const manualSelection = useRef(
    (request.laps ?? stored.selectedLapIds).length > 0 || (request.ref ?? stored.refLapId) != null,
  );

  // Apply a new deep link while the view is mounted (pasted URL).
  const requestKey = `${request.session ?? ""}|${(request.laps ?? []).join(",")}|${request.ref ?? ""}|${(request.channels ?? []).join(",")}`;
  const firstRequest = useRef(true);
  useEffect(() => {
    if (firstRequest.current) {
      firstRequest.current = false; // initial state already covers the mount
      return;
    }
    if (request.session == null && request.laps == null && request.ref == null) return;
    if (request.session != null) setSessionId(request.session);
    if (request.laps != null || request.ref != null) {
      manualSelection.current = true;
      const lapIds = request.laps ?? [];
      const withRef =
        request.ref != null && !lapIds.includes(request.ref) ? [...lapIds, request.ref] : lapIds;
      if (withRef.length > 0) setSelected(withRef);
      if (request.ref != null) setRefLap(request.ref);
    }
    if (request.channels != null) {
      setChannelKeys(request.channels.filter((k) => k in CHANNEL_BY_KEY));
    }
    // Deliberately keyed on the serialized request only — re-running on every
    // object identity change would clobber in-view selection edits.
  }, [requestKey]);

  // Load sessions (refreshed when a new lap arrives live)
  useEffect(() => {
    api.sessions().then((s) => {
      setSessions(s);
      // Default to the newest session that actually has laps to chart.
      setSessionId((cur) => cur ?? s.find((x) => x.lap_count > 0)?.id ?? s[0]?.id ?? null);
    }).catch(() => setError("Could not load sessions"));
  }, [lapEpoch]);

  // Load laps for the chosen session.
  useEffect(() => {
    if (sessionId == null) return;
    api.sessionLaps(sessionId).then((all) => {
      // Laps without samples (phantoms from menu/replay flicker in old
      // recordings) have nothing to chart — keep them out of the picker.
      // Unknown tick counts are treated as empty, not as chartable.
      const ls = all.filter((lap) => (lap.total_ticks ?? 0) > 0);
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

  // Publish the resolved selection: shared store (tab switches) + URL (sharing).
  const setSharedSelection = useAnalysisSelection((s) => s.setSelection);
  useEffect(() => {
    if (sessionId == null || refLap == null || selected.length === 0) return;
    setSharedSelection({ sessionId, selectedLapIds: selected, refLapId: refLap });
    reflectAnalysisSelection({
      session: sessionId,
      laps: selected,
      ref: refLap,
      channels: isDefaultChannelSet(channelKeys) ? undefined : channelKeys,
    });
  }, [sessionId, selected, refLap, channelKeys, setSharedSelection]);

  // Fetch comparison + deviation when the selection or channel set changes.
  // The request always carries the per-corner columns for the Corner Detail
  // widget on top of whatever the picked panels need.
  const requestColumns = useMemo(
    () => [...new Set([...columnsForChannels(channelKeys), ...CORNER_COLUMNS, ...MAP_COLUMNS])],
    [channelKeys],
  );
  useEffect(() => {
    if (refLap == null || selected.length === 0) {
      setCompare(null);
      return;
    }
    setLoading(true);
    api.compare(selected, refLap, requestColumns)
      .then((c) => {
        setCompare(c);
        setError(null);
      })
      .catch(() => setError("Comparison failed"))
      .finally(() => setLoading(false));
  }, [selected, refLap, requestColumns]);

  useEffect(() => {
    if (sessionId == null) return;
    api.deviation(sessionId).then(setDeviation).catch(() => setDeviation(null));
  }, [sessionId, lapEpoch]);

  // Synchronized zoom state across all charts (minDist, maxDist in meters)
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null);

  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const resizeGesture = useRef<ResizeGesture | null>(null);
  const [workspaceSize, setWorkspaceSize] = useState({ width: 0, height: 0 });
  const [workspace, setWorkspace] = useState<AnalysisWorkspacePreferences>(() => {
    return hasStoredWorkspacePreferences()
      ? loadWorkspacePreferences()
      : defaultWorkspacePreferences(window.innerWidth - 24, window.innerHeight - 100);
  });

  useEffect(() => saveWorkspacePreferences(workspace), [workspace]);

  useEffect(() => {
    const element = workspaceRef.current;
    if (!element) return;
    const update = () => {
      const rect = element.getBoundingClientRect();
      const next = { width: rect.width, height: rect.height };
      setWorkspaceSize((current) =>
        current.width === next.width && current.height === next.height ? current : next,
      );
      if (next.width > 0 && next.height > 0) {
        setWorkspace((current) =>
          clampWorkspacePreferences(current, next.width, next.height),
        );
      }
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [sessions]);

  const updateWorkspaceSize = useCallback(
    (updates: Partial<AnalysisWorkspacePreferences>) => {
      setWorkspace((current) =>
        clampWorkspacePreferences(
          { ...current, ...updates },
          workspaceSize.width || window.innerWidth,
          workspaceSize.height || window.innerHeight,
        ),
      );
    },
    [workspaceSize],
  );

  const resetWorkspace = useCallback(() => {
    setWorkspace(
      defaultWorkspacePreferences(
        workspaceSize.width || window.innerWidth,
        workspaceSize.height || window.innerHeight,
      ),
    );
  }, [workspaceSize]);

  const resetLayoutSizes = useCallback(() => {
    const defaults = defaultWorkspacePreferences(
      workspaceSize.width || window.innerWidth,
      workspaceSize.height || window.innerHeight,
    );
    updateWorkspaceSize({
      inspectorWidth: defaults.inspectorWidth,
      mapHeight: defaults.mapHeight,
    });
  }, [workspaceSize, updateWorkspaceSize]);

  const beginResize = useCallback(
    (kind: ResizeKind, event: ReactPointerEvent<HTMLElement>) => {
      if (workspaceSize.width <= 0 || workspaceSize.height <= 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      resizeGesture.current = {
        kind,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        inspectorWidth: workspace.inspectorWidth,
        mapHeight: workspace.mapHeight,
        workspaceWidth: workspaceSize.width,
        workspaceHeight: workspaceSize.height,
      };
    },
    [workspace, workspaceSize],
  );

  const continueResize = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const gesture = resizeGesture.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const horizontal = gesture.kind === "vertical" || gesture.kind === "diagonal";
    const vertical = gesture.kind === "horizontal" || gesture.kind === "diagonal";
    setWorkspace((current) =>
      clampWorkspacePreferences(
        {
          ...current,
          inspectorWidth: horizontal
            ? gesture.inspectorWidth - (event.clientX - gesture.startX)
            : current.inspectorWidth,
          mapHeight: vertical
            ? gesture.mapHeight + (event.clientY - gesture.startY)
            : current.mapHeight,
        },
        gesture.workspaceWidth,
        gesture.workspaceHeight,
      ),
    );
  }, []);

  const finishResize = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (resizeGesture.current?.pointerId !== event.pointerId) return;
    resizeGesture.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const resizeByKeyboard = useCallback(
    (kind: ResizeKind, event: ReactKeyboardEvent<HTMLElement>) => {
      const step = event.shiftKey ? 60 : 20;
      let inspectorWidth = workspace.inspectorWidth;
      let mapHeight = workspace.mapHeight;
      if (event.key === "Home") {
        if (kind !== "horizontal") inspectorWidth = MIN_INSPECTOR_WIDTH;
        if (kind !== "vertical") mapHeight = MIN_MAP_HEIGHT;
      } else if (event.key === "End") {
        if (kind !== "horizontal") inspectorWidth = Number.POSITIVE_INFINITY;
        if (kind !== "vertical") mapHeight = Number.POSITIVE_INFINITY;
      } else if (event.key === "ArrowLeft" && kind !== "horizontal") {
        inspectorWidth += step;
      } else if (event.key === "ArrowRight" && kind !== "horizontal") {
        inspectorWidth -= step;
      } else if (event.key === "ArrowUp" && kind !== "vertical") {
        mapHeight -= step;
      } else if (event.key === "ArrowDown" && kind !== "vertical") {
        mapHeight += step;
      } else {
        return;
      }
      event.preventDefault();
      updateWorkspaceSize({ inspectorWidth, mapHeight });
    },
    [workspace, updateWorkspaceSize],
  );

  // Reset zoom window when session or lap selection changes
  useEffect(() => {
    setZoomRange(null);
  }, [sessionId, selected, refLap]);

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
  const maximumInspectorWidth = Math.max(
    MIN_INSPECTOR_WIDTH,
    workspaceSize.width - MIN_CENTER_WIDTH - WORKSPACE_DIVIDER_SIZE,
  );
  const maximumMapHeight = Math.max(
    MIN_MAP_HEIGHT,
    workspaceSize.height - MIN_TIMELINE_HEIGHT - WORKSPACE_DIVIDER_SIZE,
  );
  const workspaceStyle = {
    "--analysis-inspector-width": `${workspace.inspectorWidth}px`,
    "--analysis-map-height": `${workspace.mapHeight}px`,
  } as CSSProperties;

  // One color assignment for everything that shows the compared laps together
  // (chips, chart series, map, corner detail): id-keyed, but two selected laps
  // never share a color (laps 6 apart otherwise would — latest vs best hits it).
  const lapColors = useMemo<Record<string, string>>(() => {
    const ids = new Set<number>(selected);
    if (refLap != null) ids.add(refLap);
    for (const id of Object.keys(compare?.laps ?? {})) ids.add(Number(id));
    return Object.fromEntries(
      [...lapColorMap(ids)].map(([id, color]) => [String(id), color]),
    );
  }, [selected, refLap, compare]);
  const colorOf = (id: string | number) =>
    lapColors[String(id)] ?? lapColor(Number(id));

  // Laps for the track map, colored exactly like the chart series.
  const mapLaps = useMemo<MapLap[]>(() => {
    if (!compare) return [];
    return Object.keys(compare.laps).map((id) => ({
      id,
      entry: compare.laps[id],
      color: lapColors[id] ?? lapColor(Number(id)),
      label: lapLabels[id] ?? `Lap ${id}`,
      isRef: id === String(refLap),
    }));
  }, [compare, lapLabels, refLap, lapColors]);

  // Same laps, shaped for the Corner Detail widget (cursor-synced with the
  // charts and the map dot).
  const cornerLaps = useMemo<CornerLap[]>(() => {
    if (!compare) return [];
    return Object.keys(compare.laps).map((id) => ({
      id,
      label: lapLabels[id] ?? `Lap ${id}`,
      color: lapColors[id] ?? lapColor(Number(id)),
      isRef: id === String(refLap),
      series: compare.laps[id].series,
    }));
  }, [compare, lapLabels, refLap, lapColors]);

  if (sessions == null) {
    // Failed fetch would otherwise leave the skeleton up forever.
    if (error) {
      return (
        <div className="flex h-64 flex-col items-center justify-center gap-1 text-ink-dim">
          <div className="text-lg text-brake">{error}</div>
          <div className="text-sm">Check that the server is running, then reload.</div>
        </div>
      );
    }
    return (
      <div className="grid grid-cols-1 gap-3 p-3 xl:grid-cols-[1fr_360px]">
        <div className="space-y-3">
          <div className="skeleton h-14" />
          <div className="skeleton h-96" />
        </div>
        <div className="hidden space-y-3 xl:block">
          <div className="skeleton h-64" />
          <div className="skeleton h-40" />
        </div>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-1 text-ink-dim">
        <div className="text-lg">No sessions yet</div>
        <div className="text-sm">Drive some laps first — they'll show up here for comparison.</div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col gap-3 p-3 xl:h-full xl:min-h-0 xl:overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-xl bg-panel p-3">
          <Select
            ariaLabel="Session"
            value={String(sessionId ?? "")}
            onValueChange={(v) => {
              manualSelection.current = false;
              setSessionId(Number(v));
            }}
            options={sessions.map((s) => ({
              value: String(s.id),
              label: `#${s.id} · ${s.car_name} · ${s.lap_count} laps`,
            }))}
            className="px-2 py-1.5 text-sm"
          />
          {/* Scrolls horizontally on narrow screens instead of overflowing */}
          <div className="flex min-w-0 max-w-full gap-1.5 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-x-visible sm:pb-0">
            {laps.map((lap) => {
              const active = selected.includes(lap.id);
              const isRef = lap.id === refLap;
              return (
                <Tip key={lap.id} content="Click to toggle, double-click to set as reference">
                  <button
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
                    className={`flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1 font-tabular text-xs transition-colors ${
                      isRef
                        ? "border-accent bg-accent/15 text-accent"
                        : active
                          ? "border-edge bg-panel-2 text-ink"
                          : "border-edge text-ink-dim hover:text-ink"
                    }`}
                  >
                    {active && (
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: colorOf(lap.id) }}
                      />
                    )}
                    L{lap.number} {formatLapTime(lap.time_ms)}
                  </button>
                </Tip>
              );
            })}
          </div>
          <ChannelPicker selected={channelKeys} onChange={setChannelKeys} />
          <button
            type="button"
            className="btn px-2 py-1 text-[11px]"
            onClick={resetWorkspace}
            title="Restore map size, inspector width, timeline density, and map camera defaults"
          >
            Reset workspace
          </button>
          {refLap != null && (
            <div className="ml-auto">
              <Select
                ariaLabel="Reference lap"
                value={String(refLap)}
                onValueChange={(v) => {
                  manualSelection.current = true;
                  setRefLap(Number(v));
                }}
                options={laps.map((lap) => ({
                  value: String(lap.id),
                  label: `ref: L${lap.number} ${formatLapTime(lap.time_ms)}`,
                }))}
                className="px-2 py-1.5 text-xs"
              />
            </div>
          )}
      </div>

      {error && <div className="shrink-0 rounded-md bg-brake/10 p-2 text-sm text-brake">{error}</div>}

      <div
        ref={workspaceRef}
        className="analysis-workspace min-h-0 flex-1"
        style={workspaceStyle}
      >
        <div className="analysis-center min-w-0">
          <section className="analysis-map-viewport flex min-h-0 flex-col overflow-hidden rounded-xl bg-panel">
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
              <span className="mr-auto text-[10px] font-semibold uppercase tracking-widest text-ink-dim">
                {mapLaps.length > 1 ? "Race lines — selected laps" : "Race line (reference lap)"}
              </span>
              <button
                type="button"
                aria-pressed={workspace.followCursor}
                onClick={() => updateWorkspaceSize({ followCursor: !workspace.followCursor })}
                className={`rounded border px-2 py-0.5 text-[11px] transition-colors ${
                  workspace.followCursor
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-edge text-ink-dim hover:border-edge-bright hover:text-ink"
                }`}
              >
                Follow cursor
              </button>
              <button
                type="button"
                aria-pressed={workspace.showTravelDirection}
                onClick={() =>
                  updateWorkspaceSize({ showTravelDirection: !workspace.showTravelDirection })
                }
                title="Show native world-velocity direction above 0.1 m/s"
                className={`rounded border px-2 py-0.5 text-[11px] transition-colors ${
                  workspace.showTravelDirection
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-edge text-ink-dim hover:border-edge-bright hover:text-ink"
                }`}
              >
                Travel direction
              </button>
              <button
                type="button"
                aria-pressed={workspace.keepLapMarkersVisible}
                onClick={() =>
                  updateWorkspaceSize({
                    keepLapMarkersVisible: !workspace.keepLapMarkersVisible,
                  })
                }
                title="Pan minimally and temporarily zoom out when needed to keep every lap marker visible"
                className={`rounded border px-2 py-0.5 text-[11px] transition-colors ${
                  workspace.keepLapMarkersVisible
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-edge text-ink-dim hover:border-edge-bright hover:text-ink"
                }`}
              >
                Keep laps in frame
              </button>
              <MapScaleControls
                value={workspace.mapMetersPerPixel}
                onChange={(mapMetersPerPixel) => updateWorkspaceSize({ mapMetersPerPixel })}
              />
            </div>
            <div className="min-h-0 flex-1">
              {refEntry && compare ? (
                <RaceLineMap
                  laps={mapLaps}
                  cursorDist={cursorDist}
                  zoomRange={zoomRange}
                  followCursor={workspace.followCursor}
                  mapMetersPerPixel={workspace.mapMetersPerPixel}
                  showTravelDirection={workspace.showTravelDirection}
                  keepLapMarkersVisible={workspace.keepLapMarkersVisible}
                />
              ) : loading ? (
                <div className="skeleton h-full min-h-72 w-full" />
              ) : (
                <div className="flex h-full min-h-72 items-center justify-center text-sm text-ink-dim">
                  Select a lap with position telemetry to display the track map.
                </div>
              )}
            </div>
          </section>

          <div
            role="separator"
            aria-label="Resize map and timeline"
            aria-orientation="horizontal"
            aria-valuemin={MIN_MAP_HEIGHT}
            aria-valuemax={maximumMapHeight}
            aria-valuenow={Math.round(workspace.mapHeight)}
            tabIndex={0}
            className="analysis-horizontal-resizer hidden touch-none cursor-row-resize items-center justify-center xl:flex"
            onPointerDown={(event) => beginResize("horizontal", event)}
            onPointerMove={continueResize}
            onPointerUp={finishResize}
            onPointerCancel={finishResize}
            onKeyDown={(event) => resizeByKeyboard("horizontal", event)}
            onDoubleClick={resetLayoutSizes}
          >
            <span className="h-px w-12 bg-edge-bright" />
          </div>

          <section className="analysis-timeline mt-3 min-w-0 rounded-xl bg-panel p-2 xl:mt-0">
            {loading && !compare && <div className="skeleton h-96" />}
            {compare && (
              <StackedCharts
                data={compare}
                lapLabels={lapLabels}
                lapColors={lapColors}
                units={units}
                channels={channelDefs}
                onCursorDist={onCursorDist}
                zoomRange={zoomRange}
                onZoomChange={setZoomRange}
                panelHeight={TIMELINE_PANEL_HEIGHTS[workspace.timelineDensity]}
                timelineDensity={workspace.timelineDensity}
                onTimelineDensityChange={(timelineDensity) =>
                  updateWorkspaceSize({ timelineDensity })
                }
              />
            )}
          </section>
        </div>

        <div
          role="separator"
          aria-label="Resize analysis and inspector"
          aria-orientation="vertical"
          aria-valuemin={MIN_INSPECTOR_WIDTH}
          aria-valuemax={maximumInspectorWidth}
          aria-valuenow={Math.round(workspace.inspectorWidth)}
          tabIndex={0}
          className="analysis-vertical-resizer hidden touch-none cursor-col-resize items-center justify-center xl:flex"
          onPointerDown={(event) => beginResize("vertical", event)}
          onPointerMove={continueResize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
          onKeyDown={(event) => resizeByKeyboard("vertical", event)}
          onDoubleClick={resetLayoutSizes}
        >
          <span className="h-12 w-px bg-edge-bright" />
        </div>

        <aside className="analysis-inspector mt-3 flex min-w-0 flex-col gap-3 xl:mt-0">
          {cornerLaps.length > 0 && (
            <SidePanel title="Corner detail — cursor synced">
              <CornerDetail
                laps={cornerLaps}
                cursorDist={cursorDist}
                step={compare!.step}
                trackCorners={refEntry?.corners}
              />
            </SidePanel>
          )}
          {refLap != null && (
            <SidePanel title="Gearing (reference lap)">
              <GearingPanel lapId={refLap} units={units} />
            </SidePanel>
          )}
          {deviation && deviation.dist.length > 0 && (
            <SidePanel title={`Consistency — best ${deviation.lap_ids.length} laps`}>
              <DeviationChart data={deviation} units={units} zoomRange={zoomRange} />
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
                {refSummary.tcs_active_pct != null && (
                  <Info k="TCS active" v={`${refSummary.tcs_active_pct.toFixed(1)}%`} />
                )}
                {refSummary.asm_active_pct != null && (
                  <Info k="ASM active" v={`${refSummary.asm_active_pct.toFixed(1)}%`} />
                )}
                {(refSummary.max_water_temp ?? 0) > 0 && (
                  <Info k="Max water" v={`${refSummary.max_water_temp!.toFixed(0)}°C`} />
                )}
                {(refSummary.max_oil_temp ?? 0) > 0 && (
                  <Info k="Max oil" v={`${refSummary.max_oil_temp!.toFixed(0)}°C`} />
                )}
                {(refSummary.min_oil_pressure ?? -1) >= 0 && (
                  <Info k="Min oil press." v={`${refSummary.min_oil_pressure!.toFixed(1)} bar`} />
                )}
                {refSummary.event_counts && Object.keys(refSummary.event_counts).length > 0 && (
                  <Info
                    k="Events"
                    v={Object.entries(refSummary.event_counts)
                      .map(([type, n]) => `${n} ${type}`)
                      .join(" · ")}
                  />
                )}
              </div>
            </SidePanel>
          )}
        </aside>

        <button
          type="button"
          aria-label="Resize map, timeline, and inspector"
          className="analysis-diagonal-resizer hidden touch-none cursor-nwse-resize rounded-sm border border-edge-bright bg-panel-2 shadow-md xl:block"
          onPointerDown={(event) => beginResize("diagonal", event)}
          onPointerMove={continueResize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
          onKeyDown={(event) => resizeByKeyboard("diagonal", event)}
          onDoubleClick={resetLayoutSizes}
          title="Drag diagonally to resize map and inspector; double-click to reset"
        >
          <span aria-hidden="true" className="block text-[11px] leading-none text-ink-dim">↘</span>
        </button>
      </div>
    </div>
  );
}

function formatMapScale(value: number): string {
  return String(Math.round(value * 1000) / 1000);
}

function MapScaleControls({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(() => formatMapScale(value));

  useEffect(() => setDraft(formatMapScale(value)), [value]);

  const commit = () => {
    const parsed = Number(draft);
    if (draft.trim() === "" || !Number.isFinite(parsed)) {
      setDraft(formatMapScale(value));
      return;
    }
    const normalized = normalizeMapMetersPerPixel(parsed);
    setDraft(formatMapScale(normalized));
    onChange(normalized);
  };

  return (
    <div
      className="flex items-center gap-1"
      title="World metres shown per CSS pixel; lower values zoom in"
    >
      <span className="text-[10px] uppercase tracking-wide text-ink-dim">Scale</span>
      {MAP_SCALE_PRESETS.map((scale) => (
        <button
          type="button"
          key={scale}
          onClick={() => onChange(scale)}
          aria-pressed={value === scale}
          className={`rounded border px-2 py-0.5 font-tabular text-[11px] transition-colors ${
            value === scale
              ? "border-accent bg-accent/15 text-accent"
              : "border-edge text-ink-dim hover:border-edge-bright hover:text-ink"
          }`}
        >
          {formatMapScale(scale)}
        </button>
      ))}
      <input
        type="number"
        aria-label="Map scale in metres per CSS pixel"
        min={MIN_MAP_METERS_PER_PIXEL}
        max={MAX_MAP_METERS_PER_PIXEL}
        step={MAP_SCALE_STEP}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            setDraft(formatMapScale(value));
            event.currentTarget.blur();
          }
        }}
        className="w-16 rounded border border-edge bg-panel-2 px-1.5 py-0.5 text-right font-tabular text-[11px] text-ink"
      />
      <span className="whitespace-nowrap text-[10px] text-ink-dim">m/CSS px</span>
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
