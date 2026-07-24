// Visual builder for the overlay: pick widgets (with order), layout, and
// appearance; the result is encoded into a URL for OBS or a phone browser.

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import {
  buildOverlayUrl,
  DEFAULT_CONFIG,
  PHONE_PRESET,
  WIDGET_IDS,
  WIDGET_LABELS,
  type OverlayConfig,
  type WidgetId,
} from "@/lib/overlay";

const STORAGE_KEY = "gt7-overlay-builder";

function loadSaved(): OverlayConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULT_CONFIG, ...(JSON.parse(raw) as OverlayConfig) };
  } catch {
    // fall through to default
  }
  return DEFAULT_CONFIG;
}

export function OverlayBuilder({ flash }: { flash: (text: string) => void }) {
  const [config, setConfig] = useState<OverlayConfig>(loadSaved);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  }, [config]);

  const url = useMemo(() => buildOverlayUrl(config), [config]);

  // LAN URL for other devices (OBS on another PC, TikTok LIVE Studio, phone).
  const [lan, setLan] = useState<{ ip: string; port: number } | null>(null);
  useEffect(() => {
    api.admin
      .stats()
      .then((s) => s.lan_ip && setLan({ ip: s.lan_ip, port: s.http_port }))
      .catch(() => {});
  }, []);
  const lanUrl = useMemo(() => {
    if (!lan) return null;
    const origin = `http://${lan.ip}:${lan.port}`;
    return origin === window.location.origin ? null : buildOverlayUrl(config, origin);
  }, [lan, config]);

  function toggleWidget(id: WidgetId) {
    setConfig((c) => ({
      ...c,
      widgets: c.widgets.includes(id)
        ? c.widgets.filter((w) => w !== id)
        : [...c.widgets, id],
    }));
  }

  function moveWidget(id: WidgetId, dir: -1 | 1) {
    setConfig((c) => {
      const i = c.widgets.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= c.widgets.length) return c;
      const widgets = [...c.widgets];
      [widgets[i], widgets[j]] = [widgets[j], widgets[i]];
      return { ...c, widgets };
    });
  }

  return (
    <div className="space-y-3 p-4">
      {/* Presets */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-dim">Presets:</span>
        <button className="btn" onClick={() => setConfig(DEFAULT_CONFIG)}>
          OBS strip
        </button>
        <button className="btn" onClick={() => setConfig(PHONE_PRESET)}>
          Phone dashboard
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Options */}
        <div className="space-y-3">
          <div>
            <span className="mb-1 block text-xs text-ink-dim">Layout</span>
            <div className="flex overflow-hidden rounded-md border border-edge">
              {(
                [
                  ["strip", "Strip (OBS)"],
                  ["stack", "Stack (side)"],
                  ["grid", "Grid (phone)"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setConfig((c) => ({ ...c, layout: value }))}
                  className={`px-3 py-1.5 text-xs ${
                    config.layout === value
                      ? "bg-accent/15 text-accent"
                      : "text-ink-dim hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {config.layout !== "grid" && (
            <div>
              <span className="mb-1 block text-xs text-ink-dim">Vertical alignment</span>
              <div className="flex overflow-hidden rounded-md border border-edge">
                {(["top", "center", "bottom"] as const).map((a) => (
                  <button
                    key={a}
                    onClick={() => setConfig((c) => ({ ...c, align: a }))}
                    className={`px-3 py-1.5 text-xs capitalize ${
                      config.align === a ? "bg-accent/15 text-accent" : "text-ink-dim hover:text-ink"
                    }`}
                  >
                    {a}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-4">
            <label className="text-xs text-ink-dim">
              Scale
              <select
                value={config.scale}
                onChange={(e) => setConfig((c) => ({ ...c, scale: Number(e.target.value) }))}
                className="ml-2 rounded-md border border-edge bg-panel-2 px-2 py-1 text-xs text-ink"
              >
                {[0.75, 1, 1.25, 1.5, 2].map((s) => (
                  <option key={s} value={s}>
                    {s * 100}%
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-1 items-center gap-2 text-xs text-ink-dim">
              Background {config.bg}%
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={config.bg}
                onChange={(e) => setConfig((c) => ({ ...c, bg: Number(e.target.value) }))}
                className="flex-1 accent-[#38bdf8]"
              />
            </label>
          </div>

          {/* Widget picker */}
          <div>
            <span className="mb-1 block text-xs text-ink-dim">
              Widgets ({config.widgets.length} shown, in order)
            </span>
            <div className="space-y-0.5">
              {[...config.widgets, ...WIDGET_IDS.filter((w) => !config.widgets.includes(w))].map(
                (id) => {
                  const active = config.widgets.includes(id);
                  return (
                    <div
                      key={id}
                      className={`flex items-center gap-2 rounded-md px-2 py-1 text-xs ${
                        active ? "bg-panel-2" : "opacity-60"
                      }`}
                    >
                      <input
                        id={`w-${id}`}
                        type="checkbox"
                        checked={active}
                        onChange={() => toggleWidget(id)}
                        className="accent-[#38bdf8]"
                      />
                      <label htmlFor={`w-${id}`} className="flex-1 cursor-pointer">
                        {WIDGET_LABELS[id]}
                      </label>
                      {active && (
                        <>
                          <button
                            className="px-1 text-ink-dim hover:text-ink"
                            onClick={() => moveWidget(id, -1)}
                            title="Move up"
                          >
                            ↑
                          </button>
                          <button
                            className="px-1 text-ink-dim hover:text-ink"
                            onClick={() => moveWidget(id, 1)}
                            title="Move down"
                          >
                            ↓
                          </button>
                        </>
                      )}
                    </div>
                  );
                },
              )}
            </div>
          </div>
        </div>

        {/* Live preview */}
        <div className="flex flex-col gap-2">
          <span className="text-xs text-ink-dim">Live preview</span>
          <iframe
            title="Overlay preview"
            src={url}
            className="h-72 w-full rounded-lg border border-edge"
            style={{
              background:
                config.layout === "grid"
                  ? undefined
                  : "repeating-conic-gradient(#1b1f26 0% 25%, #14171c 0% 50%) 0 0 / 24px 24px",
            }}
          />
          <p className="text-[11px] text-ink-dim">
            {config.layout === "grid"
              ? "Open this URL in a phone or tablet browser for a pit-wall dashboard."
              : "Add as an OBS Browser source (transparent). Suggested size 1920×260 for the strip."}
          </p>
        </div>
      </div>

      {/* URLs */}
      <UrlRow label="This device" url={url} flash={flash} />
      {lanUrl && (
        <UrlRow
          label="Other devices (OBS PC, TikTok LIVE Studio, phone)"
          url={lanUrl}
          flash={flash}
        />
      )}
    </div>
  );
}

function UrlRow({
  label,
  url,
  flash,
}: {
  label: string;
  url: string;
  flash: (text: string) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-dim">{label}</div>
      <div className="flex gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md border border-edge bg-panel-2 px-3 py-1.5 font-tabular text-xs leading-6">
          {url}
        </code>
        <button
          className="btn shrink-0"
          onClick={() =>
            navigator.clipboard
              .writeText(url)
              .then(() => flash("Overlay URL copied"))
              .catch(() => flash("Copy failed — select the URL manually"))
          }
        >
          Copy
        </button>
        <a className="btn shrink-0" href={url} target="_blank" rel="noreferrer">
          Open
        </a>
      </div>
    </div>
  );
}
