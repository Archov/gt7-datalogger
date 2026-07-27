// All comparison series in ONE ECharts instance with stacked grids and a
// linked axis pointer: hovering any panel shows the cursor at the same
// distance in every panel. Far cheaper than N connected chart instances.

import type * as echarts from "echarts";
import type { EChartsOption, SeriesOption } from "echarts";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { CHART_COLORS, EChart } from "@/components/EChart";
import { lapColor } from "@/lib/colors";
import { speedUnit, speedValue, type Units } from "@/lib/format";
import type { CompareResult } from "@/lib/types";

interface PanelDef {
  key: string;
  title: string;
  height: number; // relative weight
  transform?: (v: number, units: Units) => number;
  step?: boolean;
}

const PANELS: PanelDef[] = [
  { key: "delta", title: "Time diff (s)", height: 1.2 },
  { key: "speed", title: "Speed", height: 1.6, transform: speedValue },
  { key: "throttle", title: "Throttle %", height: 0.8 },
  { key: "brake", title: "Brake %", height: 0.8 },
  { key: "coast", title: "Coasting", height: 0.5, step: true },
  { key: "gear", title: "Gear", height: 0.7, step: true },
  { key: "rpm", title: "RPM", height: 1 },
  { key: "boost", title: "Boost (bar)", height: 0.7 },
  { key: "tire_slip", title: "Tire spd / car spd", height: 0.8 },
  { key: "yaw_rate", title: "Yaw rate (rad/s)", height: 0.8 },
];

const TOP_PAD = 20;
const PANEL_GAP = 26;

export function StackedCharts({
  data,
  lapLabels,
  units,
  onCursorDist,
  zoomRange,
  onZoomChange,
}: {
  data: CompareResult;
  lapLabels: Record<string, string>;
  units: Units;
  onCursorDist?: (dist: number | null) => void;
  zoomRange?: [number, number] | null;
  onZoomChange?: (range: [number, number] | null) => void;
}) {
  const chartRef = useRef<echarts.ECharts | null>(null);
  // True while WE dispatch a zoom action, so the resulting dataZoom event
  // isn't echoed back through onZoomChange (which would loop).
  const applyingZoom = useRef(false);

  const maxDist = useMemo(() => {
    let m = 0;
    for (const lap of Object.values(data.laps)) {
      const dists = lap.series.dist;
      if (dists && dists.length > 0) {
        m = Math.max(m, dists[dists.length - 1]);
      }
    }
    return m;
  }, [data]);
  // The chart's event handlers are bound once (onInit) — read maxDist through
  // a ref so they never see a stale value after the lap selection changes.
  const maxDistRef = useRef(maxDist);
  maxDistRef.current = maxDist;

  // Drag-select zoom uses ECharts' native toolbox mechanism ("dataZoomSelect")
  // instead of hand-rolled pixel math: activating the global cursor makes a
  // plain left-drag draw the selection box and emit a dataZoom event.
  const activateDragZoom = useCallback(() => {
    chartRef.current?.dispatchAction({
      type: "takeGlobalCursor",
      key: "dataZoomSelect",
      dataZoomSelectActive: true,
    });
  }, []);

  // Apply zoomRange (from drag, sector buttons, or reset) to all axes.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    applyingZoom.current = true;
    try {
      if (zoomRange) {
        chart.dispatchAction({
          type: "dataZoom",
          startValue: zoomRange[0],
          endValue: zoomRange[1],
        });
      } else {
        chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
      }
    } finally {
      applyingZoom.current = false;
    }
    activateDragZoom(); // option/action updates can drop the select cursor
  }, [zoomRange, activateDragZoom, data]);

  const option = useMemo<EChartsOption>(() => {
    const lapIds = Object.keys(data.laps);
    const heights = PANELS.map((p) => p.height);
    const totalWeight = heights.reduce((a, b) => a + b, 0);
    const usable = 100 - 8; // percent, minus bottom margin for slider

    const grids: NonNullable<EChartsOption["grid"]> = [];
    const xAxes: object[] = [];
    const yAxes: object[] = [];
    const series: SeriesOption[] = [];
    const titles: object[] = [];
    // Parallel to `series`: which panel each series belongs to, so the
    // tooltip can label values instead of dumping bare numbers.
    const seriesMeta: { panelKey: string; panelTitle: string }[] = [];

    const formatValue = (key: string, v: number): string => {
      switch (key) {
        case "delta":
          return `${v >= 0 ? "+" : ""}${v.toFixed(3)} s`;
        case "speed":
          return `${Math.round(v)} ${speedUnit(units)}`;
        case "throttle":
        case "brake":
          return `${Math.round(v)}%`;
        case "coast":
          return v >= 0.5 ? "coasting" : "—";
        case "gear":
          return `${Math.round(v)}`;
        case "rpm":
          return `${Math.round(v).toLocaleString()} rpm`;
        case "boost":
          return `${v.toFixed(2)} bar`;
        case "tire_slip":
          return `${v.toFixed(2)}×`;
        case "yaw_rate":
          return `${v.toFixed(2)} rad/s`;
        default:
          return v.toFixed(2);
      }
    };

    let cursor = 2;
    PANELS.forEach((panel, gi) => {
      const h = (panel.height / totalWeight) * usable;
      grids.push({
        left: 56,
        right: 12,
        top: `${cursor + 2.2}%`,
        height: `${h - 3}%`,
      });
      titles.push({
        text: panel.title,
        left: 56,
        top: `${cursor - 0.4}%`,
        textStyle: { color: CHART_COLORS.label, fontSize: 11, fontWeight: 400 },
      });
      cursor += h;
      xAxes.push({
        type: "value",
        gridIndex: gi,
        min: 0,
        max: "dataMax",
        axisLabel:
          gi === PANELS.length - 1
            ? { color: CHART_COLORS.label, fontSize: 10, formatter: (v: number) => `${v} m` }
            : { show: false },
        axisLine: { lineStyle: { color: CHART_COLORS.axis } },
        splitLine: { show: false },
        axisTick: { show: gi === PANELS.length - 1 },
      });
      yAxes.push({
        type: "value",
        gridIndex: gi,
        scale: panel.key !== "throttle" && panel.key !== "brake",
        axisLabel: { color: CHART_COLORS.label, fontSize: 9 },
        splitLine: { lineStyle: { color: CHART_COLORS.split } },
        splitNumber: 3,
      });

      lapIds.forEach((lapId) => {
        const entry = data.laps[lapId];
        const isDelta = panel.key === "delta";
        if (isDelta && !entry.delta) return; // reference lap has no delta
        const dist = isDelta ? entry.delta!.dist : entry.series.dist;
        const raw = isDelta
          ? entry.delta!.delta_ms.map((v) => v / 1000)
          : entry.series[panel.key] ?? [];
        const values = panel.transform ? raw.map((v) => panel.transform!(v, units)) : raw;
        seriesMeta.push({ panelKey: panel.key, panelTitle: panel.title });
        series.push({
          type: "line",
          name: lapLabels[lapId] ?? `Lap ${lapId}`,
          xAxisIndex: gi,
          yAxisIndex: gi,
          data: dist.map((d, i) => [d, values[i]]),
          showSymbol: false,
          step: panel.step ? "end" : undefined,
          lineStyle: { width: 1.4 },
          color: lapColor(Number(lapId)),
          ...(isDelta
            ? {
                markLine: {
                  silent: true,
                  symbol: "none",
                  label: { show: false },
                  lineStyle: { color: CHART_COLORS.label, type: "dashed", width: 1 },
                  data: [{ yAxis: 0 }],
                },
              }
            : {}),
        });
      });
    });

    const allXAxisIndices = PANELS.map((_, i) => i);

    const dataZoom: EChartsOption["dataZoom"] = [
      {
        type: "inside",
        xAxisIndex: allXAxisIndices,
        filterMode: "none",
        zoomOnMouseWheel: false, // Disable scroll wheel zoom so web page scrolling is natural
        moveOnMouseMove: false,
        moveOnMouseWheel: false,
      },
      {
        type: "slider",
        xAxisIndex: allXAxisIndices,
        filterMode: "none",
        bottom: 2,
        height: 18,
        borderColor: CHART_COLORS.axis,
        backgroundColor: "#16191e",
        dataBackground: {
          lineStyle: { color: CHART_COLORS.axis },
          areaStyle: { color: CHART_COLORS.split },
        },
        selectedDataBackground: {
          lineStyle: { color: "#38bdf8" },
          areaStyle: { color: "#38bdf8", opacity: 0.2 },
        },
        fillerColor: "rgba(56, 189, 248, 0.15)",
        handleStyle: { color: "#38bdf8", borderColor: "#38bdf8" },
        moveHandleStyle: { color: "#38bdf8" },
        textStyle: { color: CHART_COLORS.label, fontSize: 10 },
        labelFormatter: (value: number) => `${Math.round(value)}m`,
        // Window state is applied via dispatchAction (single source of truth);
        // baking start/end into the option here fights the merge updates.
      },
    ];

    return {
      animation: false,
      backgroundColor: "transparent",
      title: titles,
      grid: grids,
      xAxis: xAxes as EChartsOption["xAxis"],
      yAxis: yAxes as EChartsOption["yAxis"],
      series,
      dataZoom,
      // Declares the native drag-select zoom feature; its cursor is activated
      // by dispatchAction(takeGlobalCursor) so no icon click is needed. The
      // toolbox itself is parked off-screen.
      toolbox: {
        top: -100,
        feature: {
          dataZoom: {
            xAxisIndex: allXAxisIndices,
            yAxisIndex: false,
            filterMode: "none",
            brushStyle: {
              color: "rgba(56, 189, 248, 0.15)",
              borderColor: "#38bdf8",
              borderWidth: 1,
            },
          },
        },
      },
      legend: {
        top: 0,
        right: 8,
        textStyle: { color: CHART_COLORS.label, fontSize: 11 },
        icon: "roundRect",
        itemWidth: 12,
        itemHeight: 3,
      },
      axisPointer: {
        type: "cross",
        link: [{ xAxisIndex: "all" }],
        lineStyle: { color: "#38bdf8", width: 1, type: "dashed" },
        crossStyle: { color: "#38bdf8", width: 1, type: "dashed" },
        label: { backgroundColor: "#1e232b", color: "#38bdf8", fontSize: 10, padding: [2, 5] },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1b1f26",
        borderColor: "#262b33",
        textStyle: { color: "#e6e9ee", fontSize: 11 },
        // One distance header, then one labeled row per metric — the default
        // repeats the distance for every panel and shows unlabeled numbers.
        formatter: (params: unknown) => {
          const list = (Array.isArray(params) ? params : [params]) as {
            seriesIndex: number;
            axisValue: number | string;
            value: [number, number] | number;
            marker: string;
          }[];
          if (list.length === 0) return "";
          const dist = Number(list[0].axisValue);
          const multiLap = lapIds.length > 1;

          // Group values by panel, preserving PANELS order.
          const byPanel = new Map<string, { title: string; cells: string[] }>();
          for (const p of list) {
            const meta = seriesMeta[p.seriesIndex];
            if (!meta) continue;
            const v = Array.isArray(p.value) ? p.value[1] : p.value;
            if (v == null || Number.isNaN(v)) continue;
            const cell = `${multiLap ? p.marker : ""}<span style="font-variant-numeric:tabular-nums">${formatValue(meta.panelKey, v)}</span>`;
            const group = byPanel.get(meta.panelKey) ?? { title: meta.panelTitle, cells: [] };
            group.cells.push(cell);
            byPanel.set(meta.panelKey, group);
          }

          const rows = PANELS.filter((p) => byPanel.has(p.key))
            .map((p) => {
              const g = byPanel.get(p.key)!;
              const label = g.title.replace(/ \(.*\)| %/, "");
              return `<div style="display:flex;justify-content:space-between;gap:16px;line-height:1.7">
                <span style="color:#8b93a1">${label}</span>
                <span style="display:flex;gap:10px">${g.cells.join("")}</span>
              </div>`;
            })
            .join("");
          return `<div style="min-width:150px">
            <div style="font-weight:600;margin-bottom:4px">${Math.round(dist).toLocaleString()} m</div>
            ${rows}
          </div>`;
        },
      },
    };
  }, [data, lapLabels, units]);

  return (
    <div className="flex flex-col">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-edge/60 pb-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-ink-dim">Zoom Level:</span>
          {zoomRange ? (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-accent/15 px-2 py-0.5 font-tabular text-accent">
              <span>
                🔍 {zoomRange[0].toFixed(0)}m – {zoomRange[1].toFixed(0)}m
              </span>
              <span className="text-[10px] opacity-75">
                ({(zoomRange[1] - zoomRange[0]).toFixed(0)}m section)
              </span>
            </span>
          ) : (
            <span className="text-ink-dim">Full lap (0m – {maxDist.toFixed(0)}m)</span>
          )}
          <span className="hidden text-[11px] text-ink-dim/70 sm:inline">
            • Drag across a chart to zoom · double-click to reset
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {zoomRange && (
            <button
              onClick={() => onZoomChange?.(null)}
              className="rounded border border-edge bg-panel-2 px-2 py-0.5 text-xs font-medium text-ink transition-colors hover:border-accent hover:text-accent"
              title="Reset zoom to full lap"
            >
              Reset Zoom
            </button>
          )}
          <button
            onClick={() => onZoomChange?.([0, maxDist * 0.33])}
            className="rounded border border-edge px-2 py-0.5 text-[11px] text-ink-dim transition-colors hover:border-edge-bright hover:text-ink"
          >
            S1 (0-33%)
          </button>
          <button
            onClick={() => onZoomChange?.([maxDist * 0.33, maxDist * 0.66])}
            className="rounded border border-edge px-2 py-0.5 text-[11px] text-ink-dim transition-colors hover:border-edge-bright hover:text-ink"
          >
            S2 (33-66%)
          </button>
          <button
            onClick={() => onZoomChange?.([maxDist * 0.66, maxDist])}
            className="rounded border border-edge px-2 py-0.5 text-[11px] text-ink-dim transition-colors hover:border-edge-bright hover:text-ink"
          >
            S3 (66-100%)
          </button>
        </div>
      </div>
      <div
        className="relative w-full select-none"
        onDoubleClick={() => onZoomChange?.(null)}
        title="Drag across a chart to zoom into that section; double-click to reset"
      >
        <EChart
          option={option}
          className="w-full"
          notMerge={false}
          onInit={(chart) => {
            chartRef.current = chart;
            chart.getDom().style.height = `${PANELS.length * 110 + TOP_PAD + PANEL_GAP}px`;
            chart.resize();
            chart.on("updateAxisPointer", (e) => {
              const info = (e as { axesInfo?: { axisDim: string; value: number }[] }).axesInfo;
              const x = info?.find((a) => a.axisDim === "x");
              onCursorDist?.(x ? x.value : null);
            });
            // Fired by the native drag-select box and by the bottom slider.
            chart.on("dataZoom", (e: any) => {
              if (applyingZoom.current) return; // our own dispatch echoing back
              let startVal: number | undefined;
              let endVal: number | undefined;

              if (e.batch && e.batch[0]) {
                startVal = e.batch[0].startValue;
                endVal = e.batch[0].endValue;
              } else if (e.startValue != null && e.endValue != null) {
                startVal = e.startValue;
                endVal = e.endValue;
              }

              if (startVal != null && endVal != null) {
                onZoomChange?.([startVal, endVal]);
              } else {
                const startPct = e.batch?.[0]?.start ?? e.start ?? 0;
                const endPct = e.batch?.[0]?.end ?? e.end ?? 100;
                if (startPct <= 1 && endPct >= 99) {
                  onZoomChange?.(null);
                } else {
                  const minD = (startPct / 100) * maxDistRef.current;
                  const maxD = (endPct / 100) * maxDistRef.current;
                  onZoomChange?.([minD, maxD]);
                }
              }
            });
            chart.getZr().on("globalout", () => onCursorDist?.(null));
            activateDragZoom();
          }}
        />
      </div>
    </div>
  );
}
