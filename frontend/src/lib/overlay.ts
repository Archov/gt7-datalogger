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
// Page behind the widgets: transparent (OBS browser sources), green for
// chroma keying (webviews without alpha support), or solid dark (phones).
export type OverlayPage = "transparent" | "green" | "dark";

export interface OverlayConfig {
  widgets: WidgetId[];
  layout: OverlayLayout;
  scale: number; // 0.5 .. 2
  bg: number; // 0 .. 100, card background opacity
  align: OverlayAlign;
  demo: boolean; // animated placeholder data while no telemetry is flowing
  page: OverlayPage;
}

export const DEFAULT_CONFIG: OverlayConfig = {
  widgets: ["gear", "speed", "rpm", "inputs", "times", "tires", "fuel"],
  layout: "strip",
  scale: 1,
  bg: 70,
  align: "bottom",
  demo: false,
  page: "transparent",
};

export const PHONE_PRESET: OverlayConfig = {
  widgets: ["speed", "gear", "times", "delta", "position", "tires", "fuel", "strategy", "clock"],
  layout: "grid",
  scale: 1,
  bg: 100,
  align: "top",
  demo: false,
  page: "dark",
};

// Preferred URL form is the plain path /overlay?w=… — hash-fragment URLs
// (/#overlay?…) still work but are rejected by some apps' URL validators
// (e.g. TikTok LIVE Studio web sources).
export function isOverlayLocation(loc: {
  pathname: string;
  hash: string;
}): boolean {
  return (
    loc.pathname === "/overlay" ||
    loc.hash === "#overlay" ||
    loc.hash.startsWith("#overlay?")
  );
}

export function parseOverlayLocation(loc: { search: string; hash: string }): OverlayConfig {
  const query = loc.hash.includes("?")
    ? loc.hash.slice(loc.hash.indexOf("?") + 1)
    : loc.search.replace(/^\?/, "");
  const params = new URLSearchParams(query);
  const ids = (params.get("w") ?? "")
    .split(",")
    .filter((w): w is WidgetId => (WIDGET_IDS as readonly string[]).includes(w));
  const layout = params.get("layout");
  const align = params.get("align");
  const scale = Number(params.get("scale"));
  const bg = Number(params.get("bg"));
  const demo = params.get("demo");
  const page = params.get("page");
  const resolvedLayout = layout === "stack" || layout === "grid" ? layout : "strip";
  return {
    widgets: ids.length > 0 ? ids : DEFAULT_CONFIG.widgets,
    layout: resolvedLayout,
    scale: isFinite(scale) && scale >= 0.5 && scale <= 2 ? scale : 1,
    bg: isFinite(bg) && bg >= 0 && bg <= 100 && params.has("bg") ? bg : DEFAULT_CONFIG.bg,
    align: align === "center" || align === "top" ? align : "bottom",
    demo: demo === "1" || demo === "true",
    page:
      page === "green" || page === "dark" || page === "transparent"
        ? page
        : resolvedLayout === "grid"
          ? "dark"
          : "transparent",
  };
}

export function buildOverlayUrl(
  config: OverlayConfig,
  origin: string = window.location.origin,
): string {
  const params = new URLSearchParams();
  params.set("w", config.widgets.join(","));
  params.set("layout", config.layout);
  if (config.scale !== 1) params.set("scale", String(config.scale));
  params.set("bg", String(config.bg));
  if (config.align !== "bottom") params.set("align", config.align);
  if (config.demo) params.set("demo", "1");
  const defaultPage = config.layout === "grid" ? "dark" : "transparent";
  if (config.page !== defaultPage) params.set("page", config.page);
  return `${origin}/overlay?${params.toString()}`;
}
