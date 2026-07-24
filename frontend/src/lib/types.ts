// Shared API/WebSocket types. Sample columns mirror backend SAMPLE_COLUMNS.

export interface LiveFrame {
  on_track: boolean;
  paused: boolean;
  speed_kmh: number;
  rpm: number;
  rpm_alert: number;
  gear: number;
  suggested_gear: number;
  throttle: number;
  brake: number;
  boost: number;
  fuel_level: number;
  fuel_capacity: number;
  current_lap: number;
  total_laps: number;
  best_lap_ms: number;
  last_lap_ms: number;
  position: number;
  total_positions: number;
  tire_temps: [number, number, number, number];
  tire_slip: number;
  water_temp: number;
  oil_temp: number;
  car_id: number;
  car_name: string;
  session_best_ms: number;
  pos_x: number;
  pos_z: number;
}

export interface ConnectionStatus {
  source: string;
  recording: boolean;
  session_id: number | null;
  connected: boolean;
  console_ip: string;
  packets_received: number;
  decode_errors: number;
}

export interface LapSummary {
  id: number;
  session_id: number;
  number: number;
  time_ms: number;
  finished_at?: string;
  car_id?: number;
  car_name?: string;
  fuel_consumed: number;
  full_throttle_pct: number;
  full_brake_pct: number;
  coasting_pct: number;
  tire_spin_pct: number;
  max_speed: number;
  min_body_height: number;
  total_ticks?: number;
}

export interface SessionSummary {
  id: number;
  started_at: string;
  car_id: number;
  car_name: string;
  note: string;
  lap_count: number;
  best_lap_time_ms: number | null;
}

export type Samples = Record<string, number[]>;

export interface PeakValley {
  dist: number;
  speed: number;
  x: number;
  z: number;
}

export interface CompareLapEntry {
  series: Samples & { dist: number[] };
  peaks_valleys: { peaks: PeakValley[]; valleys: PeakValley[] };
  delta?: { dist: number[]; delta_ms: number[] };
}

export interface CompareResult {
  ref: number;
  step: number;
  laps: Record<string, CompareLapEntry>;
}

export interface DeviationResult {
  dist: number[];
  median: number[];
  deviation: number[];
  lap_ids: number[];
}

export interface FuelMapRow {
  setting: number;
  fuel_per_lap: number;
  laps_remaining: number;
  time_remaining_ms: number;
  lap_time_delta_ms: number;
}

export interface FuelMapResult {
  fuel_level: number;
  base_lap_ms: number;
  base_fuel_per_lap: number;
  rows: FuelMapRow[];
}

export interface AdminSettings {
  ps_ip: string;
  source: "udp" | "sim";
  log_level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  ws_rate: number;
  heartbeat_port: number;
  telemetry_port: number;
}

export interface LogRecord {
  ts: string;
  level: string;
  logger: string;
  message: string;
}

export interface AdminStats {
  uptime_s: number;
  db: { sessions: number; laps: number; size_bytes: number; path: string };
  cars_loaded: number;
  source: ConnectionStatus;
  clients: number;
}

export type WsMessage =
  | { type: "telemetry"; data: LiveFrame }
  | { type: "lap"; data: LapSummary }
  | { type: "status"; data: ConnectionStatus }
  | { type: "session"; data: ConnectionStatus };
