import type {
  CallLog,
  DispatcherStatus,
  Lead,
} from "@/types";

// Backend origin. In production (served behind nginx on the same domain),
// relative URLs work — `/api/*` and `/ws/*` are proxied. For local dev we
// fall back to NEXT_PUBLIC_API_URL (or localhost:8099).
const origin =
  typeof window !== "undefined"
    ? ""
    : process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8099";

export function apiUrl(path: string): string {
  // Use window.location origin in the browser so relative paths work
  // whether we're served from the same domain as the API or not.
  if (typeof window !== "undefined") {
    if (process.env.NEXT_PUBLIC_API_URL) {
      return `${process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, "")}${path}`;
    }
    return path;
  }
  return `${origin}${path}`;
}

export function wsUrl(path: string): string {
  if (typeof window === "undefined") return "";
  const base =
    process.env.NEXT_PUBLIC_API_URL ||
    `${window.location.protocol}//${window.location.host}`;
  return base.replace(/^http/, "ws").replace(/\/$/, "") + path;
}

function _handle401(path: string) {
  // Session expired or unauthenticated. Bounce to /login unless we're
  // already there (avoid a loop on the login page itself or on auth
  // endpoints that legitimately return 401 for bad password).
  if (typeof window === "undefined") return;
  if (path.startsWith("/api/auth/")) return;
  if (window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  const url = new URL("/login", window.location.origin);
  if (next && next !== "/") url.searchParams.set("next", next);
  window.location.replace(url.toString());
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { credentials: "include" });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`GET ${path} 401`);
  }
  if (!res.ok) throw new Error(`GET ${path} ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`POST ${path} 401`);
  }
  if (!res.ok) throw new Error(`POST ${path} ${res.status}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`PUT ${path} 401`);
  }
  if (!res.ok) throw new Error(`PUT ${path} ${res.status}`);
  return res.json();
}

// ---- Dispatcher ----
export const getDispatcherStatus = () =>
  get<DispatcherStatus>("/api/dispatcher/status");

export const toggleDispatcher = (enabled: boolean, target_calls?: number) =>
  post<DispatcherStatus>("/api/dispatcher/toggle", {
    enabled,
    target_calls: target_calls ?? null,
  });

export const startDispatcherBatch = (count: number) =>
  post<DispatcherStatus>("/api/dispatcher/start-batch", { count });

// ---- Calls ----
export interface CallsResponse {
  calls: CallLog[];
  total: number;
}

export const listCalls = (
  limit = 25,
  offset = 0,
  filters?: { outcome?: string; mode?: string; q?: string },
) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (filters?.outcome && filters.outcome !== "all") params.set("outcome", filters.outcome);
  if (filters?.mode && filters.mode !== "all") params.set("mode", filters.mode);
  if (filters?.q) params.set("q", filters.q);
  return get<CallsResponse>(`/api/calls?${params}`);
};

export function recordingUrl(recordingPath: string | null): string | null {
  if (!recordingPath) return null;
  const path = recordingPath.startsWith("app/audio/recordings/")
    ? recordingPath.slice("app/audio/".length)
    : recordingPath.startsWith("recordings/")
      ? recordingPath
      : `recordings/${recordingPath}`;
  return apiUrl(`/audio/${path}`);
}

export const getCall = (callId: string) =>
  get<CallLog>(`/api/calls/${callId}`);

export const getActiveCall = () =>
  get<{ active: boolean; call: CallLog | null }>("/api/calls/active");

export const clearActiveCall = () =>
  post<{ status: string }>("/api/calls/clear-active");

export const startCall = (patientId: string, mode: "twilio" | "web" = "twilio") =>
  post<{ call: CallLog }>("/api/call/start", { patient_id: patientId, mode });

// ---- Cadence priority queue (Layer 1: autorespond signals) ----

export type CadencePriorityRow = {
  id: string;
  pif_id: string;
  firm_name: string;
  cadence_stage: string;
  next_action: string | null;
  next_action_due: string | null;
  owner: string | null;
  outcome: string;
  call_ids: string[];
  contacts_tried: Array<{ name: string; phone: string; title?: string }>;
  available_contacts: Array<{
    name: string;
    title: string;
    phone: string;
    email: string | null;
    source: string;
  }>;
  intel: Record<string, unknown>;
  icp_tier: string | null;
  icp_score: number | null;
  notes: string | null;
  priority_score: number;
  autorespond: {
    events_24h: number;
    events_7d: number;
    latest_event_at: string | null;
    latest_subject: string;
    top_agent_types: string[];
    distinct_contact_count: number;
  };
  last_call_age_hours: number | null;
  created_at: string;
  updated_at: string;
};

export const getCadenceNextUp = (limit = 50) =>
  get<{ items: CadencePriorityRow[]; total: number }>(
    `/api/cadence/next-up?limit=${limit}`,
  );

export type AutorespondSummary = {
  total_events?: number;
  events_today?: number;
  events_this_week?: number;
  by_agent_type?: Record<string, number>;
  by_day?: Array<{ date: string; count: number }>;
  top_firms?: Array<{ firm_name: string; pif_id: string; count: number }>;
  error?: string;
};

export const getAutorespondSummary = () =>
  get<AutorespondSummary>("/api/cadence/autorespond-summary");

export const getFirmAutorespondEvents = (pifId: string, page = 1, pageSize = 50) =>
  get<{ items: unknown[]; total: number; page: number; page_size: number }>(
    `/api/cadence/${pifId}/autorespond-events?page=${page}&page_size=${pageSize}`,
  );

// Skip a cadence entry — bumps it to the next stage in the cadence
// FSM (signal_detected → call_1 → … → exhausted). Used by the
// Now-page Next-up widget so the operator can defer a row without
// opening the full /cadence page.
export const skipCadenceEntry = (entryId: string) =>
  put<unknown>(`/api/cadence/${entryId}`, { action: "skip" });

// ---- Leads (patients table) ----
export const listLeads = () =>
  get<{ patients: Lead[] }>("/api/patients");

export const listNextUp = () =>
  get<{ patients: Lead[] }>("/api/patients/next-up");

export const getLead = (id: string) =>
  get<Lead>(`/api/patients/${id}`);

// ---- Settings ----
export const getSettings = () =>
  get<Record<string, unknown>>("/api/settings");

export const setSystemEnabled = (enabled: boolean) =>
  put<Record<string, unknown>>("/api/settings/system-enabled", { enabled });

export const setMockMode = (enabled: boolean, mock_phone = "") =>
  put<Record<string, unknown>>("/api/settings/mock-mode", { enabled, mock_phone });

export const setVoiceProvider = (provider: "openai" | "gemini", model = "") =>
  put<Record<string, unknown>>("/api/settings/voice", { provider, model });

export type VoiceConfigPatch = {
  provider: "openai" | "gemini";
  voice?: string;
  temperature?: number;
  affective_dialog?: boolean; // Gemini-only
  proactive_audio?: boolean;  // Gemini-only
  speed?: number;             // OpenAI-only (0.25-4.0)
  top_p?: number;             // Gemini-only (0.0-1.0)
};

export const setVoiceConfig = (patch: VoiceConfigPatch) =>
  put<Record<string, unknown>>("/api/settings/voice-config", patch);

// Build the URL for a voice preview clip. Backend caches per-voice so
// repeated calls are cheap; the <audio> element can fetch it directly.
export const voicePreviewUrl = (
  provider: "openai" | "gemini",
  voice: string,
) => apiUrl(`/api/voice/preview/${provider}/${encodeURIComponent(voice)}`);

// Manual IVR: operator drives digits; AI stays muted until disabled.
export const setManualIvr = (callId: string, enabled: boolean) =>
  post<{ status: string; manual_ivr_active: boolean }>(
    `/api/calls/${callId}/manual-ivr`,
    { enabled },
  );

// Send one digit (legacy — still supported by the backend).
export const sendDtmf = (callId: string, digit: string) =>
  post<{ status: string; digits: string }>(
    `/api/calls/${callId}/dtmf`,
    { digit },
  );

// Send a multi-digit sequence (e.g. "701") as a single batch. The
// orchestrator streams each tone with an 80ms inter-digit gap so the
// phone tree registers the whole string as one input.
export const sendDtmfBatch = (callId: string, digits: string) =>
  post<{ status: string; digits: string }>(
    `/api/calls/${callId}/dtmf`,
    { digits },
  );


export type VoicemailRecipient = {
  call_id: string;
  patient_id: string;
  patient_name: string;
  firm_name: string | null;
  phone: string;
  lead_state: string | null;
  started_at: string | null;
  duration_seconds: number;
  voicemail_left: boolean;
  prompt_version: string | null;
};

export const getVoicemailRecipients = () =>
  get<{ rows: VoicemailRecipient[]; count: number }>(
    "/api/call-lists/voicemail?limit=500",
  );


export type ConsultBooking = {
  id: number;
  name: string;
  firm_name: string | null;
  email: string;
  phone: string | null;
  slot_start: string;
  slot_end: string;
  notes: string | null;
  status: string;
  source: string;
  created_at: string;
};

export const getConsultBookings = () =>
  get<{ bookings: ConsultBooking[] }>("/api/consults?limit=200");

// Unacknowledged bookings — drives the global popup. Polled.
export type PendingBooking = {
  id: number;
  name: string;
  firm_name: string | null;
  email: string;
  phone: string | null;
  slot_start: string;
  slot_end: string;
  notes: string | null;
  created_at: string;
};

export const getPendingBookings = () =>
  get<{ pending: PendingBooking[] }>("/api/consults/pending");

export const acknowledgeBooking = (id: number) =>
  post<{ id: number; acknowledged: boolean }>(
    `/api/consults/${id}/acknowledge`,
  );


// ---- Firm reviews (operator-pasted, split by source) ----
export type FirmReviews = {
  pif_id: string;
  google: string;
  yelp: string;
  updated_at: string | null;
};

export const getFirmReviews = (pifId: string) =>
  get<FirmReviews>(`/api/firms/${encodeURIComponent(pifId)}/reviews`);

// Patch semantics: omit a field to leave it untouched. Pass "" to
// explicitly clear that source's blob.
export const putFirmReviews = (
  pifId: string,
  patch: { google?: string; yelp?: string },
) =>
  put<FirmReviews>(`/api/firms/${encodeURIComponent(pifId)}/reviews`, patch);


// Force-pull researched firms from PIF Stats into the local patients
// table. Returns counts; the same op the background loop runs every
// CADENCE_SCAN_INTERVAL_SECONDS.
export type FirmsSyncResult = {
  fetched: number;
  inserted: number;
  updated: number;
  skipped: number;
};

export const syncFirms = () =>
  post<FirmsSyncResult>("/api/firms/sync");


export const OPENAI_VOICES = [
  "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse",
] as const;
export const GEMINI_VOICES = [
  "Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Zephyr",
] as const;

export const setDispatcherCooldown = (cooldown_seconds: number) =>
  put<Record<string, unknown>>("/api/settings/dispatcher/cooldown", { cooldown_seconds });

export const setDispatcherBatchSize = (batch_size: number) =>
  put<Record<string, unknown>>("/api/settings/dispatcher/batch-size", { batch_size });

export const setIVRNavigate = (enabled: boolean) =>
  put<Record<string, unknown>>("/api/settings/ivr-navigate", { enabled });

export const retryLead = (leadId: string) =>
  post<{ status: string; patient_id: string }>(`/api/patients/${leadId}/retry`);

export const skipLead = (leadId: string) =>
  post<{ status: string; patient_id: string }>(`/api/patients/${leadId}/skip`);

// ---- Health ----
export const checkHealth = () =>
  fetch(apiUrl("/health")).then((r) => r.ok);

export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export const getHealthChecks = () =>
  get<{ checks: HealthCheck[] }>("/api/health/checks");

export interface FunnelStage {
  name: string;
  count: number;
}

export const getFunnel = (days = 7) =>
  get<{ days: number; stages: FunnelStage[] }>(`/api/health/funnel?days=${days}`);

export interface JudgeAggregate {
  pending: number;
  judged_7d: number;
  score_p25: number | null;
  score_p50: number | null;
  score_p75: number | null;
  score_mean: number | null;
  by_disposition: { disposition: string; count: number }[];
}

export const getJudgeAggregate = () =>
  get<JudgeAggregate>("/api/health/judge");

// ---- Daily stats ----
export interface DailyStats {
  total: number;
  outcomes: Record<string, number>;
  dm: { reached: number; path_captured: number; no_path: number; reach_rate: number };
  ivr_detected: number;
  avg_duration: number;
  total_duration_min: number;
}

export const getDailyStats = () => get<DailyStats>("/api/stats/daily");

// ---- Carrier (telephony provider: twilio | telnyx) ----
export interface CarrierInfo {
  provider: string;                  // "twilio" | "telnyx"
  label: string | null;
  account_sid: string;
  account_sid_masked: string;
  from_number: string;
  configured: boolean;
  status: string | null;
  account_type: string | null;
  account_name: string | null;
  balance: string | null;
  currency: string | null;
  number_status: string | null;
  reachable: boolean;
  error: string | null;
}

export interface CarrierStatus extends CarrierInfo {
  default_carrier: string;
  carriers: { twilio: CarrierInfo; telnyx: CarrierInfo };
}

export const getCarrier = () => get<CarrierStatus>("/api/carrier");

export const setDefaultCarrier = (carrier: "twilio" | "telnyx") =>
  put<{ default_carrier: string }>("/api/carrier", { carrier });
