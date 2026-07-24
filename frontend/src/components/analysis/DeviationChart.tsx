// Speed consistency across the session's best laps: median speed line with a
// deviation band; high deviation = inconsistent corner.

import type { EChartsOption } from "echarts";
import { useMemo } from "react";
import { CHART_COLORS, EChart } from "@/components/EChart";
import { speedValue, type Units } from "@/lib/format";
import type { DeviationResult } from "@/lib/types";

export function DeviationChart({ data, units }: { data: DeviationResult; units: Units }) {
  const option = useMemo<EChartsOption>(() => {
    const median = data.median.map((v) => speedValue(v, units));
    const dev = data.deviation.map((v) => speedValue(v, units));
    return {
      animation: false,
      grid: { left: 48, right: 12, top: 24, bottom: 22 },
      xAxis: {
        type: "value",
        min: 0,
        max: "dataMax",
        axisLabel: { color: CHART_COLORS.label, fontSize: 10, formatter: (v: number) => `${v} m` },
        axisLine: { lineStyle: { color: CHART_COLORS.axis } },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: "value",
          scale: true,
          axisLabel: { color: CHART_COLORS.label, fontSize: 9 },
          splitLine: { lineStyle: { color: CHART_COLORS.split } },
        },
        {
          type: "value",
          axisLabel: { color: CHART_COLORS.label, fontSize: 9 },
          splitLine: { show: false },
        },
      ],
      tooltip: {
        trigger: "axis",
        backgroundColor: "#1b1f26",
        borderColor: "#262b33",
        textStyle: { color: "#e6e9ee", fontSize: 11 },
      },
      legend: {
        top: 0,
        right: 8,
        textStyle: { color: CHART_COLORS.label, fontSize: 10 },
      },
      series: [
        {
          name: "Median speed",
          type: "line",
          data: data.dist.map((d, i) => [d, median[i]]),
          showSymbol: false,
          lineStyle: { width: 1.4 },
          color: CHART_COLORS.series[0],
        },
        {
          name: "Deviation",
          type: "line",
          yAxisIndex: 1,
          data: data.dist.map((d, i) => [d, dev[i]]),
          showSymbol: false,
          lineStyle: { width: 1 },
          areaStyle: { opacity: 0.25 },
          color: CHART_COLORS.series[3],
        },
      ],
    };
  }, [data, units]);

  return <EChart option={option} className="h-44 w-full" />;
}
