// Track map built from lap positions, colored by input zone
// (throttle green / brake red / coast blue), with speed peaks & valleys and
// a cursor dot synced to the distance charts.

import type * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useRef } from "react";
import { CHART_COLORS, EChart } from "@/components/EChart";
import type { CompareLapEntry } from "@/lib/types";

const ZONE_COLORS = [CHART_COLORS.brake, CHART_COLORS.coast, CHART_COLORS.throttle];

function zoneOf(throttle: number, brake: number): number {
  if (brake >= 1) return 0;
  if (throttle >= 1) return 2;
  return 1;
}

export function RaceLineMap({
  lap,
  cursorDist,
  step,
}: {
  lap: CompareLapEntry;
  cursorDist: number | null;
  step: number;
}) {
  const chartRef = useRef<echarts.ECharts | null>(null);

  const option = useMemo<EChartsOption>(() => {
    const s = lap.series;
    const points = s.dist.map((_, i) => ({
      value: [s.pos_x[i], s.pos_z[i]],
      itemStyle: { color: ZONE_COLORS[zoneOf(s.throttle[i], s.brake[i])] },
    }));
    const pv = lap.peaks_valleys;
    return {
      animation: false,
      grid: { left: 8, right: 8, top: 8, bottom: 8 },
      xAxis: { type: "value", show: false, scale: true },
      yAxis: { type: "value", show: false, scale: true, inverse: true },
      tooltip: { show: false },
      series: [
        { type: "scatter", data: points, symbolSize: 3.5, silent: true },
        {
          type: "scatter",
          data: pv.peaks.map((p) => [p.x, p.z]),
          symbol: "triangle",
          symbolSize: 9,
          itemStyle: { color: "#facc15" },
          silent: true,
          z: 5,
        },
        {
          type: "scatter",
          data: pv.valleys.map((p) => [p.x, p.z]),
          symbol: "triangle",
          symbolRotate: 180,
          symbolSize: 9,
          itemStyle: { color: "#c084fc" },
          silent: true,
          z: 5,
        },
        {
          id: "cursor",
          type: "scatter",
          data: [] as number[][],
          symbolSize: 12,
          itemStyle: { color: "#fff", borderColor: CHART_COLORS.series[0], borderWidth: 3 },
          z: 10,
          silent: true,
        },
      ],
    };
  }, [lap]);

  // Cursor updates merge into the existing chart by series id — no rebuild.
  useEffect(() => {
    const s = lap.series;
    let data: number[][] = [];
    if (cursorDist != null && s.dist.length > 0 && step > 0) {
      const i = Math.min(s.dist.length - 1, Math.max(0, Math.round(cursorDist / step)));
      if (Number.isFinite(i) && s.pos_x[i] != null && s.pos_z[i] != null) {
        data = [[s.pos_x[i], s.pos_z[i]]];
      }
    }
    chartRef.current?.setOption(
      { series: [{ id: "cursor", data }] },
      { notMerge: false, lazyUpdate: true },
    );
  }, [lap, cursorDist, step]);

  return (
    <div className="relative">
      <EChart
        option={option}
        className="aspect-square w-full"
        onInit={(chart) => {
          chartRef.current = chart;
        }}
      />
      <div className="absolute bottom-2 left-2 flex gap-3 text-[10px] text-ink-dim">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-throttle" />throttle</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-brake" />brake</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-coast" />coast</span>
        <span className="text-warn">▲ peak</span>
        <span className="text-[#c084fc]">▼ valley</span>
      </div>
    </div>
  );
}
