// Overlay configuration: which widgets, which layout, and appearance —
// all encoded in the URL hash so OBS, a phone, and a second monitor can each
// load their own setup, e.g. /#overlay?w=gear,speed&layout=grid&scale=1.25

export const WIDGET_IDS = [
  "gear",
  "speed",
  "rpm",
  "inputs",
  "times",
  "delta",
  "position",
  "tires",
  "fuel",
  "strategy",
  "clock",
] as const;

export type WidgetId = (typeof WIDGET_IDS)[number];

export const WIDGET_LABELS: Record<WidgetId, string> = {
  gear: "Gear",
  speed: "Speed",
  rpm: "RPM bar",
  inputs: "Throttle / brake",
  times: "Lap times",
  delta: "Delta (big)",
  position: "Race position",
  tires: "Tire temps",
  fuel: "Fuel",
  strategy: "Fuel strategy",
  clock: "In-game clock",
};

export type OverlayLayout = "strip" | "stack" | "grid";
export type OverlayAlign = "bottom" | "center" | "top";

export interface OverlayConfig {
  widgets: WidgetId[];
  layout: OverlayLayout;
  scale: number; // 0.5 .. 2
  bg: number; // 0 .. 100, card background opacity
  align: OverlayAlign;
}

export const DEFAULT_CONFIG: OverlayConfig = {
  widgets: ["gear", "speed", "rpm", "inputs", "times", "tires", "fuel"],
  layout: "strip",
  scale: 1,
  bg: 70,
  align: "bottom",
};

export const PHONE_PRESET: OverlayConfig = {
  widgets: ["speed", "gear", "times", "delta", "position", "tires", "fuel", "strategy", "clock"],
  layout: "grid",
  scale: 1,
  bg: 100,
  align: "top",
};

export function isOverlayHash(hash: string): boolean {
  return hash === "#overlay" || hash.startsWith("#overlay?");
}

export function parseOverlayHash(hash: string): OverlayConfig {
  const query = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const ids = (params.get("w") ?? "")
    .split(",")
    .filter((w): w is WidgetId => (WIDGET_IDS as readonly string[]).includes(w));
  const layout = params.get("layout");
  const align = params.get("align");
  const scale = Number(params.get("scale"));
  const bg = Number(params.get("bg"));
  return {
    widgets: ids.length > 0 ? ids : DEFAULT_CONFIG.widgets,
    layout: layout === "stack" || layout === "grid" ? layout : "strip",
    scale: isFinite(scale) && scale >= 0.5 && scale <= 2 ? scale : 1,
    bg: isFinite(bg) && bg >= 0 && bg <= 100 && params.has("bg") ? bg : DEFAULT_CONFIG.bg,
    align: align === "center" || align === "top" ? align : "bottom",
  };
}

export function buildOverlayUrl(config: OverlayConfig, origin: string = window.location.origin): string {
  const params = new URLSearchParams();
  params.set("w", config.widgets.join(","));
  params.set("layout", config.layout);
  if (config.scale !== 1) params.set("scale", String(config.scale));
  params.set("bg", String(config.bg));
  if (config.align !== "bottom") params.set("align", config.align);
  return `${origin}/#overlay?${params.toString()}`;
}
