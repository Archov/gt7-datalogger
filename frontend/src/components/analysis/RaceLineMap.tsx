// Track map built from lap positions. The reference lap is colored by input
// zone (throttle green / brake red / coast blue) with speed peaks & valleys;
// every other selected lap is overlaid as a solid line in its chart color —
// like GT7's own Data Logger, with independently available chassis/travel
// direction markers showing each lap at the hovered distance.

import type * as echarts from "echarts";
import type { EChartsOption, SeriesOption } from "echarts";
import { useEffect, useMemo, useRef, useState } from "react";
import { CHART_COLORS, EChart } from "@/components/EChart";
import {
  cameraBounds,
  distanceAtReferenceTime,
  fixedScaleBounds,
  MAP_GRID_PADDING_PX,
  markerInclusiveFixedScaleBounds,
  positionAtDistance,
  zoomWindowIntervals,
} from "@/lib/raceLineCamera";
import { type CompareLapEntry, kerbWheelCount, looseWheelCount } from "@/lib/types";
import { vehicleMarkerHeadings } from "@/lib/vehicleOrientation";

const ZONE_COLORS = [CHART_COLORS.brake, CHART_COLORS.coast, CHART_COLORS.throttle];

// Surface-contact halos under the reference line (packet-C recordings):
// kerb strikes in yellow, wheels on grass/gravel/dirt in orange.
const KERB_COLOR = "#eab308";
const LOOSE_COLOR = "#f97316";
const CHEVRON_SYMBOL = "path://M-8,6 L0,-8 L8,6 L4,8 L0,1 L-4,8 Z";

// Numbered circles are readable up to about this many corners in view;
// beyond that (or fully zoomed out on a long track) they collapse to dots.
const MAX_NUMBERED_CORNERS = 30;

function zoneOf(throttle: number, brake: number): number {
  if (brake >= 1) return 0;
  if (throttle >= 1) return 2;
  return 1;
}

function positionAt(series: MapLap["entry"]["series"], index: number): [number, number] | null {
  const x = series.pos_x?.[index];
  const z = series.pos_z?.[index];
  return Number.isFinite(x) && Number.isFinite(z) ? [x, z] : null;
}

export interface MapLap {
  id: string;
  entry: CompareLapEntry;
  color: string; // chart series color for this lap
  label: string;
  isRef: boolean;
}

export function RaceLineMap({
  laps,
  cursorDist,
  zoomRange,
  followCursor = true,
  mapMetersPerPixel = 0.5,
  showTravelDirection = true,
  keepLapMarkersVisible = true,
}: {
  laps: MapLap[];
  cursorDist: number | null;
  zoomRange?: [number, number] | null;
  followCursor?: boolean;
  mapMetersPerPixel?: number;
  showTravelDirection?: boolean;
  keepLapMarkersVisible?: boolean;
}) {
  const chartRef = useRef<echarts.ECharts | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [heldCursorDist, setHeldCursorDist] = useState<number | null>(null);
  const ref = laps.find((lap) => lap.isRef);
  const lapSetKey = laps.map((lap) => lap.id).join("|");
  const zoomKey = zoomRange ? `${zoomRange[0]}:${zoomRange[1]}` : "full";
  const previousZoomKey = useRef(zoomKey);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const update = () => {
      const rect = element.getBoundingClientRect();
      setViewport((current) =>
        current.width === rect.width && current.height === rect.height
          ? current
          : { width: rect.width, height: rect.height },
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // The map keeps its last hovered camera after timeline pointer exit. A
  // selection/zoom/follow-mode change deliberately releases that hold.
  useEffect(() => {
    setHeldCursorDist(null);
  }, [ref?.id, lapSetKey]);

  useEffect(() => {
    if (!followCursor) setHeldCursorDist(null);
  }, [followCursor]);

  useEffect(() => {
    if (previousZoomKey.current !== zoomKey) {
      previousZoomKey.current = zoomKey;
      setHeldCursorDist(null);
    }
  }, [zoomKey]);

  useEffect(() => {
    if (followCursor && cursorDist != null) setHeldCursorDist(cursorDist);
  }, [followCursor, cursorDist, ref?.id, lapSetKey]);

  const markerDistance = cursorDist ?? (followCursor ? heldCursorDist : null);
  const markerStates = useMemo(
    () =>
      laps.map((lap) => {
        const series = lap.entry.series;
        const synchronizedDistance =
          markerDistance != null && ref
            ? distanceAtReferenceTime(ref.entry.series, series, markerDistance)
            : null;
        const lapMarkerDistance = synchronizedDistance ?? markerDistance;
        const position =
          lapMarkerDistance != null && series.dist.length > 0
            ? positionAtDistance(series, lapMarkerDistance)
            : null;
        const headings =
          lapMarkerDistance != null && series.dist.length > 0
            ? vehicleMarkerHeadings(series, lapMarkerDistance)
            : { chassisRotationDeg: null, travelRotationDeg: null };
        return { lap, position, ...headings };
      }),
    [laps, ref, markerDistance],
  );

  const bounds = useMemo(() => {
    if (!ref) return null;
    const series = ref.entry.series;
    const cameraDistance = followCursor ? (cursorDist ?? heldCursorDist) : null;
    const center = cameraDistance == null ? null : positionAtDistance(series, cameraDistance);
    const fixedBounds = center
      ? (keepLapMarkersVisible
          ? markerInclusiveFixedScaleBounds(
              center,
              markerStates.flatMap((state) => (state.position ? [state.position] : [])),
              viewport.width,
              viewport.height,
              mapMetersPerPixel,
              MAP_GRID_PADDING_PX,
            )
          : null) ??
        fixedScaleBounds(
          center,
          viewport.width,
          viewport.height,
          mapMetersPerPixel,
          MAP_GRID_PADDING_PX,
        )
      : null;
    return (
      fixedBounds ??
      cameraBounds(
        series,
        zoomWindowIntervals(series.dist, zoomRange),
        viewport.width,
        viewport.height,
      )
    );
  }, [
    ref,
    followCursor,
    cursorDist,
    heldCursorDist,
    mapMetersPerPixel,
    keepLapMarkersVisible,
    markerStates,
    zoomRange,
    viewport,
  ]);

  const option = useMemo<EChartsOption>(() => {
    const series: SeriesOption[] = [];

    // Comparison laps first (under the reference), as solid colored lines.
    // Per-point itemStyle only affects symbols, never the line stroke, so
    // zoom-dimming needs two series: a dim full-lap line plus a bright
    // overlay covering only the zoomed section.
    for (const lap of laps) {
      if (lap.isRef) continue;
      const s = lap.entry.series;
      series.push({
        id: `line-${lap.id}`,
        type: "line",
        data: s.dist.map((_, i) => positionAt(s, i) ?? [null, null]),
        showSymbol: false,
        lineStyle: { color: lap.color, width: 1.6, opacity: zoomRange ? 0.15 : 0.9 },
        silent: true,
        z: 2,
      });
      if (zoomRange) {
        const inZoom: [number, number][] = [];
        for (let i = 0; i < s.dist.length; i++) {
          if (s.dist[i] >= zoomRange[0] && s.dist[i] <= zoomRange[1]) {
            const position = positionAt(s, i);
            if (position) inZoom.push(position);
          }
        }
        series.push({
          id: `line-zoom-${lap.id}`,
          type: "line",
          data: inZoom,
          showSymbol: false,
          lineStyle: { color: lap.color, width: 2, opacity: 0.9 },
          silent: true,
          z: 2,
        });
      }
    }

    if (ref) {
      const s = ref.entry.series;
      const points = s.dist.flatMap((d, i) => {
        const position = positionAt(s, i);
        if (!position) return [];
        const inZoom = zoomRange ? d >= zoomRange[0] && d <= zoomRange[1] : true;
        return [{
          value: position,
          symbolSize: inZoom ? 4 : 2,
          itemStyle: {
            color: ZONE_COLORS[zoneOf(s.throttle[i], s.brake[i])],
            opacity: inZoom ? 1 : 0.15,
          },
        }];
      });
      // Surface halos, drawn beneath the input-zone dots. A kerb-only touch
      // is routine; any loose-surface wheel is the interesting one, so loose
      // wins when a sample has both (two wheels on the kerb, two on grass).
      const surface = s.surface;
      if (surface?.some((v) => v > 0)) {
        const kerbPts: Array<{ value: number[]; itemStyle: { opacity: number } }> = [];
        const loosePts: Array<{ value: number[]; itemStyle: { opacity: number } }> = [];
        for (let i = 0; i < s.dist.length; i++) {
          const v = surface[i] ?? 0;
          const bucket =
            looseWheelCount(v) > 0 ? loosePts : kerbWheelCount(v) > 0 ? kerbPts : null;
          if (!bucket) continue;
          const position = positionAt(s, i);
          if (!position) continue;
          const inZoom = zoomRange
            ? s.dist[i] >= zoomRange[0] && s.dist[i] <= zoomRange[1]
            : true;
          bucket.push({
            value: position,
            itemStyle: { opacity: inZoom ? 0.55 : 0.1 },
          });
        }
        series.push(
          {
            id: "surface-kerb",
            type: "scatter",
            data: kerbPts,
            symbolSize: 8,
            itemStyle: { color: KERB_COLOR },
            silent: true,
            z: 2.5,
          },
          {
            id: "surface-loose",
            type: "scatter",
            data: loosePts,
            symbolSize: 9,
            itemStyle: { color: LOOSE_COLOR },
            silent: true,
            z: 2.6,
          },
        );
      }

      const pv = ref.entry.peaks_valleys;
      const peaks = pv.peaks.filter(
        (p) => !zoomRange || (p.dist >= zoomRange[0] && p.dist <= zoomRange[1]),
      );
      const valleys = pv.valleys.filter(
        (p) => !zoomRange || (p.dist >= zoomRange[0] && p.dist <= zoomRange[1]),
      );

      series.push(
        { type: "scatter", data: points, symbolSize: 3.5, silent: true, z: 3 },
        {
          type: "scatter",
          data: peaks.map((p) => [p.x, p.z]),
          symbol: "triangle",
          symbolSize: 9,
          itemStyle: { color: "#facc15" },
          silent: true,
          z: 5,
        },
        {
          type: "scatter",
          data: valleys.map((p) => [p.x, p.z]),
          symbol: "triangle",
          symbolRotate: 180,
          symbolSize: 9,
          itemStyle: { color: "#c084fc" },
          silent: true,
          z: 5,
        },
      );

      // Auto-numbered corners (detected on the reference lap). Numbered
      // circles while the view shows a readable amount; plain dots otherwise.
      const corners = ref.entry.corners ?? [];
      const cornersInView = corners.filter(
        (c) => !zoomRange || (c.apex_dist >= zoomRange[0] && c.apex_dist <= zoomRange[1]),
      );
      const numbered =
        cornersInView.length > 0 && cornersInView.length <= MAX_NUMBERED_CORNERS;
      if (cornersInView.length > 0) {
        series.push({
          id: "corners",
          type: "scatter",
          data: cornersInView.map((c) => ({
            value: [c.apex_x, c.apex_z],
            name: String(c.n),
          })),
          symbolSize: numbered ? 15 : 5,
          itemStyle: numbered
            ? { color: "#14171c", borderColor: CHART_COLORS.label, borderWidth: 1 }
            : { color: CHART_COLORS.label, opacity: 0.85 },
          label: {
            show: numbered,
            position: "inside",
            formatter: "{b}",
            color: "#e5e7eb",
            fontSize: 9,
            fontWeight: "bold",
          },
          silent: true,
          z: 4, // above the race line dots, below peak/valley markers & cursors
        });
      }
    }

    // Fixed-size orientation markers. Dynamic updates below independently
    // choose chassis chevron, fallback dot, and travel chevron per lap.
    for (const lap of laps) {
      series.push(
        {
          id: `cursor-dot-${lap.id}`,
          type: "scatter",
          data: [] as number[][],
          symbolSize: lap.isRef ? 12 : 9,
          itemStyle: lap.isRef
            ? { color: "#fff", borderColor: CHART_COLORS.series[0], borderWidth: 3 }
            : { color: lap.color, borderColor: "#fff", borderWidth: 1.5 },
          z: 10,
          silent: true,
        },
        {
          id: `cursor-chassis-${lap.id}`,
          type: "scatter",
          data: [] as number[][],
          symbol: CHEVRON_SYMBOL,
          symbolSize: 18,
          itemStyle: { color: "#fff", borderColor: lap.color, borderWidth: 2 },
          z: 11,
          silent: true,
        },
        {
          id: `cursor-travel-${lap.id}`,
          type: "scatter",
          data: [] as number[][],
          symbol: CHEVRON_SYMBOL,
          symbolSize: 12,
          itemStyle: { color: lap.color, borderColor: "#fff", borderWidth: 1 },
          z: 12,
          silent: true,
        },
      );
    }

    return {
      animation: false,
      grid: {
        left: MAP_GRID_PADDING_PX,
        right: MAP_GRID_PADDING_PX,
        top: MAP_GRID_PADDING_PX,
        bottom: MAP_GRID_PADDING_PX,
      },
      xAxis: {
        type: "value",
        show: false,
        scale: true,
      },
      yAxis: {
        type: "value",
        show: false,
        scale: true,
        inverse: true,
      },
      tooltip: { show: false },
      series,
    };
    // Deliberately depends only on laps/zoomRange: cursor updates merge separately below.
  }, [laps, zoomRange]);

  // Cursor and camera updates merge by id/component only. Scrubbing never
  // reconstructs the full race-line, surface, corner, or marker series.
  const dynamicOption = useMemo<EChartsOption>(() => {
    const updates: SeriesOption[] = markerStates.flatMap((state) => {
      const { lap, position, chassisRotationDeg, travelRotationDeg } = state;
      return [
        {
          id: `cursor-dot-${lap.id}`,
          data: position && chassisRotationDeg == null ? [position] : [],
        } as SeriesOption,
        {
          id: `cursor-chassis-${lap.id}`,
          data: position && chassisRotationDeg != null ? [position] : [],
          symbolRotate: chassisRotationDeg ?? 0,
        } as SeriesOption,
        {
          id: `cursor-travel-${lap.id}`,
          data: position && showTravelDirection && travelRotationDeg != null ? [position] : [],
          symbolRotate: travelRotationDeg ?? 0,
        } as SeriesOption,
      ];
    });
    return {
      ...(bounds
        ? {
            xAxis: { min: bounds.xMin, max: bounds.xMax },
            yAxis: { min: bounds.zMin, max: bounds.zMax },
          }
        : {}),
      series: updates,
    };
  }, [markerStates, showTravelDirection, bounds]);

  useEffect(() => {
    chartRef.current?.setOption(dynamicOption, { notMerge: false, lazyUpdate: true });
  }, [dynamicOption]);

  const others = laps.filter((lap) => !lap.isRef);
  const hasSurface = !!ref?.entry.series.surface?.some((v) => v > 0);

  return (
    <div ref={containerRef} className="relative h-full min-h-0 w-full overflow-hidden">
      <EChart
        option={option}
        className="h-full w-full"
        onInit={(chart) => {
          chartRef.current = chart;
          chart.setOption(dynamicOption, { notMerge: false, lazyUpdate: true });
        }}
      />
      {others.length > 0 && (
        <div className="absolute right-2 top-2 space-y-0.5 text-[10px]">
          {others.map((lap) => (
            <div key={lap.id} className="flex items-center justify-end gap-1.5 text-ink-dim">
              {lap.label}
              <i className="inline-block h-0.5 w-4" style={{ backgroundColor: lap.color }} />
            </div>
          ))}
        </div>
      )}
      <div className="absolute bottom-2 left-2 flex gap-3 text-[10px] text-ink-dim">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-throttle" />throttle</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-brake" />brake</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-coast" />coast</span>
        <span className="text-warn">▲ peak</span>
        <span className="text-[#c084fc]">▼ valley</span>
        {hasSurface && (
          <>
            <span>
              <i
                className="mr-1 inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: KERB_COLOR }}
              />
              kerb
            </span>
            <span>
              <i
                className="mr-1 inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: LOOSE_COLOR }}
              />
              off-track
            </span>
          </>
        )}
        {(ref?.entry.corners?.length ?? 0) > 0 && (
          <span>
            <i className="mr-1 inline-block h-2.5 w-2.5 rounded-full border border-ink-dim text-center align-middle text-[7px] leading-[9px]">
              1
            </i>
            corner
          </span>
        )}
      </div>
    </div>
  );
}
