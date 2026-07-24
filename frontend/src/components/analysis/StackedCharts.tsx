// All comparison series in ONE ECharts instance with stacked grids and a
// linked axis pointer: hovering any panel shows the cursor at the same
// distance in every panel. Far cheaper than N connected chart instances.

import type { EChartsOption, SeriesOption } from "echarts";
import { useMemo } from "react";
import { CHART_COLORS, EChart } from "@/components/EChart";
import { speedValue, type Units } from "@/lib/format";
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
}: {
  data: CompareResult;
  lapLabels: Record<string, string>;
  units: Units;
  onCursorDist?: (dist: number | null) => void;
}) {
  const option = useMemo<EChartsOption>(() => {
    const lapIds = Object.keys(data.laps);
    const heights = PANELS.map((p) => p.height);
    const totalWeight = heights.reduce((a, b) => a + b, 0);
    const usable = 100 - 6; // percent, minus bottom margin

    const grids: NonNullable<EChartsOption["grid"]> = [];
    const xAxes: object[] = [];
    const yAxes: object[] = [];
    const series: SeriesOption[] = [];
    const titles: object[] = [];

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

      lapIds.forEach((lapId, li) => {
        const entry = data.laps[lapId];
        const isDelta = panel.key === "delta";
        if (isDelta && !entry.delta) return; // reference lap has no delta
        const dist = isDelta ? entry.delta!.dist : entry.series.dist;
        const raw = isDelta
          ? entry.delta!.delta_ms.map((v) => v / 1000)
          : entry.series[panel.key] ?? [];
        const values = panel.transform ? raw.map((v) => panel.transform!(v, units)) : raw;
        series.push({
          type: "line",
          name: lapLabels[lapId] ?? `Lap ${lapId}`,
          xAxisIndex: gi,
          yAxisIndex: gi,
          data: dist.map((d, i) => [d, values[i]]),
          showSymbol: false,
          step: panel.step ? "end" : undefined,
          lineStyle: { width: 1.4 },
          color: CHART_COLORS.series[li % CHART_COLORS.series.length],
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

    return {
      animation: false,
      backgroundColor: "transparent",
      title: titles,
      grid: grids,
      xAxis: xAxes as EChartsOption["xAxis"],
      yAxis: yAxes as EChartsOption["yAxis"],
      series,
      legend: {
        top: 0,
        right: 8,
        textStyle: { color: CHART_COLORS.label, fontSize: 11 },
        icon: "roundRect",
        itemWidth: 12,
        itemHeight: 3,
      },
      axisPointer: {
        link: [{ xAxisIndex: "all" }],
        lineStyle: { color: CHART_COLORS.label },
        label: { backgroundColor: "#2a3140", fontSize: 10 },
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1b1f26",
        borderColor: "#262b33",
        textStyle: { color: "#e6e9ee", fontSize: 11 },
        valueFormatter: (v) => (typeof v === "number" ? v.toFixed(2) : `${v}`),
      },
    };
  }, [data, lapLabels, units]);

  // Height: enough vertical room for all panels
  return (
    <EChart
      option={option}
      className="w-full"
      onInit={(chart) => {
        chart.getDom().style.height = `${PANELS.length * 110 + TOP_PAD + PANEL_GAP}px`;
        chart.resize();
        chart.on("updateAxisPointer", (e) => {
          const info = (e as { axesInfo?: { axisDim: string; value: number }[] }).axesInfo;
          const x = info?.find((a) => a.axisDim === "x");
          onCursorDist?.(x ? x.value : null);
        });
        chart.getZr().on("globalout", () => onCursorDist?.(null));
      }}
    />
  );
}
