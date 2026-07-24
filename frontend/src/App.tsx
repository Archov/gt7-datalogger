import { useEffect, useState } from "react";
import { StatusBar } from "@/components/StatusBar";
import { AnalysisView } from "@/views/AnalysisView";
import { LiveView } from "@/views/LiveView";
import { SessionsView } from "@/views/SessionsView";
import { useTelemetry } from "@/store/telemetry";

export type View = "live" | "analysis" | "sessions";

export default function App() {
  const [view, setView] = useState<View>("live");
  const connect = useTelemetry((s) => s.connect);

  useEffect(() => connect(), [connect]);

  return (
    <div className="flex h-full flex-col">
      <StatusBar view={view} onViewChange={setView} />
      <main className="min-h-0 flex-1 overflow-y-auto">
        {view === "live" && <LiveView />}
        {view === "analysis" && <AnalysisView />}
        {view === "sessions" && <SessionsView />}
      </main>
    </div>
  );
}
