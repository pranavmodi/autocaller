"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
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

function jsonPreview(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function jsonNodeSummary(value: unknown) {
  if (Array.isArray(value)) return `Array(${value.length})`;
  if (value && typeof value === "object") return `Object(${Object.keys(value).length})`;
  if (typeof value === "string") return `"${value}"`;
  if (value === null) return "null";
  return String(value);
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
  const expandable = value !== null && typeof value === "object";
  if (!expandable) {
    return (
      <div className="grid grid-cols-[minmax(120px,0.25fr)_minmax(0,1fr)] gap-3 border-b border-neutral-100 py-1.5">
        <span className="truncate font-medium text-neutral-600">{label}</span>
        <span className="min-w-0 whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-neutral-800">
          {jsonNodeSummary(value)}
        </span>
      </div>
    );
  }

  const entries = Array.isArray(value)
    ? value.map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>);

  return (
    <details
      className={cn("group rounded-md border border-neutral-100 bg-white", depth > 0 ? "mt-1" : "")}
      open={defaultOpen}
    >
      <summary className="flex cursor-pointer select-none items-center gap-2 px-2 py-1.5 text-xs hover:bg-neutral-50">
        <ChevronRight className="h-3.5 w-3.5 text-neutral-400 group-open:hidden" />
        <ChevronDown className="hidden h-3.5 w-3.5 text-neutral-400 group-open:block" />
        <span className="font-semibold text-neutral-800">{label}</span>
        <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 font-mono text-[10px] text-neutral-500">
          {jsonNodeSummary(value)}
        </span>
      </summary>
      <div className="space-y-1 border-t border-neutral-100 px-2 py-2" style={{ marginLeft: Math.min(depth, 4) * 10 }}>
        {entries.length === 0 ? (
          <div className="font-mono text-[11px] text-neutral-400">empty</div>
        ) : (
          entries.map(([key, child]) => (
            <JsonTree
              key={`${depth}-${key}`}
              label={key}
              value={child}
              depth={depth + 1}
              defaultOpen={depth === 0 && ["mission", "configuration", "current_tasks"].includes(key)}
            />
          ))
        )}
      </div>
    </details>
  );
}

function activitySummary(event: AgentTaskEvent) {
  const output = event.output || {};
  if (event.event_type === "master_heartbeat_completed") {
    const humanStatus = output.human_status as { state?: unknown } | undefined;
    if (typeof humanStatus?.state === "string" && humanStatus.state.trim()) {
      return humanStatus.state;
    }
    return `active ${output.active_task_count ?? 0}, queued ${output.queued_task_count ?? 0}, blocked ${output.blocked_task_count ?? 0}`;
  }
  if (event.event_type === "task_created") {
    const input = event.input || {};
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
  const [heartbeatEnabledDraft, setHeartbeatEnabledDraft] = useState(true);
  const [heartbeatIntervalDraft, setHeartbeatIntervalDraft] = useState("300");

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
  const statusLlm = heartbeat?.status_llm;
  const activeGoal = heartbeat?.active_goal || goals.data?.goals?.[0] || null;
  const queueAnalysis = heartbeat?.queue_analysis || {};
  const staleQueueItems = Array.isArray(queueAnalysis.stale_queue_items)
    ? queueAnalysis.stale_queue_items
    : [];
  const capabilityRows = capabilities.data?.capabilities ?? [];
  useEffect(() => {
    if (!status.data) return;
    setHeartbeatEnabledDraft(status.data.heartbeat_enabled);
    setHeartbeatIntervalDraft(String(status.data.heartbeat_interval_seconds));
  }, [status.data?.heartbeat_enabled, status.data?.heartbeat_interval_seconds]);
  const heartbeatIntervalNumber = Number(heartbeatIntervalDraft);
  const heartbeatConfigValid =
    Number.isFinite(heartbeatIntervalNumber) &&
    heartbeatIntervalNumber >= 60 &&
    heartbeatIntervalNumber <= 3600;
  const heartbeatConfigDirty =
    Boolean(status.data) &&
    (heartbeatEnabledDraft !== status.data?.heartbeat_enabled ||
      heartbeatIntervalDraft !== String(status.data?.heartbeat_interval_seconds ?? ""));

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
              checks active subagent tasks, and marks stale workers. It does not edit `soul.md`
              or execute external actions.
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
          <div className="rounded-lg border border-neutral-200 p-3 sm:col-span-2 lg:col-span-2">
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
              The Enabled checkbox saves immediately. Period changes use Save. Allowed range: 60-3600 seconds.
            </div>
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
          <h2 className="text-sm font-semibold text-neutral-950">Wake-up context</h2>
          <span className="text-xs text-neutral-400">
            complete V1 context packet loaded by the heartbeat
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
                <div className="font-semibold text-neutral-800">Mission</div>
                <div className="mt-1 text-neutral-500">
                  {typeof wakeContext?.mission === "object" && wakeContext?.mission !== null
                    ? String((wakeContext.mission as Record<string, unknown>).goal || "-")
                    : "-"}
                </div>
                <div className="mt-2 text-[11px] text-neutral-400">
                  {typeof wakeContext?.mission === "object" && wakeContext?.mission !== null
                    ? String((wakeContext.mission as Record<string, unknown>).goal_source || "")
                    : ""}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Loaded at</div>
                <div className="mt-1 text-neutral-500">
                  {typeof wakeContext?.woke_at === "string" ? shortDate(wakeContext.woke_at) : "-"}
                </div>
              </div>
              <div className="rounded-lg border border-neutral-200 p-3">
                <div className="font-semibold text-neutral-800">Protected context</div>
                <div className="mt-1 text-neutral-500">
                  {heartbeat?.soul?.loaded === true ? "soul.md loaded read-only" : "soul.md not loaded"}
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
        <div className="divide-y divide-neutral-100">
          {activity.isLoading && (
            <div className="flex items-center gap-2 px-4 py-4 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading activity...
            </div>
          )}
          {!activity.isLoading && (activity.data?.events ?? []).length === 0 && (
            <div className="px-4 py-5 text-sm text-neutral-500">
              No agent activity has been recorded yet.
            </div>
          )}
          {(activity.data?.events ?? []).map((event) => (
            <div key={event.id} className="grid gap-2 px-4 py-3 sm:grid-cols-[12rem_minmax(0,1fr)_10rem]">
              <div className="text-xs text-neutral-500">
                <div className="font-medium text-neutral-800">{shortDate(event.created_at)}</div>
                <div>{event.agent_id}</div>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-0.5 text-[11px] font-medium text-neutral-700">
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
              </div>
              <details className="text-xs text-neutral-500">
                <summary className="cursor-pointer select-none text-right font-medium text-neutral-600">
                  JSON
                </summary>
                <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-neutral-50 p-2 text-left">
                  {jsonPreview({ input: event.input, output: event.output, metadata: event.metadata })}
                </pre>
              </details>
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
    </div>
  );
}
