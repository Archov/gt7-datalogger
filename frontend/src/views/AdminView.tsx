// Admin view: connection settings (PS IP, source), diagnostics, live log
// viewer, and data management.

import { useCallback, useEffect, useRef, useState } from "react";
import { OverlayBuilder } from "@/components/OverlayBuilder";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import type { AdminSettings, AdminStats, LogRecord } from "@/lib/types";
import { useTelemetry } from "@/store/telemetry";

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "text-ink-dim",
  INFO: "text-ink",
  WARNING: "text-warn",
  ERROR: "text-brake",
  CRITICAL: "text-brake",
};

export function AdminView() {
  const setStatus = useTelemetry((s) => s.setStatus);
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const flash = useCallback((text: string, error = false) => {
    setMessage({ text, error });
    window.setTimeout(() => setMessage(null), 4000);
  }, []);

  const refreshStats = useCallback(() => {
    api.admin.stats().then((s) => {
      setStats(s);
      setStatus(s.source);
    }).catch(() => {});
  }, [setStatus]);

  useEffect(() => {
    api.admin.settings().then(setSettings).catch(() => flash("Could not load settings", true));
    refreshStats();
    const t = window.setInterval(refreshStats, 5000);
    return () => window.clearInterval(t);
  }, [refreshStats, flash]);

  async function apply(patch: Parameters<typeof api.admin.updateSettings>[0], label: string) {
    setBusy(label);
    try {
      setSettings(await api.admin.updateSettings(patch));
      flash(`${label} applied`);
      refreshStats();
    } catch (e) {
      flash(e instanceof Error ? e.message : `${label} failed`, true);
    } finally {
      setBusy(null);
    }
  }

  async function run(label: string, fn: () => Promise<unknown>, done?: (r: unknown) => string) {
    setBusy(label);
    try {
      const r = await fn();
      flash(done ? done(r) : `${label} done`);
      refreshStats();
    } catch (e) {
      flash(e instanceof Error ? e.message : `${label} failed`, true);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-3 p-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">Admin</h2>
        {message && (
          <span className={`text-sm ${message.error ? "text-brake" : "text-accent"}`}>
            {message.text}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Connection settings */}
        <Panel title="Connection">
          {settings ? (
            <ConnectionForm settings={settings} busy={busy} onApply={apply} />
          ) : (
            <div className="p-4 text-sm text-ink-dim">Loading…</div>
          )}
        </Panel>

        {/* Diagnostics */}
        <Panel title="Diagnostics">
          {stats ? (
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 p-4 font-tabular text-sm">
              <Stat k="Telemetry" v={stats.source.connected ? "connected" : "no data"}
                cls={stats.source.connected ? "text-throttle" : "text-brake"} />
              <Stat k="Console" v={stats.source.console_ip || "auto-discover"} />
              <Stat k="Packets received" v={stats.source.packets_received.toLocaleString()} />
              <Stat k="Decode errors" v={String(stats.source.decode_errors)}
                cls={stats.source.decode_errors > 0 ? "text-warn" : undefined} />
              <Stat k="Server uptime" v={formatDuration(stats.uptime_s * 1000)} />
              <Stat k="Live clients" v={String(stats.clients)} />
              <Stat k="Sessions / laps" v={`${stats.db.sessions} / ${stats.db.laps}`} />
              <Stat k="Database size" v={`${(stats.db.size_bytes / 1048576).toFixed(1)} MB`} />
              <Stat k="Car names loaded" v={String(stats.cars_loaded)} />
              <Stat k="Recording" v={stats.source.recording ? "on" : "off"} />
            </div>
          ) : (
            <div className="p-4 text-sm text-ink-dim">Loading…</div>
          )}
          <div className="flex gap-2 border-t border-edge p-3">
            <button
              className="btn"
              disabled={busy !== null}
              onClick={() => run("Restart source", api.admin.restartSource)}
            >
              Restart telemetry source
            </button>
            <button
              className="btn"
              disabled={busy !== null}
              onClick={() =>
                run("Car DB update", api.admin.updateCars, (r) =>
                  `Car database updated: ${(r as { cars: number }).cars} cars`)
              }
            >
              Update car database
            </button>
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {/* Webhook notifications */}
        <Panel title="Notifications">
          {settings ? (
            <WebhookForm settings={settings} busy={busy} onApply={apply} flash={flash} setBusy={setBusy} />
          ) : (
            <div className="p-4 text-sm text-ink-dim">Loading…</div>
          )}
        </Panel>

      </div>

      {/* Overlay builder */}
      <Panel title="Overlay & dashboard builder">
        <OverlayBuilder flash={flash} />
      </Panel>

      {/* Logs */}
      <Panel title="Logs">
        <LogViewer />
      </Panel>

      {/* Data management */}
      <Panel title="Data management">
        <div className="flex flex-wrap items-center gap-2 p-3">
          <button
            className="btn"
            disabled={busy !== null}
            onClick={() => run("Vacuum", api.admin.vacuum, () => "Database compacted")}
          >
            Compact database
          </button>
          <button
            className="btn-danger"
            disabled={busy !== null}
            onClick={() => {
              if (!confirm("Delete ALL recorded sessions and laps? This cannot be undone.")) return;
              run("Clear data", api.admin.clearData, () => "All sessions and laps deleted");
            }}
          >
            Delete all recorded data
          </button>
          <span className="text-xs text-ink-dim">
            Settings are kept. Export laps you want to keep first (Sessions view).
          </span>
        </div>
      </Panel>
    </div>
  );
}

function ConnectionForm({
  settings,
  busy,
  onApply,
}: {
  settings: AdminSettings;
  busy: string | null;
  onApply: (patch: Parameters<typeof api.admin.updateSettings>[0], label: string) => void;
}) {
  const [ip, setIp] = useState(settings.ps_ip);
  useEffect(() => setIp(settings.ps_ip), [settings.ps_ip]);

  return (
    <div className="space-y-4 p-4">
      <div>
        <label className="mb-1 block text-xs text-ink-dim" htmlFor="ps-ip">
          PlayStation IP address
        </label>
        <div className="flex gap-2">
          <input
            id="ps-ip"
            value={ip}
            onChange={(e) => setIp(e.target.value)}
            placeholder="e.g. 192.168.1.30 — empty = auto-discover"
            className="w-full rounded-md border border-edge bg-panel-2 px-3 py-1.5 font-tabular text-sm placeholder:text-ink-dim/60 focus:border-accent focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && ip !== settings.ps_ip) onApply({ ps_ip: ip }, "Console IP");
            }}
          />
          <button
            className="btn shrink-0"
            disabled={busy !== null || ip === settings.ps_ip}
            onClick={() => onApply({ ps_ip: ip }, "Console IP")}
          >
            Apply
          </button>
        </div>
        <p className="mt-1 text-[11px] text-ink-dim">
          Applied immediately — no restart needed. Heartbeat goes to port {settings.heartbeat_port},
          telemetry arrives on {settings.telemetry_port}/udp.
        </p>
      </div>

      <div className="flex items-center gap-6">
        <div>
          <span className="mb-1 block text-xs text-ink-dim">Telemetry source</span>
          <div className="flex overflow-hidden rounded-md border border-edge">
            {(["udp", "sim"] as const).map((s) => (
              <button
                key={s}
                disabled={busy !== null}
                onClick={() => s !== settings.source && onApply({ source: s }, "Source")}
                className={`px-3 py-1.5 text-xs ${
                  settings.source === s ? "bg-accent/15 text-accent" : "text-ink-dim hover:text-ink"
                }`}
              >
                {s === "udp" ? "PlayStation" : "Simulated"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <span className="mb-1 block text-xs text-ink-dim">Log level</span>
          <select
            value={settings.log_level}
            disabled={busy !== null}
            onChange={(e) =>
              onApply({ log_level: e.target.value as AdminSettings["log_level"] }, "Log level")
            }
            className="rounded-md border border-edge bg-panel-2 px-2 py-1.5 text-xs"
          >
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}

function WebhookForm({
  settings,
  busy,
  onApply,
  flash,
  setBusy,
}: {
  settings: AdminSettings;
  busy: string | null;
  onApply: (patch: Parameters<typeof api.admin.updateSettings>[0], label: string) => void;
  flash: (text: string, error?: boolean) => void;
  setBusy: (b: string | null) => void;
}) {
  const [url, setUrl] = useState(settings.webhook_url);
  useEffect(() => setUrl(settings.webhook_url), [settings.webhook_url]);

  return (
    <div className="space-y-2 p-4">
      <label className="block text-xs text-ink-dim" htmlFor="webhook-url">
        Webhook URL — notified on new personal bests and session summaries
      </label>
      <div className="flex gap-2">
        <input
          id="webhook-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://discord.com/api/webhooks/… (or any HTTP endpoint)"
          className="w-full rounded-md border border-edge bg-panel-2 px-3 py-1.5 font-tabular text-sm placeholder:text-ink-dim/60 focus:border-accent focus:outline-none"
        />
        <button
          className="btn shrink-0"
          disabled={busy !== null || url === settings.webhook_url}
          onClick={() => onApply({ webhook_url: url }, "Webhook")}
        >
          Apply
        </button>
        <button
          className="btn shrink-0"
          disabled={busy !== null || !settings.webhook_url}
          onClick={async () => {
            setBusy("test-webhook");
            try {
              await api.admin.testWebhook();
              flash("Test notification sent");
            } catch (e) {
              flash(e instanceof Error ? e.message : "Webhook test failed", true);
            } finally {
              setBusy(null);
            }
          }}
        >
          Test
        </button>
      </div>
      <p className="text-[11px] text-ink-dim">
        Discord webhook URLs get a rich embed; any other URL receives plain JSON. Leave empty
        to disable.
      </p>
    </div>
  );
}

function LogViewer() {
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [level, setLevel] = useState<string>("");
  const [paused, setPaused] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      if (paused) return;
      api.admin.logs(300, level || undefined).then((ls) => {
        if (cancelled) return;
        setLogs(ls);
        const el = scroller.current;
        if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 60) {
          requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight }));
        }
      }).catch(() => {});
    };
    load();
    const t = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [level, paused]);

  return (
    <div>
      <div className="flex items-center gap-2 border-b border-edge px-3 py-2">
        <select
          value={level}
          onChange={(e) => setLevel(e.target.value)}
          className="rounded-md border border-edge bg-panel-2 px-2 py-1 text-xs"
        >
          <option value="">All levels</option>
          {LOG_LEVELS.map((l) => (
            <option key={l} value={l}>{l}+</option>
          ))}
        </select>
        <button className="btn" onClick={() => setPaused((p) => !p)}>
          {paused ? "Resume" : "Pause"}
        </button>
        <button
          className="btn"
          onClick={() => api.admin.clearLogs().then(() => setLogs([]))}
        >
          Clear
        </button>
        <span className="ml-auto text-[11px] text-ink-dim">
          {logs.length} entries · refreshes every 2 s
        </span>
      </div>
      <div ref={scroller} className="h-72 overflow-y-auto p-2 font-mono text-[11px] leading-5">
        {logs.length === 0 && <div className="p-2 text-ink-dim">No log entries.</div>}
        {logs.map((r, i) => (
          <div key={`${r.ts}-${i}`} className="flex gap-2 whitespace-pre-wrap break-all px-1 hover:bg-panel-2/60">
            <span className="shrink-0 text-ink-dim">{r.ts.slice(11, 19)}</span>
            <span className={`w-16 shrink-0 ${LEVEL_COLORS[r.level] ?? "text-ink"}`}>{r.level}</span>
            <span className="shrink-0 text-ink-dim">{r.logger}</span>
            <span>{r.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-panel">
      <div className="border-b border-edge px-3 py-2 text-[10px] font-semibold uppercase tracking-widest text-ink-dim">
        {title}
      </div>
      {children}
    </div>
  );
}

function Stat({ k, v, cls }: { k: string; v: string; cls?: string }) {
  return (
    <>
      <span className="text-ink-dim">{k}</span>
      <span className={`text-right ${cls ?? ""}`}>{v}</span>
    </>
  );
}
