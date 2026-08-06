// Full-screen driver dashboard / race-engineer screen for a second display.
// Renders a built-in preset or a saved server layout on the shared grid.

import { useEffect, useState } from "react";
import { CalloutBanner } from "@/components/CalloutBanner";
import { GridRenderer } from "@/components/GridRenderer";
import { RaceEngineerPanel } from "@/components/RaceEngineerPanel";
import { api } from "@/lib/api";
import type { DashParams } from "@/lib/dash";
import { DASH_PRESETS, DEFAULT_DASH_PRESET } from "@/lib/dashPresets";
import { normalizeLayout, type LayoutConfig } from "@/lib/layout";
import { useLiveFrame } from "@/lib/useLiveFrame";
import { useVoiceClient } from "@/lib/useVoiceClient";
import { clientId, useEngineer } from "@/store/engineer";

export function DashView({ params }: { params: DashParams }) {
  const [serverLayout, setServerLayout] = useState<LayoutConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [engineerOpen, setEngineerOpen] = useState(false);
  // The dashboard is the primary driver-facing surface, so it is one of the
  // two pages allowed to speak (see lib/useVoiceClient).
  useVoiceClient("dash");
  const voiceEnabled = useEngineer((s) => s.enabled && s.audioReady);
  const isSpeaker = useEngineer((s) => s.activeClientId !== "" && s.activeClientId === clientId());

  useEffect(() => {
    document.body.classList.add("overlay-page");
    return () => document.body.classList.remove("overlay-page");
  }, []);

  useEffect(() => {
    setServerLayout(null);
    setError(null);
    if (!params.layout) return;
    let cancelled = false;
    api.layouts
      .get(params.layout)
      .then((l) => {
        if (!cancelled) setServerLayout(normalizeLayout(l.config));
      })
      .catch(() => {
        if (!cancelled) setError(`Layout "${params.layout}" not found`);
      });
    return () => {
      cancelled = true;
    };
  }, [params.layout]);

  const preset = DASH_PRESETS[params.preset ?? ""] ?? DASH_PRESETS[DEFAULT_DASH_PRESET];
  const layout = params.layout ? serverLayout : preset.layout;
  // Force the dashboard shape regardless of source: fill the screen, dark page.
  const resolved: LayoutConfig | null = layout
    ? { ...layout, size: null, page: "dark" }
    : null;

  const demo = params.demo || (resolved?.demo ?? false);
  const { frame, laps, placeholder } = useLiveFrame(demo);

  const status = placeholder ? "placeholder" : frame ? "live" : "waiting";

  return (
    <div className="relative h-full w-full font-tabular">
      {error ? (
        <div className="flex h-full items-center justify-center text-sm text-ink-dim">
          {error} — save it in the Admin builder first.
        </div>
      ) : !resolved ? null : !frame ? (
        <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-ink-dim">
          <div>Waiting for telemetry…</div>
          <div className="text-xs">
            add <code className="text-ink">?demo=1</code> to preview with placeholder data
          </div>
        </div>
      ) : (
        <GridRenderer layout={resolved} frame={frame} laps={laps} />
      )}

      <CalloutBanner />

      {engineerOpen && (
        <div className="absolute right-2 top-9 z-10 max-h-[80vh] w-80 overflow-y-auto rounded-xl border border-edge bg-panel/95 shadow-xl backdrop-blur">
          <div className="flex items-baseline justify-between border-b border-edge px-3 py-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-ink-dim">
              Race Engineer
            </span>
            <button
              className="text-xs text-ink-dim hover:text-ink"
              onClick={() => setEngineerOpen(false)}
            >
              close
            </button>
          </div>
          <RaceEngineerPanel compact />
        </div>
      )}

      {/* status dot + fullscreen, kept tiny so they don't distract mid-race */}
      <div className="absolute right-2 top-2 flex items-center gap-2">
        <button
          className={`rounded border border-white/10 bg-black/40 px-1.5 py-0.5 text-[10px] ${
            voiceEnabled && isSpeaker ? "text-throttle" : "text-ink-dim hover:text-ink"
          }`}
          title={
            voiceEnabled && isSpeaker
              ? "Race Engineer: speaking on this device"
              : "Race Engineer voice settings"
          }
          onClick={() => setEngineerOpen((open) => !open)}
        >
          {voiceEnabled && isSpeaker ? "🔊" : "🔈"}
        </button>
        <span
          title={status}
          className={`h-2 w-2 rounded-full ${
            status === "live"
              ? "bg-throttle"
              : status === "placeholder"
                ? "bg-warn"
                : "bg-brake"
          }`}
        />
        <button
          className="rounded border border-white/10 bg-black/40 px-1.5 py-0.5 text-[10px] text-ink-dim hover:text-ink"
          title="Toggle fullscreen"
          onClick={() => {
            if (document.fullscreenElement) void document.exitFullscreen();
            else void document.documentElement.requestFullscreen();
          }}
        >
          ⛶
        </button>
      </div>
    </div>
  );
}
