"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Braces,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Clipboard,
  Check,
  Code2,
  FileText,
  HeartPulse,
  ListChecks,
  Loader2,
  RefreshCw,
  Search,
  Target,
} from "lucide-react";
import {
  createResearchScoutTask,
  createSystemsHealthTask,
  getAgentEvent,
  getAgentTask,
  getAgentsStatus,
  listAgentCapabilities,
  listAgentEvents,
  listAgentTasks,
  listMasterGoals,
  refreshAgentCapabilities,
  runSystemsHealthTask,
  runMasterHeartbeat,
  updateAgentConfig,
  updateAgentTaskStatus,
  type AgentTaskEvent,
  type AgentTaskEventSummary,
  type AgentTask,
  type AgentsStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function shortDate(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statusTone(status: string) {
  if (status === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "failed" || status === "cancelled" || status === "stale") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  if (status === "blocked" || status === "waiting_on_user") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-neutral-200 bg-neutral-50 text-neutral-700";
}

function objectiveTone(status: string) {
  if (status === "satisfied") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "waiting_on_user") return "border-amber-200 bg-amber-50 text-amber-700";
  if (status === "blocked" || status === "stale" || status === "missing_goal") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  return "border-sky-200 bg-sky-50 text-sky-700";
}

function eventTone(eventType: string) {
  if (eventType === "master_heartbeat_completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (eventType === "master_heartbeat_started") return "border-teal-200 bg-teal-50 text-teal-700";
  if (eventType === "agent_config_updated") return "border-amber-200 bg-amber-50 text-amber-700";
  if (eventType === "master_goal_set" || eventType === "master_goal_synthesized") return "border-violet-200 bg-violet-50 text-violet-700";
  if (eventType === "report_created") return "border-sky-200 bg-sky-50 text-sky-700";
  if (eventType.includes("task_")) return "border-blue-200 bg-blue-50 text-blue-700";
  if (eventType.includes("capabilit")) return "border-cyan-200 bg-cyan-50 text-cyan-700";
  if (eventType.includes("action_")) return "border-rose-200 bg-rose-50 text-rose-700";
  return "border-neutral-200 bg-neutral-50 text-neutral-700";
}

const ACTIVITY_FILTERS = [
  { key: "all", label: "All" },
  { key: "heartbeat", label: "Heartbeats" },
  { key: "config", label: "Config" },
  { key: "goals", label: "Goals" },
  { key: "tasks", label: "Tasks" },
  { key: "reports", label: "Reports" },
  { key: "actions", label: "Actions" },
  { key: "capabilities", label: "Capabilities" },
  { key: "other", label: "Other" },
] as const;

type ActivityFilter = (typeof ACTIVITY_FILTERS)[number]["key"];

function activityCategory(eventType: string): ActivityFilter {
  if (eventType.startsWith("master_heartbeat_")) return "heartbeat";
  if (eventType === "agent_config_updated") return "config";
  if (eventType.startsWith("master_goal_") || eventType.includes("goal_")) return "goals";
  if (eventType === "report_created") return "reports";
  if (eventType.includes("task_")) return "tasks";
  if (eventType.includes("action_")) return "actions";
  if (eventType.includes("capabilit")) return "capabilities";
  return "other";
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

const JSON_KEY_ORDER: Record<string, string[]> = {
  master_agent_wake_context_v2: [
    "kind",
    "note",
    "cached_static_context",
    "volatile_wake_state",
    "cached_static_context_sha256",
    "prompt_cache",
  ],
  cached_static_context: [
    "prime_directives",
    "soul_compact",
    "stable_operating_doctrine",
    "stable_output_schema",
    "stable_capability_definitions",
    "stable_knowledge_summaries",
    "wake_decision_questions",
    "cache_design",
  ],
  volatile_wake_state: [
    "woke_at",
    "actor",
    "goal_stack",
    "active_goal",
    "objective_status",
    "current_state",
    "recent_evidence",
    "capabilities_state",
    "configuration",
    "current_tasks",
    "recent_actions",
    "goal_evidence",
    "queue_analysis",
    "recent_reports",
    "recent_events",
    "recent_heartbeat_summary",
    "auto_delegated_task",
    "auto_executed_lead_gen_sends",
    "llm_call",
  ],
  heartbeat_event_output: [
    "active_task_count",
    "queued_task_count",
    "blocked_task_count",
    "stale_task_ids",
    "queue_analysis",
    "human_status",
    "objective_status",
    "tool_loop",
    "auto_delegated_task",
    "auto_executed_lead_gen_sends",
    "active_goal",
  ],
  heartbeat_result: [
    "status",
    "started_at",
    "completed_at",
    "active_task_count",
    "queued_task_count",
    "blocked_task_count",
    "stale_task_ids",
    "queue_analysis",
    "heartbeat_enabled",
    "heartbeat_interval_seconds",
    "human_status",
    "objective_status",
    "wake_context",
    "tool_loop",
    "status_llm",
    "tool_runner",
    "auto_delegated_task",
    "auto_executed_lead_gen_sends",
    "active_goal",
    "soul",
    "next_recommended_slice",
  ],
  status_llm: [
    "used_llm",
    "model",
    "skill_path",
    "raw_response",
    "usage",
    "cached_tokens",
    "prompt_cache",
  ],
  human_status: [
    "state",
    "goal",
    "current_focus",
    "intended_next_steps",
    "needs_from_user",
    "confidence",
    "reasoning",
  ],
  objective_status: ["active_goal_id", "goal", "status", "evidence", "remaining_work", "next_best_action"],
  prompt_cache: ["strategy", "provider", "cache_key", "cache_retention", "passthrough_enabled"],
  llm_call: ["enabled", "model", "skill_path", "status"],
  goal_stack: ["short_term", "medium_term", "long_term"],
};

function jsonOrderKey(label: string, value: Record<string, unknown>) {
  if (value.kind === "master_agent_wake_context_v2") return "master_agent_wake_context_v2";
  if (label === "event.output" && "human_status" in value && "active_task_count" in value) return "heartbeat_event_output";
  if (label === "output" && "human_status" in value && "active_task_count" in value) return "heartbeat_event_output";
  if (label === "heartbeat" && "wake_context" in value && "status_llm" in value) return "heartbeat_result";
  return label;
}

function orderedJsonValue(value: unknown, label = "root"): unknown {
  if (Array.isArray(value)) return value.map((item) => orderedJsonValue(item));
  if (!value || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  const order = JSON_KEY_ORDER[jsonOrderKey(label, record)] || [];
  const ordered: Record<string, unknown> = {};
  for (const key of order) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      ordered[key] = orderedJsonValue(record[key], key);
    }
  }
  for (const key of Object.keys(record)) {
    if (!Object.prototype.hasOwnProperty.call(ordered, key)) {
      ordered[key] = orderedJsonValue(record[key], key);
    }
  }
  return ordered;
}

function jsonPreview(value: unknown, label = "root") {
  return JSON.stringify(orderedJsonValue(value ?? {}, label), null, 2);
}

function jsonNodeSummary(value: unknown) {
  if (Array.isArray(value)) return `Array(${value.length})`;
  if (value && typeof value === "object") return `Object(${Object.keys(value).length})`;
  if (typeof value === "string") return value.length > 80 ? `"${value.slice(0, 77)}..."` : `"${value}"`;
  if (value === null) return "null";
  return String(value);
}

function jsonType(value: unknown) {
  if (Array.isArray(value)) return "array";
  if (value === null) return "null";
  return typeof value;
}

function jsonValueClass(value: unknown) {
  if (typeof value === "string") return "text-emerald-700";
  if (typeof value === "number") return "text-sky-700";
  if (typeof value === "boolean") return "text-violet-700";
  if (value === null) return "text-neutral-400";
  return "text-neutral-800";
}

function shouldOpenJsonKey(depth: number, key: string) {
  if (depth > 1) return false;
  return [
    "cached_static_context",
    "volatile_wake_state",
    "human_status",
    "active_goal",
    "objective_status",
    "auto_executed_lead_gen_sends",
    "status_llm",
    "recent_actions",
    "goal_evidence",
  ].includes(key);
}

function JsonPrimitiveValue({ label, value }: { label: string; value: unknown }) {
  const [previewPosition, setPreviewPosition] = useState<{ left: number; top: number } | null>(null);
  const isLongString = typeof value === "string" && value.length > 80;

  function updatePreviewPosition(clientX: number, clientY: number) {
    const width = Math.min(680, Math.max(320, window.innerWidth - 32));
    const height = Math.min(420, Math.max(220, window.innerHeight - 32));
    setPreviewPosition({
      left: Math.max(16, Math.min(clientX + 14, window.innerWidth - width - 16)),
      top: Math.max(16, Math.min(clientY + 14, window.innerHeight - height - 16)),
    });
  }

  return (
    <span
      className={cn(
        "relative min-w-0 whitespace-pre-wrap break-words font-mono text-[11px] leading-5",
        jsonValueClass(value),
        isLongString ? "cursor-help rounded-sm outline-none focus:ring-2 focus:ring-emerald-200" : "",
      )}
      tabIndex={isLongString ? 0 : undefined}
      onMouseEnter={(event) => {
        if (isLongString) updatePreviewPosition(event.clientX, event.clientY);
      }}
      onMouseMove={(event) => {
        if (isLongString) updatePreviewPosition(event.clientX, event.clientY);
      }}
      onMouseLeave={() => setPreviewPosition(null)}
      onFocus={(event) => {
        if (!isLongString) return;
        const rect = event.currentTarget.getBoundingClientRect();
        updatePreviewPosition(rect.left, rect.bottom);
      }}
      onBlur={() => setPreviewPosition(null)}
    >
      {jsonNodeSummary(value)}
      {isLongString && previewPosition && (
        <div
          className="fixed z-[70] max-h-[420px] w-[min(680px,calc(100vw-32px))] overflow-auto rounded-lg border border-neutral-200 bg-white p-3 text-left shadow-2xl"
          style={{ left: previewPosition.left, top: previewPosition.top }}
          role="tooltip"
        >
          <div className="mb-2 flex items-center justify-between gap-3 border-b border-neutral-100 pb-2">
            <span className="truncate font-sans text-xs font-semibold text-neutral-700">{label}</span>
            <span className="shrink-0 rounded-full bg-neutral-100 px-2 py-0.5 font-sans text-[10px] font-medium text-neutral-500">
              {value.length.toLocaleString()} chars
            </span>
          </div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-neutral-800">
            {value}
          </pre>
        </div>
      )}
    </span>
  );
}

function JsonTree({
  value,
  label = "root",
  depth = 0,
  defaultOpen = true,
}: {
  value: unknown;
  label?: string;
  depth?: number;
  defaultOpen?: boolean;
}) {
  const displayValue = orderedJsonValue(value, label);
  const expandable = displayValue !== null && typeof displayValue === "object";
  if (!expandable) {
    return (
      <div className="grid grid-cols-[minmax(120px,0.28fr)_minmax(0,1fr)] gap-3 border-b border-neutral-100 px-2 py-1.5 hover:bg-white">
        <span className="truncate font-mono text-[11px] font-semibold text-neutral-500">{label}</span>
        <JsonPrimitiveValue label={label} value={displayValue} />
      </div>
    );
  }

  const entries = Array.isArray(displayValue)
    ? displayValue.map((item, index) => [String(index), item] as const)
    : Object.entries(displayValue as Record<string, unknown>);

  return (
    <details
      className={cn("group rounded-lg border border-neutral-200 bg-white shadow-sm", depth > 0 ? "mt-1" : "")}
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-2 text-xs hover:bg-neutral-50">
        <ChevronRight className="h-3.5 w-3.5 text-neutral-400 group-open:hidden" />
        <ChevronDown className="hidden h-3.5 w-3.5 text-neutral-400 group-open:block" />
        <span className="min-w-0 truncate font-mono text-[11px] font-semibold text-neutral-800">{label}</span>
        <span className="rounded-full border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 font-mono text-[10px] text-neutral-500">
          {jsonType(displayValue)}
        </span>
        <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 font-mono text-[10px] text-neutral-500">
          {jsonNodeSummary(displayValue)}
        </span>
      </summary>
      <div className="space-y-1 border-t border-neutral-100 bg-neutral-50/60 px-2 py-2" style={{ marginLeft: Math.min(depth, 4) * 10 }}>
        {entries.length === 0 ? (
          <div className="font-mono text-[11px] text-neutral-400">empty</div>
        ) : (
          entries.map(([key, child]) => (
            <JsonTree
              key={`${depth}-${key}`}
              label={key}
              value={child}
              depth={depth + 1}
              defaultOpen={shouldOpenJsonKey(depth, key)}
            />
          ))
        )}
      </div>
    </details>
  );
}

function JsonModalPanel({
  title,
  description,
  badge,
  value,
  mode,
  copied,
  onCopy,
}: {
  title: string;
  description: string;
  badge: string;
  value: unknown;
  mode: "parsed" | "raw";
  copied: boolean;
  onCopy: () => void;
}) {
  const orderedValue = orderedJsonValue(value || {}, badge);
  const raw = jsonPreview(value || {}, badge);
  return (
    <section className="flex min-h-0 min-w-0 flex-col border-b border-neutral-200 bg-white lg:border-b-0 lg:border-r last:border-r-0">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
            <span className="rounded-full bg-neutral-100 px-2 py-0.5 font-mono text-[10px] text-neutral-500">
              {badge}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-neutral-400">{description}</p>
        </div>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Clipboard className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy JSON"}
        </button>
      </div>
      <div className="min-h-[340px] min-w-0 flex-1 overflow-auto bg-neutral-50 p-3">
        {mode === "raw" ? (
          <pre className="min-h-full w-max min-w-full rounded-lg border border-neutral-200 bg-neutral-950 p-3 font-mono text-[11px] leading-5 text-neutral-100 shadow-inner">
            {raw}
          </pre>
        ) : (
          <JsonTree value={orderedValue} label={badge} />
        )}
      </div>
    </section>
  );
}

function activitySummary(event: AgentTaskEvent | AgentTaskEventSummary) {
  if ("summary" in event && event.summary) return event.summary;
  const output = "output" in event ? event.output || {} : {};
  if (event.event_type === "master_heartbeat_completed") {
    const humanStatus = output.human_status as { state?: unknown } | undefined;
    if (typeof humanStatus?.state === "string" && humanStatus.state.trim()) {
      return humanStatus.state;
    }
    return `active ${output.active_task_count ?? 0}, queued ${output.queued_task_count ?? 0}, blocked ${output.blocked_task_count ?? 0}`;
  }
  if (event.event_type === "task_created") {
    const input = "input" in event ? event.input || {} : {};
    return typeof input.title === "string" ? input.title : event.message;
  }
  if (event.event_type === "status_changed") {
    return typeof output.status === "string" ? `status ${output.status}` : event.message;
  }
  return event.message || event.event_type;
}

function TaskRow({
  task,
  selected,
  onSelect,
}: {
  task: AgentTask;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        selected ? "border-neutral-900 bg-neutral-50" : "border-neutral-200 bg-white hover:bg-neutral-50",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-neutral-950">{task.title}</span>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", statusTone(task.status))}>
          {task.status}
        </span>
      </div>
      <div className="mt-2 grid gap-1 text-xs text-neutral-500 sm:grid-cols-2">
        <span>{task.assigned_agent}</span>
        <span>last heartbeat: {shortDate(task.last_heartbeat_at)}</span>
        <span>priority {task.priority}</span>
        <span>updated {shortDate(task.updated_at)}</span>
      </div>
    </button>
  );
}

export default function AgentsPage() {
  const qc = useQueryClient();
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("all");
  const [heartbeatEnabledDraft, setHeartbeatEnabledDraft] = useState(true);
  const [heartbeatIntervalDraft, setHeartbeatIntervalDraft] = useState("300");
  const [toolRunnerEnabledDraft, setToolRunnerEnabledDraft] = useState(false);
  const [toolRunnerIterationsDraft, setToolRunnerIterationsDraft] = useState("3");
  const [toolRunnerRuntimeDraft, setToolRunnerRuntimeDraft] = useState("90");
  const [toolRunnerPersistDraft, setToolRunnerPersistDraft] = useState(true);
  const [autoSendLeadGenDraft, setAutoSendLeadGenDraft] = useState(false);
  const [autoSendLeadGenLimitDraft, setAutoSendLeadGenLimitDraft] = useState("1");
  const [jsonDisplayMode, setJsonDisplayMode] = useState<"parsed" | "raw">("parsed");
  const [copiedJsonPanel, setCopiedJsonPanel] = useState<"input" | "output" | "metadata" | null>(null);
  const [loadingJsonEventId, setLoadingJsonEventId] = useState<number | null>(null);
  const [jsonModal, setJsonModal] = useState<{
    eventId: number;
    createdAt: string | null;
    agentId: string;
    eventType: string;
    summary: string;
    input: unknown;
    output: unknown;
    metadata?: Record<string, unknown>;
  } | null>(null);

  async function copyJsonPanel(panel: "input" | "output" | "metadata", value: unknown) {
    const label = panel === "input" ? "event.input" : panel === "output" ? "event.output" : "metadata";
    const text = jsonPreview(value || {}, label);
    await navigator.clipboard.writeText(text);
    setCopiedJsonPanel(panel);
    window.setTimeout(() => setCopiedJsonPanel((current) => (current === panel ? null : current)), 1400);
  }

  async function openEventJson(event: AgentTaskEventSummary) {
    setJsonDisplayMode("parsed");
    setCopiedJsonPanel(null);
    setLoadingJsonEventId(event.id);
    try {
      const detail = await getAgentEvent(event.id);
      setJsonModal({
        eventId: detail.event.id,
        createdAt: detail.event.created_at,
        agentId: detail.event.agent_id,
        eventType: detail.event.event_type,
        summary: activitySummary(detail.event),
        input: detail.event.input || {},
        output: detail.event.output || {},
        metadata: detail.event.metadata || {},
      });
    } finally {
      setLoadingJsonEventId((current) => (current === event.id ? null : current));
    }
  }

  const status = useQuery({
    queryKey: ["agents-status"],
    queryFn: getAgentsStatus,
    refetchInterval: 15_000,
  });

  const tasks = useQuery({
    queryKey: ["agent-tasks", statusFilter],
    queryFn: () => listAgentTasks({ status: statusFilter, limit: 150 }),
    refetchInterval: 15_000,
  });

  const activity = useQuery({
    queryKey: ["agent-events", 40],
    queryFn: () => listAgentEvents({ limit: 40 }),
    refetchInterval: 15_000,
  });

  const capabilities = useQuery({
    queryKey: ["agent-capabilities"],
    queryFn: () => listAgentCapabilities({ limit: 100 }),
    refetchInterval: 60_000,
  });

  const goals = useQuery({
    queryKey: ["master-goals", "active"],
    queryFn: () => listMasterGoals({ status: "active", limit: 5 }),
    refetchInterval: 30_000,
  });

  const selectedTask = useQuery({
    queryKey: ["agent-task", selectedTaskId],
    queryFn: () => getAgentTask(selectedTaskId),
    enabled: Boolean(selectedTaskId),
    refetchInterval: 15_000,
  });

  const runHeartbeat = useMutation({
    mutationFn: runMasterHeartbeat,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents-status"] });
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const saveAgentConfig = useMutation({
    mutationFn: () =>
      updateAgentConfig({
        heartbeat_enabled: heartbeatEnabledDraft,
        heartbeat_interval_seconds: Number(heartbeatIntervalDraft),
        tool_runner_enabled: toolRunnerEnabledDraft,
        tool_runner_max_iterations: Number(toolRunnerIterationsDraft),
        tool_runner_max_runtime_seconds: Number(toolRunnerRuntimeDraft),
        tool_runner_persist_continuation: toolRunnerPersistDraft,
        auto_execute_approved_lead_gen_email_enabled: autoSendLeadGenDraft,
        auto_execute_approved_lead_gen_email_limit: Number(autoSendLeadGenLimitDraft),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents-status"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const updateHeartbeatEnabled = useMutation({
    mutationFn: (enabled: boolean) => updateAgentConfig({ heartbeat_enabled: enabled }),
    onSuccess: (data) => {
      qc.setQueryData(["agents-status"], (current: AgentsStatus | undefined) => {
        if (!current) return current;
        return {
          ...current,
          heartbeat_enabled: data.config.heartbeat_enabled,
          heartbeat_interval_seconds: data.config.heartbeat_interval_seconds,
          tool_runner_enabled: data.config.tool_runner_enabled,
          tool_runner_max_iterations: data.config.tool_runner_max_iterations,
          tool_runner_max_runtime_seconds: data.config.tool_runner_max_runtime_seconds,
          tool_runner_persist_continuation: data.config.tool_runner_persist_continuation,
          auto_execute_approved_lead_gen_email_enabled: data.config.auto_execute_approved_lead_gen_email_enabled,
          auto_execute_approved_lead_gen_email_limit: data.config.auto_execute_approved_lead_gen_email_limit,
        };
      });
      qc.invalidateQueries({ queryKey: ["agents-status"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const createScout = useMutation({
    mutationFn: createResearchScoutTask,
    onSuccess: (data) => {
      setSelectedTaskId(data.task.id);
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const createSystemsHealth = useMutation({
    mutationFn: createSystemsHealthTask,
    onSuccess: (data) => {
      setSelectedTaskId(data.task.id);
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const runSystemsHealth = useMutation({
    mutationFn: (taskId?: string) => runSystemsHealthTask(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents-status"] });
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
      qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
    },
  });

  const refreshCapabilities = useMutation({
    mutationFn: () => refreshAgentCapabilities(true),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-capabilities"] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const setDone = useMutation({
    mutationFn: (taskId: string) =>
      updateAgentTaskStatus(taskId, "completed", "Marked completed by operator."),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agent-tasks"] });
      qc.invalidateQueries({ queryKey: ["agent-task", selectedTaskId] });
      qc.invalidateQueries({ queryKey: ["agent-events"] });
    },
  });

  const allTasks = tasks.data?.tasks ?? [];
  const counts = useMemo(() => {
    return {
      total: allTasks.length,
      queued: allTasks.filter((task) => task.status === "queued").length,
      active: allTasks.filter((task) =>
        ["accepted", "running", "waiting_on_tool", "waiting_on_user", "blocked", "stale"].includes(task.status),
      ).length,
    };
  }, [allTasks]);

  const heartbeat = status.data?.last_heartbeat;
  const humanStatus = heartbeat?.human_status;
  const wakeContext = heartbeat?.wake_context;
  const cachedStaticContext = objectValue(objectValue(wakeContext).cached_static_context);
  const volatileWakeState = objectValue(objectValue(wakeContext).volatile_wake_state);
  const statusLlm = heartbeat?.status_llm;
  const activeGoal = heartbeat?.active_goal || goals.data?.goals?.[0] || null;
  const queueAnalysis = heartbeat?.queue_analysis || {};
  const objectiveStatus = objectValue(heartbeat?.objective_status || volatileWakeState.objective_status);
  const objectiveEvidence = arrayValue(objectiveStatus.evidence).map((row) => objectValue(row));
  const objectiveRemainingWork = arrayValue(objectiveStatus.remaining_work)
    .map((item) => stringValue(item))
    .filter(Boolean);
  const objectiveStatusValue = stringValue(objectiveStatus.status) || "unknown";
  const recentActionRows = arrayValue(volatileWakeState.recent_actions)
    .map((row) => objectValue(row))
    .filter((row) => row.id || row.action_type);
  const jsonModalInput = objectValue(jsonModal?.input);
  const jsonModalKind = stringValue(jsonModalInput.kind);
  const jsonModalHasV2 =
    Boolean(jsonModalInput.cached_static_context) && Boolean(jsonModalInput.volatile_wake_state);
  const staleQueueItems = Array.isArray(queueAnalysis.stale_queue_items)
    ? queueAnalysis.stale_queue_items
    : [];
  const capabilityRows = capabilities.data?.capabilities ?? [];
  const activityRows = activity.data?.events ?? [];
  const activityCounts = useMemo(() => {
    const countsByKind = Object.fromEntries(ACTIVITY_FILTERS.map((filter) => [filter.key, 0])) as Record<ActivityFilter, number>;
    countsByKind.all = activityRows.length;
    for (const row of activityRows) {
      countsByKind[activityCategory(row.event_type)] += 1;
    }
    return countsByKind;
  }, [activityRows]);
  const filteredActivityRows = useMemo(() => {
    if (activityFilter === "all") return activityRows;
    return activityRows.filter((row) => activityCategory(row.event_type) === activityFilter);
  }, [activityFilter, activityRows]);
  useEffect(() => {
    if (!status.data) return;
    setHeartbeatEnabledDraft(status.data.heartbeat_enabled);
    setHeartbeatIntervalDraft(String(status.data.heartbeat_interval_seconds));
    setToolRunnerEnabledDraft(status.data.tool_runner_enabled);
    setToolRunnerIterationsDraft(String(status.data.tool_runner_max_iterations));
    setToolRunnerRuntimeDraft(String(status.data.tool_runner_max_runtime_seconds));
    setToolRunnerPersistDraft(status.data.tool_runner_persist_continuation);
    setAutoSendLeadGenDraft(status.data.auto_execute_approved_lead_gen_email_enabled);
    setAutoSendLeadGenLimitDraft(String(status.data.auto_execute_approved_lead_gen_email_limit));
  }, [
    status.data?.heartbeat_enabled,
    status.data?.heartbeat_interval_seconds,
    status.data?.tool_runner_enabled,
    status.data?.tool_runner_max_iterations,
    status.data?.tool_runner_max_runtime_seconds,
    status.data?.tool_runner_persist_continuation,
    status.data?.auto_execute_approved_lead_gen_email_enabled,
    status.data?.auto_execute_approved_lead_gen_email_limit,
  ]);
  const heartbeatIntervalNumber = Number(heartbeatIntervalDraft);
  const toolRunnerIterationsNumber = Number(toolRunnerIterationsDraft);
  const toolRunnerRuntimeNumber = Number(toolRunnerRuntimeDraft);
  const autoSendLeadGenLimitNumber = Number(autoSendLeadGenLimitDraft);
  const heartbeatConfigValid =
    Number.isFinite(heartbeatIntervalNumber) &&
    heartbeatIntervalNumber >= 60 &&
    heartbeatIntervalNumber <= 3600 &&
    Number.isFinite(toolRunnerIterationsNumber) &&
    toolRunnerIterationsNumber >= 1 &&
    toolRunnerIterationsNumber <= 5 &&
    Number.isFinite(toolRunnerRuntimeNumber) &&
    toolRunnerRuntimeNumber >= 15 &&
    toolRunnerRuntimeNumber <= 180 &&
    Number.isFinite(autoSendLeadGenLimitNumber) &&
    autoSendLeadGenLimitNumber >= 1 &&
    autoSendLeadGenLimitNumber <= 25;
  const heartbeatConfigDirty =
    Boolean(status.data) &&
    (heartbeatEnabledDraft !== status.data?.heartbeat_enabled ||
      heartbeatIntervalDraft !== String(status.data?.heartbeat_interval_seconds ?? "") ||
      toolRunnerEnabledDraft !== status.data?.tool_runner_enabled ||
      toolRunnerIterationsDraft !== String(status.data?.tool_runner_max_iterations ?? "") ||
      toolRunnerRuntimeDraft !== String(status.data?.tool_runner_max_runtime_seconds ?? "") ||
      toolRunnerPersistDraft !== status.data?.tool_runner_persist_continuation ||
      autoSendLeadGenDraft !== status.data?.auto_execute_approved_lead_gen_email_enabled ||
      autoSendLeadGenLimitDraft !== String(status.data?.auto_execute_approved_lead_gen_email_limit ?? ""));

  function openLatestHeartbeatJson() {
    if (!heartbeat) return;
    const { wake_context: wakeContextPayload, ...heartbeatOutput } = heartbeat;
    setJsonDisplayMode("parsed");
    setCopiedJsonPanel(null);
    setJsonModal({
      eventId: 0,
      createdAt: heartbeat.completed_at,
      agentId: "master-agent",
      eventType: "master_heartbeat_completed",
      summary: heartbeat.human_status?.state || "Latest persisted heartbeat result.",
      input: wakeContextPayload || {},
      output: heartbeatOutput,
      metadata: {
        source: "GET /api/agents/status last_heartbeat",
        status_llm: heartbeat.status_llm || {},
        tool_runner: heartbeat.tool_runner || {},
      },
    });
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-900">Agents</h1>
        <span className="text-xs text-neutral-400">
          master heartbeat, delegation, status checks, report back
        </span>
        <button
          type="button"
          onClick={() => {
            status.refetch();
            tasks.refetch();
            activity.refetch();
          }}
          disabled={status.isFetching || tasks.isFetching || activity.isFetching}
          className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          {status.isFetching || tasks.isFetching || activity.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-start gap-4">
          <span className="rounded-lg bg-neutral-900 p-2 text-white">
            <HeartPulse className="h-5 w-5" />
          </span>
          <div className="min-w-[260px] flex-1">
            <h2 className="text-sm font-semibold text-neutral-950">Master heartbeat</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-neutral-600">
              V1 heartbeat reads protected `soul.md` as constitutional context, records traces,
              checks active subagent tasks, and marks stale workers. It does not edit `soul.md`.
              When enabled, it can execute only already-approved lead-gen email actions through
              the durable policy gate.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => runHeartbeat.mutate()}
              disabled={runHeartbeat.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {runHeartbeat.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <HeartPulse className="h-4 w-4" />}
              Run heartbeat
            </button>
            <button
              type="button"
              onClick={openLatestHeartbeatJson}
              disabled={!heartbeat}
              className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              <Braces className="h-4 w-4" />
              Latest heartbeat JSON
            </button>
            <button
              type="button"
              onClick={() => createScout.mutate()}
              disabled={createScout.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {createScout.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Create ResearchScout task
            </button>
            <button
              type="button"
              onClick={() => createSystemsHealth.mutate()}
              disabled={createSystemsHealth.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {createSystemsHealth.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ListChecks className="h-4 w-4" />}
              Create SystemsHealth task
            </button>
            <button
              type="button"
              onClick={() => runSystemsHealth.mutate(undefined)}
              disabled={runSystemsHealth.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {runSystemsHealth.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <HeartPulse className="h-4 w-4" />}
              Run SystemsHealth
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg border border-neutral-200 p-3">
            <div className="text-xs text-neutral-500">Heartbeat</div>
            <div className="mt-1 text-sm font-semibold text-neutral-950">
              {status.data?.heartbeat_enabled ? "enabled" : "disabled"}
            </div>
            <div className="mt-1 text-xs text-neutral-500">
              {status.data?.heartbeat_enabled
                ? `every ${status.data?.heartbeat_interval_seconds ?? "-"}s`
                : "periodic loop stopped"}
            </div>
          </div>
          <div className="rounded-lg border border-neutral-200 p-3 sm:col-span-2 lg:col-span-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex items-center gap-2 text-xs font-medium text-neutral-700">
                <input
                  type="checkbox"
                  checked={heartbeatEnabledDraft}
                  onChange={(event) => {
                    const nextEnabled = event.target.checked;
                    setHeartbeatEnabledDraft(nextEnabled);
                    updateHeartbeatEnabled.mutate(nextEnabled);
                  }}
                  disabled={updateHeartbeatEnabled.isPending}
                  className="h-4 w-4 rounded border-neutral-300"
                />
                Enabled
                {updateHeartbeatEnabled.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-neutral-400" />
                ) : null}
              </label>
              <label className="min-w-[180px] flex-1 text-xs font-medium text-neutral-700">
                Period seconds
                <input
                  type="number"
                  min={60}
                  max={3600}
                  step={60}
                  value={heartbeatIntervalDraft}
                  onChange={(event) => setHeartbeatIntervalDraft(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-neutral-200 px-3 text-sm text-neutral-900"
                />
              </label>
              <label className="flex min-w-[260px] items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-950">
                <input
                  type="checkbox"
                  checked={autoSendLeadGenDraft}
                  onChange={(event) => setAutoSendLeadGenDraft(event.target.checked)}
                  className="h-4 w-4 rounded border-amber-300"
                />
                Master may send approved lead-gen emails
              </label>
              <label className="w-28 text-xs font-medium text-neutral-700">
                Send limit
                <input
                  type="number"
                  min={1}
                  max={25}
                  step={1}
                  value={autoSendLeadGenLimitDraft}
                  onChange={(event) => setAutoSendLeadGenLimitDraft(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-neutral-200 px-3 text-sm text-neutral-900"
                />
              </label>
              <label className="flex min-w-[250px] items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-950">
                <input
                  type="checkbox"
                  checked={toolRunnerEnabledDraft}
                  onChange={(event) => setToolRunnerEnabledDraft(event.target.checked)}
                  className="h-4 w-4 rounded border-emerald-300"
                />
                Master may use read-only tools
              </label>
              <label className="w-28 text-xs font-medium text-neutral-700">
                Tool calls
                <input
                  type="number"
                  min={1}
                  max={5}
                  step={1}
                  value={toolRunnerIterationsDraft}
                  onChange={(event) => setToolRunnerIterationsDraft(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-neutral-200 px-3 text-sm text-neutral-900"
                />
              </label>
              <label className="w-32 text-xs font-medium text-neutral-700">
                Runtime sec
                <input
                  type="number"
                  min={15}
                  max={180}
                  step={15}
                  value={toolRunnerRuntimeDraft}
                  onChange={(event) => setToolRunnerRuntimeDraft(event.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-neutral-200 px-3 text-sm text-neutral-900"
                />
              </label>
              <label className="flex min-w-[220px] items-center gap-2 text-xs font-medium text-neutral-700">
                <input
                  type="checkbox"
                  checked={toolRunnerPersistDraft}
                  onChange={(event) => setToolRunnerPersistDraft(event.target.checked)}
                  className="h-4 w-4 rounded border-neutral-300"
                />
                Persist continuation
              </label>
              <button
                type="button"
                onClick={() => saveAgentConfig.mutate()}
                disabled={!heartbeatConfigValid || !heartbeatConfigDirty || saveAgentConfig.isPending}
                className="inline-flex h-9 items-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
              >
                {saveAgentConfig.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Save
              </button>
            </div>
            <div className="mt-2 text-xs text-neutral-500">
              The Enabled checkbox saves immediately. Period, runner, and approved-send automation changes use Save. The runner only uses bounded read-only filesystem inspection.
            </div>
            {toolRunnerEnabledDraft ? (
              <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
                When saved, each manual or scheduled heartbeat may make up to {toolRunnerIterationsDraft || "3"} read-only tool call(s) and save compact continuation notes for the next wake-up.
              </div>
            ) : null}
            {autoSendLeadGenDraft ? (
              <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                When saved, each heartbeat may send up to {autoSendLeadGenLimitDraft || "1"} already-approved lead-gen email action(s). It cannot create recipients or bypass approval hashes.
              </div>
            ) : null}
            {status.data?.heartbeat_enabled === false ? (
              <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                Periodic heartbeat is disabled. The Run heartbeat button still performs one manual check.
              </div>
            ) : null}
          </div>
          <div className="rounded-lg border border-neutral-200 p-3">
            <div className="text-xs text-neutral-500">Last run historical</div>
            <div className="mt-1 text-sm font-semibold text-neutral-950">
              {shortDate(heartbeat?.completed_at)}
            </div>
            <div className="mt-1 text-xs text-neutral-500">
              {heartbeat?.status ?? "no heartbeat yet"}
            </div>
            {status.data?.heartbeat_enabled === false && heartbeat ? (
              <div className="mt-1 text-xs text-amber-700">scheduler disabled after this run</div>
            ) : null}
          </div>
          <div className="rounded-lg border border-neutral-200 p-3">
            <div className="text-xs text-neutral-500">Active tasks</div>
            <div className="mt-1 text-sm font-semibold text-neutral-950">
              {heartbeat?.active_task_count ?? counts.active}
            </div>
            <div className="mt-1 text-xs text-neutral-500">
              queued {heartbeat?.queued_task_count ?? counts.queued}
            </div>
          </div>
          <div className="rounded-lg border border-neutral-200 p-3">
            <div className="text-xs text-neutral-500">Soul context</div>
            <div className="mt-1 text-sm font-semibold text-neutral-950">
              {heartbeat?.soul?.loaded === true ? "loaded read-only" : "not loaded"}
            </div>
            <div className="mt-1 truncate text-xs text-neutral-500">
              {typeof heartbeat?.soul?.sha256 === "string" ? heartbeat.soul.sha256.slice(0, 12) : "protected"}
            </div>
          </div>
        </div>

        {(runHeartbeat.isError || createScout.isError || createSystemsHealth.isError || runSystemsHealth.isError || saveAgentConfig.isError) && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertTriangle className="h-4 w-4" />
            Agent operation failed. Check backend logs.
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Adaptive goal</h2>
          <span className="text-xs text-neutral-400">durable goal synthesized from current state</span>
        </div>
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Current goal</div>
            <p className="mt-2 text-base font-semibold leading-7 text-neutral-950">
              {activeGoal?.goal || "No adaptive goal has been synthesized yet."}
            </p>
            {activeGoal?.why && (
              <p className="mt-2 text-sm leading-6 text-neutral-600">{activeGoal.why}</p>
            )}
            {activeGoal?.success_metric && (
              <div className="mt-3 rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm text-neutral-700">
                <span className="font-medium text-neutral-900">Success:</span> {activeGoal.success_metric}
              </div>
            )}
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Next actions</div>
            <ul className="mt-2 space-y-2 text-sm leading-6 text-neutral-700">
              {(activeGoal?.next_actions?.length ? activeGoal.next_actions : ["Run a heartbeat to synthesize the next goal."]).map((action) => (
                <li key={action} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-400" />
                  <span>{action}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3 text-xs text-neutral-500">
              {activeGoal ? `${activeGoal.confidence} confidence - ${activeGoal.time_horizon}` : ""}
            </div>
          </div>
        </div>
        {staleQueueItems.length > 0 && (
          <div className="border-t border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {staleQueueItems.length} queued task{staleQueueItems.length === 1 ? "" : "s"} exceeded the queue-age threshold.
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Objective status</h2>
          <span className="text-xs text-neutral-400">deterministic read on whether the current goal is done, blocked, stale, or moving</span>
          <span className={cn("ml-auto rounded-full border px-2 py-0.5 text-[11px] font-medium", objectiveTone(objectiveStatusValue))}>
            {objectiveStatusValue}
          </span>
        </div>
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
          <div className="space-y-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Goal being interpreted</div>
              <p className="mt-2 text-sm leading-6 text-neutral-700">
                {stringValue(objectiveStatus.goal) || activeGoal?.goal || "Run a heartbeat to load objective status."}
              </p>
            </div>
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Next best action</div>
              <p className="mt-2 text-sm leading-6 text-neutral-700">
                {stringValue(objectiveStatus.next_best_action) || "Run a heartbeat to compute the next best action."}
              </p>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-1">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Evidence</div>
              <div className="mt-2 space-y-2">
                {objectiveEvidence.length === 0 && (
                  <div className="rounded-lg border border-dashed border-neutral-200 p-3 text-sm text-neutral-500">
                    No objective evidence has been computed yet.
                  </div>
                )}
                {objectiveEvidence.slice(0, 4).map((item, index) => (
                  <div key={`${stringValue(item.type) || "evidence"}-${index}`} className="rounded-lg border border-neutral-200 p-3 text-xs leading-5 text-neutral-600">
                    <div className="font-semibold text-neutral-800">{stringValue(item.type) || "evidence"}</div>
                    <div className="mt-1">
                      {stringValue(item.summary)
                        || stringValue(item.title)
                        || stringValue(item.error)
                        || stringValue(item.action_id)
                        || stringValue(item.task_id)
                        || "Evidence available in the heartbeat JSON."}
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Remaining work</div>
              <ul className="mt-2 space-y-2 text-sm leading-6 text-neutral-700">
                {(objectiveRemainingWork.length ? objectiveRemainingWork : ["No remaining work listed for this objective."]).slice(0, 5).map((item) => (
                  <li key={item} className="flex gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-400" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Capability registry</h2>
          <span className="text-xs text-neutral-400">known tools, risk, and verification state</span>
          <button
            type="button"
            onClick={() => refreshCapabilities.mutate()}
            disabled={refreshCapabilities.isPending}
            className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {refreshCapabilities.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh capabilities
          </button>
        </div>
        <div className="grid gap-2 p-4 md:grid-cols-2 xl:grid-cols-3">
          {capabilities.isLoading && (
            <div className="text-sm text-neutral-500">Loading capabilities...</div>
          )}
          {!capabilities.isLoading && capabilityRows.length === 0 && (
            <div className="text-sm text-neutral-500">No capabilities discovered yet.</div>
          )}
          {capabilityRows.map((capability) => (
            <div key={capability.id} className="rounded-lg border border-neutral-200 p-3">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-neutral-950">{capability.name}</div>
                  <div className="mt-1 text-xs text-neutral-500">{capability.capability_type} - {capability.risk_level}</div>
                </div>
                <span className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                  capability.last_status === "ok"
                    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                    : capability.last_status === "failed"
                      ? "border-red-200 bg-red-50 text-red-700"
                      : "border-neutral-200 bg-neutral-50 text-neutral-700",
                )}>
                  {capability.last_status}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-neutral-600">{capability.purpose}</p>
              <div className="mt-2 break-words font-mono text-[10px] text-neutral-400">{capability.source}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Human status update</h2>
          <span className="text-xs text-neutral-400">state, goal, intent, and required help</span>
          <span
            className={cn(
              "ml-auto rounded-full border px-2 py-0.5 text-[11px] font-medium",
              statusLlm?.used_llm
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-amber-200 bg-amber-50 text-amber-700",
            )}
          >
            {statusLlm?.used_llm ? `OpenClaw ${statusLlm.model || "LLM"}` : "fallback"}
          </span>
        </div>
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                <HeartPulse className="h-4 w-4" />
                State
              </div>
              <p className="mt-2 text-base font-semibold leading-7 text-neutral-950">
                {humanStatus?.state || "No heartbeat status has been recorded yet."}
              </p>
            </div>
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                <Target className="h-4 w-4" />
                Goal
              </div>
              <p className="mt-2 text-sm leading-6 text-neutral-700">
                {humanStatus?.goal || "Run a heartbeat to load the current master-agent goal."}
              </p>
            </div>
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                <Bot className="h-4 w-4" />
                Current focus
              </div>
              <p className="mt-2 text-sm leading-6 text-neutral-700">
                {humanStatus?.current_focus || "Waiting for a current heartbeat."}
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                <ListChecks className="h-4 w-4" />
                Intended next moves
              </div>
              <ul className="mt-2 space-y-2 text-sm leading-6 text-neutral-700">
                {(humanStatus?.intended_next_steps?.length
                  ? humanStatus.intended_next_steps
                  : ["Run a heartbeat to load the current intent."]).map((step) => (
                  <li key={step} className="flex gap-2">
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-400" />
                    <span>{step}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                What I need from Pranav
              </div>
              <p className="mt-2 text-sm leading-6 text-neutral-700">
                {humanStatus?.needs_from_user || "Nothing yet. Run a heartbeat to refresh this."}
              </p>
            </div>
            <div className="text-xs leading-5 text-neutral-500">
              {humanStatus?.confidence || "Confidence will appear after the first heartbeat with the new status packet."}
            </div>
            {statusLlm?.error && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">
                OpenClaw status call failed, so this update used deterministic fallback: {statusLlm.error}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Recent durable actions</h2>
          <span className="text-xs text-neutral-400">what the master agent can see about approved work and sends</span>
        </div>
        <div className="divide-y divide-neutral-100">
          {recentActionRows.length === 0 && (
            <div className="px-4 py-5 text-sm text-neutral-500">
              Run a heartbeat to load recent durable actions.
            </div>
          )}
          {recentActionRows.map((action) => {
            const input = objectValue(action.input_summary);
            const policy = objectValue(action.policy_summary);
            const result = objectValue(action.result_summary);
            const status = stringValue(action.status);
            return (
              <div key={stringValue(action.id)} className="grid gap-3 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)_12rem]">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn(
                      "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                      status === "succeeded"
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : status === "failed"
                          ? "border-red-200 bg-red-50 text-red-700"
                          : status === "approved"
                            ? "border-amber-200 bg-amber-50 text-amber-700"
                            : "border-neutral-200 bg-neutral-50 text-neutral-700",
                    )}>
                      {status || "unknown"}
                    </span>
                    <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[11px] text-neutral-600">
                      {stringValue(action.action_type)}
                    </span>
                    <span className="font-mono text-[11px] text-neutral-400">{stringValue(action.id)}</span>
                  </div>
                  <div className="mt-2 truncate text-sm font-semibold text-neutral-950">
                    {stringValue(input.subject) || stringValue(result.sent_subject) || "No subject"}
                  </div>
                  <div className="mt-1 text-xs text-neutral-500">
                    to {stringValue(input.to) || stringValue(result.sent_to) || "-"}
                  </div>
                </div>
                <div className="grid gap-2 text-xs text-neutral-600 sm:grid-cols-2">
                  <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-2">
                    <div className="font-semibold text-neutral-800">Policy</div>
                    <div className="mt-1">
                      {policy.allowed === true ? "allowed" : policy.allowed === false ? "blocked" : "not checked"}
                      {stringValue(policy.reason) ? ` · ${stringValue(policy.reason)}` : ""}
                    </div>
                  </div>
                  <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-2">
                    <div className="font-semibold text-neutral-800">Send evidence</div>
                    <div className="mt-1">
                      {stringValue(result.email_log_id) || "no email log linked"}
                    </div>
                    <div className="mt-1 text-neutral-500">
                      {stringValue(result.transport) || "-"} {stringValue(result.email_log_status) || ""}
                    </div>
                  </div>
                </div>
                <div className="text-xs text-neutral-500 lg:text-right">
                  <div>created {shortDate(stringValue(action.created_at))}</div>
                  <div>completed {shortDate(stringValue(action.completed_at))}</div>
                  {stringValue(result.sent_message_id) && (
                    <div className="mt-1 truncate font-mono text-[10px] text-neutral-400" title={stringValue(result.sent_message_id)}>
                      {stringValue(result.sent_message_id)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Wake-up context</h2>
          <span className="text-xs text-neutral-400">
            v2 packet: cached static context plus volatile wake state
          </span>
        </div>
        <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div className="space-y-3 text-sm leading-6 text-neutral-700">
            <p>
              This is the context the heartbeat builds when it wakes up. The status writer receives this
              packet, plus stable compact soul context, through the OpenClaw gateway when enabled.
            </p>
            <div className="grid gap-2 text-xs">
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Operating goal</div>
                <div className="mt-1 text-neutral-500">
                  {stringValue(objectValue(objectValue(volatileWakeState.goal_stack).short_term).goal)
                    || stringValue(objectValue(objectValue(volatileWakeState.goal_stack).long_term).goal)
                    || "-"}
                </div>
                <div className="mt-2 text-[11px] text-neutral-400">
                  {stringValue(objectValue(objectValue(volatileWakeState.goal_stack).short_term).source)
                    || stringValue(objectValue(objectValue(volatileWakeState.goal_stack).long_term).source)}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Loaded at</div>
                <div className="mt-1 text-neutral-500">
                  {stringValue(volatileWakeState.woke_at) ? shortDate(stringValue(volatileWakeState.woke_at)) : "-"}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Protected context</div>
                <div className="mt-1 text-neutral-500">
                  {heartbeat?.soul?.loaded === true ? "soul.md loaded read-only" : "soul.md not loaded"}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Cached prefix</div>
                <div className="mt-1 font-mono text-[11px] text-neutral-500">
                  {stringValue(objectValue(cachedStaticContext.cache_design).hash).slice(0, 16) || "-"}
                </div>
                <div className="mt-1 text-[11px] text-neutral-400">
                  {Array.isArray(cachedStaticContext.prime_directives)
                    ? `${cachedStaticContext.prime_directives.length} prime directives`
                    : "not loaded"}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">OpenAI cache telemetry</div>
                <div className="mt-1 text-neutral-500">
                  {typeof statusLlm?.cached_tokens === "number"
                    ? `${statusLlm.cached_tokens.toLocaleString()} cached tokens`
                    : "not returned"}
                </div>
                <div className="mt-1 text-[11px] text-neutral-400">
                  {stringValue(objectValue(statusLlm?.prompt_cache).cache_key) || "possible-os-master-agent-v1"}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Volatile state</div>
                <div className="mt-1 text-neutral-500">
                  {stringValue(volatileWakeState.woke_at) ? shortDate(stringValue(volatileWakeState.woke_at)) : "-"}
                </div>
                <div className="mt-1 text-[11px] text-neutral-400">
                  {Object.keys(volatileWakeState).length ? `${Object.keys(volatileWakeState).length} fields` : "not loaded"}
                </div>
              </div>
            </div>
          </div>
          <details className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-600" open>
            <summary className="cursor-pointer select-none font-semibold text-neutral-800">
              Parsed context JSON
            </summary>
            <div className="mt-3 max-h-[520px] overflow-auto rounded-md bg-white p-2">
              <JsonTree value={wakeContext || {}} label="wake_context" />
            </div>
          </details>
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Recent agent activity</h2>
          <span className="text-xs text-neutral-400">
            heartbeat ticks, task creation, status changes, reports
          </span>
          <button
            type="button"
            onClick={() => activity.refetch()}
            disabled={activity.isFetching}
            className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {activity.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh activity
          </button>
        </div>
        <div className="border-b border-neutral-100 px-4 py-3">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {ACTIVITY_FILTERS.map((filter) => (
              <button
                key={filter.key}
                type="button"
                onClick={() => setActivityFilter(filter.key)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                  activityFilter === filter.key
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50 hover:text-neutral-950",
                )}
              >
                <span>{filter.label}</span>
                <span className={cn(
                  "rounded-full px-1.5 py-0.5 text-[10px]",
                  activityFilter === filter.key ? "bg-white/15 text-white" : "bg-neutral-100 text-neutral-500",
                )}>
                  {activityCounts[filter.key] ?? 0}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="divide-y divide-neutral-100">
          {activity.isLoading && (
            <div className="flex items-center gap-2 px-4 py-4 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading activity...
            </div>
          )}
          {activity.isError && (
            <div className="px-4 py-4 text-sm text-red-700">
              Could not load recent agent activity. Try refreshing the activity feed.
            </div>
          )}
          {!activity.isLoading && (activity.data?.events ?? []).length === 0 && (
            <div className="px-4 py-5 text-sm text-neutral-500">
              No agent activity has been recorded yet.
            </div>
          )}
          {!activity.isLoading && activityRows.length > 0 && filteredActivityRows.length === 0 && (
            <div className="px-4 py-5 text-sm text-neutral-500">
              No activity matches this filter.
            </div>
          )}
          {filteredActivityRows.map((event) => (
            <div key={event.id} className="grid gap-2 px-4 py-3 sm:grid-cols-[12rem_minmax(0,1fr)_10rem]">
              <div className="text-xs text-neutral-500">
                <div className="font-medium text-neutral-800">{shortDate(event.created_at)}</div>
                <div>{event.agent_id}</div>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-neutral-200 bg-white px-2 py-0.5 text-[11px] font-medium capitalize text-neutral-500">
                    {activityCategory(event.event_type)}
                  </span>
                  <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", eventTone(event.event_type))}>
                    {event.event_type}
                  </span>
                  {event.task_id && (
                    <button
                      type="button"
                      onClick={() => setSelectedTaskId(event.task_id || "")}
                      className="truncate text-xs font-medium text-neutral-600 underline decoration-neutral-300 underline-offset-2 hover:text-neutral-950"
                    >
                      {event.task_id}
                    </button>
                  )}
                </div>
                <p className="mt-1 truncate text-sm text-neutral-700">{activitySummary(event)}</p>
                {event.event_type === "agent_config_updated" ? (
                  <p className="mt-1 text-[11px] text-amber-700">
                    Configuration change, not a heartbeat run.
                  </p>
                ) : null}
                {event.has_payload && (
                  <p className="mt-1 text-[11px] text-neutral-400">
                    JSON available · {Math.max(1, Math.round(event.payload_size_bytes / 1024))} KB
                  </p>
                )}
              </div>
              {event.has_payload ? (
                <div className="flex flex-wrap justify-start gap-2 sm:justify-end">
                  <button
                    type="button"
                    onClick={() => void openEventJson(event)}
                    disabled={loadingJsonEventId === event.id}
                    className="inline-flex items-center justify-center gap-2 rounded-md border border-neutral-900 bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {loadingJsonEventId === event.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    View JSON
                  </button>
                </div>
              ) : (
                <div className="text-xs text-neutral-400 sm:text-right">No JSON payload</div>
              )}
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="rounded-xl border border-neutral-200 bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-neutral-950">Subagent tasks</h2>
            <span className="text-xs text-neutral-400">{counts.total} shown</span>
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="ml-auto h-8 rounded-md border border-neutral-200 bg-white px-2 text-xs text-neutral-700"
            >
              <option value="all">All statuses</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="blocked">Blocked</option>
              <option value="stale">Stale</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
          </div>
          <div className="space-y-2 p-3">
            {tasks.isLoading && (
              <div className="flex items-center gap-2 rounded-lg border border-neutral-200 p-3 text-sm text-neutral-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading tasks...
              </div>
            )}
            {!tasks.isLoading && allTasks.length === 0 && (
              <div className="rounded-lg border border-dashed border-neutral-200 p-5 text-sm text-neutral-500">
                No tasks yet. Create a ResearchScout task to start the first safe subagent loop.
              </div>
            )}
            {allTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                selected={selectedTaskId === task.id}
                onSelect={() => setSelectedTaskId(task.id)}
              />
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-neutral-200 bg-white">
          <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-neutral-950">Task detail</h2>
            {selectedTask.data?.task && (
              <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", statusTone(selectedTask.data.task.status))}>
                {selectedTask.data.task.status}
              </span>
            )}
            {selectedTask.data?.task && selectedTask.data.task.status !== "completed" && (
              <button
                type="button"
                onClick={() => setDone.mutate(selectedTask.data.task.id)}
                disabled={setDone.isPending}
                className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
              >
                {setDone.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                Mark complete
              </button>
            )}
          </div>

          {!selectedTaskId && (
            <div className="p-5 text-sm text-neutral-500">
              Select a task to inspect objective, boundaries, reports, and events.
            </div>
          )}

          {selectedTaskId && selectedTask.isLoading && (
            <div className="flex items-center gap-2 p-5 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading task...
            </div>
          )}

          {selectedTask.data?.task && (
            <div className="space-y-4 p-4">
              <div>
                <div className="flex items-center gap-2 text-sm font-semibold text-neutral-950">
                  <Bot className="h-4 w-4" />
                  {selectedTask.data.task.title}
                </div>
                <p className="mt-2 text-sm leading-6 text-neutral-600">
                  {selectedTask.data.task.objective}
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-neutral-200 p-3 text-xs">
                  <div className="font-semibold text-neutral-800">Boundaries</div>
                  <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-neutral-500">
                    {jsonPreview({
                      allowed_tools: selectedTask.data.task.allowed_tools,
                      forbidden_actions: selectedTask.data.task.forbidden_actions,
                      risk_level: selectedTask.data.task.risk_level,
                    })}
                  </pre>
                </div>
                <div className="rounded-lg border border-neutral-200 p-3 text-xs">
                  <div className="font-semibold text-neutral-800">Acceptance</div>
                  <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-neutral-500">
                    {jsonPreview(selectedTask.data.task.acceptance_criteria)}
                  </pre>
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-neutral-950">
                  <FileText className="h-4 w-4" />
                  Reports
                </div>
                <div className="space-y-2">
                  {selectedTask.data.reports.length === 0 && (
                    <div className="rounded-lg border border-dashed border-neutral-200 p-3 text-sm text-neutral-500">
                      No reports yet.
                    </div>
                  )}
                  {selectedTask.data.reports.map((report) => (
                    <div key={report.id} className="rounded-lg border border-neutral-200 p-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                        <span className="font-medium text-neutral-800">{report.agent_id}</span>
                        <span>{report.status}</span>
                        <span>{shortDate(report.created_at)}</span>
                      </div>
                      <p className="mt-2 text-sm text-neutral-700">{report.summary || "No summary."}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-neutral-950">
                  <Clock3 className="h-4 w-4" />
                  Recent events
                </div>
                <div className="space-y-2">
                  {selectedTask.data.events.map((event) => (
                    <div key={event.id} className="rounded-lg border border-neutral-200 p-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                        <span className="font-medium text-neutral-800">{event.event_type}</span>
                        <span>{event.agent_id}</span>
                        <span>{shortDate(event.created_at)}</span>
                      </div>
                      {event.message && <p className="mt-2 text-sm text-neutral-700">{event.message}</p>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>
      {jsonModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-3">
          <div className="flex max-h-[92vh] w-full max-w-7xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
            <div className="border-b border-neutral-100 px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-sm font-semibold text-neutral-950">Agent Event JSON</h2>
                    <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 font-mono text-[11px] text-neutral-500">
                      event #{jsonModal.eventId}
                    </span>
                    <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[11px] text-neutral-500">
                      {jsonModal.agentId}
                    </span>
                    <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[11px] text-neutral-500">
                      {jsonModal.eventType}
                    </span>
                    <span className={cn(
                      "rounded-full border px-2 py-0.5 font-mono text-[11px]",
                      jsonModalHasV2
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                        : "border-amber-200 bg-amber-50 text-amber-700",
                    )}>
                      {jsonModalKind || "unknown context"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-neutral-500">
                    {shortDate(jsonModal.createdAt)} · input is what the event received; output is what it produced.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="inline-flex rounded-md border border-neutral-200 bg-neutral-50 p-0.5">
                    <button
                      type="button"
                      onClick={() => setJsonDisplayMode("parsed")}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-medium",
                        jsonDisplayMode === "parsed" ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-500 hover:text-neutral-800",
                      )}
                    >
                      <Braces className="h-3.5 w-3.5" />
                      Parsed
                    </button>
                    <button
                      type="button"
                      onClick={() => setJsonDisplayMode("raw")}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-medium",
                        jsonDisplayMode === "raw" ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-500 hover:text-neutral-800",
                      )}
                    >
                      <Code2 className="h-3.5 w-3.5" />
                      Raw
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => setJsonModal(null)}
                    className="rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
                  >
                    Close
                  </button>
                </div>
              </div>
              <div className="mt-3 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs leading-5 text-neutral-600">
                {jsonModal.summary}
              </div>
            </div>
            <div className="grid min-h-0 min-w-0 flex-1 gap-0 bg-neutral-100 lg:grid-cols-2">
              <JsonModalPanel
                title="Input"
                description={jsonModal.eventType === "master_heartbeat_completed"
                  ? "Wake context loaded before the status decision."
                  : "Payload captured before this event ran."}
                badge="event.input"
                value={jsonModal.input || {}}
                mode={jsonDisplayMode}
                copied={copiedJsonPanel === "input"}
                onCopy={() => copyJsonPanel("input", jsonModal.input || {})}
              />
              <JsonModalPanel
                title="Output"
                description={jsonModal.eventType === "master_heartbeat_completed"
                  ? "Counts, human status, goal state, and execution results."
                  : "Payload captured after this event ran."}
                badge="event.output"
                value={jsonModal.output || {}}
                mode={jsonDisplayMode}
                copied={copiedJsonPanel === "output"}
                onCopy={() => copyJsonPanel("output", jsonModal.output || {})}
              />
            </div>
            {jsonModal.metadata && Object.keys(jsonModal.metadata).length > 0 && (
              <details className="border-t border-neutral-100 bg-white px-4 py-2 text-xs">
                <summary className="cursor-pointer select-none font-semibold text-neutral-700">
                  Metadata
                </summary>
                <div className="mt-2 max-h-52 min-w-0 overflow-auto rounded-md border border-neutral-200 bg-neutral-50 p-2">
                  <div className="mb-2 flex justify-end">
                    <button
                      type="button"
                      onClick={() => copyJsonPanel("metadata", jsonModal.metadata || {})}
                      className="inline-flex items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
                    >
                      {copiedJsonPanel === "metadata" ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Clipboard className="h-3.5 w-3.5" />}
                      {copiedJsonPanel === "metadata" ? "Copied" : "Copy JSON"}
                    </button>
                  </div>
                  {jsonDisplayMode === "raw" ? (
                    <pre className="w-max min-w-full rounded-lg border border-neutral-200 bg-neutral-950 p-3 font-mono text-[11px] leading-5 text-neutral-100">
                      {jsonPreview(jsonModal.metadata, "metadata")}
                    </pre>
                  ) : (
                    <JsonTree value={orderedJsonValue(jsonModal.metadata, "metadata")} label="metadata" />
                  )}
                </div>
              </details>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
