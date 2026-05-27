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
  const configuredBase = process.env.NEXT_PUBLIC_API_URL;
  const isLocalDevHost =
    (window.location.hostname === "127.0.0.1" ||
      window.location.hostname === "localhost") &&
    window.location.port &&
    window.location.port !== "8099";
  const base =
    configuredBase ||
    (isLocalDevHost
      ? `${window.location.protocol}//${window.location.hostname}:8099`
      : `${window.location.protocol}//${window.location.host}`);
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

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`PATCH ${path} 401`);
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`PATCH ${path} ${res.status}${detail ? ` — ${detail}` : ""}`);
  }
  return res.json();
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "DELETE",
    credentials: "include",
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`DELETE ${path} 401`);
  }
  if (!res.ok) throw new Error(`DELETE ${path} ${res.status}`);
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

export type FirmCallRow = {
  call_id: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  patient_name: string;
  phone: string;
  outcome: string;
  call_status: string;
  call_disposition: string;
  ended_by: string | null;
  voicemail_left: boolean;
  judge_score: number | null;
  prompt_version: string | null;
  voice_provider: string | null;
  ivr_detected: boolean;
  ivr_outcome: string | null;
  demo_scheduled_at: string | null;
};

export const getFirmCalls = (pifId: string, limit = 50) =>
  get<{ items: FirmCallRow[]; total: number; firm_name: string | null }>(
    `/api/cadence/firm/${pifId}/calls?limit=${limit}`,
  );

export type ReviewsSummary = {
  google: string[];        // pif_ids with non-empty google_content
  yelp: string[];          // pif_ids with non-empty yelp_content
  any: string[];           // union (unique, sorted)
  google_count: number;
  yelp_count: number;
  total_count: number;
};

export const getReviewsSummary = () =>
  get<ReviewsSummary>("/api/firms/reviews-summary");

export type FirmsStats = {
  total_firms: number | null;
  researched_count: number | null;
  with_reviews_count: number;
  autorespond_7d_count: number | null;
};

export const getFirmsStats = () =>
  get<FirmsStats>("/api/firms/stats");

export type AutorespondFirmRow = {
  pif_id: string;
  firm_name: string;
  events_24h: number;
  events_7d: number;
  latest_event_at: string | null;
  latest_subject: string;
  top_agent_types: string[];
  distinct_contact_count: number;
};

export const getFirmsAutorespondSummary = (days = 7) =>
  get<{ items: AutorespondFirmRow[]; total: number; days: number }>(
    `/api/firms/autorespond-summary?days=${days}`,
  );

export type FirmWithReviewsRow = {
  pif_id: string;
  firm_name: string;
  website: string | null;
  phones: string[];
  addresses: string[];
  contacts_count: number;
  leadership_count: number;
  icp_tier: string | null;
  icp_score: number | null;
  research_status: string | null;
  last_researched_at: string | null;
  google_chars: number;
  yelp_chars: number;
  reviews_updated_at: string | null;
  missing?: boolean;
  error?: string;
};

export const getFirmsWithReviews = (source: "any" | "google" | "yelp" = "any") =>
  get<{ items: FirmWithReviewsRow[]; total: number; source: string }>(
    `/api/firms/with-reviews?source=${source}`,
  );

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

// Voice-AI prompt style. "current" = long Sobczak-style cold-call
// prompt; "minimal" = trimmed-down variant. DB-backed, hot-reloads
// on the next call (no daemon restart needed).
export type PromptStyle = "current" | "minimal";

export const setPromptStyle = (style: PromptStyle) =>
  put<Record<string, unknown>>("/api/settings/prompt-style", { style });

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


// ---- Outbound communications dashboard ----
export type CommsItem = {
  id: string;
  channel: "call" | "voicemail" | "email" | "sms";
  occurred_at: string;
  pif_id: string | null;
  firm_name: string | null;
  contact_name: string | null;
  recipient: string | null;
  summary: string;
  status: string;
  body_excerpt: string | null;
  call_id: string | null;
  duration_seconds: number | null;
  message_type: string | null;
};

export type CommsResponse = {
  items: CommsItem[];
  total: number;
};

export type CommsListParams = {
  channel?: "call" | "voicemail" | "email" | "sms";
  status?: string;
  since?: string;
  until?: string;
  q?: string;
  limit?: number;
};

const _commsQuery = (params: CommsListParams) => {
  const u = new URLSearchParams();
  if (params.channel) u.set("channel", params.channel);
  if (params.status) u.set("status", params.status);
  if (params.since) u.set("since", params.since);
  if (params.until) u.set("until", params.until);
  if (params.q) u.set("q", params.q);
  if (params.limit != null) u.set("limit", String(params.limit));
  const qs = u.toString();
  return qs ? `?${qs}` : "";
};

export const listCommunications = (params: CommsListParams = {}) =>
  get<CommsResponse>(`/api/communications${_commsQuery(params)}`);

export const listFirmCommunications = (
  pifId: string,
  params: Pick<CommsListParams, "channel" | "since" | "limit"> = {},
) =>
  get<CommsResponse>(
    `/api/firms/${encodeURIComponent(pifId)}/communications${_commsQuery(params)}`,
  );


// ---- Email sequence dashboard ----
export type FirmWithContacts = {
  pif_id: string;
  firm_name: string;
  contact_count: number;
  has_pain_quote: boolean;
  extracted_at: string | null;
};

export type FirmContact = {
  id: string;
  pif_id: string;
  full_name: string;
  first_name: string;
  email: string | null;
  phone: string | null;
  title: string | null;
  source: string;
};

export type RenderedSequenceStep = {
  step: number;
  subject: string;
  body: string;
  message_type: string;
};

export type SequenceTemplate = {
  template_key: string;
  label: string;
  description: string;
  steps_total: number;
  default_variant: string;
};

export type SequenceState = {
  id: string;
  contact_id: string;
  template_key: string;
  status: string;
  current_step: number;
  steps_total: number;
  variant: string;
  last_sent_at: string | null;
  next_step_due_at: string | null;
  paused_reason: string | null;
  pain_point_key: string | null;
  frozen_pain_quote: string | null;
  frozen_reviewer_name: string | null;
  frozen_review_date: string | null;
};

export type ContactDetail = {
  contact: FirmContact;
  pain: {
    pain_quote: string | null;
    reviewer_name: string | null;
    review_date: string | null;
    pain_point_key: string | null;
  };
  sequence: SequenceState | null;
  sent_steps: Array<{
    id: string;
    message_type: string;
    subject: string;
    status: string;
    sent_at: string | null;
  }>;
};

export type SequenceRecommendation = {
  contact_id: string;
  pif_id: string;
  firm_name: string;
  contact_name: string;
  contact_email: string;
  contact_title: string;
  contact_source: string;
  persona: string;
  score: number;
  reason: string;
};

export type SequenceRecommendationResponse = {
  template_key: string;
  limit: number;
  recommended: SequenceRecommendation[];
  counts: Record<string, number>;
};

export const listSequenceTemplates = () =>
  get<SequenceTemplate[]>("/api/sequences/templates");

export const recommendSequenceContacts = (templateKey: string, limit = 50) =>
  get<SequenceRecommendationResponse>(
    `/api/sequences/recommendations?template_key=${encodeURIComponent(templateKey)}&limit=${limit}`,
  );

export const listFirmsWithContacts = () =>
  get<FirmWithContacts[]>("/api/firms/with-contacts");

export const listContactsForFirm = (pifId: string) =>
  get<FirmContact[]>(`/api/firms/${encodeURIComponent(pifId)}/contacts`);

export const getContactDetail = (contactId: string, templateKey?: string) => {
  const qs = templateKey ? `?template_key=${encodeURIComponent(templateKey)}` : "";
  return get<ContactDetail>(`/api/contacts/${encodeURIComponent(contactId)}${qs}`);
};

export const previewSequence = (contactId: string, templateKey?: string) => {
  const qs = templateKey ? `?template_key=${encodeURIComponent(templateKey)}` : "";
  return (
  get<RenderedSequenceStep[]>(
    `/api/contacts/${encodeURIComponent(contactId)}/sequence/preview${qs}`,
  ));
};

export const startSequence = (contactId: string, templateKey?: string) =>
  post<{
    sequence_id: string;
    template_key: string;
    variant: string;
    steps_total: number;
    next_step_due_at: string | null;
  }>(
    `/api/contacts/${encodeURIComponent(contactId)}/sequence/start`,
    { template_key: templateKey ?? "precise_pain_4step" },
  );

export type PauseResumeResponse = {
  sequence_id: string;
  status: string;
  paused_reason: string | null;
  next_step_due_at: string | null;
};

export const pauseSequence = (contactId: string, reason?: string, templateKey?: string) => {
  const qs = templateKey ? `?template_key=${encodeURIComponent(templateKey)}` : "";
  return (
  post<PauseResumeResponse>(
    `/api/contacts/${encodeURIComponent(contactId)}/sequence/pause${qs}`,
    { reason: reason ?? "" },
  ));
};

export const resumeSequence = (contactId: string, templateKey?: string) => {
  const qs = templateKey ? `?template_key=${encodeURIComponent(templateKey)}` : "";
  return (
  post<PauseResumeResponse>(
    `/api/contacts/${encodeURIComponent(contactId)}/sequence/resume${qs}`,
  ));
};

export type DeleteContactResult = {
  deleted: boolean;
  contact_id: string;
  sequences_deleted: number;
};

export const deleteContact = (contactId: string) =>
  del<DeleteContactResult>(
    `/api/contacts/${encodeURIComponent(contactId)}`,
  );

export type DeleteFirmResult = {
  deleted: boolean;
  pif_id: string;
  patients: number;
  cadence_entries: number;
  firm_reviews: number;
  firm_contacts: number;
  patient_call_state: number;
};

export const deleteFirm = (pifId: string) =>
  del<DeleteFirmResult>(`/api/firms/${encodeURIComponent(pifId)}`);

export const backfillFirmContacts = () =>
  post<{ firms: number; inserted: number; updated: number; skipped: number; errors: number }>(
    "/api/firm-contacts/backfill",
  );

export type SequenceListItem = {
  sequence_id: string;
  contact_id: string;
  contact_name: string;
  contact_email: string | null;
  pif_id: string;
  firm_name: string | null;
  template_key: string;
  status: string;
  current_step: number;
  steps_total: number;
  variant: string;
  last_sent_at: string | null;
  next_step_due_at: string | null;
  paused_reason: string | null;
};

export const listSequences = (status?: string) => {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return get<SequenceListItem[]>(`/api/sequences${qs}`);
};

// ---- Cybernetic lead generation loop ----
export type LeadGenPolicy = {
  version: string;
  label: string;
  target_metric: string;
  weights: Record<string, unknown>;
  suppressions: Record<string, unknown>;
  active: boolean;
  created_at: string | null;
};

export type LeadGenBatch = {
  id: string;
  name: string;
  target_metric: string;
  template_key: string;
  policy_version: string;
  status: string;
  counts: Record<string, number>;
  created_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type LeadGenBatchItem = {
  id: string;
  batch_id: string;
  contact_id: string;
  pif_id: string;
  firm_name: string;
  contact_name: string;
  contact_email: string;
  contact_title: string;
  persona: string;
  template_key: string;
  score: number;
  reason: Record<string, unknown>;
  approval_status: string;
  sequence_id: string | null;
  outcome: string | null;
  outcome_confidence: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type LeadGenObservation = {
  id: string;
  batch_id: string | null;
  batch_item_id: string | null;
  contact_id: string | null;
  pif_id: string | null;
  event_type: string;
  raw_event: Record<string, unknown>;
  classified_outcome: string | null;
  confidence: number | null;
  next_action: string | null;
  llm_reasoning: string | null;
  llm_model: string | null;
  created_at: string | null;
};

export type LeadGenBatchDetail = {
  batch: LeadGenBatch;
  items: LeadGenBatchItem[];
  observations: LeadGenObservation[];
};

export type LeadGenProposal = {
  id: string;
  source_batch_id: string | null;
  proposal_type: string;
  proposed_change: Record<string, unknown>;
  evidence: Record<string, unknown>;
  status: string;
  created_at: string | null;
};

export const getLeadGenPolicy = () =>
  get<LeadGenPolicy>("/api/lead-gen/policy/current");

export const createLeadGenBatch = (args: {
  name?: string;
  template_key: string;
  limit: number;
  created_by?: string;
}) => post<LeadGenBatchDetail>("/api/lead-gen/batches", args);

export const listLeadGenBatches = (args: { status?: string; limit?: number } = {}) => {
  const params = new URLSearchParams();
  if (args.status && args.status !== "all") params.set("status", args.status);
  if (args.limit) params.set("limit", String(args.limit));
  const qs = params.toString();
  return get<{ batches: LeadGenBatch[] }>(`/api/lead-gen/batches${qs ? `?${qs}` : ""}`);
};

export const getLeadGenBatch = (batchId: string, includeObservations = true) =>
  get<LeadGenBatchDetail>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}?include_observations=${includeObservations ? "true" : "false"}`,
  );

export const approveLeadGenBatch = (
  batchId: string,
  args: {
    approved_by?: string;
    start_sequences?: boolean;
    stagger_minutes?: number;
    scheduled_start_at?: string;
    scheduled_timezone?: string;
  },
) =>
  post<LeadGenBatchDetail>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/approve`,
    {
      approved_by: args.approved_by ?? "operator",
      start_sequences: args.start_sequences ?? false,
      stagger_minutes: args.stagger_minutes ?? 60,
      scheduled_start_at: args.scheduled_start_at,
      scheduled_timezone: args.scheduled_timezone ?? "America/Los_Angeles",
    },
  );

export const classifyLeadGenObservation = (args: {
  event_type: string;
  raw_event: Record<string, unknown>;
  batch_id?: string;
  contact_id?: string;
  batch_item_id?: string;
  model?: string;
}) => post<LeadGenObservation>("/api/lead-gen/observations/classify", args);

export const createLeadGenProposal = (batchId: string, createdBy = "operator") =>
  post<LeadGenProposal>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/proposal`,
    { created_by: createdBy },
  );


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

// ---- Outreach (blog-post campaigns, LLM-composed) -------------------------

export interface OutreachCampaign {
  id: number;
  name: string;
  post_slug: string;
  post_title: string;
  status: string;
  intent: string;
  sender_name: string;
  sender_email: string;
  bcc_email?: string | null;
  created_at: string;
}

export interface OutreachStats {
  campaign_id: number;
  total: number;
  pending: number;
  composed: number;
  sent: number;
  skipped: number;
  failed: number;
  opens: number;
  unique_opens: number;
  clicks: number;
  unique_clicks: number;
}

export interface OutreachCampaignDetail extends OutreachCampaign {
  post_url: string;
  post_description: string;
  post_category: string | null;
  post_tags: string[];
  post_excerpts: string[];
  sender_title: string | null;
  composer_model: string;
  notes: string | null;
  updated_at: string;
  stats: OutreachStats;
}

export interface OutreachSend {
  id: number;
  campaign_id: number;
  contact_id: string | null;
  pif_id: string | null;
  recipient_email: string;
  recipient_name: string | null;
  recipient_first_name: string | null;
  recipient_title: string | null;
  firm_name: string | null;
  token: string;
  status: string;
  composed_subject: string | null;
  composed_preheader: string | null;
  composed_body_html: string | null;
  composed_plaintext: string | null;
  composed_reasoning: string | null;
  composed_at: string | null;
  composer_model: string | null;
  edited_subject: string | null;
  edited_body_html: string | null;
  edited_plaintext: string | null;
  edited_by: string | null;
  edited_at: string | null;
  skip_reason: string | null;
  failure_reason: string | null;
  send_attempted_at: string | null;
  sent_at: string | null;
  message_id: string | null;
  transport: string | null;
  opens?: number;
  clicks?: number;
  last_event_at?: string | null;
}

export interface OutreachLinkEvent {
  id: number;
  send_id: number;
  recipient_email: string;
  kind: "open" | "click";
  url: string | null;
  ip: string | null;
  user_agent: string | null;
  ts: string;
}

export interface OutreachPreview {
  send_id: number;
  subject: string;
  full_html: string;
  full_plaintext: string;
  from_header: string;
  to: string;
  tracked_click_url: string;
  open_pixel_url: string;
}

export interface OutreachAudienceResult {
  added: number;
  skipped_no_email: number;
  skipped_duplicate: number;
  skipped_recent_outreach: number;
}

export const listOutreachCampaigns = (status?: string) => {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return get<OutreachCampaign[]>(`/api/outreach/campaigns${q}`);
};

export const getOutreachCampaign = (id: number) =>
  get<OutreachCampaignDetail>(`/api/outreach/campaigns/${id}`);

export const createOutreachCampaign = (body: {
  post_slug: string;
  name?: string;
  sender_email?: string;
  sender_name?: string;
  sender_title?: string;
  bcc_email?: string;
  intent?: string;
  notes?: string;
  with_excerpts?: boolean;
}) => post<OutreachCampaign>("/api/outreach/campaigns", body);

export const listOutreachBlogPosts = () =>
  get<{ slug: string }[]>("/api/outreach/blog-posts");

export const updateOutreachCampaignBcc = (
  campaignId: number,
  bcc_email: string | null,
) =>
  patch<OutreachCampaign>(`/api/outreach/campaigns/${campaignId}/bcc`, {
    bcc_email,
  });

export const addOutreachAudience = (
  campaignId: number,
  body: { contact_ids?: string[]; pif_ids?: string[]; exclude_recent_days?: number },
) =>
  post<OutreachAudienceResult>(
    `/api/outreach/campaigns/${campaignId}/audience`,
    body,
  );

export const listOutreachSends = (campaignId: number, status?: string) => {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return get<OutreachSend[]>(`/api/outreach/campaigns/${campaignId}/sends${q}`);
};

export const getNextOutreachSend = (campaignId: number) =>
  get<OutreachSend | null>(`/api/outreach/campaigns/${campaignId}/next`);

export const listOutreachEvents = (
  campaignId: number,
  opts?: { kind?: "open" | "click"; limit?: number },
) => {
  const params = new URLSearchParams();
  if (opts?.kind) params.set("kind", opts.kind);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const q = params.toString();
  return get<OutreachLinkEvent[]>(
    `/api/outreach/campaigns/${campaignId}/events${q ? `?${q}` : ""}`,
  );
};

export const composeOutreachSend = (sendId: number, regenerate = false) =>
  post<OutreachSend>(`/api/outreach/sends/${sendId}/compose`, {
    regenerate,
  });

export const previewOutreachSend = (sendId: number) =>
  get<OutreachPreview>(`/api/outreach/sends/${sendId}/preview`);

export const sendOutreachSend = (sendId: number) =>
  post<{ send_id: number; message_id: string; transport: string }>(
    `/api/outreach/sends/${sendId}/send`,
  );

export const skipOutreachSend = (sendId: number, reason: string) =>
  post<OutreachSend>(`/api/outreach/sends/${sendId}/skip`, { reason });

export const editOutreachSend = (
  sendId: number,
  body: { subject?: string; body_html?: string; plaintext?: string; by?: string },
) => post<OutreachSend>(`/api/outreach/sends/${sendId}/edit`, body);
