// Live telemetry store: owns the WebSocket, latest frame, and lap feed.
// The 30 Hz frames update a plain ref consumers read on their own rAF loop;
// React state only changes on lap/status events to avoid 30 Hz re-renders.

import { create } from "zustand";
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
export const liveFrameRef: { current: LiveFrame | null } = { current: null };

let socket: WebSocket | null = null;
let retryTimer: number | undefined;

export const useTelemetry = create<TelemetryState>((set) => {
  function open() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws/live`);
    socket.onopen = () => set({ wsConnected: true });
    socket.onclose = () => {
      set({ wsConnected: false });
      retryTimer = window.setTimeout(open, 2000);
    };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as WsMessage;
      switch (msg.type) {
        case "telemetry":
          liveFrameRef.current = msg.data;
          break;
        case "lap":
          set((st) => ({
            recentLaps: [msg.data, ...st.recentLaps].slice(0, 50),
            lapEpoch: st.lapEpoch + 1,
          }));
          break;
        case "status":
        case "session":
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
