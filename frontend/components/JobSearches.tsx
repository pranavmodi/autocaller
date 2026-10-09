"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Play, Settings2, Clock, Loader2, ArrowUpRight, ChevronLeft, Tags } from "lucide-react";
import { jobAgentRequest as request, type Candidate, type Overview } from "@/lib/job-agent";

type Mode = "required" | "preferred";
type Config = {
  name: string; description: string; target_roles: string; preferred_industries: string; industry_mode: Mode;
  location_preferences: string; location_mode: Mode; employment_type: "any" | "contract" | "non_contract";
  employment_mode: Mode; exclusions: string; additional_preferences: string; prefer_overseas_employers: boolean;
  posted_within_days: number; source_ids: string[]; employer_urls: string[]; max_candidates: number; max_sources: number;
  include_quick_save_portals: boolean;
  ai_provider: "gateway" | "openai"; openai_model: string;
  schedule_enabled: boolean; timezone: string; local_time: string;
};
type Saved = { id: string; revision: number; config: Config };
type Progress = { found: number; assessed: number; saved: number; errors: number;
  updated_at?: string; heartbeat_at?: string; last_activity_at?: string; live_telemetry: boolean;
  execution_started_at?: string; waiting_for_model: boolean;
  model_request?: { mode: string; attempt: number; started_at: string; timeout_seconds: number } };
type Activity = { id: number; at: string; kind: string; message: string; source_url?: string };
type Run = { id: string; name: string; search_id?: string; status: string; phase: string; trigger: string;
  started_at: string; completed_at?: string; new_jobs: number; verified: number; duplicates: number; errors: number;
  counts: Record<string, number>; progress?: Progress; ai_provider?: string; model?: string };
type Result = { candidate: { firm_name?: string; title?: string; source_url?: string }; candidate_id?: string;
  outcome: string; reason: string; already_known?: boolean; contract_status?: string;
  contacts?: { verified: number }; decision?: { location?: string; posted_date?: string; work_arrangement?: string;
    search_checks?: { criterion: string; result: string; reason: string; confidence: number; evidence?: { source_url: string; text: string } }[] } };
type CoverageItem = { id: string; source_key: string; name: string; url: string; adapter_type: string; status: string;
  pages_checked: number; listings_seen: number; candidates_emitted: number; closed_count: number; retry_count: number;
  details: { researcher_report?: string }; error?: string; updated_at: string };
type Coverage = { run_id: string; total: number; statuses: Record<string, number>; listings_seen: number;
  candidates_emitted: number; closed: number; items: CoverageItem[] };
type ScreeningItem = { id: string; source_key: string; provider: string; native_id: string; job_url: string;
  title: string; employer_name: string; location: string; employment_type: string; description: string;
  published_at?: string; status: string; choice?: string; selected: boolean; error?: string; updated_at: string;
  judgment: { model?: string; confidence?: number; probabilities?: Record<string, number>;
    input_sha256?: string; classified_at?: string } };
type ScreeningPage = { run_id: string; summary: { total: number; classified: number; selected: number;
  pending: number; errors: number; choices: Record<string, number> }; items: ScreeningItem[]; total: number;
  page: number; page_size: number; total_pages: number; view: string };
type DiscoveryOccurrence = { candidate_id?: string; job_url?: string; title: string; employer_name: string;
  location: string; posted_date?: string; source: string; outcome: string; reason: string; saved_to_queue: boolean;
  search_id?: string; search_name: string; run_id: string; run_status: string; trigger: string;
  found_at: string; run_started_at: string };
type DiscoveryJob = { id: string; candidate_id?: string; job_url?: string; title: string; employer_name: string;
  location: string; posted_date?: string; source: string; latest_outcome: string; latest_reason: string;
  saved_to_queue: boolean; first_found_at: string; latest_found_at: string; discoveries: DiscoveryOccurrence[] };
type DiscoveryPage = { items: DiscoveryJob[]; total: number; occurrences: number; page: number;
  page_size: number; total_pages: number; filters: {
    searches: { id: string; name: string }[];
    runs: { id: string; search_id?: string; search_name: string; status: string; trigger: string; started_at: string }[];
  } };
type Detail = Run & { activity?: Activity[]; settings: Record<string, unknown>; results: Result[]; queries: string[]; sources: string[];
  source_checks: { url: string; status: string; reason: string }[];
  coverage?: Coverage; errors_detail: { source_url?: string; phase?: string; error?: string }[]; legacy: boolean };
const input = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-100";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50";
const primary = `${button} !border-slate-900 !bg-slate-900 !text-white hover:!bg-slate-800`;
const label = "grid gap-2 text-sm font-medium text-slate-700";
const date = (value: string) => new Date(value).toLocaleString();
const readable = (value: string) => value.replaceAll("_", " ");
const url = (value?: string) => { try { const u = new URL(value || ""); return ["https:", "http:"].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } };
const tone = (status: string) => ["match", "completed", "met"].includes(status) ? "bg-emerald-50 text-emerald-800" : ["error", "failed", "not_met"].includes(status) ? "bg-rose-50 text-rose-800" : ["uncertain", "partial", "unknown", "interrupted"].includes(status) ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-600";
const Badge = ({ value }: { value: string }) => <span className={`rounded-full px-2 py-1 text-xs font-medium ${tone(value)}`}>{readable(value)}</span>;

export default function JobSearches({ overview, onOpen }: { overview: Overview; onOpen: (job: Candidate) => void }) {
  const client = useQueryClient();
  const [edit, setEdit] = useState<Saved | null>(null);
  const [runId, setRunId] = useState("");
  const [workspace, setWorkspace] = useState<"searches" | "discoveries">("searches");
  useEffect(() => { const saved = new URLSearchParams(window.location.search).get('run'); if (saved) { setRunId(saved); setWorkspace("searches"); } }, []);
  useEffect(() => {
    if (!runId) return;
    const u = new URL(window.location.href); u.searchParams.set('run', runId); u.searchParams.set('tab', 'searches');
    window.history.replaceState(null, '', u);
  }, [runId]);
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [inferenceChanged, setInferenceChanged] = useState(false);
  const searches = useQuery({ queryKey: ["job-agent", "searches"], queryFn: () => request<{ items: Saved[] }>("/searches") });
  const detail = useQuery({ queryKey: ["job-agent", "search-run", runId], queryFn: () => request<Detail>(`/search-runs/${runId}`), enabled: !!runId, refetchInterval: query => ['running', 'queued'].includes(query.state.data?.status || '') ? 2000 : 10000 });
  const refresh = () => client.invalidateQueries({ queryKey: ["job-agent"] });
  async function act(key: string, fn: () => Promise<void>) { setBusy(key); setError(""); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "Something went wrong. Try again."); } finally { setBusy(""); } }
  function fresh(): Saved {
    const c = overview.config;
    return { id: "", revision: 0, config: { name: "New job search", description: "", target_roles: c.target_roles, preferred_industries: c.preferred_industries,
      location_preferences: c.location_preferences, industry_mode: "required", location_mode: "preferred",
      employment_type: "any", employment_mode: "preferred", exclusions: "", additional_preferences: "",
      prefer_overseas_employers: c.prefer_overseas_employers, posted_within_days: 7, source_ids: c.search_source_ids,
      include_quick_save_portals: c.include_quick_save_portals,
      ai_provider: "openai", openai_model: "gpt-5.6-luna", employer_urls: [], max_candidates: 10, max_sources: 200, schedule_enabled: false, timezone: "Asia/Kolkata", local_time: "01:00" } };
  }
  function update<K extends keyof Config>(key: K, value: Config[K]) { setEdit(old => old ? { ...old, config: { ...old.config, [key]: value } } : old); }
  const describe = (config: Config) => config.description?.trim() || `Find ${config.target_roles}. Industries: ${config.preferred_industries}. Location: ${config.location_preferences}. ${config.exclusions ? `Exclude: ${config.exclusions}.` : ""}`;
  const beginEdit = (search: Saved) => { setInferenceChanged(false); setEdit({ ...search, config: { ...search.config, description: describe(search.config) } }); };
  async function saveSearch() {
    if (!edit) return;
    const description = edit.config.description.trim();
    const inferred = await request<{ config: Config }>("/searches/draft", {
      description, ai_provider: edit.config.ai_provider, openai_model: edit.config.openai_model,
    });
    const config = { ...inferred.config, description,
      ai_provider: edit.config.ai_provider, openai_model: edit.config.openai_model,
      schedule_enabled: edit.config.schedule_enabled, timezone: edit.config.timezone, local_time: edit.config.local_time };
    await request(`/searches${edit.id ? '/' + edit.id : ''}`, { revision: edit.revision, config });
    setEdit(null);
    refresh();
  }
  const current = detail.data;
  return <section role="tabpanel" id="panel-searches" aria-labelledby="tab-searches" className="space-y-5">
    <div className="rounded-2xl bg-slate-900 p-6 text-white"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-medium uppercase tracking-widest text-sky-300">Discovery workspace</p><h2 className="mt-2 text-xl font-semibold">Focused searches. Traceable results.</h2><p className="mt-2 max-w-2xl text-sm text-slate-300">Save separate searches for different career paths. Every run keeps its settings, findings and explanations. Searching never submits an application.</p></div><div className="flex flex-wrap gap-2"><button className={button + " text-slate-900"} onClick={() => { setWorkspace(workspace === "discoveries" ? "searches" : "discoveries"); setEdit(null); setRunId(""); }}><Tags size={16} />{workspace === "discoveries" ? "Saved searches" : "All discovered jobs"}</button><button className={button + " text-slate-900"} onClick={() => { setWorkspace("searches"); setInferenceChanged(false); setEdit(fresh()); setRunId(""); }}><Plus size={16} />New search</button></div></div></div>
    {(error || searches.error || detail.error) && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error || String(searches.error || detail.error)}<button className="ml-3 underline" onClick={() => { setError(""); refresh(); }}>Refresh</button></div>}
    {workspace === "discoveries" && !edit && !runId && <DiscoveryLedger onOpen={onOpen} onOpenRun={identity => { setWorkspace("searches"); setRunId(identity); }} />}
    {workspace === "searches" && edit && <form className="space-y-5 rounded-2xl border border-sky-200 bg-sky-50/50 p-5" onSubmit={e => { e.preventDefault(); act("save", saveSearch); }}>
      <div className="flex items-center justify-between"><h3 className="font-semibold">{edit.id ? "Edit search" : "Create search"}</h3><button type="button" className={button} onClick={() => setEdit(null)}>Cancel</button></div>
      <div className="rounded-xl border border-slate-200 bg-white p-4"><div className="grid gap-4 sm:grid-cols-2"><label className={label}>Search AI provider<select className={input} value={edit.config.ai_provider || 'openai'} onChange={e => update('ai_provider', e.target.value as Config['ai_provider'])}><option value="openai">OpenAI API</option><option value="gateway">OpenClaw gateway</option></select></label>{edit.config.ai_provider === 'openai' && <label className={label}>OpenAI search model<input required className={input} value={edit.config.openai_model || 'gpt-5.6-luna'} onChange={e => update('openai_model', e.target.value)} /></label>}</div><p className="mt-3 text-xs text-slate-500">{edit.config.ai_provider === 'openai' ? 'Uses the server API key and API billing, with OpenAI web search. No gateway fallback.' : 'Uses the OpenClaw research agent and its web tools.'} Applies to this search’s settings assistant and future manual or scheduled runs. Existing runs retain their provider. Application providers are configured separately.</p></div>
      <div className="rounded-xl border border-sky-100 bg-white p-4"><label className={label}>What jobs should the agent find?<textarea required minLength={5} maxLength={5000} className={`${input} min-h-36`} value={edit.config.description} onChange={e => { setInferenceChanged(true); update("description", e.target.value); }} placeholder="Find Agentic AI Engineer roles building production agents, tool use and workflow automation. Require remote work from Colombia or LATAM; prefer legal-tech companies but allow other industries. Include permanent and contract roles posted within 14 days. Exclude roles requiring a law degree or work authorization outside Colombia. Prefer overseas startups, small teams and hands-on ownership." /></label><p className="mt-2 text-xs text-slate-500">The agent infers roles, industries, location rules, employment type, posting window, exclusions and preferences from this description when you save.</p></div>
      {edit.id && <details className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-emerald-950">View inferred search criteria</summary>
        <p className={`mt-3 text-xs ${inferenceChanged ? "text-amber-800" : "text-emerald-800"}`}>{inferenceChanged ? "This is the previous saved interpretation. Save the search to infer it again from your updated description." : "This is the saved interpretation used for searching and result verification."}</p>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Roles</dt><dd className="mt-1 whitespace-pre-wrap text-slate-800">{edit.config.target_roles}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Industries · {edit.config.industry_mode}</dt><dd className="mt-1 whitespace-pre-wrap text-slate-800">{edit.config.preferred_industries}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Location · {edit.config.location_mode}</dt><dd className="mt-1 whitespace-pre-wrap text-slate-800">{edit.config.location_preferences}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Employment · {edit.config.employment_mode}</dt><dd className="mt-1 text-slate-800">{readable(edit.config.employment_type)} · posted within {edit.config.posted_within_days} days</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Exclusions</dt><dd className="mt-1 whitespace-pre-wrap text-slate-800">{edit.config.exclusions || "None"}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Other preferences</dt><dd className="mt-1 whitespace-pre-wrap text-slate-800">{edit.config.additional_preferences || "None"}</dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Employer ranking</dt><dd className="mt-1 text-slate-800">{edit.config.prefer_overseas_employers ? "Prioritize employers based outside India" : "No employer-country ranking preference"}</dd></div>
        </dl>
      </details>}
      <details className="rounded-xl border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold">View all {overview.search_sources.total_count} search sources</summary>
        <p className="mt-3 text-xs text-slate-500">Every run receives this complete, deduplicated list. Sources are view-only.</p>
        <div className="mt-3 grid max-h-72 gap-2 overflow-auto sm:grid-cols-3">{overview.search_sources.items.map(source => <a key={source.id} href={source.url} target="_blank" rel="noreferrer" className="truncate text-sm text-sky-700 underline">{source.name}</a>)}</div>
      </details>
      <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4"><label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={edit.config.schedule_enabled} onChange={e => update("schedule_enabled", e.target.checked)} /><Clock size={16} />Run daily</label>{edit.config.schedule_enabled && <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className={label}>Time<input type="time" required className={input} value={edit.config.local_time} onChange={e => update("local_time", e.target.value)} /></label><label className={label}>Timezone<input required className={input} value={edit.config.timezone} onChange={e => update("timezone", e.target.value)} placeholder="Asia/Kolkata" /></label></div>}<p className="mt-2 text-xs text-slate-500">The scheduler checks every five minutes. Queued searches run one at a time.</p></div>
      <button className={primary} disabled={!!busy || edit.config.description.trim().length < 5}>{busy === "save" ? "Understanding and saving…" : "Save search"}</button>
    </form>}
    {workspace === "searches" && runId && <div className="rounded-2xl border border-sky-200 bg-white p-5"><button className="mb-3 flex items-center gap-1 text-xs text-slate-500" onClick={() => { setRunId(''); const u = new URL(window.location.href); u.searchParams.delete('run'); window.history.replaceState(null, '', u); }}><ChevronLeft size={14} />Close run details</button>{detail.isPending && <p>Loading results…</p>}{current && <>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-lg font-semibold">{current.name}</h3><p className="mt-1 text-xs text-slate-500">{date(current.started_at)}{current.completed_at && ` → ${date(current.completed_at)}`}</p></div><Badge value={current.status} /></div>
      <LiveRunProgress run={current} refreshing={detail.isFetching} lastRefresh={detail.dataUpdatedAt} onRefresh={() => detail.refetch()} />
      {current.coverage && <SourceCoverage value={current.coverage} active={['running','queued'].includes(current.status)} />}
      <ScreeningAudit runId={current.id} active={['running','queued'].includes(current.status)} />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">Jobs found in this run ({current.results.length})</h4><span className="text-xs text-slate-500">{current.new_jobs} new · {current.duplicates} already in queue</span></div>
      <details className="mb-4 rounded-lg border p-3"><summary className="cursor-pointer text-sm font-medium">Settings and sources used for this run</summary><p className="my-2 text-xs text-slate-500">This snapshot does not change when you edit the saved search.</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-3 text-xs">{JSON.stringify(current.settings, null, 2)}</pre><h4 className="mt-3 text-sm font-medium">Queries</h4><ul className="list-inside list-disc text-xs text-slate-600">{current.queries.map((q,i) => <li key={i}>{q}</li>)}</ul><h4 className="mt-3 text-sm font-medium">Sources assigned</h4>{current.sources.map((s,i) => <p className="break-all text-xs" key={i}><a href={url(s)} target="_blank" rel="noreferrer" className="text-sky-700 underline">{s}</a></p>)}<h4 className="mt-3 text-sm font-medium">Source checks reported by the researcher</h4>{!current.source_checks.length && <p className="text-xs text-slate-500">No source-check report was saved. Assigned sources alone do not prove they were searched.</p>}{current.source_checks.map((s,i) => <p className="mt-1 break-words text-xs" key={i}>{s.url} · {s.status} · {s.reason}</p>)}</details>
      {current.legacy && <p className="mb-4 text-xs text-amber-800">Earlier run: showing recorded decisions. Detailed requirement checks and queue links were not recorded at the time.</p>}
      {!!current.errors_detail.length && <details className="mb-4 rounded-lg border border-rose-100 bg-rose-50 p-3"><summary className="cursor-pointer text-sm text-rose-800">{current.errors_detail.length} processing errors</summary>{current.errors_detail.map((e,i) => <p key={i} className="mt-2 break-words text-xs text-rose-800">{e.phase || e.source_url}: {e.error}</p>)}</details>}
      <div className="mb-4 flex flex-wrap gap-2">{['all','match','uncertain','excluded','error','pending'].map(f => <button key={f} className={`${button} ${filter===f ? '!border-sky-500 !bg-sky-50' : ''}`} onClick={() => setFilter(f)}>{readable(f)} ({current.results.filter(r => f==='all' || r.outcome===f).length})</button>)}</div>
      <div className="space-y-3">{current.results.filter(r => filter==='all' || r.outcome===filter).map((r,i) => <article key={`${r.candidate?.source_url}-${i}`} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="font-medium">{r.candidate?.title || 'Unresolved job'}</h4><p className="mt-1 text-sm text-slate-600">{r.candidate?.firm_name} · {r.decision?.location || 'Location unknown'}</p></div><Badge value={r.outcome} /></div><p className="my-3 text-sm text-slate-700">{r.reason}</p><div className="flex flex-wrap gap-2 text-xs text-slate-500">{r.already_known && <Badge value="Already in your queue" />}<span>{r.decision?.posted_date || 'Posting date unknown'}</span>{r.contract_status && <span>· {readable(r.contract_status)}</span>}{r.contacts && <span>· {r.contacts.verified} verified contacts</span>}</div>{!!r.decision?.search_checks?.length && <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-sky-700">Why this result?</summary><div className="mt-2 space-y-2">{r.decision.search_checks.map((c,j) => <div className="rounded bg-slate-50 p-2 text-xs" key={j}><span className="font-medium capitalize">{c.criterion}</span> · <Badge value={c.result} /><p className="mt-2">{c.reason}</p>{c.evidence && <blockquote className="mt-2 border-l-2 border-sky-200 pl-2 text-slate-500">{c.evidence.text}</blockquote>}</div>)}</div></details>}<div className="mt-3 flex gap-2">{url(r.candidate?.source_url) && <a className={button} href={url(r.candidate?.source_url)} target="_blank" rel="noreferrer">View listing<ArrowUpRight size={14} /></a>}{r.candidate_id && <button className={button} disabled={!!busy} onClick={() => act('open', async () => onOpen(await request<Candidate>(`/jobs/${r.candidate_id}`)))}>Open saved job</button>}</div></article>)}</div>
      {!current.results.length && <p className="py-6 text-center text-sm text-slate-500">{['running','queued'].includes(current.status) ? 'Findings will appear as research progresses.' : 'No findings were recorded. Check source reports and errors, or broaden the search.'}</p>}
    </>}</div>}
    {workspace === "searches" && !edit && <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{searches.isPending && <p className="text-sm text-slate-500">Loading saved searches…</p>}{searches.data?.items.map(search => <article key={search.id} className="flex flex-col rounded-xl border border-slate-200 bg-white p-5"><div className="flex items-start justify-between gap-2"><h3 className="font-semibold">{search.config.name}</h3><button aria-label={`Edit ${search.config.name}`} className="rounded p-1 text-slate-500 hover:bg-slate-100" onClick={() => beginEdit(search)}><Settings2 size={18} /></button></div><p className="mt-3 line-clamp-5 text-sm text-slate-600">{describe(search.config)}</p><p className="my-4 text-xs text-slate-600">{search.config.ai_provider === 'openai' ? `OpenAI API · ${search.config.openai_model}` : 'OpenClaw gateway'}</p><p className="mb-4 text-xs text-indigo-700">{search.config.schedule_enabled ? `Daily · ${search.config.local_time} ${search.config.timezone}` : 'Manual runs only'}</p><button className={`${primary} mt-auto`} disabled={!!busy} onClick={() => act(search.id, async () => { const r = await request<{ id: string }>(`/searches/${search.id}/run`, {}); setRunId(r.id); setFilter('all'); refresh(); })}><Play size={14} />{busy === search.id ? 'Queuing…' : 'Run now'}</button></article>)}</div>}

  </section>;
}

function DiscoveryLedger({ onOpen, onOpenRun }: { onOpen: (job: Candidate) => void;
  onOpenRun: (identity: string) => void }) {
  const [term, setTerm] = useState("");
  const [searchId, setSearchId] = useState("");
  const [runId, setRunId] = useState("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["job-agent", "search-discoveries", term, searchId, runId, outcome, page],
    queryFn: () => request<DiscoveryPage>(`/search-discoveries?search=${encodeURIComponent(term)}&search_id=${encodeURIComponent(searchId)}&run_id=${encodeURIComponent(runId)}&outcome=${encodeURIComponent(outcome)}&page=${page}&page_size=25`),
    refetchInterval: 10000,
  });
  async function openCandidate(identity: string) {
    setError("");
    try { onOpen(await request<Candidate>(`/jobs/${identity}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not open the saved job."); }
  }
  const value = query.data;
  return <section className="rounded-2xl border border-violet-200 bg-white p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-medium uppercase tracking-widest text-violet-600">Discovery history</p><h3 className="mt-1 text-lg font-semibold">Jobs found across every search run</h3><p className="mt-1 text-sm text-slate-600">One row per job. The tags retain every search and run that found it, including excluded, failed and repeated discoveries.</p></div>{value && <div className="text-right"><p className="text-2xl font-semibold">{value.total}</p><p className="text-xs text-slate-500">unique jobs · {value.occurrences} findings</p></div>}</div>
    <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-4"><input className={input} aria-label="Search discovered jobs" placeholder="Search role, employer or location…" value={term} onChange={event => { setTerm(event.target.value); setPage(1); }} /><select className={input} aria-label="Filter discoveries by saved search" value={searchId} onChange={event => { setSearchId(event.target.value); setRunId(""); setPage(1); }}><option value="">All searches</option>{value?.filters.searches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select className={input} aria-label="Filter discoveries by run" value={runId} onChange={event => { setRunId(event.target.value); setPage(1); }}><option value="">All runs</option>{value?.filters.runs.filter(item => !searchId || item.search_id === searchId).map(item => <option key={item.id} value={item.id}>{item.search_name} · {date(item.started_at)} · {item.id.slice(0, 8)}</option>)}</select><select className={input} aria-label="Filter discoveries by outcome" value={outcome} onChange={event => { setOutcome(event.target.value); setPage(1); }}><option value="">All outcomes</option>{["match","uncertain","excluded","error","pending","legacy"].map(item => <option key={item} value={item}>{readable(item)}</option>)}</select></div>
    {(query.error || error) && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error || String(query.error)}</p>}
    {query.isPending && <p className="py-8 text-center text-sm text-slate-500">Loading discovery history…</p>}
    {value && !value.items.length && <p className="py-8 text-center text-sm text-slate-500">No discovered jobs match these filters.</p>}
    <div className="mt-4 space-y-3">{value?.items.map(item => <article key={item.id} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div>{item.job_url ? <a className="font-semibold text-sky-700 underline" href={url(item.job_url)} target="_blank" rel="noreferrer">{item.title}</a> : <h4 className="font-semibold">{item.title}</h4>}<p className="mt-1 text-sm text-slate-600">{item.employer_name}{item.location ? ` · ${item.location}` : ""}</p><p className="mt-1 text-xs text-slate-500">{item.source} · first found {date(item.first_found_at)} · latest {date(item.latest_found_at)}</p></div><div className="flex flex-wrap gap-2"><Badge value={item.latest_outcome} />{item.saved_to_queue && <Badge value="saved to jobs" />}</div></div>{item.latest_reason && <p className="mt-3 text-sm text-slate-700">{item.latest_reason}</p>}
      <div className="mt-3 flex flex-wrap gap-2" aria-label="Discovery provenance">{item.discoveries.map(discovery => <button key={`${discovery.run_id}-${discovery.found_at}`} className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-left text-xs text-violet-950 hover:bg-violet-100" title={`Open full run ${discovery.run_id}`} onClick={() => onOpenRun(discovery.run_id)}><span className="font-semibold">{discovery.search_name}</span><span className="ml-1 text-violet-700">· {discovery.run_id.slice(0, 8)}</span><br/><span>{date(discovery.found_at)} · {readable(discovery.trigger)} · {readable(discovery.outcome)}</span></button>)}</div>
      {item.candidate_id && <button className={`${button} mt-3`} onClick={() => openCandidate(item.candidate_id!)}>Open saved job</button>}
    </article>)}</div>
    {value && value.total_pages > 1 && <div className="mt-4 flex items-center justify-between text-xs text-slate-600"><span>Page {value.page} of {value.total_pages} · {value.total} jobs</span><div className="flex gap-2"><button className={button} disabled={value.page <= 1} onClick={() => setPage(old => Math.max(1, old - 1))}>Previous</button><button className={button} disabled={value.page >= value.total_pages} onClick={() => setPage(old => old + 1)}>Next</button></div></div>}
  </section>;
}

function ScreeningAudit({ runId, active }: { runId: string; active: boolean }) {
  const [view, setView] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => { setView("all"); setSearch(""); setPage(1); }, [runId]);
  const query = useQuery({
    queryKey: ["job-agent", "search-run", runId, "listings", view, search, page],
    queryFn: () => request<ScreeningPage>(`/search-runs/${runId}/listings?view=${encodeURIComponent(view)}&search=${encodeURIComponent(search)}&page=${page}&page_size=25`),
    enabled: !!runId,
    refetchInterval: active ? 2000 : false,
  });
  const value = query.data;
  const summary = value?.summary;
  return <details className="mb-4 rounded-xl border border-violet-200 bg-violet-50/40 p-4">
    <summary className="cursor-pointer list-none"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold text-violet-950">Candidate screening audit</p><p className="mt-1 text-xs text-violet-800">Every normalized structured listing and its saved Jev judgment for this run.</p></div>{summary && <div className="flex flex-wrap gap-2"><Badge value={`${summary.total} collected`} /><Badge value={`${summary.classified} classified`} /><Badge value={`${summary.selected} selected`} />{!!summary.errors && <Badge value={`${summary.errors} errors`} />}</div>}</div></summary>
    <p className="mt-3 text-xs text-slate-600">Running the same run again updates these rows. A later run keeps a separate historical snapshot; the main jobs queue still deduplicates the underlying job.</p>
    <div className="mt-4 flex flex-wrap gap-2"><select aria-label="Screening result" className={input} value={view} onChange={event => { setView(event.target.value); setPage(1); }}><option value="all">All candidates</option><option value="selected">Selected for research</option><option value="match">Match</option><option value="possible">Possible</option><option value="unrelated">Unrelated</option><option value="pending">Awaiting judgment</option><option value="error">Screening errors</option></select><input aria-label="Search screened candidates" className={input} value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Search role or employer…" /></div>
    {query.isPending && <p className="mt-4 text-sm text-slate-500">Loading collected candidates…</p>}
    {query.error && <p role="alert" className="mt-4 text-sm text-rose-700">Could not load the screening audit: {String(query.error)}</p>}
    {value && !summary?.total && <p className="mt-4 text-sm text-slate-500">{active ? "Structured listings will appear after source collection begins." : "No listing snapshots were saved. This run may predate candidate-level audit storage."}</p>}
    {!!value?.items.length && <div className="mt-4 max-h-[36rem] space-y-3 overflow-y-auto pr-1">{value.items.map(item => {
      const probabilities = item.judgment?.probabilities || {};
      return <article key={item.id} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex flex-wrap items-start justify-between gap-2"><div><a href={url(item.job_url)} target="_blank" rel="noreferrer" className="text-sm font-medium text-sky-700 underline">{item.title}</a><p className="mt-1 text-xs text-slate-600">{item.employer_name || "Employer unknown"}{item.location ? ` · ${item.location}` : ""}</p></div><div className="flex gap-2">{item.selected && <Badge value="selected" />}<Badge value={item.choice || item.status} /></div></div><p className="mt-2 text-xs text-slate-500">{item.source_key} · {readable(item.provider)}{item.published_at ? ` · ${item.published_at}` : ""}</p>{item.description && <p className="mt-2 line-clamp-3 text-xs text-slate-700">{item.description}</p>}{Object.keys(probabilities).length > 0 && <p className="mt-2 text-xs text-violet-800">Probabilities: {Object.entries(probabilities).map(([name, probability]) => `${name} ${Math.round(Number(probability) * 100)}%`).join(" · ")}{typeof item.judgment.confidence === "number" ? ` · confidence ${Math.round(item.judgment.confidence * 100)}%` : ""}</p>}{item.judgment?.model && <p className="mt-1 break-all text-[11px] text-slate-500">{item.judgment.model}{item.judgment.input_sha256 ? ` · input ${item.judgment.input_sha256.slice(0, 12)}…` : ""}</p>}{item.error && <p className="mt-2 text-xs text-rose-700">{item.error}</p>}</article>;
    })}</div>}
    {value && value.total_pages > 1 && <div className="mt-4 flex items-center justify-between text-xs text-slate-600"><span>Page {value.page} of {value.total_pages} · {value.total} results</span><div className="flex gap-2"><button className={button} disabled={value.page <= 1} onClick={() => setPage(old => Math.max(1, old - 1))}>Previous</button><button className={button} disabled={value.page >= value.total_pages} onClick={() => setPage(old => old + 1)}>Next</button></div></div>}
  </details>;
}

function SourceCoverage({ value, active }: { value: Coverage; active: boolean }) {
  const resolved = (value.statuses.completed || 0) + (value.statuses.unavailable || 0) +
    (value.statuses.not_checked || 0) + (value.statuses.failed || 0);
  const problems = (value.statuses.failed || 0) + (value.statuses.not_checked || 0);
  return <details open={active || problems > 0} className="mb-4 rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
    <summary className="cursor-pointer list-none"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold text-indigo-950">Source coverage</p><p className="mt-1 text-xs text-indigo-800">{resolved} of {value.total} sources resolved · {value.listings_seen} structured listings examined · {value.candidates_emitted} shortlisted</p></div><div className="flex flex-wrap gap-2"><Badge value={`${value.statuses.completed || 0} completed`} />{!!(value.statuses.running || value.statuses.pending) && <Badge value={`${(value.statuses.running || 0) + (value.statuses.pending || 0)} in progress`} />}{!!problems && <Badge value={`${problems} need attention`} />}</div></div></summary>
    <p className="mt-3 text-xs text-slate-600">Structured adapters report actual API pages and listings. Web-search rows are marked complete only when the researcher reports inspecting that source.</p>
    <div className="mt-3 max-h-96 space-y-2 overflow-y-auto">{value.items.map(item => <div key={item.id} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex flex-wrap items-start justify-between gap-2"><div><a href={url(item.url)} target="_blank" rel="noreferrer" className="text-sm font-medium text-sky-700 underline">{item.name}</a><p className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">{readable(item.adapter_type)}</p></div><Badge value={item.status} /></div><p className="mt-2 text-xs text-slate-600">{item.pages_checked} pages · {item.listings_seen} listings · {item.candidates_emitted} shortlisted{item.closed_count ? ` · ${item.closed_count} closed` : ''}</p>{item.details?.researcher_report && <p className="mt-2 text-xs text-slate-500">{item.details.researcher_report}</p>}{item.error && <p className="mt-2 text-xs text-rose-700">{item.error}</p>}</div>)}</div>
  </details>;
}


function LiveRunProgress({ run, refreshing, lastRefresh, onRefresh }: { run: Detail; refreshing: boolean; lastRefresh: number; onRefresh: () => void }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const active = ['queued', 'running'].includes(run.status);
  const elapsed = Math.max(0, Math.floor(((run.completed_at ? Date.parse(run.completed_at) : now) - Date.parse(run.started_at)) / 1000));
  const age = run.progress?.updated_at ? Math.max(0, Math.floor((now - Date.parse(run.progress.updated_at))/1000)) : null;
  const terminal: Record<string, string> = { completed: 'Search finished. Review the jobs below.', partial: 'Search finished with some incomplete checks. Findings and errors are preserved below.', failed: 'Search failed. Any findings are preserved below.', interrupted: 'The worker stopped before completion. Findings are preserved below.' };
  return <div className="my-4 space-y-3"><p className="text-xs text-slate-600">Run provider: {run.ai_provider === 'openai' ? `OpenAI API · ${run.model}` : 'OpenClaw gateway'}</p>
    <div className="rounded-xl border border-sky-100 bg-sky-50 p-4">
      <div role="status" className="flex items-center gap-2 text-sm font-medium text-sky-950">{active && <Loader2 size={16} className="animate-spin" />}{run.status === 'queued' ? 'Queued — waiting for the research worker' : terminal[run.status] || run.phase}</div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-sky-800"><span>{Math.floor(elapsed/60)}m {elapsed%60}s elapsed{run.progress?.execution_started_at ? ' including queue time' : ''}</span><span>{active ? 'Updates automatically every 2 seconds' : 'Saved run history'}</span><button className="underline" disabled={refreshing} onClick={onRefresh}>{refreshing ? 'Refreshing…' : 'Refresh now'}</button><span>Last checked {lastRefresh ? new Date(lastRefresh).toLocaleTimeString() : '…'}</span></div>
      {active && run.progress?.waiting_for_model && <p className="mt-3 text-xs text-sky-900">Waiting for the researcher’s response · {readable(run.progress.model_request?.mode || 'research')} · attempt {run.progress.model_request?.attempt || 1}. Jobs appear when the discovery batch returns; individual browser/tool actions are not streamed.</p>}
      {active && age !== null && <p className={`mt-2 text-xs ${age > 45 ? 'text-amber-800' : 'text-sky-700'}`}>{age > 45 ? `No worker update for ${age}s. The page is still polling; this alone does not confirm a failure.` : `Worker last reported ${age}s ago. A heartbeat confirms the worker is responsive, not that new jobs were found.`}</p>}
      {active && !run.progress?.live_telemetry && <p className="mt-2 text-xs text-slate-600">This run began before detailed activity reporting. Its saved findings and status still update here.</p>}
    </div>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{[
      ['Found', run.progress?.found ?? run.results.length], ['Assessed', run.progress?.assessed ?? 0],
      ['Saved to queue', run.progress?.saved ?? run.verified], ['Processing errors', run.errors]
    ].map(([name,count]) => <div key={name} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><p className="text-xs text-slate-500">{name}</p><p className="mt-1 text-xl font-semibold">{count}</p></div>)}</div>
    <details open={active} className="rounded-xl border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-medium">Run activity ({run.activity?.length || 0})</summary>
      <div className="mt-3 max-h-64 space-y-3 overflow-y-auto" aria-label="Search run activity">{!(run.activity?.length) && <p className="text-xs text-slate-500">No detailed events were recorded for this run. See its status and findings.</p>}{[...(run.activity || [])].reverse().map(event => <div key={event.id} className="border-l-2 border-sky-200 pl-3"><time className="text-[11px] text-slate-500">{new Date(event.at).toLocaleTimeString()}</time><p className="text-sm text-slate-700">{event.message}</p>{url(event.source_url) && <a href={url(event.source_url)} target="_blank" rel="noreferrer" className="text-xs text-sky-700 underline">Source page</a>}</div>)}</div>
    </details>
  </div>;
}
