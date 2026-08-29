"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Braces,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Code2,
  Copy,
  DatabaseZap,
  ExternalLink,
  FileText,
  History,
  List,
  Loader2,
  Pause,
  Play,
  Search,
  Sparkles,
  Users,
  Wrench,
} from "lucide-react";
import {
  createLeadFinderRun,
  getLeadFinderContext,
  getLeadFinderLLMSession,
  getLeadFinderRun,
  listLeadFinderRuns,
  queueLeadFinderStep,
  resetAllLeadFinderRuns,
  startLeadFinderAutoRun,
  stopLeadFinderAutoRun,
  updateLeadFinderLLMProvider,
  type LeadFinderContext,
  type LeadFinderFoundLead,
  type LeadFinderLLMSessionRaw,
  type LeadFinderPersistedStep,
  type LeadFinderRun,
} from "@/lib/api";

const ACTIVE_STATUSES = new Set(["queued", "running", "retrying"]);

function newRequestId() {
  const value = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "")
    : `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `lfreq_${value}`.slice(0, 64);
}

function JsonPanel({ value }: { value: unknown }) {
  return (
    <div className="max-h-[38rem] overflow-auto rounded-xl bg-neutral-950 p-4 font-mono text-xs leading-5 text-neutral-200">
      <JsonTreeNode value={value} />
    </div>
  );
}

type JsonlRecord = {
  line: number;
  raw: string;
  value: unknown;
  error: string | null;
};

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function parseEmbeddedJson(value: string): unknown | null {
  const trimmed = value.trim();
  let candidate = trimmed;
  if (trimmed.startsWith("```") && trimmed.endsWith("```")) {
    candidate = trimmed.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  }
  if (!(candidate.startsWith("{") || candidate.startsWith("["))) return null;
  try {
    const parsed = JSON.parse(candidate) as unknown;
    return parsed !== null && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function JsonTextPanel({ text, className = "" }: { text: string; className?: string }) {
  const parsed = parseEmbeddedJson(text);
  if (parsed !== null) return <JsonPanel value={parsed} />;
  return <pre className={`max-h-80 overflow-auto whitespace-pre-wrap p-4 text-xs leading-5 ${className}`}>{text}</pre>;
}

function parseJsonl(raw: string): JsonlRecord[] {
  return raw.split(/\r?\n/).reduce<JsonlRecord[]>((records, line, index) => {
    if (!line.trim()) return records;
    try {
      records.push({ line: index + 1, raw: line, value: JSON.parse(line) as unknown, error: null });
    } catch (cause) {
      records.push({
        line: index + 1,
        raw: line,
        value: line,
        error: cause instanceof Error ? cause.message : "Invalid JSON record",
      });
    }
    return records;
  }, []);
}

function JsonScalar({ label, value }: { label?: string; value: unknown }) {
  const prefix = label === undefined ? null : <span className="text-sky-300">{label}: </span>;
  if (value === null) return <div>{prefix}<span className="text-rose-300">null</span></div>;
  if (typeof value === "boolean") return <div>{prefix}<span className="text-amber-300">{String(value)}</span></div>;
  if (typeof value === "number") return <div>{prefix}<span className="text-cyan-300">{String(value)}</span></div>;
  const text = String(value);
  if (text.includes("\n") || text.length > 180) {
    return (
      <div className="min-w-0">
        <div>{prefix}<span className="text-emerald-300">string · {text.length.toLocaleString()} chars</span></div>
        <pre className="mt-1 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black/25 p-2 text-emerald-200">{text}</pre>
      </div>
    );
  }
  return <div className="break-words">{prefix}<span className="text-emerald-300">{JSON.stringify(text)}</span></div>;
}

function JsonTreeNode({ label, value, depth = 0 }: { label?: string; value: unknown; depth?: number }) {
  const embeddedJson = typeof value === "string" ? parseEmbeddedJson(value) : null;
  const isContainer = Array.isArray(value) || objectValue(value) !== null;
  const [isOpen, setIsOpen] = useState(embeddedJson === null && isContainer && depth === 0);
  if (embeddedJson !== null) {
    const embeddedEntries = Array.isArray(embeddedJson)
      ? embeddedJson.length
      : Object.keys(objectValue(embeddedJson) || {}).length;
    const embeddedKind = Array.isArray(embeddedJson)
      ? `Array(${embeddedEntries})`
      : `Object(${embeddedEntries})`;
    return (
      <details open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)} className="min-w-0">
        <summary className="cursor-pointer select-none list-none py-0.5 text-neutral-300 marker:hidden">
          <span className={`mr-1 inline-block w-3 text-neutral-500 transition-transform ${isOpen ? "rotate-90" : ""}`}>▶</span>
          {label !== undefined && <span className="text-sky-300">{label}: </span>}
          <span className="text-amber-300">JSON string</span>
          <span className="text-neutral-500"> → </span>
          <span className="text-violet-300">{embeddedKind}</span>
        </summary>
        <div className="ml-2 border-l border-amber-900/60 pl-3">
          <JsonTreeNode value={embeddedJson} depth={0} />
        </div>
      </details>
    );
  }
  const isArray = Array.isArray(value);
  const object = objectValue(value);
  if (!isArray && !object) return <JsonScalar label={label} value={value} />;
  const entries = isArray
    ? value.map((item, index) => [String(index), item] as const)
    : Object.entries(object || {});
  const kind = isArray ? `Array(${entries.length})` : `Object(${entries.length})`;
  return (
    <details open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)} className="min-w-0">
      <summary className="cursor-pointer select-none list-none py-0.5 text-neutral-300 marker:hidden">
        <span className={`mr-1 inline-block w-3 text-neutral-500 transition-transform ${isOpen ? "rotate-90" : ""}`}>▶</span>
        {label !== undefined && <span className="text-sky-300">{label}: </span>}
        <span className="text-violet-300">{kind}</span>
      </summary>
      <div className="ml-2 space-y-0.5 border-l border-neutral-700 pl-3">
        {entries.map(([key, item]) => (
          <JsonTreeNode key={key} label={key} value={item} depth={depth + 1} />
        ))}
      </div>
    </details>
  );
}

function jsonlRecordLabel(record: JsonlRecord): string {
  const root = objectValue(record.value);
  if (!root) return record.error ? "Invalid JSON" : "JSON value";
  const message = objectValue(root.message);
  const parts = [String(root.type || "record")];
  if (message?.role) parts.push(String(message.role));
  if (root.seq !== undefined) parts.push(`seq ${String(root.seq)}`);
  if (root.ts || root.timestamp) parts.push(String(root.ts || root.timestamp));
  return parts.join(" · ");
}

function shortDate(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function stepTone(status: string) {
  if (status === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "failed" || status === "interrupted") return "border-red-200 bg-red-50 text-red-700";
  if (status === "running" || status === "retrying" || status === "queued") return "border-sky-200 bg-sky-50 text-sky-700";
  return "border-neutral-200 bg-neutral-50 text-neutral-600";
}

function toolResultSummary(toolCall: LeadFinderPersistedStep["tool_calls"][number]) {
  if (toolCall.error) return toolCall.error;
  const result = objectValue(toolCall.result) || {};
  const lead = objectValue(result.lead);
  const person = objectValue(result.person);
  if (lead) return `Added ${String(lead.name || "researched lead")} to Found Leads.`;
  if (person) {
    const confidence = Number(person.identity_confidence);
    const suffix = Number.isFinite(confidence) ? ` · ${Math.round(confidence * 100)}% identity confidence` : "";
    return `Verified ${String(person.name || "candidate")}${suffix}.`;
  }
  if (Array.isArray(result.results)) return `Returned ${result.results.length} search result${result.results.length === 1 ? "" : "s"}.`;
  if (Array.isArray(result.passages)) return `Retrieved ${result.passages.length} transcript passage${result.passages.length === 1 ? "" : "s"}.`;
  if (toolCall.status === "running") return "Tool is running…";
  return toolCall.status === "completed" ? "Result persisted." : `Tool ${toolCall.status}.`;
}

function toolProviderSummary(
  toolCall: LeadFinderPersistedStep["tool_calls"][number],
) {
  if (toolCall.tool_name !== "web.research_person") return "";
  const result = objectValue(toolCall.result) || {};
  const metadata = objectValue(result._meta) || {};
  const provider = String(metadata.provider || "");
  const model = String(metadata.model || "");
  if (!provider && !model) return "";
  const label = provider === "openai"
    ? "Direct OpenAI"
    : provider === "openclaw" ? "OpenClaw gateway" : "Web research";
  return model ? `${label} · ${model}` : label;
}

function stepProviderLabel(
  step: LeadFinderPersistedStep,
  runProvider: LeadFinderRun["llm_provider"] | undefined,
) {
  if (step.model?.startsWith("openclaw/")) return "OpenClaw";
  if (step.model) return "Direct OpenAI";
  return runProvider === "openclaw" ? "OpenClaw" : "Direct OpenAI";
}

export default function LeadFinderPage() {
  const [baseline, setBaseline] = useState<LeadFinderContext | null>(null);
  const [runs, setRuns] = useState<LeadFinderRun[]>([]);
  const [run, setRun] = useState<LeadFinderRun | null>(null);
  const [userDirection, setUserDirection] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [autoChanging, setAutoChanging] = useState(false);
  const [providerChanging, setProviderChanging] = useState(false);
  const [resettingAll, setResettingAll] = useState(false);
  const [error, setError] = useState("");
  const [activeView, setActiveView] = useState<"runs" | "overview" | "context" | "session" | "leads" | "history">("overview");
  const [llmSession, setLlmSession] = useState<LeadFinderLLMSessionRaw | null>(null);
  const [llmSessionSource, setLlmSessionSource] = useState<"session" | "trajectory">("session");
  const [llmSessionDisplay, setLlmSessionDisplay] = useState<"readable" | "raw">("readable");
  const [llmSessionLoading, setLlmSessionLoading] = useState(false);
  const [llmSessionError, setLlmSessionError] = useState("");
  const submissionLock = useRef(false);
  const llmSessionTree = useRef<HTMLDivElement>(null);

  const loadRun = useCallback(async (runId: string) => {
    const response = await getLeadFinderRun(runId);
    setRun(response.run);
    setUserDirection(response.run.user_direction || "");
    return response.run;
  }, []);

  const refreshRuns = useCallback(async () => {
    const response = await listLeadFinderRuns();
    setRuns(response.runs);
    return response.runs;
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      setLoading(true);
      setError("");
      try {
        const [contextResponse, existingRuns] = await Promise.all([
          getLeadFinderContext(),
          refreshRuns(),
        ]);
        if (cancelled) return;
        setBaseline(contextResponse.context);
        if (existingRuns[0]) await loadRun(existingRuns[0].id);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Unable to load Lead Finder.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void bootstrap();
    return () => { cancelled = true; };
  }, [loadRun, refreshRuns]);

  useEffect(() => {
    if (!run || resettingAll || (!ACTIVE_STATUSES.has(run.status) && !run.auto_run_enabled)) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const updated = await getLeadFinderRun(run.id);
        if (cancelled) return;
        setRun(updated.run);
        if (!ACTIVE_STATUSES.has(updated.run.status)) {
          setSubmitting(false);
          submissionLock.current = false;
          void refreshRuns();
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Unable to refresh run status.");
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshRuns, resettingAll, run?.auto_run_enabled, run?.id, run?.status]);

  useEffect(() => {
    if (activeView !== "session" || !run) return;
    if (run.llm_provider === "openai") {
      setLlmSession(null);
      setLlmSessionError("");
      setLlmSessionLoading(false);
      return;
    }
    if (run.current_step === 0) {
      setLlmSession(null);
      setLlmSessionError("The OpenClaw session is created when step 1 starts.");
      return;
    }
    let cancelled = false;
    setLlmSessionLoading(true);
    setLlmSessionError("");
    void getLeadFinderLLMSession(run.id)
      .then((response) => {
        if (!cancelled) setLlmSession(response.session);
      })
      .catch((cause) => {
        if (!cancelled) {
          setLlmSession(null);
          setLlmSessionError(cause instanceof Error ? cause.message : "Unable to load the OpenClaw session.");
        }
      })
      .finally(() => {
        if (!cancelled) setLlmSessionLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeView, run?.current_step, run?.id, run?.llm_provider, run?.status]);

  const context = useMemo(() => {
    const source = run?.current_context || baseline;
    return source ? { ...source, user_direction: userDirection } : null;
  }, [baseline, run, userDirection]);
  const steps = run?.steps || [];
  const latestResponse = [...steps].reverse().find((step) => step.response_raw);
  const latestCache = [...steps].reverse().find((step) => step.prompt_cache)?.prompt_cache;
  const foundLeads = useMemo(() => {
    const value = context?.agent_state.working_state.found_leads;
    return Array.isArray(value) ? value as LeadFinderFoundLead[] : [];
  }, [context]);
  const files = Object.values(context?.baseline_context.files || {});
  const isActive = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const rawSessionText = llmSessionSource === "session"
    ? llmSession?.session_jsonl || ""
    : llmSession?.trajectory_jsonl || "";
  const rawSessionFile = llmSessionSource === "session"
    ? llmSession?.session_file
    : llmSession?.trajectory_file;
  const jsonlRecords = useMemo(() => parseJsonl(rawSessionText), [rawSessionText]);
  const directResponseTrace = useMemo(() => steps.flatMap((step) =>
    (step.attempts || [])
      .filter((attempt) => !attempt.model.startsWith("openclaw/"))
      .map((attempt) => ({
        step_number: step.step_number,
        attempt_number: attempt.attempt_number,
        status: attempt.status,
        model: attempt.model,
        request: attempt.request,
        provider_response: attempt.response_raw,
        parsed_response: attempt.response_parsed,
        usage: attempt.usage,
        started_at: attempt.started_at,
        completed_at: attempt.completed_at,
        error: attempt.error,
      })),
  ), [steps]);

  function setAllSessionNodes(open: boolean) {
    llmSessionTree.current?.querySelectorAll("details").forEach((node) => {
      node.open = open;
    });
  }

  async function startRun() {
    setError("");
    setSubmitting(true);
    try {
      const response = await createLeadFinderRun(
        userDirection,
        run?.llm_provider || "openai",
      );
      await loadRun(response.run.id);
      await refreshRuns();
      setActiveView("overview");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create run.");
    } finally {
      setSubmitting(false);
    }
  }

  async function doNextStep() {
    if (!run || run.auto_run_enabled || submissionLock.current || isActive) return;
    submissionLock.current = true;
    setSubmitting(true);
    setError("");
    try {
      await queueLeadFinderStep(run.id, newRequestId(), userDirection);
      const updated = await loadRun(run.id);
      if (!ACTIVE_STATUSES.has(updated.status)) {
        submissionLock.current = false;
        setSubmitting(false);
      }
      setActiveView("overview");
    } catch (cause) {
      submissionLock.current = false;
      setSubmitting(false);
      setError(cause instanceof Error ? cause.message : "Unable to queue the next step.");
    }
  }

  async function startAutoRun() {
    if (!run || run.auto_run_enabled || isActive || autoChanging) return;
    setAutoChanging(true);
    setError("");
    try {
      const response = await startLeadFinderAutoRun(run.id, userDirection, 25);
      setRun({ ...response.run, steps: run.steps });
      setActiveView("overview");
      void refreshRuns();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to start automatic execution.");
    } finally {
      setAutoChanging(false);
    }
  }

  async function stopAutoRun() {
    if (!run || !run.auto_run_enabled || autoChanging) return;
    setAutoChanging(true);
    setError("");
    try {
      const response = await stopLeadFinderAutoRun(run.id);
      setRun((current) => current ? { ...current, ...response.run, steps: current.steps } : response.run);
      void refreshRuns();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to stop automatic execution.");
    } finally {
      setAutoChanging(false);
    }
  }

  async function changeLLMProvider(provider: "openai" | "openclaw") {
    if (!run || providerChanging || run.llm_provider === provider) return;
    setProviderChanging(true);
    setError("");
    try {
      const response = await updateLeadFinderLLMProvider(run.id, provider);
      setRun((current) => current
        ? { ...current, ...response.run, steps: current.steps }
        : response.run);
      void refreshRuns();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to change the run-wide LLM provider.");
    } finally {
      setProviderChanging(false);
    }
  }

  async function deleteAllAndRestart() {
    if (resettingAll) return;
    const confirmed = window.confirm(
      "Delete every Lead Finder run, step, gateway attempt, and tool call? This cannot be undone.",
    );
    if (!confirmed) return;
    setResettingAll(true);
    setError("");
    try {
      const response = await resetAllLeadFinderRuns(
        userDirection,
        run?.llm_provider || "openai",
      );
      submissionLock.current = false;
      setSubmitting(false);
      setRun({ ...response.run, steps: [] });
      setRuns([response.run]);
      setUserDirection(response.run.user_direction || "");
      setActiveView("overview");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to delete Lead Finder runs.");
    } finally {
      setResettingAll(false);
    }
  }

  async function selectRun(runId: string) {
    setLoading(true);
    setError("");
    try {
      await loadRun(runId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load run.");
    } finally {
      setLoading(false);
    }
  }

  async function openRun(runId: string) {
    await selectRun(runId);
    setActiveView("overview");
  }

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500"><Search className="h-4 w-4" /> Lead Finder Agent</div>
            <h1 className="text-2xl font-semibold tracking-tight text-neutral-950">Debug workspace</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-600">
              Runs, requests, gateway attempts, raw responses, and context evolution are persisted in Postgres.
              Step manually for inspection, or run continuously through the same persisted transitions.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!run ? (
              <button type="button" onClick={startRun} disabled={loading || submitting}
                className="inline-flex items-center gap-2 rounded-lg bg-neutral-950 px-4 py-2.5 text-sm font-medium text-white disabled:bg-neutral-300">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Start debug run
              </button>
            ) : (
              <button type="button" onClick={doNextStep}
                disabled={submitting || isActive || run.auto_run_enabled || run.status === "completed" || run.status === "failed"}
                className="inline-flex items-center gap-2 rounded-lg bg-neutral-950 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-neutral-300">
                {isActive || submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
                {isActive ? "Agent step in progress…" : "Do next step"}
              </button>
            )}
            {run && run.auto_run_enabled ? (
              <button type="button" onClick={stopAutoRun} disabled={autoChanging}
                className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50">
                {autoChanging ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
                Stop after this step
              </button>
            ) : run && (
              <button type="button" onClick={startAutoRun}
                disabled={autoChanging || isActive || run.status === "completed" || run.status === "failed"}
                className="inline-flex items-center gap-2 rounded-lg bg-violet-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:bg-neutral-300">
                {autoChanging ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Run without pauses
              </button>
            )}
            {run && (
              <button type="button" onClick={startRun} disabled={loading || submitting || isActive || run.auto_run_enabled}
                className="inline-flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50">
                <Play className="h-4 w-4" /> New run
              </button>
            )}
            <button type="button" onClick={deleteAllAndRestart} disabled={loading || resettingAll || isActive || Boolean(run?.auto_run_enabled)}
              className="inline-flex items-center gap-2 rounded-lg border border-red-300 bg-white px-3 py-2.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">
              {resettingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <DatabaseZap className="h-4 w-4" />}
              Delete all &amp; restart
            </button>
          </div>
        </div>

        {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="mt-6 grid gap-4 border-t border-neutral-100 pt-5 sm:grid-cols-2 lg:grid-cols-6">
          <div>
            <div className="text-xs text-neutral-500">Persisted run</div>
            <select value={run?.id || ""} onChange={(event) => void selectRun(event.target.value)}
              className="mt-1 w-full rounded-lg border border-neutral-200 bg-white px-2 py-1.5 text-xs text-neutral-800">
              <option value="">No run selected</option>
              {runs.map((item) => <option key={item.id} value={item.id}>{item.id.slice(0, 16)} · {item.status} · step {item.current_step}</option>)}
            </select>
          </div>
          <div>
            <div className="text-xs text-neutral-500">Run status</div>
            <div className="mt-1 flex items-center gap-2 text-sm font-medium text-neutral-900">
              {isActive ? <Loader2 className="h-4 w-4 animate-spin text-sky-600" /> : <Pause className="h-4 w-4 text-amber-600" />}
              {run?.status || "ready"}
            </div>
          </div>
          <div>
            <div className="text-xs text-neutral-500">Execution mode</div>
            <div className="mt-1 text-sm font-medium text-neutral-900">
              {run?.auto_run_enabled
                ? `automatic · ${run.auto_run_steps_used}/${run.auto_run_max_steps}`
                : run?.auto_run_stop_reason === "step_limit_reached"
                  ? "paused · safety limit reached"
                  : "manual debug"}
            </div>
          </div>
          <div><div className="text-xs text-neutral-500">Completed step</div><div className="mt-1 text-sm font-medium text-neutral-900">{run?.current_step || 0}</div></div>
          <div>
            <label htmlFor="llm-provider" className="text-xs text-neutral-500">LLM provider</label>
            <select
              id="llm-provider"
              value={run?.llm_provider || "openai"}
              onChange={(event) => void changeLLMProvider(event.target.value as "openai" | "openclaw")}
              disabled={!run || providerChanging}
              className="mt-1 w-full rounded-lg border border-neutral-200 bg-white px-2 py-1.5 text-xs font-medium text-neutral-900 disabled:opacity-50"
            >
              <option value="openai">Direct OpenAI</option>
              <option value="openclaw">OpenClaw gateway</option>
            </select>
            <div className={`mt-1 truncate text-[10px] ${run?.llm_configured ? "text-neutral-400" : "text-red-600"}`}>
              {providerChanging
                ? "Saving…"
                : run?.llm_configured
                  ? `${run.llm_model} · reasoning + web research`
                  : `${run?.llm_model || "provider"} not configured`}
            </div>
          </div>
          <div>
            <div className="text-xs text-neutral-500">Prompt cache</div>
            <div className="mt-1 text-sm font-medium text-neutral-900">
              {latestCache?.status === "hit"
                ? `hit · ${(latestCache.cached_tokens || 0).toLocaleString()} tokens`
                : latestCache?.status === "miss" ? "cold · 0 cached" : "waiting for usage"}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <aside className="space-y-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
            <label htmlFor="lead-direction" className="text-sm font-semibold text-neutral-900">What kinds of leads are you looking for?</label>
            <p className="mt-1 text-xs leading-5 text-neutral-500">Saved when the run starts and with every step request.</p>
            <textarea id="lead-direction" value={userDirection} onChange={(event) => setUserDirection(event.target.value)} maxLength={10000}
              placeholder="Example: California PI firms with intake teams struggling with after-hours response."
              className="mt-3 min-h-36 w-full resize-y rounded-xl border border-neutral-200 px-3 py-2.5 text-sm outline-none placeholder:text-neutral-400 focus:border-neutral-500" />
            <div className="mt-2 text-right text-xs text-neutral-400">{userDirection.length.toLocaleString()} / 10,000</div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-neutral-900"><FileText className="h-4 w-4" /> Baseline snapshot</div>
            <div className="mt-3 space-y-2">
              {files.map((file) => (
                <details key={file.name} className="rounded-lg border border-neutral-200">
                  <summary className="cursor-pointer list-none px-3 py-2 text-sm font-medium text-neutral-700"><span className="flex items-center justify-between gap-2">{file.name}<CheckCircle2 className="h-4 w-4 text-emerald-600" /></span></summary>
                  <div className="max-h-64 overflow-auto whitespace-pre-wrap border-t border-neutral-200 p-3 text-xs leading-5 text-neutral-600">{file.content}</div>
                </details>
              ))}
            </div>
            {run && <div className="mt-3 break-all font-mono text-[10px] text-neutral-400">sha256 {run.baseline_context_hash}</div>}
          </div>

          {run?.restarted_from_run_id && (
            <div className="rounded-xl border border-violet-200 bg-violet-50 p-3 text-xs text-violet-800">
              Restarted at step 1 from <span className="font-mono">{run.restarted_from_run_id}</span>. The prior run remains intact.
            </div>
          )}
        </aside>

        <div className="min-w-0 rounded-2xl border border-neutral-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center gap-1 border-b border-neutral-200 p-2">
            <button type="button" onClick={() => setActiveView("runs")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "runs" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <List className="h-4 w-4" /> Runs <span className="rounded-full bg-white/15 px-1.5 text-xs">{runs.length}</span>
            </button>
            <button type="button" onClick={() => setActiveView("overview")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "overview" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <Activity className="h-4 w-4" /> Run overview
            </button>
            <button type="button" onClick={() => setActiveView("context")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "context" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <Braces className="h-4 w-4" /> Current context
            </button>
            <button type="button" onClick={() => setActiveView("session")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "session" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <Code2 className="h-4 w-4" /> LLM trace / session
            </button>
            <button type="button" onClick={() => setActiveView("history")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "history" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <History className="h-4 w-4" /> Persisted history <span className="rounded-full bg-white/15 px-1.5 text-xs">{steps.length}</span>
            </button>
            <button type="button" onClick={() => setActiveView("leads")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "leads" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <Users className="h-4 w-4" /> Found leads <span className="rounded-full bg-white/15 px-1.5 text-xs">{foundLeads.length}</span>
            </button>
          </div>

          <div className="p-4 sm:p-5">
            {activeView === "runs" ? (
              runs.length === 0 ? (
                <div className="flex min-h-72 flex-col items-center justify-center text-center">
                  <List className="h-8 w-8 text-neutral-300" />
                  <div className="mt-3 text-sm font-medium text-neutral-800">No persisted runs yet</div>
                  <p className="mt-1 max-w-md text-xs leading-5 text-neutral-500">Start a new run to create the first persisted Lead Finder session.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-neutral-950">Persisted runs</h2>
                      <p className="mt-1 text-xs leading-5 text-neutral-500">Newest first. Open a run to inspect its timeline, context, LLM trace, and found leads.</p>
                    </div>
                    <div className="text-xs text-neutral-400">Showing {runs.length} run{runs.length === 1 ? "" : "s"}</div>
                  </div>
                  <div className="overflow-hidden rounded-xl border border-neutral-200">
                    <div className="hidden grid-cols-[minmax(0,1.5fr)_7rem_9rem_5rem_8rem] gap-3 border-b border-neutral-200 bg-neutral-50 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-500 lg:grid">
                      <div>Run</div><div>Status</div><div>Provider</div><div>Steps</div><div>Updated</div>
                    </div>
                    <div className="divide-y divide-neutral-200">
                      {runs.map((item) => {
                        const isSelected = item.id === run?.id;
                        const itemLeads = item.current_context?.agent_state?.working_state?.found_leads;
                        const leadCount = Array.isArray(itemLeads) ? itemLeads.length : 0;
                        return (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => void openRun(item.id)}
                            className={`grid w-full gap-3 px-4 py-4 text-left transition-colors hover:bg-neutral-50 lg:grid-cols-[minmax(0,1.5fr)_7rem_9rem_5rem_8rem] lg:items-center ${isSelected ? "bg-violet-50/60" : "bg-white"}`}
                          >
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="truncate font-mono text-xs font-medium text-neutral-900">{item.id}</span>
                                {isSelected && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-700">selected</span>}
                                {item.auto_run_enabled && <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-700">auto</span>}
                              </div>
                              <div className="mt-1 line-clamp-2 text-xs leading-5 text-neutral-600">{item.user_direction || "No run-specific lead direction"}</div>
                              <div className="mt-1 line-clamp-1 text-[10px] text-neutral-400">{item.next_step || (item.status === "completed" ? "Run complete" : "Ready to begin")}</div>
                            </div>
                            <div>
                              <span className={`inline-flex rounded-full border px-2 py-1 text-xs ${stepTone(item.status)}`}>{item.status}</span>
                            </div>
                            <div className="min-w-0">
                              <div className="truncate text-xs font-medium text-neutral-800">{item.llm_provider === "openai" ? "Direct OpenAI" : "OpenClaw"}</div>
                              <div className="mt-0.5 truncate text-[10px] text-neutral-400">{item.llm_model}</div>
                            </div>
                            <div className="text-xs text-neutral-600">
                              <div>{item.current_step}</div>
                              <div className="mt-0.5 text-[10px] text-neutral-400">{leadCount} lead{leadCount === 1 ? "" : "s"}</div>
                            </div>
                            <div className="text-xs text-neutral-500">
                              <div>{shortDate(item.updated_at || item.created_at)}</div>
                              <div className="mt-1 text-[10px] font-medium text-violet-600">Open run →</div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )
            ) : activeView === "overview" ? (
              <div className="space-y-5">
                <section className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-neutral-500">Current position</div>
                      <div className="mt-1 text-base font-semibold text-neutral-950">
                        {run?.status === "completed" ? "Run complete" : run?.next_step || "Ready to begin"}
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span className="rounded-full border border-neutral-200 bg-white px-2.5 py-1 text-neutral-700">{steps.length} step{steps.length === 1 ? "" : "s"}</span>
                      <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-700">{foundLeads.length} found lead{foundLeads.length === 1 ? "" : "s"}</span>
                      {run?.auto_run_enabled && <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-violet-700">Auto-running</span>}
                    </div>
                  </div>
                  {run?.auto_run_enabled && (
                    <div className="mt-3">
                      <div className="mb-1 flex justify-between text-[10px] font-medium text-violet-700">
                        <span>Unattended safety budget</span>
                        <span>{run.auto_run_steps_used} / {run.auto_run_max_steps}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-violet-100">
                        <div className="h-full rounded-full bg-violet-600 transition-all" style={{ width: `${Math.min(100, (run.auto_run_steps_used / Math.max(1, run.auto_run_max_steps)) * 100)}%` }} />
                      </div>
                    </div>
                  )}
                </section>

                {steps.length === 0 ? (
                  <div className="flex min-h-72 flex-col items-center justify-center text-center">
                    <Activity className="h-8 w-8 text-neutral-300" />
                    <div className="mt-3 text-sm font-medium text-neutral-800">The run has not taken its first step</div>
                    <p className="mt-1 max-w-md text-xs leading-5 text-neutral-500">Use Do next step for manual inspection or Run without pauses for bounded unattended execution.</p>
                  </div>
                ) : (
                  <div className="relative space-y-4 before:absolute before:bottom-6 before:left-[1.05rem] before:top-6 before:w-px before:bg-neutral-200">
                    {steps.map((step) => {
                      const response = step.response_parsed;
                      const waiting = ACTIVE_STATUSES.has(step.status);
                      return (
                        <article key={step.id} className="relative pl-11">
                          <div className={`absolute left-0 top-4 z-10 flex h-9 w-9 items-center justify-center rounded-full border-4 border-white ${waiting ? "bg-sky-100 text-sky-700" : step.status === "completed" ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
                            {waiting ? <Loader2 className="h-4 w-4 animate-spin" /> : response.action?.type === "tool_call" ? <Wrench className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
                          </div>
                          <div className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                              <div>
                                <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-600">Step {step.step_number}</div>
                                <h2 className="mt-1 text-sm font-semibold text-neutral-950">{response.step_name || (waiting ? `${stepProviderLabel(step, run?.llm_provider)} is reasoning` : "Persisted transition")}</h2>
                                <p className="mt-1 text-sm leading-6 text-neutral-600">{response.summary || step.error || "Waiting for the model response."}</p>
                              </div>
                              <span className={`shrink-0 rounded-full border px-2 py-1 text-xs ${stepTone(step.status)}`}>{step.status}</span>
                            </div>

                            {response.reasoning && (
                              <div className="mt-3 rounded-lg bg-violet-50/70 p-3">
                                <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-violet-600">Reasoning</div>
                                <p className="mt-1 text-xs leading-5 text-violet-950">{response.reasoning}</p>
                              </div>
                            )}

                            {(step.tool_calls || []).map((toolCall) => (
                              <div key={toolCall.id || `${step.id}-${toolCall.tool_name}`} className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-emerald-900">
                                    <Wrench className="h-3.5 w-3.5" /> {toolCall.tool_name}
                                    {toolProviderSummary(toolCall) && (
                                      <span className="font-normal text-emerald-700">
                                        {toolProviderSummary(toolCall)}
                                      </span>
                                    )}
                                  </div>
                                  <span className={`rounded-full border px-2 py-0.5 text-[10px] ${stepTone(toolCall.status)}`}>{toolCall.status}</span>
                                </div>
                                <p className="mt-1 text-xs leading-5 text-emerald-800">{toolResultSummary(toolCall)}</p>
                              </div>
                            ))}

                            {response.next_step && (
                              <div className="mt-3 flex items-start gap-2 border-t border-neutral-100 pt-3 text-xs leading-5 text-neutral-500">
                                <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                <span><strong className="font-medium text-neutral-700">Next:</strong> {response.next_step}</span>
                              </div>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : activeView === "context" ? (
              <div className="space-y-5">
                <section className="rounded-xl border border-violet-200 bg-violet-50/50">
                  <div className="flex items-center justify-between gap-3 border-b border-violet-200 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-violet-950"><Sparkles className="h-4 w-4" /> Latest persisted LLM response</div>
                    {latestResponse && <span className="text-xs text-violet-600">{latestResponse.model}</span>}
                  </div>
                  {latestResponse ? (
                    <div className="p-3"><JsonTextPanel text={latestResponse.response_raw} className="text-violet-950" /></div>
                  ) : (
                    <div className="p-6 text-center text-sm text-violet-700">The exact response will appear here after a persisted step completes.</div>
                  )}
                </section>
                <div><div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-neutral-500">Full current context</div>{context ? <JsonPanel value={context} /> : <div className="p-8 text-center text-sm text-neutral-500">Loading context…</div>}</div>
              </div>
            ) : activeView === "session" ? (
              <div className="space-y-4">
                {run?.llm_provider === "openai" ? (
                  <>
                    <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-xs leading-5 text-sky-900">
                      Direct mode uses the OpenAI Responses API. Possible OS persists each exact request, full provider response, parsed transition, and usage record below; no local OpenClaw JSONL is created for these turns.
                    </div>
                    <div className="grid gap-2 rounded-xl border border-neutral-200 p-3 text-xs text-neutral-500 sm:grid-cols-2">
                      <div><span className="font-medium text-neutral-700">provider</span> Direct OpenAI</div>
                      <div><span className="font-medium text-neutral-700">model</span> {run.llm_model}</div>
                      <div className="break-all sm:col-span-2"><span className="font-medium text-neutral-700">latest response id</span> {run.openai_previous_response_id || "created after the first direct reasoning step"}</div>
                    </div>
                    {directResponseTrace.length > 0 ? (
                      <JsonPanel value={directResponseTrace} />
                    ) : (
                      <div className="flex min-h-72 items-center justify-center text-center text-sm text-neutral-500">The direct Responses trace will appear after the first reasoning step completes.</div>
                    )}
                  </>
                ) : (
                  <>
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">
                  This is OpenClaw&apos;s unredacted on-disk JSONL. Each line is one JSON record. It may include injected workspace instructions, tool definitions, and sensitive configuration.
                </div>
                <div className="flex flex-wrap items-center gap-2 rounded-xl border border-neutral-200 p-3">
                  <div className="flex gap-1 rounded-lg bg-neutral-100 p-1">
                    <button type="button" onClick={() => setLlmSessionSource("session")}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium ${llmSessionSource === "session" ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-600"}`}>
                      Session JSONL
                    </button>
                    <button type="button" onClick={() => setLlmSessionSource("trajectory")}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium ${llmSessionSource === "trajectory" ? "bg-white text-neutral-950 shadow-sm" : "text-neutral-600"}`}>
                      Trajectory JSONL
                    </button>
                  </div>
                  <button type="button" disabled={!rawSessionText}
                    onClick={() => void navigator.clipboard.writeText(rawSessionText)}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 px-3 py-2 text-xs font-medium text-neutral-700 disabled:opacity-40">
                    <Copy className="h-3.5 w-3.5" /> Copy raw JSONL
                  </button>
                </div>
                {llmSession && (
                  <div className="grid gap-2 text-xs text-neutral-500 sm:grid-cols-2">
                    <div className="break-all"><span className="font-medium text-neutral-700">session key</span> {llmSession.session_key}</div>
                    <div className="break-all"><span className="font-medium text-neutral-700">session id</span> {llmSession.session_id}</div>
                    <div className="break-all sm:col-span-2"><span className="font-medium text-neutral-700">raw file</span> {rawSessionFile}</div>
                  </div>
                )}
                {llmSessionLoading ? (
                  <div className="flex min-h-72 items-center justify-center gap-2 text-sm text-neutral-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading raw OpenClaw session…</div>
                ) : llmSessionError ? (
                  <div className="flex min-h-72 items-center justify-center text-center text-sm text-neutral-500">{llmSessionError}</div>
                ) : (
                  <div ref={llmSessionTree} className="max-h-[70vh] overflow-auto rounded-xl bg-neutral-950 font-mono text-[11px] leading-5">
                    <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-neutral-800 bg-neutral-900/95 px-3 py-2 backdrop-blur">
                      <div className="flex gap-1 rounded-lg bg-neutral-800 p-1">
                        <button type="button" onClick={() => setLlmSessionDisplay("readable")}
                          className={`rounded-md px-3 py-1.5 text-xs font-medium ${llmSessionDisplay === "readable" ? "bg-neutral-100 text-neutral-950 shadow-sm" : "text-neutral-400 hover:text-neutral-200"}`}>
                          Readable JSON
                        </button>
                        <button type="button" onClick={() => setLlmSessionDisplay("raw")}
                          className={`rounded-md px-3 py-1.5 text-xs font-medium ${llmSessionDisplay === "raw" ? "bg-neutral-100 text-neutral-950 shadow-sm" : "text-neutral-400 hover:text-neutral-200"}`}>
                          Raw JSONL
                        </button>
                      </div>
                      {llmSessionDisplay === "readable" && rawSessionText && (
                        <div className="flex gap-1">
                          <button type="button" onClick={() => setAllSessionNodes(true)} className="rounded-md border border-neutral-700 px-2.5 py-2 text-xs font-medium text-neutral-300 hover:bg-neutral-800">Expand all</button>
                          <button type="button" onClick={() => setAllSessionNodes(false)} className="rounded-md border border-neutral-700 px-2.5 py-2 text-xs font-medium text-neutral-300 hover:bg-neutral-800">Collapse all</button>
                        </div>
                      )}
                      {rawSessionText && llmSessionDisplay === "readable" && (
                        <div className="ml-auto flex flex-wrap items-center gap-x-3 text-neutral-500">
                          <span>{jsonlRecords.length.toLocaleString()} JSON record{jsonlRecords.length === 1 ? "" : "s"}</span>
                          <span>Click any row or nested object to expand</span>
                        </div>
                      )}
                    </div>
                    {rawSessionText && llmSessionDisplay === "readable" ? (
                      <div className="space-y-2 p-3">
                        {jsonlRecords.map((record) => (
                          <details key={record.line} className="group/record rounded-lg border border-neutral-800 bg-neutral-900/70">
                            <summary className="cursor-pointer list-none px-3 py-2 text-neutral-200 marker:hidden">
                              <span className="mr-2 inline-block text-neutral-500 transition-transform group-open/record:rotate-90">▶</span>
                              <span className="mr-2 rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400">line {record.line}</span>
                              <span className={record.error ? "text-rose-300" : "text-violet-300"}>{jsonlRecordLabel(record)}</span>
                            </summary>
                            <div className="border-t border-neutral-800 p-3">
                              {record.error && <div className="mb-2 rounded bg-rose-950/50 p-2 text-rose-300">{record.error}</div>}
                              <JsonTreeNode value={record.value} />
                            </div>
                          </details>
                        ))}
                      </div>
                    ) : rawSessionText ? (
                      <pre className="whitespace-pre p-4 text-neutral-200">{rawSessionText}</pre>
                    ) : (
                      <div className="flex min-h-72 items-center justify-center text-center text-sm text-neutral-500">This raw OpenClaw file does not exist yet.</div>
                    )}
                  </div>
                )}
                  </>
                )}
              </div>
            ) : activeView === "leads" ? (
              foundLeads.length === 0 ? (
                <div className="flex min-h-72 flex-col items-center justify-center text-center">
                  <Users className="h-8 w-8 text-neutral-300" />
                  <div className="mt-3 text-sm font-medium text-neutral-800">No researched leads yet</div>
                  <p className="mt-1 max-w-md text-xs leading-5 text-neutral-500">
                    The agent must verify a transcript candidate with web research, then explicitly add that research result.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {[...foundLeads].reverse().map((lead) => (
                    <article key={lead.id} className="rounded-xl border border-neutral-200 p-4 sm:p-5">
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <h2 className="text-base font-semibold text-neutral-950">{lead.name}</h2>
                            <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-emerald-700">{lead.status}</span>
                          </div>
                          <p className="mt-1 text-sm text-neutral-600">{[lead.role, lead.organization].filter(Boolean).join(" · ") || "Current role unverified"}</p>
                        </div>
                        {lead.official_profile_url && (
                          <a href={lead.official_profile_url} target="_blank" rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs font-medium text-violet-700 hover:underline">
                            Public profile <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      <p className="mt-4 text-sm leading-6 text-neutral-700">{lead.profile_summary}</p>

                      <div className="mt-5 grid gap-4 lg:grid-cols-2">
                        <section>
                          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-neutral-500">Recent signals</h3>
                          <div className="mt-2 space-y-2">
                            {lead.recent_signals.map((signal, index) => (
                              <div key={`${lead.id}-signal-${index}`} className="rounded-lg bg-neutral-50 p-3">
                                <a href={signal.source_url} target="_blank" rel="noreferrer" className="text-sm font-medium text-neutral-900 hover:underline">{signal.title}</a>
                                <div className="mt-1 text-[10px] text-neutral-400">{signal.date || "Date not published"}</div>
                                <p className="mt-1 text-xs leading-5 text-neutral-600">{signal.summary}</p>
                              </div>
                            ))}
                          </div>
                        </section>
                        <section>
                          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-neutral-500">Possible outreach angles</h3>
                          <div className="mt-2 space-y-2">
                            {lead.outreach_angles.map((angle, index) => (
                              <div key={`${lead.id}-angle-${index}`} className="rounded-lg border border-violet-100 bg-violet-50/60 p-3">
                                <div className="text-sm font-medium text-violet-950">{angle.title}</div>
                                <p className="mt-1 text-xs leading-5 text-violet-900">{angle.why_relevant}</p>
                                <p className="mt-2 text-xs font-medium text-violet-950">Question: {angle.question}</p>
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>

                      <details className="mt-4 rounded-lg border border-neutral-200">
                        <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-neutral-600">Sources and contrary evidence</summary>
                        <div className="space-y-3 border-t border-neutral-200 p-3 text-xs">
                          <div className="flex flex-wrap gap-2">
                            {lead.sources.map((source, index) => (
                              <a key={`${lead.id}-source-${index}`} href={source.url} target="_blank" rel="noreferrer" className="rounded bg-neutral-100 px-2 py-1 text-neutral-700 hover:underline">{source.title || source.url}</a>
                            ))}
                          </div>
                          {lead.contrary_evidence.length > 0 && <JsonPanel value={{ contrary_evidence: lead.contrary_evidence }} />}
                        </div>
                      </details>
                    </article>
                  ))}
                </div>
              )
            ) : steps.length === 0 ? (
              <div className="flex min-h-72 flex-col items-center justify-center text-center"><History className="h-8 w-8 text-neutral-300" /><div className="mt-3 text-sm font-medium text-neutral-800">No persisted steps yet</div></div>
            ) : (
              <div className="space-y-3">
                {[...steps].reverse().map((step: LeadFinderPersistedStep) => (
                  <article key={step.id} className="rounded-xl border border-neutral-200 p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="flex items-center gap-2 text-xs font-medium text-violet-600"><Sparkles className="h-3.5 w-3.5" /> STEP {step.step_number}</div>
                        <h2 className="mt-1 text-sm font-semibold text-neutral-900">{step.response_parsed.step_name || `${stepProviderLabel(step, run?.llm_provider)} request`}</h2>
                        <p className="mt-1 text-sm text-neutral-600">{step.response_parsed.summary || step.error || "Waiting for a response."}</p>
                      </div>
                      <span className={`rounded-full border px-2 py-1 text-xs ${stepTone(step.status)}`}>{step.status}</span>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-neutral-500 sm:grid-cols-3">
                      <div><Clock3 className="mr-1 inline h-3.5 w-3.5" />{shortDate(step.started_at || step.created_at)}</div>
                      <div>{step.model || "openclaw/main"}</div>
                      <div>{step.attempts.length} gateway attempt{step.attempts.length === 1 ? "" : "s"}</div>
                    </div>
                    {step.response_raw && <div className="mt-3"><JsonTextPanel text={step.response_raw} className="rounded-lg bg-violet-50 text-violet-950" /></div>}
                    {(step.tool_calls || []).length > 0 && (
                      <div className="mt-3 space-y-2">
                        {(step.tool_calls || []).map((toolCall) => (
                          <details key={toolCall.id || `${step.id}-${toolCall.tool_name}`} open className="rounded-lg border border-emerald-200 bg-emerald-50/40">
                            <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-emerald-800">
                              Tool · {toolCall.tool_name}
                              {toolProviderSummary(toolCall)
                                ? ` · ${toolProviderSummary(toolCall)}`
                                : ""}
                              {` · ${toolCall.status}`}
                            </summary>
                            <div className="space-y-3 border-t border-emerald-200 p-3">
                              {toolCall.error && <div className="rounded bg-red-50 p-2 text-xs text-red-700">{toolCall.error}</div>}
                              <div><div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">Arguments</div><JsonPanel value={toolCall.arguments} /></div>
                              <div><div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">Persisted result</div><JsonPanel value={toolCall.result} /></div>
                            </div>
                          </details>
                        ))}
                      </div>
                    )}
                    <div className="mt-3 flex flex-wrap gap-1.5">{(step.context_diff.changed_paths || []).map((path) => <span key={path} className="rounded bg-neutral-100 px-2 py-1 font-mono text-[10px] text-neutral-600">{path}</span>)}</div>
                    <div className="mt-4 grid gap-3 xl:grid-cols-3">
                      <details className="rounded-lg border border-neutral-200"><summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-neutral-600">Exact request</summary><div className="border-t border-neutral-200 p-2"><JsonPanel value={step.request} /></div></details>
                      <details className="rounded-lg border border-neutral-200"><summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-neutral-600">Context before</summary><div className="border-t border-neutral-200 p-2"><JsonPanel value={step.context_before} /></div></details>
                      <details className="rounded-lg border border-neutral-200"><summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-neutral-600">Context after</summary><div className="border-t border-neutral-200 p-2"><JsonPanel value={step.context_after} /></div></details>
                    </div>
                    {step.attempts.length > 0 && (
                      <details className="mt-3 rounded-lg border border-sky-200 bg-sky-50/40">
                        <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-sky-700">Gateway attempts</summary>
                        <div className="space-y-2 border-t border-sky-200 p-3">
                          {step.attempts.map((attempt) => (
                            <div key={attempt.id} className="rounded-lg bg-white p-3 text-xs text-neutral-600">
                              <div className="flex justify-between"><strong>Attempt {attempt.attempt_number}</strong><span>{attempt.status}</span></div>
                              <div className="mt-1">{attempt.model} · HTTP {attempt.http_status || "-"}</div>
                              <div className="mt-1">
                                prompt cache {attempt.prompt_cache.status}
                                {attempt.prompt_cache.cached_tokens != null
                                  ? ` · ${attempt.prompt_cache.cached_tokens.toLocaleString()} cached tokens`
                                  : ""}
                                {attempt.prompt_cache.hit_rate_percent != null
                                  ? ` · ${attempt.prompt_cache.hit_rate_percent}%`
                                  : ""}
                              </div>
                              {attempt.error && <div className="mt-1 text-red-600">{attempt.error}</div>}
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                    <div className="mt-3 flex items-center gap-1 text-[10px] text-neutral-400"><Copy className="h-3 w-3" /> request_id {step.request_id}</div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
