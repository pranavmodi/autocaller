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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { credentials: "include" });
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

export const listCalls = (limit = 25, offset = 0) =>
  get<CallsResponse>(`/api/calls?limit=${limit}&offset=${offset}`);

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

// ---- Leads (patients table) ----
export const listLeads = () =>
  get<{ patients: Lead[] }>("/api/patients");

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

export const setDispatcherCooldown = (cooldown_seconds: number) =>
  put<Record<string, unknown>>("/api/settings/dispatcher/cooldown", { cooldown_seconds });

export const setIVRNavigate = (enabled: boolean) =>
  put<Record<string, unknown>>("/api/settings/ivr-navigate", { enabled });

export const retryLead = (leadId: string) =>
  post<{ status: string; patient_id: string }>(`/api/patients/${leadId}/retry`);

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
