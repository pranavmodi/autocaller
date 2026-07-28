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

function publicApiOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "";
  if (!configured) return "";
  try {
    const url = new URL(configured);
    if (["localhost", "127.0.0.1", "::1"].includes(url.hostname)) {
      return "";
    }
    return configured;
  } catch {
    return "";
  }
}

export function apiUrl(path: string): string {
  // Use window.location origin in the browser so relative paths work
  // whether we're served from the same domain as the API or not.
  if (typeof window !== "undefined") {
    const configured = publicApiOrigin();
    if (configured) return `${configured}${path}`;
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

type ApiRequestOptions = {
  traceId?: string;
};

const TRACE_SESSION_KEY = "possible_os_trace_session_id";
let memoryTraceSessionId = "";

export function newProductTraceId(): string {
  const randomUuid =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
  return randomUuid.replace(/-/g, "").slice(0, 64);
}

export function getTraceSessionId(): string {
  if (typeof window === "undefined") {
    if (!memoryTraceSessionId) memoryTraceSessionId = newProductTraceId();
    return memoryTraceSessionId;
  }
  const existing = window.localStorage.getItem(TRACE_SESSION_KEY);
  if (existing) return existing;
  const sessionId = newProductTraceId();
  window.localStorage.setItem(TRACE_SESSION_KEY, sessionId);
  return sessionId;
}

function traceHeaders(options?: ApiRequestOptions): Record<string, string> {
  return {
    "x-possible-request-id": newProductTraceId(),
    "x-possible-trace-id": options?.traceId || newProductTraceId(),
  };
}

export type ProductTracePayload = {
  trace_id?: string;
  session_id?: string;
  request_id?: string;
  actor_type?: string;
  actor_id?: string;
  event_type: string;
  surface?: string;
  entity_type?: string;
  entity_id?: string;
  parent_trace_id?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  diff?: Record<string, unknown>;
  context?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type ProductTrace = {
  id: number;
  trace_id: string;
  session_id: string | null;
  request_id: string | null;
  actor_type: string;
  actor_id: string | null;
  event_type: string;
  surface: string;
  entity_type: string | null;
  entity_id: string | null;
  parent_trace_id: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  diff: Record<string, unknown>;
  context: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string | null;
};

export type Todo = {
  id: number;
  area: string;
  section: string;
  title: string;
  status: string;
  body: string;
  source_url: string | null;
  created_by: string | null;
  updated_by: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type TodoPayload = {
  title?: string;
  area?: string;
  section?: string;
  status?: string;
  body?: string;
  source_url?: string | null;
  actor?: string;
};

export const listTodos = (args: { area?: string; status?: string } = {}) => {
  const params = new URLSearchParams();
  if (args.area) params.set("area", args.area);
  if (args.status) params.set("status", args.status);
  const qs = params.toString();
  return get<{ todos: Todo[] }>(`/api/todos${qs ? `?${qs}` : ""}`);
};

export const createTodo = (payload: TodoPayload & { title: string }) =>
  post<{ todo: Todo }>("/api/todos", payload);

export const updateTodo = (id: number, payload: TodoPayload) =>
  patch<{ todo: Todo }>(`/api/todos/${id}`, payload);

export const deleteTodo = (id: number) =>
  del<{ deleted: boolean; id: number }>(`/api/todos/${id}`);

export function recordProductTrace(payload: ProductTracePayload): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();
  const traceId = payload.trace_id || newProductTraceId();
  const body = {
    actor_type: "user",
    surface: "frontend",
    ...payload,
    trace_id: traceId,
    session_id: payload.session_id || getTraceSessionId(),
  };
  return fetch(apiUrl("/api/traces"), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...traceHeaders({ traceId }),
    },
    body: JSON.stringify(body),
    credentials: "include",
    keepalive: true,
  })
    .then(() => undefined)
    .catch(() => undefined);
}

export const getProductTraces = (args?: {
  limit?: number;
  trace_id?: string;
  session_id?: string;
  event_type?: string;
  entity_type?: string;
  entity_id?: string;
}) => {
  const params = new URLSearchParams();
  if (args?.limit) params.set("limit", String(args.limit));
  if (args?.trace_id) params.set("trace_id", args.trace_id);
  if (args?.session_id) params.set("session_id", args.session_id);
  if (args?.event_type) params.set("event_type", args.event_type);
  if (args?.entity_type) params.set("entity_type", args.entity_type);
  if (args?.entity_id) params.set("entity_id", args.entity_id);
  const suffix = params.toString() ? `?${params}` : "";
  return get<{ traces: ProductTrace[] }>(`/api/traces${suffix}`);
};

export type ImprovementFinding = {
  id: string;
  finding_key: string;
  workflow: string;
  finding_type: string;
  summary: string;
  details: string;
  evidence_trace_ids: string[];
  evidence: Record<string, unknown>;
  severity: string;
  confidence: number | null;
  suggested_change: Record<string, unknown>;
  status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type EvalCase = {
  id: string;
  finding_id: string | null;
  workflow: string;
  name: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  status: string;
  created_at: string | null;
};

export type CodexTaskPacket = {
  id: string;
  finding_id: string | null;
  eval_case_id: string | null;
  title: string;
  status: string;
  packet_path: string | null;
  task_markdown: string;
  traces: ProductTrace[];
  eval_cases: EvalCase[];
  relevant_files: string[];
  validation_commands: string[];
  created_at: string | null;
  exported_at: string | null;
};

export type AgentTask = {
  id: string;
  parent_task_id: string | null;
  assigned_agent: string;
  title: string;
  objective: string;
  context: Record<string, unknown>;
  allowed_tools: unknown[];
  forbidden_actions: unknown[];
  expected_output_schema: Record<string, unknown>;
  acceptance_criteria: unknown[];
  verification_commands: unknown[];
  artifacts: unknown[];
  risk_level: string;
  requires_human_approval: boolean;
  status: string;
  priority: number;
  heartbeat_interval_seconds: number;
  last_heartbeat_at: string | null;
  claimed_at: string | null;
  deadline_at: string | null;
  completed_at: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AgentTaskEvent = {
  id: number;
  task_id: string | null;
  agent_id: string;
  event_type: string;
  message: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string | null;
};

export type AgentTaskEventSummary = {
  id: number;
  task_id: string | null;
  agent_id: string;
  event_type: string;
  message: string;
  summary: string;
  has_payload: boolean;
  payload_size_bytes: number;
  created_at: string | null;
};

export type AgentReport = {
  id: string;
  task_id: string | null;
  agent_id: string;
  status: string;
  summary: string;
  key_findings: unknown[];
  actions_taken: unknown[];
  artifacts: unknown[];
  evidence: unknown[];
  verification: unknown[];
  risks: unknown[];
  open_questions: unknown[];
  recommended_next_actions: unknown[];
  created_at: string | null;
};

export type AgentCapability = {
  id: string;
  name: string;
  capability_type: string;
  source: string;
  purpose: string;
  risk_level: string;
  requires_approval: boolean;
  autonomous_allowed: boolean;
  command: Record<string, unknown>;
  metadata: Record<string, unknown>;
  last_verified_at: string | null;
  last_status: string;
  created_at: string | null;
  updated_at: string | null;
};

export type MasterGoal = {
  id: string;
  status: string;
  goal: string;
  why: string;
  time_horizon: string;
  success_metric: string;
  next_actions: string[];
  source: Record<string, unknown>;
  confidence: string;
  created_by: string;
  created_at: string | null;
  expires_at: string | null;
};

export type MasterHeartbeat = {
  status: string;
  started_at: string;
  completed_at: string;
  active_task_count: number;
  queued_task_count: number;
  blocked_task_count: number;
  stale_task_ids: string[];
  heartbeat_enabled: boolean;
  heartbeat_interval_seconds: number;
  human_status?: {
    state?: string;
    goal?: string;
    current_focus?: string;
    intended_next_steps?: string[];
    needs_from_user?: string;
    confidence?: string;
  };
  objective_status?: {
    active_goal_id?: string | null;
    goal?: string;
    status?: string;
    evidence?: unknown[];
    remaining_work?: string[];
    next_best_action?: string;
  };
  wake_context?: Record<string, unknown>;
  tool_loop?: Record<string, unknown>;
  status_llm?: {
    used_llm?: boolean;
    model?: string;
    skill_path?: string;
    error?: string;
    disabled?: boolean;
    raw_response?: string;
    cached_tokens?: number | null;
    usage?: Record<string, unknown>;
    prompt_cache?: Record<string, unknown>;
  };
  auto_executed_lead_gen_sends?: Record<string, unknown>;
  tool_runner?: Record<string, unknown>;
  active_goal?: MasterGoal | null;
  queue_analysis?: Record<string, unknown>;
  soul: Record<string, unknown>;
  next_recommended_slice: string;
};

export type AgentsStatus = {
  heartbeat_enabled: boolean;
  heartbeat_interval_seconds: number;
  tool_runner_enabled: boolean;
  tool_runner_max_iterations: number;
  tool_runner_max_runtime_seconds: number;
  tool_runner_persist_continuation: boolean;
  auto_execute_approved_lead_gen_email_enabled: boolean;
  auto_execute_approved_lead_gen_email_limit: number;
  last_heartbeat: MasterHeartbeat | null;
};

export const getAgentsStatus = () => get<AgentsStatus>("/api/agents/status");

export const updateAgentConfig = (payload: {
  heartbeat_enabled?: boolean;
  heartbeat_interval_seconds?: number;
  tool_runner_enabled?: boolean;
  tool_runner_max_iterations?: number;
  tool_runner_max_runtime_seconds?: number;
  tool_runner_persist_continuation?: boolean;
  auto_execute_approved_lead_gen_email_enabled?: boolean;
  auto_execute_approved_lead_gen_email_limit?: number;
}) =>
  patch<{ config: {
    heartbeat_enabled: boolean;
    heartbeat_interval_seconds: number;
    tool_runner_enabled: boolean;
    tool_runner_max_iterations: number;
    tool_runner_max_runtime_seconds: number;
    tool_runner_persist_continuation: boolean;
    auto_execute_approved_lead_gen_email_enabled: boolean;
    auto_execute_approved_lead_gen_email_limit: number;
  } }>(
    "/api/agents/config",
    {
      ...payload,
      actor: "operator",
    },
  );

export const runMasterHeartbeat = () =>
  post<{ heartbeat: MasterHeartbeat }>("/api/agents/heartbeat/run");

export const listAgentTasks = (args?: {
  status?: string;
  assigned_agent?: string;
  limit?: number;
}) => {
  const params = new URLSearchParams();
  if (args?.status && args.status !== "all") params.set("status", args.status);
  if (args?.assigned_agent) params.set("assigned_agent", args.assigned_agent);
  if (args?.limit) params.set("limit", String(args.limit));
  const suffix = params.toString() ? `?${params}` : "";
  return get<{ tasks: AgentTask[] }>(`/api/agents/tasks${suffix}`);
};

export const getAgentTask = (taskId: string) =>
  get<{ task: AgentTask; events: AgentTaskEvent[]; reports: AgentReport[] }>(
    `/api/agents/tasks/${encodeURIComponent(taskId)}`,
  );

export const getAgentEvent = (eventId: number) =>
  get<{ event: AgentTaskEvent }>(`/api/agents/events/${encodeURIComponent(eventId)}`);

export const listAgentEvents = (args?: { task_id?: string; limit?: number }) => {
  const params = new URLSearchParams();
  if (args?.task_id) params.set("task_id", args.task_id);
  if (args?.limit) params.set("limit", String(args.limit));
  const suffix = params.toString() ? `?${params}` : "";
  return get<{ events: AgentTaskEventSummary[] }>(`/api/agents/events${suffix}`);
};

export const createResearchScoutTask = () =>
  post<{ task: AgentTask }>("/api/agents/tasks/research-scout");

export const createSystemsHealthTask = () =>
  post<{ task: AgentTask }>("/api/agents/tasks/systems-health");

export const runSystemsHealthTask = (taskId?: string) => {
  const suffix = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
  return post<{ report: AgentReport | null }>(`/api/agents/tasks/systems-health/run${suffix}`);
};

export const listAgentCapabilities = (args?: { limit?: number }) => {
  const params = new URLSearchParams();
  if (args?.limit) params.set("limit", String(args.limit));
  const suffix = params.toString() ? `?${params}` : "";
  return get<{ capabilities: AgentCapability[] }>(`/api/agents/capabilities${suffix}`);
};

export const refreshAgentCapabilities = (probe = true) =>
  post<{ capabilities: AgentCapability[] }>(`/api/agents/capabilities/refresh?probe=${probe ? "true" : "false"}`);

export const listMasterGoals = (args?: { status?: string; limit?: number }) => {
  const params = new URLSearchParams();
  if (args?.status && args.status !== "all") params.set("status", args.status);
  if (args?.limit) params.set("limit", String(args.limit));
  const suffix = params.toString() ? `?${params}` : "";
  return get<{ goals: MasterGoal[] }>(`/api/agents/goals${suffix}`);
};

export const updateAgentTaskStatus = (
  taskId: string,
  status: string,
  message = "",
) =>
  patch<{ task: AgentTask }>(`/api/agents/tasks/${encodeURIComponent(taskId)}/status`, {
    status,
    message,
    actor: "operator",
  });

export type LearningMeasurementWindow = {
  days: number;
  since: string;
  until: string;
  manual_edit_rate: number | null;
  edited_draft_count: number;
  reviewed_draft_count: number;
  bounce_rate: number | null;
  bounced_email_count: number;
  failed_email_count: number;
  sent_email_count: number;
  reply_rate: number | null;
  matched_reply_count: number;
  all_inbound_email_count: number;
  booked_qualified_conversation_count: number;
  consult_booking_count: number;
  qualified_observation_count: number;
};

export type LearningMeasurements = {
  generated_at: string;
  windows: LearningMeasurementWindow[];
  definitions: Record<string, string>;
};

export const getImprovementFindings = (args?: {
  status?: string;
  workflow?: string;
  limit?: number;
}) => {
  const params = new URLSearchParams();
  if (args?.status) params.set("status", args.status);
  if (args?.workflow) params.set("workflow", args.workflow);
  if (args?.limit) params.set("limit", String(args.limit));
  const suffix = params.toString() ? `?${params}` : "";
  return get<{ findings: ImprovementFinding[] }>(`/api/learning/findings${suffix}`);
};

export const getLearningMeasurements = () =>
  get<LearningMeasurements>("/api/learning/measurements");

export const analyzeLearningFindings = (limit = 500) =>
  post<{ created_or_updated_count: number; findings: ImprovementFinding[] }>(
    "/api/learning/analyze",
    { limit },
  );

export const syncLearningOutcomes = (limit = 100) =>
  post<{ created_count: number; limit: number }>("/api/learning/sync-outcomes", {
    limit,
  });

export const reviewImprovementFinding = (
  findingId: string,
  status: "proposed" | "accepted" | "rejected" | "implemented",
) =>
  post<{ finding: ImprovementFinding }>(
    `/api/learning/findings/${encodeURIComponent(findingId)}/review`,
    { status, reviewed_by: "operator" },
  );

export const createEvalCaseForFinding = (findingId: string) =>
  post<{ eval_case: EvalCase }>(
    `/api/learning/findings/${encodeURIComponent(findingId)}/eval-case`,
  );

export const getEvalCases = (limit = 100) =>
  get<{ eval_cases: EvalCase[] }>(`/api/learning/eval-cases?limit=${limit}`);

export const createTaskPacketForFinding = (findingId: string) =>
  post<{ task_packet: CodexTaskPacket }>(
    `/api/learning/findings/${encodeURIComponent(findingId)}/task-packet`,
  );

export const getTaskPackets = (limit = 100) =>
  get<{ task_packets: CodexTaskPacket[] }>(`/api/learning/task-packets?limit=${limit}`);

export type ClickAnalyticsGroupBy =
  | "app_name"
  | "source"
  | "firm_name"
  | "contact"
  | "persona"
  | "pif_id"
  | "batch_item"
  | "day";

export type ClickAnalyticsGroup = {
  key: string;
  label: string;
  click_count: number;
  contact_count: number;
  firm_count: number;
  first_clicked_at: string | null;
  last_clicked_at: string | null;
};

export type ClickAnalyticsRow = {
  id: string;
  clicked_at: string | null;
  app_name: string;
  source: string;
  source_label: string;
  firm_name: string;
  contact_name: string;
  contact_email: string;
  persona: string;
  pif_id: string | null;
  batch_item_id: string | null;
  ip: string | null;
  user_agent: string | null;
};

export type HumanSessionsByPageRow = {
  page: string;
  sessions: number;
  distinct_sessions: number;
  median_time_on_page_ms: number | null;
};

export type HumanSessionsByDayRow = {
  day: string;
  distinct_sessions: number;
};

export type ClickAnalyticsResponse = {
  since_days: number;
  source?: string | null;
  group_by: ClickAnalyticsGroupBy;
  group_label: string;
  available_groups: Array<{ key: ClickAnalyticsGroupBy; label: string }>;
  summary: {
    click_count: number;
    contact_count: number;
    firm_count: number;
    first_clicked_at: string | null;
    last_clicked_at: string | null;
    human_session_count?: number;
    distinct_human_sessions?: number;
    human_to_click_ratio?: number;
  };
  human_sessions_by_page?: HumanSessionsByPageRow[];
  human_sessions_by_day?: HumanSessionsByDayRow[];
  groups: ClickAnalyticsGroup[];
  recent_clicks: ClickAnalyticsRow[];
};

export const getClickAnalytics = (args: {
  sinceDays?: number;
  groupBy?: ClickAnalyticsGroupBy;
  limit?: number;
  source?: string;
} = {}) => {
  const params = new URLSearchParams();
  params.set("since_days", String(args.sinceDays ?? 30));
  params.set("group_by", args.groupBy ?? "firm_name");
  params.set("limit", String(args.limit ?? 50));
  if (args.source) params.set("source", args.source);
  return get<ClickAnalyticsResponse>(`/api/aiaudit/click-analytics?${params.toString()}`);
};

export type WorkshopTrackingContact = {
  contact_id: string;
  contact_name: string;
  contact_email: string;
  title: string;
  linkedin_url: string;
  firm_name: string;
  source: string;
  tracking_link_created_at: string | null;
  raw_link_clicks: number;
  scanner_link_clicks: number;
  sessions: number;
  confirmed_sessions: number;
  scanner_or_suspect_sessions: number;
  prompt_reveals: number;
  on_page_clicks: number;
  scroll_50: number;
  max_time_on_page_ms: number;
  last_activity_at: string | null;
  status: "Prompt revealed" | "Engaged" | "Visited" | "Scanner / suspect only" | "No activity";
};

export type WorkshopTrackingActivity = {
  id: string;
  contact_id: string;
  contact_name: string;
  firm_name: string;
  occurred_at: string | null;
  event: string;
  label: string;
  detail: string;
  quality: "human" | "scanner" | "suspect";
  page: string;
  session_id: string | null;
  time_on_page_ms: number | null;
  user_agent: string | null;
};

export type WorkshopClickAnalyticsResponse = {
  since_days: number;
  summary: {
    tracked_contacts: number;
    raw_link_clicks: number;
    scanner_link_clicks: number;
    confirmed_visitors: number;
    scanner_or_suspect_sessions: number;
    prompt_reveals: number;
    on_page_clicks: number;
    last_activity_at: string | null;
  };
  contacts: WorkshopTrackingContact[];
  activities: WorkshopTrackingActivity[];
};

export const getWorkshopClickAnalytics = (args: {
  sinceDays?: number;
  limit?: number;
} = {}) => {
  const params = new URLSearchParams();
  params.set("since_days", String(args.sinceDays ?? 30));
  params.set("limit", String(args.limit ?? 250));
  return get<WorkshopClickAnalyticsResponse>(
    `/api/aiaudit/workshop-click-analytics?${params.toString()}`,
  );
};

export type DataReturnedEvent = {
  id: number;
  payload: Record<string, unknown> | unknown[];
  headers: Record<string, string>;
  source_ip: string | null;
  user_agent: string | null;
  content_type: string | null;
  received_at: string | null;
};

export type DataReturnedResponse = {
  events: DataReturnedEvent[];
  total: number;
};

export const getDataReturnedEvents = (limit = 100) =>
  get<DataReturnedResponse>(`/api/datareturned?limit=${limit}`);

export async function getDataReturnedScript(): Promise<string> {
  const path = "/datareturned/script";
  const res = await fetch(apiUrl(path), { credentials: "include" });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`GET ${path} 401`);
  }
  if (!res.ok) throw new Error(`GET ${path} ${res.status}`);
  return res.text();
}

export type DataReturnedScriptConfig = {
  script: string;
  enabled: boolean;
  customized: boolean;
  updated_at: string | null;
};

export const getDataReturnedScriptConfig = () =>
  get<DataReturnedScriptConfig>("/api/datareturned/script");

export const saveDataReturnedScript = (script: string) =>
  put<DataReturnedScriptConfig>("/api/datareturned/script", { script });

export const setDataReturnedScriptEnabled = (enabled: boolean) =>
  put<DataReturnedScriptConfig>("/api/datareturned/script/enabled", { enabled });

async function get<T>(path: string, options?: ApiRequestOptions): Promise<T> {
  const res = await fetch(apiUrl(path), {
    credentials: "include",
    headers: traceHeaders(options),
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`GET ${path} 401`);
  }
  if (!res.ok) throw new Error(`GET ${path} ${res.status}`);
  return res.json();
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    if (data?.detail) return JSON.stringify(data.detail);
  } catch {
    try {
      return await res.text();
    } catch {
      return "";
    }
  }
  return "";
}

async function post<T>(
  path: string,
  body?: unknown,
  options?: ApiRequestOptions,
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: body
      ? { "content-type": "application/json", ...traceHeaders(options) }
      : traceHeaders(options),
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`POST ${path} 401`);
  }
  if (!res.ok) {
    const detail = await errorDetail(res);
    throw new Error(`POST ${path} ${res.status}${detail ? ` - ${detail}` : ""}`);
  }
  return res.json();
}

async function put<T>(
  path: string,
  body: unknown,
  options?: ApiRequestOptions,
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "PUT",
    headers: { "content-type": "application/json", ...traceHeaders(options) },
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

async function patch<T>(
  path: string,
  body: unknown,
  options?: ApiRequestOptions,
): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "PATCH",
    headers: { "content-type": "application/json", ...traceHeaders(options) },
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

async function del<T>(path: string, options?: ApiRequestOptions): Promise<T> {
  const res = await fetch(apiUrl(path), {
    method: "DELETE",
    credentials: "include",
    headers: traceHeaders(options),
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

// Durable operator notifications — drives global action modals.
export type OperatorNotification = {
  id: number;
  notification_type: string;
  priority: string;
  title: string;
  body: string;
  source_type: string;
  source_id: string;
  stimulus: {
    from_email?: string;
    from_name?: string | null;
    subject?: string;
    text_excerpt?: string;
    body_text?: string;
    received_at?: string | null;
    [key: string]: unknown;
  };
  context: {
    firm_name?: string;
    contact_name?: string;
    contact_email?: string;
    contact_title?: string | null;
    batch_id?: string;
    batch_item_id?: string;
    sequence_id?: string;
    sequence_status?: string | null;
    lead_gen_observation_id?: string;
    [key: string]: unknown;
  };
  suggested_action: {
    kind?: string;
    label?: string;
    outcome?: string;
    confidence?: number;
    reasoning?: string;
    signals?: string[];
    requires_human_review?: boolean;
    draft_subject?: string;
    draft_body?: string;
    href?: string;
    [key: string]: unknown;
  };
  status: string;
  created_at: string | null;
  updated_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
};

export const getPendingOperatorNotifications = (limit = 10) =>
  get<{ pending: OperatorNotification[] }>(
    `/api/operator-notifications/pending?limit=${encodeURIComponent(String(limit))}`,
  );

export const acknowledgeOperatorNotification = (id: number, options?: ApiRequestOptions) =>
  post<{ notification: OperatorNotification }>(
    `/api/operator-notifications/${id}/acknowledge`,
    { acknowledged_by: "operator" },
    options,
  );

export const sendOperatorNotificationDraft = (
  id: number,
  args: { subject?: string; body?: string; sent_by?: string },
  options?: ApiRequestOptions,
) =>
  post<{ notification: OperatorNotification }>(
    `/api/operator-notifications/${id}/send-draft`,
    {
      subject: args.subject,
      body: args.body,
      sent_by: args.sent_by ?? "operator",
    },
    options,
  );

export type AgentAction = {
  id: string;
  action_type: string;
  status: string;
  risk_level: string;
  requested_by: string;
  approved_by: string | null;
  entity_type: string | null;
  entity_id: string | null;
  input: Record<string, unknown>;
  policy_result: Record<string, unknown>;
  execution_result: Record<string, unknown>;
  error: string | null;
  trace_id: string | null;
  scheduled_for: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export const listAgentActions = (args: {
  status?: string;
  action_type?: string;
  scheduled?: boolean;
  limit?: number;
} = {}) => {
  const params = new URLSearchParams();
  if (args.status) params.set("status", args.status);
  if (args.action_type) params.set("action_type", args.action_type);
  if (args.scheduled) params.set("scheduled", "true");
  if (args.limit) params.set("limit", String(args.limit));
  const qs = params.toString();
  return get<{ actions: AgentAction[]; pending_scheduled_count: number }>(
    `/api/actions${qs ? `?${qs}` : ""}`,
  );
};

// ---- SEO and Agent Optimization ----
export type SeoAuditAction = {
  id: string;
  action_type: string;
  priority: "high" | "normal" | "low" | string;
  title: string;
  rationale: string;
  suggested_change: string;
  category: string;
  page_url: string;
};

export type SeoAuditPage = {
  url: string;
  status_code: number | null;
  title: string;
  description: string;
  canonical: string;
  h1: string[];
  h2: string[];
  word_count: number;
  internal_link_count: number;
  consult_link_count: number;
  schema_count: number;
  missing_image_alt_count: number;
  seo_score: number;
  aeo_score: number;
  score: number;
  issues: string[];
  opportunities: string[];
  actions: SeoAuditAction[];
};

export type SeoAudit = {
  site_url: string;
  generated_at: string;
  summary: {
    page_count: number;
    avg_seo_score: number;
    avg_aeo_score: number;
    avg_score: number;
    issue_counts: Record<string, number>;
    action_count: number;
    high_priority_action_count: number;
    top_actions: SeoAuditAction[];
  };
  pages: SeoAuditPage[];
  actions: SeoAuditAction[];
};

export const getSeoAudit = (args?: { site_url?: string; limit?: number }) => {
  const params = new URLSearchParams();
  if (args?.site_url) params.set("site_url", args.site_url);
  if (args?.limit) params.set("limit", String(args.limit));
  const suffix = params.toString() ? `?${params}` : "";
  return get<SeoAudit>(`/api/seo/audit${suffix}`);
};

export const generateSeoActions = (args?: {
  site_url?: string;
  limit?: number;
  action_limit?: number;
}) =>
  post<{ created_count: number; created: Array<{ notification_id: number; status: string; action: SeoAuditAction }>; audit: SeoAudit }>(
    "/api/seo/actions",
    {
      site_url: args?.site_url,
      limit: args?.limit ?? 20,
      action_limit: args?.action_limit ?? 20,
    },
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
  reasoning?: string | null;
  angle?: string | null;
  cta?: string | null;
  blog_link_used?: string | null;
  model?: string | null;
  composer_experiment_key?: string | null;
  composer_variant_key?: string | null;
  skill_path?: string | null;
  skill_sha256?: string | null;
  requires_human_review?: boolean;
  risk_flags?: string[];
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

export const previewSequence = (
  contactId: string,
  templateKey?: string,
  options: {
    notificationId?: number | string | null;
    sourceId?: string | null;
    composerVariantKey?: string | null;
  } = {},
) => {
  const params = new URLSearchParams();
  if (templateKey) params.set("template_key", templateKey);
  if (options.notificationId) params.set("notification_id", String(options.notificationId));
  if (options.sourceId) params.set("source_id", options.sourceId);
  if (options.composerVariantKey) params.set("composer_variant_key", options.composerVariantKey);
  const qs = params.toString() ? `?${params.toString()}` : "";
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
    { template_key: templateKey ?? "possible_minds_dynamic" },
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
  daily_send_budget: number;
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
  counts: Record<string, unknown>;
  experiment_status?: string;
  experiment?: LeadGenExperimentSummary;
  created_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type LeadGenExperimentSummary = {
  status: string;
  card: Record<string, unknown>;
  is_experiment: boolean;
  is_ready: boolean;
  missing_fields: string[];
  updated_at: string | null;
  closed_at: string | null;
};

export type LeadGenExperimentListItem = {
  batch_id: string;
  batch_name: string;
  batch_status: string;
  created_at: string | null;
  approved_at: string | null;
  experiment: LeadGenExperimentSummary;
};

export type LeadGenExperimentRollup = {
  batch_id: string;
  experiment: LeadGenExperimentSummary;
  measurement: Record<string, number>;
  event_counts: Record<string, number>;
  signal_quality: {
    clicks: Record<string, number>;
    observations: Record<string, number>;
    replies: Record<string, number>;
  };
  groups: {
    by_transport: Array<Record<string, string | number>>;
    by_persona: Array<Record<string, string | number>>;
    by_variant: Array<Record<string, string | number>>;
  };
  data_quality: Record<string, unknown>;
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
  linkedin_url: string | null;
  persona: string;
  template_key: string;
  score: number;
  reason: Record<string, unknown>;
  approval_status: string;
  sequence_id: string | null;
  outcome: string | null;
  outcome_confidence: number | null;
  predicted_transport: {
    channel: "zoho_api" | "resend" | "over_budget" | string;
    scheduled_for: string | null;
    sent_at?: string | null;
    action_id?: string | null;
    status?: string | null;
  } | null;
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

export type LeadGenDailyRun = {
  id: string;
  run_date: string | null;
  status: string;
  stage: string;
  stages: Record<string, Record<string, unknown>>;
  batch_id: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  dry_run?: boolean;
};

export type LeadGenThroughputHeldFirm = {
  pif_id: string;
  firm_name: string;
  rank: number;
  warm_score: number | null;
  persona: string;
  contact_name: string;
  contact_email: string;
  has_raw_reviews: boolean;
  has_usable_evidence: boolean;
  evidence_status?: "none" | "extracting" | "extracted_no_usable" | "usable";
  evidence_detail?: string;
  held_reason: string;
};

export type LeadGenThroughput = {
  run_date: string;
  run_status: string;
  batch_id: string | null;
  target: number;
  auto_send_on: boolean;
  provider_transport?: {
    strategy: string;
    available: boolean;
    providers: {
      transport: string;
      configured: boolean;
      sent_today: number;
      cap: number;
      remaining: number;
      available: boolean;
    }[];
  };
  history: {
    yesterday_sent: number;
    seven_day_sent: number;
  };
  funnel: {
    selected: number;
    with_evidence: number;
    composed: number;
    sending_today: number;
    sent_today: number;
    held: number;
  };
  verdict: {
    will_hit_target: boolean;
    shortfall: number;
    blocker: "none" | "no_review_evidence" | "below_target" | string;
  };
  held_firms: LeadGenThroughputHeldFirm[];
};

export type LeadGenSendPlanItem = {
  action_id: string;
  action_status: string;
  batch_id: string;
  batch_name: string;
  batch_item_id: string;
  contact_id: string;
  pif_id: string;
  firm_name: string;
  contact_name: string;
  contact_email: string;
  contact_title: string;
  persona: string;
  linkedin_url: string | null;
  action_type: string;
  subject: string | null;
  composer_variant_key: string | null;
  scheduled_for: string | null;
  scheduled_for_pt: string | null;
  sent_at: string | null;
  sent_at_pt: string | null;
  transport: string | null;
  channel: string | null;
  message_id: string | null;
  email_log_status: string | null;
};

export type LeadGenSendPlan = {
  date: string;
  timezone: string;
  summary: {
    sent: number;
    scheduled: number;
    total: number;
  };
  items: LeadGenSendPlanItem[];
};

export const getLeadGenPolicy = () =>
  get<LeadGenPolicy>("/api/lead-gen/policy/current");

export const updateLeadGenDailySendBudget = (
  budget: number,
  resendDailyBudget?: number,
) =>
  put<{
    daily_send_budget: number;
    policy_version: string;
    weights: Record<string, unknown>;
  }>("/api/lead-gen/settings/daily-send-budget", {
    budget,
    resend_daily_budget: resendDailyBudget,
    updated_by: "operator",
  });

export const createLeadGenBatch = (args: {
  name?: string;
  template_key: string;
  limit: number;
  created_by?: string;
}) => post<LeadGenBatchDetail>("/api/lead-gen/batches", args);

export const createLeadGenEmailAgentSlice = (args: {
  limit?: number;
  template_key?: string;
  created_by?: string;
  composer_variant_key?: string | null;
  approve_actions?: boolean;
  policy_check_first_action?: boolean;
}) => post<LeadGenBatchDetail & {
  drafts: Array<Record<string, unknown>>;
  action_ids: string[];
  first_policy: Record<string, unknown> | null;
  no_email_sent: boolean;
}>("/api/lead-gen/email-agent/slice", args);

export const runLeadGenDaily = (
  args: { dry_run?: boolean; force?: boolean; composer_variant_key?: string } = {},
) =>
  post<LeadGenDailyRun>("/api/lead-gen/daily-run", {
    dry_run: args.dry_run ?? false,
    force: args.force ?? false,
    created_by: "operator",
    composer_variant_key: args.composer_variant_key || null,
  });

export const listLeadGenDailyRuns = (limit = 5) =>
  get<{ runs: LeadGenDailyRun[] }>(`/api/lead-gen/daily-runs?limit=${limit}`);

export const getLeadGenThroughput = (runDate?: string) => {
  const qs = runDate ? `?run_date=${encodeURIComponent(runDate)}` : "";
  return get<LeadGenThroughput>(`/api/lead-gen/daily-run/throughput${qs}`);
};

export const getLeadGenSendPlan = (sendDate?: string) => {
  const qs = sendDate ? `?send_date=${encodeURIComponent(sendDate)}` : "";
  return get<LeadGenSendPlan>(`/api/lead-gen/send-plan${qs}`);
};

export const getLeadGenDailyEnabled = () =>
  get<{ enabled: boolean; key: string }>("/api/lead-gen/daily-run/enabled");

export const setLeadGenDailyEnabled = (enabled: boolean) =>
  put<{ enabled: boolean; key: string }>("/api/lead-gen/daily-run/enabled", { enabled });

export const listLeadGenBatches = (args: { status?: string; limit?: number } = {}) => {
  const params = new URLSearchParams();
  if (args.status && args.status !== "all") params.set("status", args.status);
  if (args.limit) params.set("limit", String(args.limit));
  const qs = params.toString();
  return get<{ batches: LeadGenBatch[] }>(`/api/lead-gen/batches${qs ? `?${qs}` : ""}`);
};

export const listLeadGenExperiments = (args: { status?: string; limit?: number } = {}) => {
  const params = new URLSearchParams();
  if (args.status && args.status !== "all") params.set("status", args.status);
  if (args.limit) params.set("limit", String(args.limit));
  const qs = params.toString();
  return get<{ experiments: LeadGenExperimentListItem[] }>(
    `/api/lead-gen/experiments${qs ? `?${qs}` : ""}`,
  );
};

export const getLeadGenBatch = (batchId: string, includeObservations = true) =>
  get<LeadGenBatchDetail>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}?include_observations=${includeObservations ? "true" : "false"}`,
  );

export const getLeadGenExperimentRollup = (batchId: string) =>
  get<LeadGenExperimentRollup>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/experiment-rollup`,
  );

export const updateLeadGenBatchExperiment = (
  batchId: string,
  card: Record<string, unknown>,
  actor = "operator",
) =>
  put<{ batch_id: string; experiment: LeadGenExperimentSummary }>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/experiment`,
    { actor, card },
  );

export const closeLeadGenBatchExperiment = (
  batchId: string,
  args: {
    verdict: string;
    learning: string;
    why: string;
    next_hypothesis: string;
    next_recommended_wave: string;
    confidence_note: string;
    superseded?: boolean;
    actor?: string;
  },
) =>
  post<{ batch_id: string; experiment: LeadGenExperimentSummary }>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/experiment/close`,
    {
      actor: args.actor ?? "operator",
      verdict: args.verdict,
      learning: args.learning,
      why: args.why,
      next_hypothesis: args.next_hypothesis,
      next_recommended_wave: args.next_recommended_wave,
      confidence_note: args.confidence_note,
      superseded: args.superseded ?? false,
    },
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
      scheduled_timezone: args.scheduled_timezone ?? "Asia/Kolkata",
    },
  );

export type ResolveBatchLinkedInResult = {
  batch_id: string;
  only_decision_makers: boolean;
  force: boolean;
  limit: number;
  results: {
    contact_id: string;
    contact_name: string;
    contact_title: string;
    status: string;
    linkedin_url?: string | null;
  }[];
  summary: {
    resolved: number;
    not_found: number;
    skipped: number;
    errors: number;
    attempted: number;
    limited_to: number;
    eligible: number;
  };
};

export const resolveLeadGenBatchLinkedIn = (
  batchId: string,
  args: { force?: boolean; only_decision_makers?: boolean; limit?: number } = {},
) =>
  post<ResolveBatchLinkedInResult>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/resolve-linkedin`,
    {
      force: args.force ?? false,
      only_decision_makers: args.only_decision_makers ?? false,
      limit: args.limit ?? 25,
    },
  );

export const approveLeadGenBatchActions = (
  batchId: string,
  args: { approved_by?: string } = {},
) =>
  post<{ batch_id: string; approved_count: number; approved_action_ids: string[]; skipped: { action_id: string; reason: string }[] }>(
    `/api/lead-gen/batches/${encodeURIComponent(batchId)}/approve-actions`,
    { approved_by: args.approved_by ?? "operator" },
  );

export const sendLeadGenBatchItemDraft = (
  batchItemId: string,
  args: {
    subject: string;
    body: string;
    sent_by?: string;
    composer_experiment_key?: string | null;
    composer_variant_key?: string | null;
    skill_path?: string | null;
    skill_sha256?: string | null;
  },
) =>
  post<{
    batch_item_id: string;
    sequence_id?: string;
    sent_to: string;
    sent_subject: string;
    sent_message_id: string;
    sent_at: string;
    step?: number;
    mode?: string;
    message_type?: string;
    agent_action?: Record<string, unknown>;
    agent_action_policy?: Record<string, unknown>;
    composer_experiment_key?: string | null;
    composer_variant_key?: string | null;
  }>(
    `/api/lead-gen/batch-items/${encodeURIComponent(batchItemId)}/send-draft`,
    {
      subject: args.subject,
      body: args.body,
      sent_by: args.sent_by ?? "operator",
      composer_experiment_key: args.composer_experiment_key,
      composer_variant_key: args.composer_variant_key,
      skill_path: args.skill_path,
      skill_sha256: args.skill_sha256,
    },
  );

export const recomposeLeadGenBatchItemDraft = (
  batchItemId: string,
  args: {
    actor?: string;
    composer_variant_key?: string | null;
  } = {},
) =>
  post<{
    batch_item_id: string;
    draft: Record<string, unknown> | null;
    action?: Record<string, unknown> | null;
    updated_existing?: boolean;
    created?: boolean;
    scheduled_for_pt?: string | null;
    scheduled_for_utc?: string | null;
  }>(
    `/api/lead-gen/batch-items/${encodeURIComponent(batchItemId)}/recompose-draft`,
    {
      actor: args.actor ?? "operator",
      composer_variant_key: args.composer_variant_key ?? undefined,
    },
  );

export type BatchItemVariantDraft = {
  variant_key: string;
  label: string;
  is_baseline?: boolean;
  subject?: string;
  body?: string;
  angle?: string;
  cta?: string;
  reasoning?: string;
  requires_human_review?: boolean;
  error?: string;
};

export const composeBatchItemVariants = (batchItemId: string) =>
  post<{ batch_item_id: string; selected_variant_key: string | null; variants: BatchItemVariantDraft[] }>(
    `/api/lead-gen/batch-items/${encodeURIComponent(batchItemId)}/compose-variants`,
    {},
  );

export const selectBatchItemVariant = (batchItemId: string, variantKey: string) =>
  post<{ batch_item_id: string; selected_variant_key: string; draft: Record<string, unknown> }>(
    `/api/lead-gen/batch-items/${encodeURIComponent(batchItemId)}/select-variant`,
    { variant_key: variantKey },
  );

export type ComposerSkillVariantStats = {
  key: string;
  label: string;
  description: string;
  skill_path: string;
  skill_sha256: string | null;
  allocation_weight: number;
  active: boolean;
  is_baseline: boolean;
  compose_count: number;
  send_count: number;
  manual_edit_count: number;
  regenerate_count: number;
  bounce_count: number;
  reply_count: number;
  booked_qualified_conversation_count: number;
  manual_edit_rate: number | null;
  send_rate: number | null;
  reply_rate: number | null;
  bounce_rate: number | null;
  booked_qualified_conversation_rate: number | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
};

export type ComposerSkillVariant = {
  key: string;
  label: string;
  description: string;
  skill_path: string;
  skill_sha256: string | null;
  allocation_weight: number;
  active: boolean;
  is_baseline: boolean;
};

export type ComposerVariantsResponse = {
  variants: ComposerSkillVariant[];
};

export type ComposerVariantStatsResponse = {
  experiment_key: string;
  days: number;
  variants_dir: string;
  variants: ComposerSkillVariantStats[];
};

export const getComposerVariants = () =>
  get<ComposerVariantsResponse>("/api/lead-email-composer/variants");

export const updateComposerVariant = (
  variantKey: string,
  args: { label: string; description?: string | null },
) =>
  patch<ComposerSkillVariant>(
    `/api/lead-email-composer/variants/${encodeURIComponent(variantKey)}`,
    args,
  );

export async function uploadComposerVariant(args: {
  file: File;
  label: string;
  description?: string;
  allocationWeight?: number;
  active?: boolean;
}) {
  const form = new FormData();
  form.set("file", args.file);
  form.set("label", args.label);
  form.set("description", args.description ?? "");
  form.set("allocation_weight", String(args.allocationWeight ?? 100));
  form.set("active", String(args.active ?? true));
  const path = "/api/lead-email-composer/variants/upload";
  const res = await fetch(apiUrl(path), {
    method: "POST",
    body: form,
    credentials: "include",
    headers: traceHeaders(),
  });
  if (res.status === 401) {
    _handle401(path);
    throw new Error(`POST ${path} 401`);
  }
  if (!res.ok) {
    const detail = await errorDetail(res);
    throw new Error(`POST ${path} ${res.status}${detail ? ` - ${detail}` : ""}`);
  }
  return res.json() as Promise<ComposerSkillVariant>;
}

export const getComposerVariantStats = (days = 30) =>
  get<ComposerVariantStatsResponse>(
    `/api/lead-email-composer/variant-stats?days=${encodeURIComponent(String(days))}`,
  );

// ---- Front observability ----
export type FrontFunnelStep = {
  key: string;
  label: string;
  total: number;
  last_24h: number;
  previous_24h: number;
  delta: number;
};

export type FrontSyncState = {
  key: string;
  cursor: string | null;
  watermark: string | null;
  updated_at: string | null;
  watermark_age_hours: number | null;
  updated_age_hours: number | null;
};

export type FrontStatus = {
  counts: Record<string, number>;
  table_counts: Record<string, number>;
  funnel: FrontFunnelStep[];
  states: FrontSyncState[];
  sync_health: {
    last_run_at: string | null;
    last_run_age_hours: number | null;
    calls_used: number | null;
    call_budget: number;
    latest_watermark: string | null;
    latest_watermark_age_hours: number | null;
    next_daily_run_at: string | null;
    last_error: string | null;
    stale: boolean;
    stale_after_hours: number;
  };
  latest_contact_synced_at: string | null;
  timing_feed: Array<{
    domain: string;
    pif_id: string | null;
    firm_name: string;
    event_at: string | null;
    last_referral_at: string | null;
    last_seen_at: string | null;
    kind: string;
    contact_count: number;
    warm_score: number;
  }>;
};

export type FrontNamedContact = {
  id: string;
  name: string;
  email: string;
  title: string | null;
  persona: string | null;
  persona_source: string | null;
  persona_confidence: number | null;
  emailed_before: boolean;
  front_last_seen: string | null;
  source: string;
};

export type FrontWarmFirm = {
  domain: string;
  firm_name: string;
  pif_id: string | null;
  pif_match: boolean;
  warm_score: number;
  last_seen_at: string | null;
  last_referral_at: string | null;
  last_records_at: string | null;
  contact_count: number;
  named_contacts: FrontNamedContact[];
  eligible_contact_count: number;
  tech_signals: Record<string, unknown>;
  inbox_breakdown: Record<string, unknown>;
  behavioral_json: Record<string, unknown>;
};

export type FrontContact = {
  front_id: string;
  name: string | null;
  primary_email: string | null;
  domain: string | null;
  front_updated_at: string | null;
  pif_id: string | null;
  warm_score: number;
  tech_signals: Record<string, unknown>;
  last_seen_at: string | null;
  last_referral_at: string | null;
};

export type FrontSignals = {
  tech_stack_counts: Array<{
    signal: string;
    values: Array<{ value: string; count: number }>;
  }>;
  inbox_activity_mix: Array<{
    inbox_id: string;
    name: string;
    domains: number;
    conversation_count: number;
    last_seen_at: string | null;
  }>;
  suppress_flagged_firms: Array<{
    domain: string;
    pif_id: string | null;
    reasons: string[];
    warm_score: number;
    last_seen_at: string | null;
  }>;
};

export type ResearchStatus = {
  coverage: {
    matched_firms: number;
    researched_firms: number;
    staff_researched_firms: number;
    behavior_analyzed_firms: number;
    research_percent: number;
    staff_percent: number;
    behavior_percent: number;
  };
  open_tasks: Array<{
    task_id: string;
    pif_id: string;
    kind: string;
    status: string;
    requested_at: string | null;
  }>;
  task_counts: Record<string, number>;
};

export type FrontCompetitorSummary = {
  firms_with_features: number;
  firms_with_metro: number;
  edge_count: number;
  last_computed_at: string | null;
  metro_counts: Array<{ metro: string; count: number }>;
  tier_distribution: Record<string, number>;
};

export type FrontCompetitor = {
  pif_id: string;
  firm_name: string;
  domain: string | null;
  metro: string | null;
  score: number;
  components: Record<string, number>;
  evidence: {
    why?: string;
    [key: string]: unknown;
  };
};

export type FrontCompetitorsResponse = {
  firm: {
    pif_id: string;
    firm_name: string;
    domain: string | null;
    metro: string | null;
    city: string | null;
    state: string | null;
    case_mix: Record<string, number>;
    value_tier: string | null;
    volume_proxy: number | null;
    evidence: Record<string, unknown>;
    computed_at: string | null;
  } | null;
  competitors: FrontCompetitor[];
};

export type FrontCompetitorSearchResult = {
  pif_id: string;
  firm_name: string;
  domain: string | null;
  metro: string | null;
  value_tier: string | null;
  edge_count: number;
  is_warm_list: boolean;
};

export type FrontCompetitorGraphNode = {
  pif_id: string;
  firm_name: string;
  domain: string | null;
  metro: string | null;
  value_tier: string | null;
  volume_proxy: number | null;
  is_center: boolean;
};

export type FrontCompetitorGraphLink = {
  source: string;
  target: string;
  score: number;
  components: Record<string, number>;
  evidence_summary: string;
};

export type FrontCompetitorGraphResponse = {
  nodes: FrontCompetitorGraphNode[];
  links: FrontCompetitorGraphLink[];
};

export const getFrontStatus = () => get<FrontStatus>("/api/front/status");

export const getFrontWarmList = (limit = 50) =>
  get<{ warm_list: FrontWarmFirm[] }>(`/api/front/warm-list?limit=${limit}`);

export const getFrontContacts = (args: { domain?: string; q?: string; limit?: number } = {}) => {
  const params = new URLSearchParams();
  if (args.domain) params.set("domain", args.domain);
  if (args.q) params.set("q", args.q);
  if (args.limit) params.set("limit", String(args.limit));
  const qs = params.toString();
  return get<{ contacts: FrontContact[] }>(`/api/front/contacts${qs ? `?${qs}` : ""}`);
};

export const getFrontSignals = () => get<FrontSignals>("/api/front/signals");

export const getResearchStatus = () => get<ResearchStatus>("/api/research/status");

export const getFrontCompetitorSummary = () =>
  get<FrontCompetitorSummary>("/api/front/competitors/summary");

export const getFrontCompetitors = (args: { domain?: string; pif_id?: string; limit?: number }) => {
  const params = new URLSearchParams();
  if (args.domain) params.set("domain", args.domain);
  if (args.pif_id) params.set("pif_id", args.pif_id);
  if (args.limit) params.set("limit", String(args.limit));
  return get<FrontCompetitorsResponse>(`/api/front/competitors?${params.toString()}`);
};

export const searchFrontCompetitors = (args: { q: string; limit?: number }) => {
  const params = new URLSearchParams();
  params.set("q", args.q);
  if (args.limit) params.set("limit", String(args.limit));
  return get<{ results: FrontCompetitorSearchResult[] }>(`/api/front/competitors/search?${params.toString()}`);
};

export const getFrontCompetitorGraph = (args: { pif_id: string; depth?: 1 | 2 }) => {
  const params = new URLSearchParams();
  params.set("pif_id", args.pif_id);
  if (args.depth) params.set("depth", String(args.depth));
  return get<FrontCompetitorGraphResponse>(`/api/front/competitors/graph?${params.toString()}`);
};

export const createFrontWarmBatch = (args: {
  domains: string[];
  name?: string;
  template_key?: string;
  created_by?: string;
}) => post<LeadGenBatchDetail & { link: string }>("/api/front/warm-batch", args);

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

export interface ComposerAbArm {
  variant: string;
  is_baseline: boolean;
  sent: number;
  opened: number;
  replied: number;
  declined: number;
  bounced: number;
  open_rate: number | null;
  reply_rate: number | null;
  p_beats_baseline_opens: number | null;
  p_beats_baseline_replies: number | null;
  verdict: string;
  personas: Record<string, { sent: number; opened: number; replied: number; declined: number; bounced: number }>;
}

export interface ComposerAbReport {
  experiment_key: string;
  axis: string;
  days: number;
  min_sends_per_arm: number;
  decision_probability: number;
  arms: ComposerAbArm[];
  warnings: string[];
}

export const getComposerAbReport = (days = 60) =>
  get<ComposerAbReport>(`/api/lead-email-composer/report?days=${encodeURIComponent(String(days))}`);
