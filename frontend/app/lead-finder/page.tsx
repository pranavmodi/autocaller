"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Braces,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Copy,
  DatabaseZap,
  ExternalLink,
  FileText,
  History,
  Loader2,
  Pause,
  Play,
  Search,
  Sparkles,
  Users,
} from "lucide-react";
import {
  createLeadFinderRun,
  getLeadFinderContext,
  getLeadFinderRun,
  listLeadFinderRuns,
  queueLeadFinderStep,
  resetAllLeadFinderRuns,
  type LeadFinderContext,
  type LeadFinderFoundLead,
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
    <pre className="max-h-[38rem] overflow-auto rounded-xl bg-neutral-950 p-4 text-xs leading-5 text-neutral-200">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
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

export default function LeadFinderPage() {
  const [baseline, setBaseline] = useState<LeadFinderContext | null>(null);
  const [runs, setRuns] = useState<LeadFinderRun[]>([]);
  const [run, setRun] = useState<LeadFinderRun | null>(null);
  const [userDirection, setUserDirection] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [resettingAll, setResettingAll] = useState(false);
  const [error, setError] = useState("");
  const [activeView, setActiveView] = useState<"context" | "leads" | "history">("context");
  const submissionLock = useRef(false);

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
    if (!run || resettingAll || !ACTIVE_STATUSES.has(run.status)) return;
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
  }, [refreshRuns, resettingAll, run?.id, run?.status]);

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

  async function startRun() {
    setError("");
    setSubmitting(true);
    try {
      const response = await createLeadFinderRun(userDirection);
      await loadRun(response.run.id);
      await refreshRuns();
      setActiveView("context");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create run.");
    } finally {
      setSubmitting(false);
    }
  }

  async function doNextStep() {
    if (!run || submissionLock.current || isActive) return;
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
      setActiveView("history");
    } catch (cause) {
      submissionLock.current = false;
      setSubmitting(false);
      setError(cause instanceof Error ? cause.message : "Unable to queue the next step.");
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
      const response = await resetAllLeadFinderRuns(userDirection);
      submissionLock.current = false;
      setSubmitting(false);
      setRun({ ...response.run, steps: [] });
      setRuns([response.run]);
      setUserDirection(response.run.user_direction || "");
      setActiveView("context");
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

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-neutral-500"><Search className="h-4 w-4" /> Lead Finder Agent</div>
            <h1 className="text-2xl font-semibold tracking-tight text-neutral-950">Debug workspace</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-600">
              Runs, requests, gateway attempts, raw responses, and context evolution are persisted in Postgres.
              Each trigger executes one reasoning step or one bounded tool and pauses.
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
                disabled={submitting || isActive || run.status === "completed" || run.status === "failed"}
                className="inline-flex items-center gap-2 rounded-lg bg-neutral-950 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-neutral-300">
                {isActive || submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
                {isActive ? "OpenClaw in progress…" : "Do next step"}
              </button>
            )}
            {run && (
              <button type="button" onClick={startRun} disabled={loading || submitting || isActive}
                className="inline-flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50">
                <Play className="h-4 w-4" /> New run
              </button>
            )}
            <button type="button" onClick={deleteAllAndRestart} disabled={loading || resettingAll}
              className="inline-flex items-center gap-2 rounded-lg border border-red-300 bg-white px-3 py-2.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">
              {resettingAll ? <Loader2 className="h-4 w-4 animate-spin" /> : <DatabaseZap className="h-4 w-4" />}
              Delete all &amp; restart
            </button>
          </div>
        </div>

        {error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

        <div className="mt-6 grid gap-4 border-t border-neutral-100 pt-5 sm:grid-cols-5">
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
          <div><div className="text-xs text-neutral-500">Completed step</div><div className="mt-1 text-sm font-medium text-neutral-900">{run?.current_step || 0}</div></div>
          <div><div className="text-xs text-neutral-500">Gateway alias</div><div className="mt-1 text-sm font-medium text-neutral-900">openclaw/main</div></div>
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
          <div className="flex items-center gap-1 border-b border-neutral-200 p-2">
            <button type="button" onClick={() => setActiveView("context")}
              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${activeView === "context" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
              <Braces className="h-4 w-4" /> Current context
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
            {activeView === "context" ? (
              <div className="space-y-5">
                <section className="rounded-xl border border-violet-200 bg-violet-50/50">
                  <div className="flex items-center justify-between gap-3 border-b border-violet-200 px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-violet-950"><Sparkles className="h-4 w-4" /> Latest persisted LLM response</div>
                    {latestResponse && <span className="text-xs text-violet-600">{latestResponse.model}</span>}
                  </div>
                  {latestResponse ? (
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap p-4 text-xs leading-5 text-violet-950">{latestResponse.response_raw}</pre>
                  ) : (
                    <div className="p-6 text-center text-sm text-violet-700">The exact response will appear here after a persisted step completes.</div>
                  )}
                </section>
                <div><div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-neutral-500">Full current context</div>{context ? <JsonPanel value={context} /> : <div className="p-8 text-center text-sm text-neutral-500">Loading context…</div>}</div>
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
                        <h2 className="mt-1 text-sm font-semibold text-neutral-900">{step.response_parsed.step_name || "OpenClaw request"}</h2>
                        <p className="mt-1 text-sm text-neutral-600">{step.response_parsed.summary || step.error || "Waiting for a response."}</p>
                      </div>
                      <span className={`rounded-full border px-2 py-1 text-xs ${stepTone(step.status)}`}>{step.status}</span>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs text-neutral-500 sm:grid-cols-3">
                      <div><Clock3 className="mr-1 inline h-3.5 w-3.5" />{shortDate(step.started_at || step.created_at)}</div>
                      <div>{step.model || "openclaw/main"}</div>
                      <div>{step.attempts.length} gateway attempt{step.attempts.length === 1 ? "" : "s"}</div>
                    </div>
                    {step.response_raw && <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-violet-50 p-3 text-xs leading-5 text-violet-950">{step.response_raw}</pre>}
                    {(step.tool_calls || []).length > 0 && (
                      <div className="mt-3 space-y-2">
                        {(step.tool_calls || []).map((toolCall) => (
                          <details key={toolCall.id || `${step.id}-${toolCall.tool_name}`} open className="rounded-lg border border-emerald-200 bg-emerald-50/40">
                            <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-emerald-800">
                              Tool · {toolCall.tool_name} · {toolCall.status}
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
