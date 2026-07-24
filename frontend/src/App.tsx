import { useEffect, useState } from "react";
import { StatusBar } from "@/components/StatusBar";
import { AdminView } from "@/views/AdminView";
import { AnalysisView } from "@/views/AnalysisView";
import { LiveView } from "@/views/LiveView";
import { OverlayView } from "@/views/OverlayView";
import { SessionsView } from "@/views/SessionsView";
import { useTelemetry } from "@/store/telemetry";

export type View = "live" | "analysis" | "sessions" | "admin";

export default function App() {
  const [view, setView] = useState<View>("live");
  const [overlay, setOverlay] = useState(() => window.location.hash === "#overlay");
  const connect = useTelemetry((s) => s.connect);

  useEffect(() => connect(), [connect]);
  useEffect(() => {
    const onHash = () => setOverlay(window.location.hash === "#overlay");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (overlay) return <OverlayView />;

  return (
    <div className="flex h-full flex-col">
      <StatusBar view={view} onViewChange={setView} />
      <main className="min-h-0 flex-1 overflow-y-auto">
        {view === "live" && <LiveView />}
        {view === "analysis" && <AnalysisView />}
        {view === "sessions" && <SessionsView />}
        {view === "admin" && <AdminView />}
      </main>
    </div>
  );
}
