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
  oil_pressure: number;
  aids: number; // AIDS_* bitmask
  car_id: number;
  car_name: string;
  session_best_ms: number;
  prev_best_ms: number; // session best BEFORE the latest lap (-1 if none)
  // Live gap vs the session-best lap; null whenever it's unavailable (no
  // reference lap yet, paused/off-track, or past the reference's last sample)
  delta_ms: number | null;
  lap_elapsed_ms: number; // time into the current lap (-1 before the first sample)
  pos_x: number;
  pos_z: number;
  tod_ms: number;
  track_name: string;
}

export interface ConnectionStatus {
  source: string;
  recording: boolean;
  session_id: number | null;
  track_name: string;
  connected: boolean;
  console_ip: string;
  packets_received: number;
  decode_errors: number;
  packet_format?: string;
  frames_dropped?: number; // console frames lost in transit (packet-id gaps)
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
  tod_ms?: number;
  tcs_active_pct?: number;
  asm_active_pct?: number;
  max_water_temp?: number;
  max_oil_temp?: number;
  min_oil_pressure?: number; // -1 = unknown
  counts_for_best?: boolean; // false = partial lap (pit out-lap)
  event_counts?: Record<string, number>;
}

// Driver-aids bitmask stored per tick in the "aids" sample column and sent in
// live frames. Mirrors backend AidsBits.
export const AIDS_TCS = 1;
export const AIDS_ASM = 2;
export const AIDS_HANDBRAKE = 4;
export const AIDS_REV_LIMITER = 8;

export type EventType = "lockup" | "wheelspin" | "bottoming" | "kerb";

export interface LapEvent {
  type: EventType;
  start_dist: number;
  end_dist: number;
  wheels: string[]; // "fl" | "fr" | "rl" | "rr"
  severity: number;
}

// Static per-lap gearing metadata (present when the recording backend saw it)
export interface LapGearing {
  ratios: number[];
  top_speed: number;
  rpm_alert: number;
}

export interface SessionSummary {
  id: number;
  started_at: string;
  car_id: number;
  car_name: string;
  note: string;
  track_name: string;
  lap_count: number;
  best_lap_time_ms: number | null;
}

export interface Track {
  id: number;
  name: string;
  length_m: number;
  created_at: string;
}

export type Samples = Record<string, number[]>;

export interface PeakValley {
  dist: number;
  speed: number;
  x: number;
  z: number;
}

// Auto-detected corner on the reference lap (numbered from the start line)
export interface Corner {
  n: number;
  apex_dist: number;
  apex_x: number;
  apex_z: number;
  entry_dist: number;
  exit_dist: number;
  direction: "L" | "R";
  min_speed: number;
  angle_deg: number;
}

export interface CompareLapEntry {
  series: Samples & { dist: number[] };
  peaks_valleys: { peaks: PeakValley[]; valleys: PeakValley[] };
  events?: LapEvent[];
  delta?: { dist: number[]; delta_ms: number[] };
  corners?: Corner[]; // reference lap only
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
  webhook_url: string;
  webhook_events: WebhookEvent[];
  packet_format: "A" | "B" | "~" | "C";
  race_engineer: boolean;
  race_engineer_verbosity: Verbosity;
  race_engineer_categories: CalloutCategory[];
  race_engineer_units: SpokenUnits;
}

// Units spoken inside callout text ("eighteen meters" / "fifty-nine feet").
// Server-side because the text is worded before it reaches a browser — the
// dashboard's own km/h-vs-mph toggle only affects what is displayed.
export type SpokenUnits = "metric" | "imperial";

// --- Race Engineer (mirrors backend app/race_engineer/models.py) ------------

export const CALLOUT_CATEGORIES = [
  "system",
  "lap",
  "pace",
  "race",
  "position",
  "fuel",
  "strategy",
  "engine",
  "tires",
  "chassis",
  "coaching",
] as const;

export type CalloutCategory = (typeof CALLOUT_CATEGORIES)[number];
export type Verbosity = "minimal" | "race" | "coach";

const MINIMAL_CATEGORIES: CalloutCategory[] = ["system", "engine", "strategy", "race"];

// Verbosity is a preset over the same categories (mirrors the backend). The
// server applies its own setting as a ceiling — a browser can only narrow it.
export const VERBOSITY_CATEGORIES: Record<Verbosity, CalloutCategory[]> = {
  minimal: MINIMAL_CATEGORIES,
  race: [...MINIMAL_CATEGORIES, "lap", "pace", "position", "fuel"],
  coach: [...CALLOUT_CATEGORIES],
};

export interface VoiceCallout {
  id: string;
  event_type: string;
  text: string;
  category: CalloutCategory;
  priority: number; // 0..100; 90+ may interrupt
  created_at_ms: number; // server clock — display/debug only
  expires_at_ms: number; // server clock — display/debug only
  // Lifetime measured from the moment the browser receives it. Server and
  // browser clocks disagree (phones, Pi without NTP), so expiry uses this.
  ttl_ms: number;
  interrupt: boolean;
  dedupe_key?: string | null;
  message_key?: string;
  message_args?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface VoiceClientInfo {
  client_id: string;
  page: string;
  voice_supported: boolean;
  voice_enabled: boolean;
  is_active_speaker: boolean;
}

export interface RaceEngineerStatus {
  enabled: boolean; // feature switched on server-side
  active: boolean; // ...and at least one browser has voice enabled
  verbosity: Verbosity;
  categories: CalloutCategory[]; // categories the server will emit
  // Whether enough laps agree on the track distance for lap-vs-lap coaching
  // to mean anything. Explains a quiet coaching category early in a session.
  coaching_ready: boolean;
  active_client_id: string;
  clients: VoiceClientInfo[];
}

export interface RaceEngineerDiagnostics extends RaceEngineerStatus {
  units: SpokenUnits;
  session_id: number | null;
  lap_history: number;
  best_lap_ms: number | null;
  corners: number;
  effective_categories: CalloutCategory[];
  stats: Record<string, number>;
  acks: Record<string, number>;
  /** Why the browser last failed to speak, in the engine's own words. */
  last_ack_reason: string;
  last_callout: VoiceCallout | null;
}

export type CalloutAckStatus =
  | "spoken"
  | "expired"
  // Stopped on purpose — by a critical callout, a disconnect, or the user
  // pressing Test voice. Not a failure, and never treated as one.
  | "interrupted"
  | "duplicate"
  | "disabled"
  | "category_disabled"
  | "not_active_speaker"
  | "speech_error";

// Browser -> server. The only client-to-server protocol on /ws/live; older
// pages send nothing and the server ignores anything it can't parse.
export type ClientMessage =
  | {
      type: "client_capabilities";
      data: {
        client_id: string;
        page: string;
        voice_supported: boolean;
        voice_enabled: boolean;
      };
    }
  | { type: "claim_voice_output"; data: { client_id: string } }
  | { type: "release_voice_output"; data: { client_id: string } }
  | {
      type: "voice_callout_ack";
      data: {
        callout_id: string;
        client_id: string;
        status: CalloutAckStatus;
        spoken_at_ms: number;
        /** Engine reason when status is speech_error — the only clue a
         *  silent setup leaves on the server. */
        reason?: string;
      };
    };

export type WebhookEvent =
  | "personal_best"
  | "session_summary"
  | "overtake"
  | "position_lost"
  | "off_road";

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
  lan_ip: string;
  http_port: number;
}

export type WsMessage =
  | { type: "telemetry"; data: LiveFrame }
  | { type: "lap"; data: LapSummary }
  | { type: "status"; data: ConnectionStatus }
  | { type: "session"; data: ConnectionStatus }
  | { type: "voice_callout"; data: VoiceCallout }
  | { type: "voice_output_status"; data: { active_client_id: string } }
  | { type: "race_engineer_status"; data: RaceEngineerStatus };
