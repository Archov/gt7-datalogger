// Samples the 30 Hz telemetry ref on the browser's animation clock — shared
// by the overlay, the driver dashboard, and the builder canvas. Falls back to
// the synthetic demo lap when telemetry is stale and demo mode is on.

import { useEffect, useRef, useState } from "react";
import { DEMO_LAPS, demoFrame } from "./demoFrame";
import type { LapSummary, LiveFrame } from "./types";
import { liveFrameRef, useTelemetry } from "@/store/telemetry";

export const STALE_AFTER_MS = 3000;

export interface LiveSample {
  frame: LiveFrame | null;
  laps: LapSummary[];
  placeholder: boolean; // true while showing demo data
}

export function useLiveFrame(demo: boolean): LiveSample {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [placeholder, setPlaceholder] = useState(false);
  const recentLaps = useTelemetry((s) => s.recentLaps);
  const raf = useRef(0);

  useEffect(() => {
    const tick = () => {
      const now = performance.now();
      const live =
        liveFrameRef.current && now - liveFrameRef.at < STALE_AFTER_MS
          ? liveFrameRef.current
          : null;
      if (live) {
        setFrame(live);
        setPlaceholder(false);
      } else if (demo) {
        setFrame(demoFrame(now));
        setPlaceholder(true);
      } else {
        setFrame(liveFrameRef.current);
        setPlaceholder(false);
      }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [demo]);

  return { frame, laps: placeholder ? DEMO_LAPS : recentLaps, placeholder };
}
