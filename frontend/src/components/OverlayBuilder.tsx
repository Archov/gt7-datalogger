// Visual builder for the overlay: pick widgets (with order and per-widget
// size), canvas size, layout, and appearance; the result is encoded into a
// URL for OBS or a phone browser. Configurations can be saved as named
// presets and exported/imported as JSON files.

import { useEffect, useMemo, useRef, useState } from "react";
import { PromptDialog } from "@/components/ui/Dialog";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import {
  buildOverlayUrl,
  DEFAULT_CONFIG,
  DEFAULT_PAD,
  PHONE_PRESET,
  SIZE_PRESETS,
  WIDGET_IDS,
  WIDGET_LABELS,
  type OverlayConfig,
  type WidgetId,
} from "@/lib/overlay";
import { toast } from "@/store/toasts";

const STORAGE_KEY = "gt7-overlay-builder";
const PRESETS_KEY = "gt7-overlay-presets";

const WIDGET_SCALE_STEPS = [0.75, 1, 1.25, 1.5, 2];

function normalizeConfig(raw: unknown): OverlayConfig {
  return { ...DEFAULT_CONFIG, ...(raw as OverlayConfig) };
}

function loadSaved(): OverlayConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return normalizeConfig(JSON.parse(raw));
  } catch {
    // fall through to default
  }
  return DEFAULT_CONFIG;
}

function loadPresets(): Record<string, OverlayConfig> {
  try {
    const raw = localStorage.getItem(PRESETS_KEY);
    if (raw) return JSON.parse(raw) as Record<string, OverlayConfig>;
  } catch {
    // corrupt store — start fresh
  }
  return {};
}

export function OverlayBuilder({ flash }: { flash: (text: string) => void }) {
  const [config, setConfig] = useState<OverlayConfig>(loadSaved);
  const [presets, setPresets] = useState<Record<string, OverlayConfig>>(loadPresets);
  const [savingPreset, setSavingPreset] = useState(false);
  const [showGuides, setShowGuides] = useState(false);
  const presetFile = useRef<HTMLInputElement>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  }, [config]);
  useEffect(() => {
    localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
  }, [presets]);

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

  function setWidgetScale(id: WidgetId, scale: number) {
    setConfig((c) => {
      const widgetScales = { ...c.widgetScales };
      if (scale === 1) delete widgetScales[id];
      else widgetScales[id] = scale;
      return { ...c, widgetScales };
    });
  }

  function exportConfig() {
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "gt7-overlay.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function importConfig(file: File) {
    try {
      const parsed = normalizeConfig(JSON.parse(await file.text()));
      if (!Array.isArray(parsed.widgets)) throw new Error("bad file");
      setConfig(parsed);
      flash(`Imported overlay config from ${file.name}`);
    } catch {
      toast("Import failed — not a valid overlay config", "error");
    }
  }

  const activeSizeLabel = config.size
    ? SIZE_PRESETS.find(
        (p) => p.size.width === config.size!.width && p.size.height === config.size!.height,
      )?.label ?? "custom"
    : "fill";

  return (
    <div className="space-y-3 p-4">
      {/* Starting points + named presets */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-dim">Start from:</span>
        <button className="btn" onClick={() => setConfig(DEFAULT_CONFIG)}>
          OBS strip
        </button>
        <button className="btn" onClick={() => setConfig(PHONE_PRESET)}>
          Phone dashboard
        </button>
        <span className="mx-2 h-4 w-px bg-edge" />
        <span className="text-xs text-ink-dim">My presets:</span>
        {Object.keys(presets).length === 0 && (
          <span className="text-xs text-ink-dim/60">none saved yet</span>
        )}
        {Object.entries(presets).map(([name]) => (
          <span key={name} className="flex items-center overflow-hidden rounded-md border border-edge">
            <button
              className="px-2 py-1 text-xs text-ink hover:bg-panel-2"
              title={`Load preset "${name}"`}
              onClick={() => {
                setConfig(normalizeConfig(presets[name]));
                flash(`Preset "${name}" loaded`);
              }}
            >
              {name}
            </button>
            <button
              className="border-l border-edge px-1.5 py-1 text-xs text-ink-dim hover:text-brake"
              title={`Delete preset "${name}"`}
              onClick={() =>
                setPresets((cur) => {
                  const next = { ...cur };
                  delete next[name];
                  return next;
                })
              }
            >
              ×
            </button>
          </span>
        ))}
        <button className="btn" onClick={() => setSavingPreset(true)}>
          Save as…
        </button>
        <button className="btn" onClick={exportConfig} title="Download the current config as JSON">
          Export
        </button>
        <button
          className="btn"
          onClick={() => presetFile.current?.click()}
          title="Load a config JSON exported from another machine"
        >
          Import…
        </button>
        <input
          ref={presetFile}
          type="file"
          accept=".json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importConfig(f);
            e.target.value = "";
          }}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Options */}
        <div className="space-y-3">
          <div>
            <span className="mb-1 block text-xs text-ink-dim">Canvas size</span>
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setConfig((c) => ({ ...c, size: null }))}
                className={`rounded-md border px-2 py-1 text-xs ${
                  config.size == null
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-edge text-ink-dim hover:text-ink"
                }`}
                title="Fill whatever size the browser source / window has"
              >
                Fill source
              </button>
              {SIZE_PRESETS.map((p) => {
                const active =
                  config.size?.width === p.size.width && config.size?.height === p.size.height;
                return (
                  <button
                    key={p.label}
                    onClick={() => setConfig((c) => ({ ...c, size: { ...p.size } }))}
                    className={`rounded-md border px-2 py-1 font-tabular text-xs ${
                      active
                        ? "border-accent bg-accent/15 text-accent"
                        : "border-edge text-ink-dim hover:text-ink"
                    }`}
                  >
                    {p.size.width} × {p.size.height} ({p.label})
                  </button>
                );
              })}
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-xs text-ink-dim">
              Custom
              <input
                type="number"
                min={100}
                max={7680}
                value={config.size?.width ?? ""}
                placeholder="W"
                onChange={(e) => {
                  const width = Number(e.target.value);
                  if (!width) return;
                  setConfig((c) => ({
                    ...c,
                    size: { width, height: c.size?.height ?? 1080 },
                  }));
                }}
                className="w-20 rounded-md border border-edge bg-panel-2 px-2 py-1 font-tabular text-xs text-ink"
              />
              ×
              <input
                type="number"
                min={100}
                max={7680}
                value={config.size?.height ?? ""}
                placeholder="H"
                onChange={(e) => {
                  const height = Number(e.target.value);
                  if (!height) return;
                  setConfig((c) => ({
                    ...c,
                    size: { width: c.size?.width ?? 1920, height },
                  }));
                }}
                className="w-20 rounded-md border border-edge bg-panel-2 px-2 py-1 font-tabular text-xs text-ink"
              />
              px — set the OBS browser source to the same size
            </div>
          </div>

          <div>
            <span className="mb-1 block text-xs text-ink-dim">Layout</span>
            <SegmentedControl
              ariaLabel="Overlay layout"
              value={config.layout}
              onValueChange={(layout) => setConfig((c) => ({ ...c, layout }))}
              options={[
                { value: "strip", label: "Strip (OBS)" },
                { value: "stack", label: "Stack (side)" },
                { value: "grid", label: "Grid (phone)" },
              ]}
            />
          </div>

          {config.layout !== "grid" && (
            <div>
              <span className="mb-1 block text-xs text-ink-dim">Vertical alignment</span>
              <SegmentedControl
                ariaLabel="Vertical alignment"
                value={config.align}
                onValueChange={(align) => setConfig((c) => ({ ...c, align }))}
                options={[
                  { value: "top", label: "Top" },
                  { value: "center", label: "Center" },
                  { value: "bottom", label: "Bottom" },
                ]}
              />
            </div>
          )}

          <div className="flex items-center gap-4">
            <label className="flex items-center text-xs text-ink-dim">
              Scale
              <span className="ml-2">
                <Select
                  ariaLabel="Global scale"
                  value={String(config.scale)}
                  onValueChange={(v) => setConfig((c) => ({ ...c, scale: Number(v) }))}
                  options={[0.75, 1, 1.25, 1.5, 2].map((s) => ({
                    value: String(s),
                    label: `${s * 100}%`,
                  }))}
                  className="px-2 py-1 text-xs"
                />
              </span>
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

          <div className="flex items-center gap-2 text-xs text-ink-dim">
            Edge padding
            <input
              type="number"
              min={0}
              max={200}
              value={config.padX}
              onChange={(e) =>
                setConfig((c) => ({ ...c, padX: Math.max(0, Number(e.target.value) || 0) }))
              }
              className="w-16 rounded-md border border-edge bg-panel-2 px-2 py-1 font-tabular text-xs text-ink"
              title="Horizontal padding (px)"
            />
            ×
            <input
              type="number"
              min={0}
              max={200}
              value={config.padY}
              onChange={(e) =>
                setConfig((c) => ({ ...c, padY: Math.max(0, Number(e.target.value) || 0) }))
              }
              className="w-16 rounded-md border border-edge bg-panel-2 px-2 py-1 font-tabular text-xs text-ink"
              title="Vertical padding (px)"
            />
            px from the edges
            {(config.padX !== DEFAULT_PAD || config.padY !== DEFAULT_PAD) && (
              <button
                className="text-ink-dim underline hover:text-ink"
                onClick={() => setConfig((c) => ({ ...c, padX: DEFAULT_PAD, padY: DEFAULT_PAD }))}
              >
                reset
              </button>
            )}
          </div>

          <div>
            <span className="mb-1 block text-xs text-ink-dim">Page behind the widgets</span>
            <SegmentedControl
              ariaLabel="Page behind the widgets"
              value={config.page}
              onValueChange={(page) => setConfig((c) => ({ ...c, page }))}
              options={[
                { value: "transparent", label: "Transparent" },
                { value: "green", label: "Green screen" },
                { value: "dark", label: "Solid dark" },
              ]}
            />
            <p className="mt-1 text-[11px] text-ink-dim">
              Transparent needs an alpha-capable source (OBS “Browser”). If your app shows the
              page as black (e.g. TikTok LIVE Studio links), pick{" "}
              <span className="text-ink">Green screen</span> and add a chroma-key filter for
              #00FF00 in the app.
            </p>
          </div>

          <label className="flex items-center gap-2 text-xs text-ink-dim">
            <input
              type="checkbox"
              checked={config.demo}
              onChange={(e) => setConfig((c) => ({ ...c, demo: e.target.checked }))}
              className="accent-[#38bdf8]"
            />
            Placeholder data when no telemetry — animated fake lap for designing the
            layout; switches to real data automatically and shows a small
            “placeholder” tag while active
          </label>

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
                          <Select
                            ariaLabel={`Size of the ${WIDGET_LABELS[id]} widget`}
                            value={String(config.widgetScales[id] ?? 1)}
                            onValueChange={(v) => setWidgetScale(id, Number(v))}
                            options={WIDGET_SCALE_STEPS.map((s) => ({
                              value: String(s),
                              label: `${s * 100}%`,
                            }))}
                            className="px-1.5 py-0.5 text-[10px]"
                          />
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
          <div className="flex items-center gap-3">
            <span className="text-xs text-ink-dim">
              Live preview
              {config.size && (
                <span className="ml-2 font-tabular">
                  {config.size.width} × {config.size.height} ({activeSizeLabel})
                </span>
              )}
            </span>
            <label className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-dim">
              <input
                type="checkbox"
                checked={showGuides}
                onChange={(e) => setShowGuides(e.target.checked)}
                className="accent-[#38bdf8]"
              />
              Safe-area guides
            </label>
          </div>
          <OverlayPreview config={config} url={url} showGuides={showGuides} />
          <p className="text-[11px] text-ink-dim">
            {config.layout === "grid"
              ? "Open this URL in a phone or tablet browser for a pit-wall dashboard."
              : config.size
                ? `Add as an OBS Browser source sized ${config.size.width} × ${config.size.height} — the preview above is true to size.`
                : "Add as an OBS Browser source (transparent); the overlay fills whatever size the source has."}
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

      <PromptDialog
        open={savingPreset}
        title="Save overlay preset"
        label="Name this configuration so you can switch back to it later."
        placeholder="e.g. Race strip, Vertical stream"
        onSubmit={(name) => {
          setSavingPreset(false);
          setPresets((cur) => ({ ...cur, [name]: config }));
          flash(`Preset "${name}" saved`);
        }}
        onCancel={() => setSavingPreset(false)}
      />
    </div>
  );
}

// True-to-size preview: renders the overlay page at its real pixel dimensions
// in an iframe, scaled down to fit — so it matches what OBS will show, unlike
// a fixed-height box. Falls back to a fluid 16:9-ish box when no size is set.
function OverlayPreview({
  config,
  url,
  showGuides,
}: {
  config: OverlayConfig;
  url: string;
  showGuides: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setContainerWidth(el.clientWidth));
    observer.observe(el);
    setContainerWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const checker =
    config.page === "transparent"
      ? "repeating-conic-gradient(#1b1f26 0% 25%, #14171c 0% 50%) 0 0 / 24px 24px"
      : undefined;

  const guides = showGuides && (
    <>
      {/* Action safe (90%) and title safe (80%) areas */}
      <div className="pointer-events-none absolute inset-[5%] border border-warn/50" />
      <div className="pointer-events-none absolute inset-[10%] border border-brake/50" />
      <span className="pointer-events-none absolute left-[5%] top-[5%] bg-black/60 px-1 text-[9px] text-warn">
        action safe
      </span>
      <span className="pointer-events-none absolute left-[10%] top-[10%] bg-black/60 px-1 text-[9px] text-brake">
        title safe
      </span>
    </>
  );

  if (!config.size) {
    return (
      <div ref={container} className="relative w-full">
        <iframe
          title="Overlay preview"
          src={url}
          className="h-72 w-full rounded-lg border border-edge"
          style={{ background: checker }}
        />
        {guides}
      </div>
    );
  }

  const { width, height } = config.size;
  const MAX_PREVIEW_HEIGHT = 480;
  const scale =
    containerWidth > 0 ? Math.min(containerWidth / width, MAX_PREVIEW_HEIGHT / height, 1) : 0;

  return (
    <div ref={container} className="w-full">
      {scale > 0 && (
        <div
          className="relative overflow-hidden rounded-lg border border-edge"
          style={{ width: width * scale, height: height * scale, background: checker }}
        >
          <iframe
            title="Overlay preview"
            src={url}
            style={{
              width,
              height,
              border: 0,
              transform: `scale(${scale})`,
              transformOrigin: "0 0",
            }}
          />
          {guides}
        </div>
      )}
      <div className="mt-1 font-tabular text-[11px] text-ink-dim">
        shown at {(scale * 100).toFixed(0)}% of actual size
      </div>
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
