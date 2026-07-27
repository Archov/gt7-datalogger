// Thin ECharts wrapper: theme defaults, resize handling, optional group connect.

import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { SERIES_COLORS } from "@/lib/colors";

export const CHART_COLORS = {
  axis: "#3a414c",
  label: "#8b93a1",
  split: "#1e232b",
  series: [...SERIES_COLORS] as string[],
  throttle: "#22c55e",
  brake: "#ef4444",
  coast: "#3b82f6",
};

export function baseGrid(): echarts.GridComponentOption {
  return { left: 52, right: 16, top: 28, bottom: 24, containLabel: false };
}

export function baseAxis(name?: string): echarts.XAXisComponentOption {
  return {
    type: "value",
    name,
    axisLine: { lineStyle: { color: CHART_COLORS.axis } },
    axisLabel: { color: CHART_COLORS.label, fontSize: 10 },
    splitLine: { lineStyle: { color: CHART_COLORS.split } },
  };
}

interface Props {
  option: echarts.EChartsOption;
  group?: string;
  className?: string;
  onInit?: (chart: echarts.ECharts) => void;
  notMerge?: boolean;
}

export function EChart({ option, group, className, onInit, notMerge }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    if (group) {
      chart.group = group;
      echarts.connect(group);
    }
    onInit?.(chart);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(el.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group]);

  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: notMerge ?? true, lazyUpdate: true });
  }, [option, notMerge]);

  return <div ref={el} className={className ?? "h-48 w-full"} />;
}
