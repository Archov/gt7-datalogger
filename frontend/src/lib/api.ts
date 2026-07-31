import type { LayoutConfig, LayoutSummary } from "./layout";
import type {
  AdminSettings,
  AdminStats,
  CompareResult,
  ConnectionStatus,
  DeviationResult,
  FuelMapResult,
  LapSummary,
  LogRecord,
  SessionSummary,
  Track,
} from "./types";

async function get<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url}: ${resp.status} ${await resp.text()}`);
  return resp.json() as Promise<T>;
}

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const resp = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`${url}: ${resp.status} ${await resp.text()}`);
  return resp.json() as Promise<T>;
}

export const api = {
  status: () => get<ConnectionStatus>("/api/status"),
  sessions: () => get<SessionSummary[]>("/api/sessions"),
  sessionLaps: (id: number) => get<LapSummary[]>(`/api/sessions/${id}/laps`),
  laps: () => get<LapSummary[]>("/api/laps"),
  lapDetail: (id: number, withSamples = true) =>
    get<LapSummary & Record<string, unknown>>(`/api/laps/${id}${withSamples ? "" : "?samples=0"}`),
  deleteSession: (id: number) => send<{ status: string }>(`/api/sessions/${id}`, "DELETE"),
  deleteLap: (id: number) => send<{ status: string }>(`/api/laps/${id}`, "DELETE"),
  exportLap: (id: number) => get<Record<string, unknown>>(`/api/laps/${id}/export`),
  importLap: (payload: unknown) => send<{ id: number }>("/api/laps/import", "POST", payload),
  compare: (lapIds: number[], ref: number, channels?: string[]) =>
    get<CompareResult>(
      `/api/analysis/compare?laps=${lapIds.join(",")}&ref=${ref}` +
        (channels && channels.length > 0 ? `&channels=${channels.join(",")}` : ""),
    ),
  deviation: (sessionId: number, count = 5) =>
    get<DeviationResult>(`/api/analysis/deviation?session_id=${sessionId}&count=${count}`),
  fuelMap: (lapId: number) => get<FuelMapResult>(`/api/analysis/fuel?lap_id=${lapId}`),
  setRecording: (recording: boolean) =>
    send<ConnectionStatus>("/api/control/recording", "POST", { recording }),
  logLapNow: () => send<{ id: number }>("/api/control/log-lap-now", "POST"),

  tracks: () => get<Track[]>("/api/tracks"),
  createTrack: (name: string, lapId: number) =>
    send<{ id: number; name: string }>("/api/tracks", "POST", { name, lap_id: lapId }),
  deleteTrack: (id: number) => send<{ status: string }>(`/api/tracks/${id}`, "DELETE"),
  lapCsvUrl: (lapId: number) => `/api/laps/${lapId}/export.csv`,

  layouts: {
    list: () => get<LayoutSummary[]>("/api/layouts"),
    get: (ref: string | number) =>
      get<LayoutSummary>(`/api/layouts/${encodeURIComponent(String(ref))}`),
    create: (name: string, kind: "overlay" | "dash", config: LayoutConfig) =>
      send<LayoutSummary>("/api/layouts", "POST", { name, kind, config }),
    update: (id: number, patch: { name?: string; config?: LayoutConfig }) =>
      send<LayoutSummary>(`/api/layouts/${id}`, "PUT", patch),
    remove: (id: number) => send<{ status: string }>(`/api/layouts/${id}`, "DELETE"),
  },

  admin: {
    settings: () => get<AdminSettings>("/api/admin/settings"),
    updateSettings: (
      patch: Partial<Pick<AdminSettings, "ps_ip" | "source" | "log_level" | "webhook_url">>,
    ) => send<AdminSettings>("/api/admin/settings", "PUT", patch),
    testWebhook: () => send<{ status: string }>("/api/admin/test-webhook", "POST"),
    logs: (limit = 300, level?: string) =>
      get<LogRecord[]>(`/api/admin/logs?limit=${limit}${level ? `&level=${level}` : ""}`),
    clearLogs: () => send<{ status: string }>("/api/admin/logs", "DELETE"),
    stats: () => get<AdminStats>("/api/admin/stats"),
    restartSource: () => send<ConnectionStatus>("/api/admin/restart-source", "POST"),
    clearData: () => send<{ status: string }>("/api/admin/clear-data", "POST"),
    vacuum: () => send<{ status: string }>("/api/admin/vacuum", "POST"),
    updateCars: () => send<{ cars: number }>("/api/admin/update-cars", "POST"),
  },
};
