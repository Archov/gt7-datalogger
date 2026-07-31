// v2 layout model: widgets placed freely on a grid with per-cell variant and
// footprint. Stored server-side as named layouts (/overlay?layout=<name>) and
// rendered by GridRenderer. The v1 URL-param OverlayConfig in overlay.ts keeps
// working for existing OBS sources; migrateOverlayConfig converts it here.

import {
  DEFAULT_PAD,
  WIDGET_IDS,
  type OverlayConfig,
  type OverlayPage,
  type OverlaySize,
  type WidgetId,
} from "./overlay";
import { defaultSize, isAllowedSize, isValidVariant, WIDGET_META } from "./widgetMeta";

export interface LayoutCell {
  id: string; // instance id — the same widget can appear more than once
  widget: WidgetId;
  variant: string;
  x: number;
  y: number;
  w: number;
  h: number;
  options?: Record<string, unknown>; // per-widget knobs, e.g. { scale: 1.25 }
}

export interface LayoutGrid {
  cols: number;
  rows: number;
  gap: number; // px between cells
}

export interface LayoutConfig {
  version: 2;
  grid: LayoutGrid;
  cells: LayoutCell[];
  page: OverlayPage;
  bg: number; // 0..100 card background opacity
  size: OverlaySize | null; // exact canvas px; null fills the viewport
  padX: number;
  padY: number;
  demo: boolean;
}

export interface LayoutSummary {
  id: number;
  name: string;
  kind: "overlay" | "dash";
  config: LayoutConfig;
  created_at: string;
  updated_at: string;
}

export const MAX_GRID_DIM = 24;

export const DEFAULT_LAYOUT: LayoutConfig = {
  version: 2,
  grid: { cols: 16, rows: 2, gap: 8 },
  cells: [
    { id: "c1", widget: "gear", variant: "digits", x: 3, y: 0, w: 1, h: 2 },
    { id: "c2", widget: "speed", variant: "digits", x: 4, y: 0, w: 1, h: 2 },
    { id: "c3", widget: "rpm", variant: "bar", x: 5, y: 0, w: 2, h: 1 },
    { id: "c4", widget: "inputs", variant: "bars-h", x: 5, y: 1, w: 2, h: 1 },
    { id: "c5", widget: "times", variant: "list", x: 7, y: 0, w: 2, h: 2 },
    { id: "c6", widget: "tires", variant: "temps", x: 9, y: 0, w: 1, h: 2 },
    { id: "c7", widget: "fuel", variant: "percent", x: 10, y: 0, w: 1, h: 2 },
    { id: "c8", widget: "alerts", variant: "banner", x: 11, y: 0, w: 2, h: 2 },
  ],
  page: "transparent",
  bg: 70,
  size: { width: 1920, height: 260 },
  padX: DEFAULT_PAD,
  padY: DEFAULT_PAD,
  demo: false,
};

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function clampInt(v: unknown, min: number, max: number, fallback: number): number {
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.round(n)));
}

function cellsOverlap(a: LayoutCell, b: LayoutCell): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// The trust boundary for layout JSON from the server, localStorage, or
// imported files: merge over defaults and drop/clamp anything later code
// would trip over. Overlapping cells keep the first one placed.
export function normalizeLayout(raw: unknown): LayoutConfig {
  const src = isPlainObject(raw) ? raw : {};
  const gridSrc = isPlainObject(src.grid) ? src.grid : {};
  const grid: LayoutGrid = {
    cols: clampInt(gridSrc.cols, 1, MAX_GRID_DIM, DEFAULT_LAYOUT.grid.cols),
    rows: clampInt(gridSrc.rows, 1, MAX_GRID_DIM, DEFAULT_LAYOUT.grid.rows),
    gap: clampInt(gridSrc.gap, 0, 64, DEFAULT_LAYOUT.grid.gap),
  };

  const cells: LayoutCell[] = [];
  let counter = 0;
  for (const entry of Array.isArray(src.cells) ? src.cells : []) {
    if (!isPlainObject(entry)) continue;
    const widget = entry.widget;
    if (typeof widget !== "string" || !(WIDGET_IDS as readonly string[]).includes(widget)) {
      continue;
    }
    const wid = widget as WidgetId;
    const meta = WIDGET_META[wid];
    const variant =
      typeof entry.variant === "string" && isValidVariant(wid, entry.variant)
        ? entry.variant
        : meta.defaultVariant;
    let [w, h] =
      isAllowedSize(wid, Number(entry.w), Number(entry.h))
        ? [Number(entry.w), Number(entry.h)]
        : defaultSize(wid);
    // A footprint larger than the whole grid falls back to the widget's
    // smallest allowed size rather than being dropped.
    if (w > grid.cols || h > grid.rows) {
      const fit = meta.sizes.find(([sw, sh]) => sw <= grid.cols && sh <= grid.rows);
      if (!fit) continue;
      [w, h] = fit;
    }
    const cell: LayoutCell = {
      id:
        typeof entry.id === "string" && entry.id.length > 0 && entry.id.length <= 40
          ? entry.id
          : `c${++counter + 1000}`,
      widget: wid,
      variant,
      x: clampInt(entry.x, 0, grid.cols - w, 0),
      y: clampInt(entry.y, 0, grid.rows - h, 0),
      w,
      h,
      ...(isPlainObject(entry.options) ? { options: entry.options } : {}),
    };
    if (cells.some((c) => c.id === cell.id || cellsOverlap(c, cell))) continue;
    cells.push(cell);
  }

  const page = src.page;
  const bg = Number(src.bg);
  const sizeSrc = src.size;
  const size: OverlaySize | null =
    isPlainObject(sizeSrc) &&
    Number.isFinite(Number(sizeSrc.width)) &&
    Number.isFinite(Number(sizeSrc.height)) &&
    Number(sizeSrc.width) >= 100 &&
    Number(sizeSrc.height) >= 100
      ? { width: Math.round(Number(sizeSrc.width)), height: Math.round(Number(sizeSrc.height)) }
      : null;

  return {
    version: 2,
    grid,
    cells,
    page: page === "green" || page === "dark" || page === "transparent" ? page : "transparent",
    bg: Number.isFinite(bg) ? Math.min(100, Math.max(0, bg)) : DEFAULT_LAYOUT.bg,
    size,
    padX: clampInt(src.padX, 0, 400, DEFAULT_PAD),
    padY: clampInt(src.padY, 0, 400, DEFAULT_PAD),
    demo: src.demo === true,
  };
}

// Convert a v1 URL-param config into a v2 grid: flow the widgets in order —
// strip fills a row, stack fills a column, grid wraps at two columns — using
// each widget's default footprint.
export function migrateOverlayConfig(old: OverlayConfig): LayoutConfig {
  const perRow = old.layout === "stack" ? 1 : old.layout === "grid" ? 2 : old.widgets.length;
  const cells: LayoutCell[] = [];
  let x = 0;
  let y = 0;
  let rowH = 1;
  let placed = 0;
  for (const [i, widget] of old.widgets.entries()) {
    const [w, h] = defaultSize(widget);
    if (placed >= perRow || x + w > MAX_GRID_DIM) {
      x = 0;
      y += rowH;
      rowH = 1;
      placed = 0;
    }
    const scale = old.widgetScales[widget];
    cells.push({
      id: `c${i + 1}`,
      widget,
      variant: WIDGET_META[widget].defaultVariant,
      x,
      y,
      w,
      h,
      ...(scale != null && scale !== 1 ? { options: { scale } } : {}),
    });
    x += w;
    rowH = Math.max(rowH, h);
    placed += 1;
  }
  const cols = Math.min(
    MAX_GRID_DIM,
    Math.max(4, ...cells.map((c) => c.x + c.w)),
  );
  const rows = Math.min(MAX_GRID_DIM, Math.max(2, ...cells.map((c) => c.y + c.h)));
  return normalizeLayout({
    version: 2,
    grid: { cols, rows, gap: 8 },
    cells,
    page: old.page,
    bg: old.bg,
    size: old.size,
    padX: old.padX,
    padY: old.padY,
    demo: old.demo,
  });
}
