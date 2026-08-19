export type TimelineDensity = "compact" | "normal" | "large";
export type MapScalePreset = 0.25 | 0.5 | 1 | 2;

export interface AnalysisWorkspacePreferences {
  version: 4;
  inspectorWidth: number;
  mapHeight: number;
  timelineDensity: TimelineDensity;
  followCursor: boolean;
  showTravelDirection: boolean;
  keepLapMarkersVisible: boolean;
  mapMetersPerPixel: number;
}

export const ANALYSIS_WORKSPACE_STORAGE_KEY = "gt7-analysis-workspace-v4";
export const LEGACY_ANALYSIS_WORKSPACE_STORAGE_KEYS = [
  "gt7-analysis-workspace-v3",
  "gt7-analysis-workspace-v2",
  "gt7-analysis-workspace-v1",
] as const;
export const DEFAULT_INSPECTOR_WIDTH = 360;
export const MIN_INSPECTOR_WIDTH = 300;
export const MIN_CENTER_WIDTH = 640;
export const MIN_MAP_HEIGHT = 280;
export const MIN_TIMELINE_HEIGHT = 240;
export const WORKSPACE_DIVIDER_SIZE = 10;
export const MIN_MAP_METERS_PER_PIXEL = 0.05;
export const MAX_MAP_METERS_PER_PIXEL = 10;
export const MAP_SCALE_STEP = 0.05;
export const MAP_SCALE_PRESETS: readonly MapScalePreset[] = [0.25, 0.5, 1, 2];
export const DEFAULT_MAP_METERS_PER_PIXEL = 0.5;

export const TIMELINE_PANEL_HEIGHTS: Record<TimelineDensity, number> = {
  compact: 90,
  normal: 110,
  large: 150,
};

export const DEFAULT_ANALYSIS_WORKSPACE: AnalysisWorkspacePreferences = {
  version: 4,
  inspectorWidth: DEFAULT_INSPECTOR_WIDTH,
  mapHeight: 420,
  timelineDensity: "normal",
  followCursor: true,
  showTravelDirection: true,
  keepLapMarkersVisible: true,
  mapMetersPerPixel: DEFAULT_MAP_METERS_PER_PIXEL,
};

const DENSITIES = new Set<TimelineDensity>(["compact", "normal", "large"]);
const LEGACY_MAP_SCALES: Record<number, MapScalePreset> = {
  150: 0.25,
  300: 0.5,
  600: 1,
  1000: 2,
};

interface LegacyAnalysisWorkspacePreferences {
  version: 1;
  inspectorWidth: number;
  mapHeight: number;
  timelineDensity: TimelineDensity;
  followCursor: boolean;
  mapWindowMeters: number;
}

interface VersionTwoAnalysisWorkspacePreferences {
  version: 2;
  inspectorWidth: number;
  mapHeight: number;
  timelineDensity: TimelineDensity;
  followCursor: boolean;
  mapMetersPerPixel: number;
}

interface VersionThreeAnalysisWorkspacePreferences
  extends Omit<VersionTwoAnalysisWorkspacePreferences, "version"> {
  version: 3;
  showTravelDirection: boolean;
}

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}

export function normalizeMapMetersPerPixel(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_MAP_METERS_PER_PIXEL;
  const clamped = clamp(value, MIN_MAP_METERS_PER_PIXEL, MAX_MAP_METERS_PER_PIXEL);
  return Math.round(clamped * 1000) / 1000;
}

export function defaultMapHeight(workspaceHeight: number): number {
  const maximum = Math.max(MIN_MAP_HEIGHT, workspaceHeight - MIN_TIMELINE_HEIGHT - WORKSPACE_DIVIDER_SIZE);
  return clamp(workspaceHeight * 0.42, MIN_MAP_HEIGHT, Math.min(420, maximum));
}

export function clampWorkspacePreferences(
  preferences: AnalysisWorkspacePreferences,
  workspaceWidth: number,
  workspaceHeight: number,
): AnalysisWorkspacePreferences {
  const maximumInspector = Math.max(
    MIN_INSPECTOR_WIDTH,
    workspaceWidth - MIN_CENTER_WIDTH - WORKSPACE_DIVIDER_SIZE,
  );
  const maximumMap = Math.max(
    MIN_MAP_HEIGHT,
    workspaceHeight - MIN_TIMELINE_HEIGHT - WORKSPACE_DIVIDER_SIZE,
  );
  return {
    ...preferences,
    inspectorWidth: clamp(preferences.inspectorWidth, MIN_INSPECTOR_WIDTH, maximumInspector),
    mapHeight: clamp(preferences.mapHeight, MIN_MAP_HEIGHT, maximumMap),
    mapMetersPerPixel: normalizeMapMetersPerPixel(preferences.mapMetersPerPixel),
  };
}

export function defaultWorkspacePreferences(
  workspaceWidth = Number.POSITIVE_INFINITY,
  workspaceHeight = 1000,
): AnalysisWorkspacePreferences {
  return clampWorkspacePreferences(
    {
      ...DEFAULT_ANALYSIS_WORKSPACE,
      mapHeight: defaultMapHeight(workspaceHeight),
    },
    workspaceWidth,
    workspaceHeight,
  );
}

export function parseWorkspacePreferences(raw: string | null): AnalysisWorkspacePreferences {
  if (!raw) return { ...DEFAULT_ANALYSIS_WORKSPACE };
  try {
    const value = JSON.parse(raw) as
      | Partial<AnalysisWorkspacePreferences>
      | Partial<VersionThreeAnalysisWorkspacePreferences>
      | Partial<VersionTwoAnalysisWorkspacePreferences>
      | Partial<LegacyAnalysisWorkspacePreferences>
      | null;
    if (
      !value ||
      (value.version !== 1 && value.version !== 2 && value.version !== 3 && value.version !== 4)
    ) {
      return { ...DEFAULT_ANALYSIS_WORKSPACE };
    }
    const legacyWindow =
      value.version === 1 && typeof value.mapWindowMeters === "number"
        ? LEGACY_MAP_SCALES[value.mapWindowMeters]
        : undefined;
    const storedScale =
      (value.version === 2 || value.version === 3 || value.version === 4) &&
      typeof value.mapMetersPerPixel === "number"
        ? value.mapMetersPerPixel
        : legacyWindow;
    return {
      version: 4,
      inspectorWidth:
        typeof value.inspectorWidth === "number" && Number.isFinite(value.inspectorWidth)
          ? value.inspectorWidth
          : DEFAULT_ANALYSIS_WORKSPACE.inspectorWidth,
      mapHeight:
        typeof value.mapHeight === "number" && Number.isFinite(value.mapHeight)
          ? value.mapHeight
          : DEFAULT_ANALYSIS_WORKSPACE.mapHeight,
      timelineDensity:
        typeof value.timelineDensity === "string" &&
        DENSITIES.has(value.timelineDensity as TimelineDensity)
          ? (value.timelineDensity as TimelineDensity)
          : DEFAULT_ANALYSIS_WORKSPACE.timelineDensity,
      followCursor:
        typeof value.followCursor === "boolean"
          ? value.followCursor
          : DEFAULT_ANALYSIS_WORKSPACE.followCursor,
      showTravelDirection:
        (value.version === 3 || value.version === 4) &&
        typeof value.showTravelDirection === "boolean"
          ? value.showTravelDirection
          : DEFAULT_ANALYSIS_WORKSPACE.showTravelDirection,
      keepLapMarkersVisible:
        value.version === 4 && typeof value.keepLapMarkersVisible === "boolean"
          ? value.keepLapMarkersVisible
          : DEFAULT_ANALYSIS_WORKSPACE.keepLapMarkersVisible,
      mapMetersPerPixel:
        storedScale != null && Number.isFinite(storedScale)
          ? normalizeMapMetersPerPixel(storedScale)
          : DEFAULT_ANALYSIS_WORKSPACE.mapMetersPerPixel,
    };
  } catch {
    return { ...DEFAULT_ANALYSIS_WORKSPACE };
  }
}

export function loadWorkspacePreferences(): AnalysisWorkspacePreferences {
  const raw =
    localStorage.getItem(ANALYSIS_WORKSPACE_STORAGE_KEY) ??
    LEGACY_ANALYSIS_WORKSPACE_STORAGE_KEYS.map((key) => localStorage.getItem(key)).find(
      (value) => value != null,
    ) ??
    null;
  return parseWorkspacePreferences(raw);
}

export function hasStoredWorkspacePreferences(): boolean {
  return (
    localStorage.getItem(ANALYSIS_WORKSPACE_STORAGE_KEY) != null ||
    LEGACY_ANALYSIS_WORKSPACE_STORAGE_KEYS.some((key) => localStorage.getItem(key) != null)
  );
}

export function saveWorkspacePreferences(preferences: AnalysisWorkspacePreferences): void {
  localStorage.setItem(ANALYSIS_WORKSPACE_STORAGE_KEY, JSON.stringify(preferences));
}
