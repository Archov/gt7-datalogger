// Live telemetry store: owns the WebSocket, latest frame, and lap feed.
// The 30 Hz frames update a plain ref consumers read on their own rAF loop;
// React state only changes on lap/status events to avoid 30 Hz re-renders.

import { create } from "zustand";
import { api } from "@/lib/api";
import type { ConnectionStatus, LapSummary, LiveFrame, WsMessage } from "@/lib/types";

interface TelemetryState {
  status: ConnectionStatus | null;
  wsConnected: boolean;
  recentLaps: LapSummary[];
  lapEpoch: number; // bump to signal views that lap data changed
  connect: () => void;
  setStatus: (s: ConnectionStatus) => void;
}

// Latest frame outside React state; LiveView polls it via requestAnimationFrame.
// `at` is performance.now() of the last frame, so consumers can detect a
// stalled stream (paused game / no console) rather than showing frozen data.
export const liveFrameRef: { current: LiveFrame | null; at: number } = {
  current: null,
  at: 0,
};

let socket: WebSocket | null = null;
let retryTimer: number | undefined;

export const useTelemetry = create<TelemetryState>((set) => {
  function open() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws/live`);
    socket.onopen = () => {
      set({ wsConnected: true });
      // Seed the lap feed with the current session's laps so widgets that
      // need lap history (fuel strategy) work right after a page load.
      void (async () => {
        try {
          const status = await api.status();
          if (status.session_id == null) return;
          const laps = await api.sessionLaps(status.session_id);
          set((st) =>
            st.recentLaps.length > 0 ? {} : { recentLaps: laps.slice(0, 50) },
          );
        } catch {
          // non-fatal: widgets fall back to waiting for the next lap event
        }
      })();
    };
    socket.onclose = () => {
      set({ wsConnected: false });
      retryTimer = window.setTimeout(open, 2000);
    };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as WsMessage;
      switch (msg.type) {
        case "telemetry":
          liveFrameRef.current = msg.data;
          liveFrameRef.at = performance.now();
          break;
        case "lap":
          set((st) => ({
            recentLaps: [msg.data, ...st.recentLaps].slice(0, 50),
            lapEpoch: st.lapEpoch + 1,
          }));
          break;
        case "status":
        case "session":
          // Laps deliberately survive session boundaries: a race restart
          // opens a new session, and losing the previous stint's laps would
          // blank the fuel projection exactly when it matters (aggressive
          // fuel-use races). projectStrategy filters by car instead.
          set({ status: msg.data });
          break;
      }
    };
  }

  return {
    status: null,
    wsConnected: false,
    recentLaps: [],
    lapEpoch: 0,
    connect: () => {
      if (socket || retryTimer) return;
      open();
    },
    setStatus: (status) => set({ status }),
  };
});
