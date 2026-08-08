// Standalone Race Engineer page (/engineer): voice output without the
// dashboard. Deliberately plain — it is often opened on a phone or in an OBS
// browser source, where the useful information is "is it going to speak?".

import { useEffect } from "react";
import { RaceEngineerPanel } from "@/components/RaceEngineerPanel";
import { useVoiceClient } from "@/lib/useVoiceClient";
import { clientId, useEngineer } from "@/store/engineer";
import { useTelemetry } from "@/store/telemetry";

export function EngineerView() {
  useVoiceClient("engineer");
  const s = useEngineer();
  const wsConnected = useTelemetry((st) => st.wsConnected);
  const isSpeaker = s.activeClientId !== "" && s.activeClientId === clientId();

  useEffect(() => {
    document.body.classList.add("overlay-page");
    return () => document.body.classList.remove("overlay-page");
  }, []);

  return (
    <div className="mx-auto max-w-xl space-y-3 p-3">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold">Race Engineer</h1>
        <span className="flex items-center gap-3 text-[11px] text-ink-dim">
          <span className="flex items-center gap-1.5">
            <span
              className={`h-2 w-2 rounded-full ${
                !wsConnected ? "bg-brake" : isSpeaker ? "bg-throttle" : "bg-warn"
              }`}
            />
            {!wsConnected ? "offline" : isSpeaker ? "speaking here" : "connected"}
          </span>
          {/* /#/live: this page has no other way back (no header, no nav). */}
          <a href="/#/live" className="hover:text-ink" title="Back to the main app">
            ⌂ home
          </a>
        </span>
      </div>

      <div className="rounded-xl bg-panel">
        <div className="border-b border-edge px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-ink-dim">
          Voice output
        </div>
        <RaceEngineerPanel />
      </div>

      <div className="rounded-xl bg-panel">
        <div className="border-b border-edge px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-ink-dim">
          Recent callouts
        </div>
        {s.history.length === 0 ? (
          <p className="p-3 text-xs text-ink-dim">
            Nothing yet. Callouts appear here as they arrive, whether or not
            this device is the one speaking.
          </p>
        ) : (
          <ul className="divide-y divide-edge">
            {s.history.map((callout) => (
              <li key={callout.id} className="flex items-baseline gap-2 px-3 py-1.5 text-xs">
                <span className="w-16 shrink-0 text-[10px] uppercase tracking-widest text-ink-dim">
                  {callout.category}
                </span>
                <span className="flex-1">{callout.text}</span>
                <span className="font-tabular text-[10px] text-ink-dim">
                  {callout.priority}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
