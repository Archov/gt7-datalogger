import type {
  CompareResult,
  ConnectionStatus,
  DeviationResult,
  FuelMapResult,
  LapSummary,
  SessionSummary,
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
  deleteSession: (id: number) => send<{ status: string }>(`/api/sessions/${id}`, "DELETE"),
  deleteLap: (id: number) => send<{ status: string }>(`/api/laps/${id}`, "DELETE"),
  exportLap: (id: number) => get<Record<string, unknown>>(`/api/laps/${id}/export`),
  importLap: (payload: unknown) => send<{ id: number }>("/api/laps/import", "POST", payload),
  compare: (lapIds: number[], ref: number) =>
    get<CompareResult>(`/api/analysis/compare?laps=${lapIds.join(",")}&ref=${ref}`),
  deviation: (sessionId: number, count = 5) =>
    get<DeviationResult>(`/api/analysis/deviation?session_id=${sessionId}&count=${count}`),
  fuelMap: (lapId: number) => get<FuelMapResult>(`/api/analysis/fuel?lap_id=${lapId}`),
  setRecording: (recording: boolean) =>
    send<ConnectionStatus>("/api/control/recording", "POST", { recording }),
  logLapNow: () => send<{ id: number }>("/api/control/log-lap-now", "POST"),
};
