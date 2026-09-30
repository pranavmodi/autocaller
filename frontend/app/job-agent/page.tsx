"use client";

import { useState, useEffect, useCallback } from "react";
import { JobApplicationControls, ResumeSettings } from "@/components/JobApplicationControls";
import { JobApplicantProfile } from "@/components/JobApplicantProfile";
import { JobCvLibrary } from "@/components/JobCvLibrary";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, ArrowUpRight, Building2, Check, ClipboardCheck, FileText, Globe2, Link2, ListFilter, Loader2, MapPin, Plus, RefreshCw, Save, Search, Settings2, SlidersHorizontal } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import JobSearches from "@/components/JobSearches";
import { jobAgentRequest, type Candidate, type CollectionRun, type JobAgentConfig, type JobSource, type Overview, type ReviewStatus } from "@/lib/job-agent";

const labels: Record<ReviewStatus, string> = { new: "To review", shortlisted: "Shortlisted", needs_info: "Needs information", skipped: "Skipped" };
const tones: Record<ReviewStatus, string> = { new: "bg-sky-50 text-sky-700", shortlisted: "bg-emerald-50 text-emerald-700", needs_info: "bg-amber-50 text-amber-800", skipped: "bg-neutral-100 text-neutral-600" };
type LegalDegreeFilter = "exclude" | "all" | "required";
type ContractFilter = "all" | "contract" | "non_contract" | "unknown";
type ImportActivity = { id: number; at: string; kind: string; message: string; source_url?: string };
type ImportRun = {
  id: string; status: string; phase?: string; started_at?: string | null; completed_at?: string | null;
  ai_provider?: string | null; model?: string | null;
  progress?: { updated_at?: string | null; heartbeat_at?: string | null; last_activity_at?: string | null;
    waiting_for_model?: boolean; live_telemetry?: boolean;
    model_request?: { mode?: string; attempt?: number; started_at?: string; timeout_seconds?: number } | null };
  activity?: ImportActivity[];
  errors_detail?: { phase?: string; source_url?: string; error?: string }[];
};
type ImportResult = { candidate?: Candidate; created?: boolean; message?: string;
  import?: { message?: string; new_job?: boolean };
  website_application?: { requested: boolean; started: boolean; status?: string; stage?: string; error?: string } };
type BulkImportItem = { attemptId: string; url: string; status: "queued" | "running" | "completed" | "failed";
  provider: "gateway" | "openai"; startsApplication: boolean;
  message?: string; candidate?: Candidate; applicationStarted?: boolean };
type ImportQueueDetail = { id: string; source_url: string; ai_provider: "gateway" | "openai";
  start_website_application: boolean; resume_path?: string | null; status: "queued" | "running" | "completed" | "failed";
  result?: ImportResult; error?: string | null; run?: ImportRun | null };
const input = "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-900";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50";
const primary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50";
const panel = "rounded-xl border border-neutral-200 bg-white";
const date = (value?: string | null) => value ? new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Not yet";
const readable = (value?: string | null) => value ? value.replaceAll("_", " ") : "Unknown";
function safeUrl(value: string) { try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } }
function publicJobUrl(value: string) { const url = safeUrl(value.trim()); return url && new URL(url).hostname ? url : undefined; }
function publicJobUrls(value: string) {
  const parts = value.split(/\s+/).map(item => item.trim()).filter(Boolean);
  const valid: string[] = [], invalid: string[] = [], seen = new Set<string>();
  for (const part of parts) {
    const url = publicJobUrl(part);
    if (!url) { invalid.push(part); continue; }
    const identity = url.replace(/#.*$/, "");
    if (!seen.has(identity)) { seen.add(identity); valid.push(url); }
  }
  return { valid, invalid, duplicates: parts.length - valid.length - invalid.length };
}
function sourceOf(job: Candidate): JobSource {
  if (job.posting.job_source === "manual") return "manual";
  return job.posting.job_source === "external_search" || job.posting.discovery_provider === "possibleos_daily_career_search" ? "external_search" : "possibleos";
}
function sourceLabel(job: Candidate) { const source = sourceOf(job); return source === "manual" ? "Manual" : source === "external_search" ? "Job Agent search" : "Possible OS"; }
function jobWorkflowState(job: Candidate) {
  const email = job.application?.status || "not_started";
  const website = job.browser_application?.status || "not_started";
  return email === "not_started" && website === "not_started" ? "ready_to_apply" : job.application_state || "stopped";
}
function queueQuery(status: ReviewStatus | "", search: string, page: number, order: string, category: string, source: JobSource | "", legalDegree: LegalDegreeFilter, contract: ContractFilter) {
  const params = new URLSearchParams({ search, page: String(page), order, category, legal_degree: legalDegree, contract });
  if (status) params.set("status", status);
  if (source) params.set("source", source);
  return params.toString();
}
function ErrorBox({ error }: { error: Error | null }) { return error ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error.message}</div> : null; }

function ImportProgress({ run, loading, refreshing, provider, startsApplication, onRefresh }: {
  run?: ImportRun; loading: boolean; refreshing: boolean; provider: "gateway" | "openai";
  startsApplication: boolean; onRefresh: () => void;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const active = !run || ["starting", "queued", "running"].includes(run.status);
  const terminal = run && !active;
  const elapsed = run?.started_at ? Math.max(0, Math.floor(((run.completed_at ? Date.parse(run.completed_at) : now) - Date.parse(run.started_at)) / 1000)) : 0;
  const updateAge = run?.progress?.updated_at ? Math.max(0, Math.floor((now - Date.parse(run.progress.updated_at)) / 1000)) : null;
  const recent = [...(run?.activity || [])].reverse().slice(0, 6);
  const requestMode: Record<string, string> = {
    url_import: "Reading the job page",
    url_import_identity: "Identifying the employer and role",
    url_import_identity_research: "Searching for this exact job listing",
    url_import_corroboration: "Finding a readable copy of the blocked job page",
    url_import_enrichment: "Finding official employer evidence",
    verification: "Checking the job against its sources",
  };
  const lastError = run?.errors_detail?.at(-1);
  const current = run?.progress?.waiting_for_model
    ? requestMode[run.progress.model_request?.mode || ""] || "Waiting for the AI researcher"
    : terminal && lastError?.error ? lastError.error : run?.phase || recent[0]?.message || "Starting job verification";
  const providerLabel = (run?.ai_provider || provider) === "openai"
    ? `OpenAI API · ${run?.model || "gpt-5.6-luna"}` : "OpenClaw gateway";
  const tone = ["failed", "partial", "interrupted"].includes(run?.status || "") ? "border-amber-200 bg-amber-50" : terminal ? "border-emerald-200 bg-emerald-50" : "border-sky-200 bg-white";
  return <div className={`mt-4 rounded-xl border p-4 ${tone}`} aria-live="polite">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="flex items-center gap-2 text-sm font-semibold text-neutral-950">{active && <Loader2 className="h-4 w-4 animate-spin text-sky-700" />}{current}</p>
        <p className="mt-1 text-xs text-neutral-600">{providerLabel} · {elapsed ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s elapsed` : "Starting now"}</p>
      </div>
      <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${["failed", "partial", "interrupted"].includes(run?.status || "") ? "bg-amber-100 text-amber-900" : active ? "bg-sky-100 text-sky-800" : "bg-emerald-100 text-emerald-800"}`}>{readable(run?.status || "starting")}</span>
    </div>
    <div className="mt-3 grid gap-2 sm:grid-cols-3">
      <div className="rounded-lg border border-black/5 bg-white/70 p-2.5"><p className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">Now</p><p className="mt-1 text-xs text-neutral-800">{current}</p></div>
      <div className="rounded-lg border border-black/5 bg-white/70 p-2.5"><p className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">Next</p><p className="mt-1 text-xs text-neutral-800">{startsApplication ? "Save the job, select a resume, then start the website application" : "Save or reuse one job in the review queue"}</p></div>
      <div className="rounded-lg border border-black/5 bg-white/70 p-2.5"><p className="text-[11px] font-medium uppercase tracking-wide text-neutral-500">Updates</p><p className="mt-1 text-xs text-neutral-800">{active ? "Automatic every 1.5 seconds" : "Final result saved"}{updateAge !== null ? ` · worker updated ${updateAge}s ago` : ""}</p></div>
    </div>
    {run?.progress?.waiting_for_model && <p className="mt-3 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-900">The request is with the AI researcher now · attempt {run.progress.model_request?.attempt || 1}. A heartbeat updates while it waits.</p>}
    {!!recent.length && <details open className="mt-3 rounded-lg border border-black/5 bg-white/70 p-3"><summary className="cursor-pointer text-xs font-medium text-neutral-800">Live activity ({run?.activity?.length || 0})</summary><div className="mt-3 max-h-52 space-y-3 overflow-y-auto">{recent.map(event => <div key={event.id} className="border-l-2 border-sky-200 pl-3"><time className="text-[11px] text-neutral-500">{new Date(event.at).toLocaleTimeString()}</time><p className="text-xs text-neutral-700">{event.message}</p></div>)}</div></details>}
    {!!run?.errors_detail?.length && <details open className="mt-3 rounded-lg border border-red-200 bg-white/70 p-3"><summary className="cursor-pointer text-xs font-medium text-red-800">What stopped ({run.errors_detail.length})</summary>{run.errors_detail.map((error, index) => <p key={index} className="mt-2 break-words text-xs text-red-800">{error.phase || "Verification"}: {error.error || "Unknown error"}</p>)}</details>}
    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-neutral-600">{loading && <span>Connecting to the saved run…</span>}<button type="button" className="font-medium text-sky-800 underline" disabled={refreshing} onClick={onRefresh}>{refreshing ? "Refreshing…" : "Refresh now"}</button><span>No application is submitted during verification.</span></div>
  </div>;
}

function BulkImportRow({ item, onOpen, onUpdate }: {
  item: BulkImportItem; onOpen: (candidate: Candidate) => void;
  onUpdate: (attemptId: string, changes: Partial<BulkImportItem>) => void;
}) {
  const query = useQuery({
    queryKey: ["job-agent", "url-import", item.attemptId],
    queryFn: () => jobAgentRequest<ImportQueueDetail>(`/listings/import-queue/${item.attemptId}`),
    refetchInterval: value => ["completed", "failed"].includes(value.state.data?.status || "") ? false : 1500,
  });
  useEffect(() => {
    const value = query.data;
    if (!value) return;
    const result = value.result || {};
    const applicationError = result.website_application?.requested && !result.website_application.started
      ? ` Job saved, but its website application could not start: ${result.website_application.error || "Open the job and try again."}` : "";
    onUpdate(item.attemptId, {
      status: value.status, candidate: result.candidate,
      applicationStarted: !!result.website_application?.started,
      message: value.status === "failed" ? value.error || "Job verification failed."
        : value.status === "completed" ? (result.website_application?.started ? "Job saved; website application started."
          : result.candidate ? result.created || result.import?.new_job ? "Verified and added to the review queue." : "Verified; existing saved job reused."
          : result.message || "Processing completed.") + applicationError : undefined,
    });
  }, [query.data, item.attemptId, onUpdate]);
  const active = !query.data || query.data.status === "queued" || query.data.status === "running";
  const status = query.data?.status || item.status;
  const candidate = query.data?.result?.candidate || item.candidate;
  const tone = status === "failed" ? "border-red-200 bg-red-50" : status === "completed" ? "border-emerald-200 bg-emerald-50" : "border-sky-200 bg-white";
  return <article className={`rounded-xl border p-3 ${tone}`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1"><p className="flex items-center gap-2 text-sm font-medium text-neutral-900">{active && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-sky-700" />}<span className="break-all">{item.url}</span></p>
        <p className="mt-1 text-xs text-neutral-600">{status === "queued" ? "Waiting for an import slot" : status === "running" ? query.data?.run?.phase || query.data?.run?.activity?.at(-1)?.message || "Opening and verifying this job" : item.message}</p></div>
      <span className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-medium">{readable(status)}</span>
    </div>
    {candidate && <button type="button" className={`${button} mt-3`} onClick={() => onOpen(candidate)}>Open saved job</button>}
    {query.error && active && <p className="mt-2 text-xs text-amber-800">Live progress is temporarily unavailable; the import request is still tracked.</p>}
    {status === "running" && <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-sky-900">Show live verification details</summary><ImportProgress run={query.data?.run || undefined} loading={query.isPending} refreshing={query.isFetching} provider={item.provider} startsApplication={item.startsApplication} onRefresh={() => query.refetch()} /></details>}
  </article>;
}

export default function JobAgentPage() {
  const client = useQueryClient();
  const [tab, setTab] = useState("queue");
  useEffect(() => { const params = new URLSearchParams(window.location.search); if (params.get('tab') === 'searches' || params.has('run')) setTab('searches'); }, []);
  const [filter, setFilter] = useState<ReviewStatus | "">("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [source, setSource] = useState<JobSource | "">("");
  const [legalDegree, setLegalDegree] = useState<LegalDegreeFilter>("exclude");
  const [contract, setContract] = useState<ContractFilter>("all");
  const [page, setPage] = useState(1);
  const [order, setOrder] = useState("updated_desc");
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [notice, setNotice] = useState("");
  const [jobUrl, setJobUrl] = useState("");
  const [importResumePath, setImportResumePath] = useState("");
  const [importProvider, setImportProvider] = useState<"gateway" | "openai">("gateway");
  const [importMessage, setImportMessage] = useState("");
  const [importItems, setImportItems] = useState<BulkImportItem[]>([]);
  const [importBusy, setImportBusy] = useState(false);
  const updateImportItem = useCallback((attemptId: string, changes: Partial<BulkImportItem>) => {
    setImportItems(current => {
      if (changes.status === "completed" || changes.status === "failed") {
        return current.filter(item => item.attemptId !== attemptId);
      }
      return current.map(item => item.attemptId === attemptId ? { ...item, ...changes } : item);
    });
  }, []);
  const overview = useQuery({ queryKey: ["job-agent", "overview"], queryFn: () => jobAgentRequest<Overview>("/overview"), refetchInterval: 15000 });
  const resumeLibrary = useQuery({ queryKey: ["job-agent", "resumes"], queryFn: () => jobAgentRequest<{ items: { path: string; filename: string }[] }>("/resumes"), staleTime: 30000 });
  const recentImports = useQuery({ queryKey: ["job-agent", "url-import-queue"], queryFn: () => jobAgentRequest<{ items: ImportQueueDetail[] }>("/listings/import-queue?limit=50"), refetchInterval: 5000 });
  useEffect(() => {
    if (!recentImports.data) return;
    setImportItems(current => {
      const existing = new Map(current.map(item => [item.attemptId, item]));
      return recentImports.data!.items
        .filter(row => row.status === "queued" || row.status === "running")
        .map(row => ({
          ...existing.get(row.id),
          attemptId: row.id, url: row.source_url, status: row.status,
          provider: row.ai_provider, startsApplication: row.start_website_application,
          message: row.status === "failed" ? row.error || "Job verification failed." : existing.get(row.id)?.message,
          candidate: row.result?.candidate || existing.get(row.id)?.candidate,
          applicationStarted: !!row.result?.website_application?.started,
        }));
    });
  }, [recentImports.data]);
  const jobs = useQuery({ queryKey: ["job-agent", "jobs", filter, search, page, order, category, source, legalDegree, contract], queryFn: () => jobAgentRequest<{ items: Candidate[]; total: number; total_pages: number }>(`/jobs?${queueQuery(filter, search, page, order, category, source, legalDegree, contract)}`), refetchInterval: 15000 });
  const refresh = () => client.invalidateQueries({ queryKey: ["job-agent"] });
  const collect = useMutation({ mutationFn: () => jobAgentRequest<CollectionRun>("/collect", {}),
    onSuccess: () => { setNotice(`Sync queued. Progress is saved automatically; all matching listings will be processed.`); refresh(); }, onError: () => refresh() });
  const runImports = async () => {
    const parsed = publicJobUrls(jobUrl);
    if (!parsed.valid.length || importBusy) return;
    const provider = importProvider, startsApplication = true;
    setImportBusy(true); setImportMessage("");
    if (parsed.invalid.length || parsed.duplicates) setImportMessage([
      parsed.invalid.length ? `${parsed.invalid.length} invalid value${parsed.invalid.length === 1 ? " was" : "s were"} skipped.` : "",
      parsed.duplicates ? `${parsed.duplicates} duplicate link${parsed.duplicates === 1 ? " was" : "s were"} collapsed.` : "",
    ].filter(Boolean).join(" "));
    try {
      const queued = await jobAgentRequest<{ items: ImportQueueDetail[]; duplicates_skipped: number }>("/listings/import-batch", {
        source_urls: parsed.valid, start_website_application: startsApplication,
        ai_provider: provider, resume_path: importResumePath || null,
      });
      const items: BulkImportItem[] = queued.items.map(item => ({
        attemptId: item.id, url: item.source_url, status: item.status,
        provider, startsApplication,
      }));
      setImportItems(current => [...items, ...current].slice(0, 50));
      setJobUrl(""); setPage(1); refresh();
      setNotice(`${items.length} job link${items.length === 1 ? " is" : "s are"} queued for verification and application. You can leave this page while they run.`);
    } catch (cause) {
      setImportMessage(cause instanceof Error ? cause.message : "Could not queue these job links.");
    } finally {
      setImportBusy(false);
    }
  };
  const data = overview.data;
  if (!data) return <div className="space-y-4"><h1 className="text-2xl font-semibold">Job agent</h1><ErrorBox error={overview.error} />{overview.isPending ? <p className="flex items-center gap-2 text-sm text-neutral-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading workspace…</p> : <button className={button} onClick={() => overview.refetch()}>Try again</button>}</div>;
  const total = Object.values(data.counts).reduce((a, b) => a + b, 0);

  return <div className="space-y-6">
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div><div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-neutral-500"><BriefcaseBusiness className="h-4 w-4" /> Career workspace</div>
        <h1 className="text-2xl font-semibold tracking-tight">Job agent</h1><p className="mt-1 max-w-xl text-sm text-neutral-500">Your job pipeline, decisions and operating preferences in one place.</p></div>
      <div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800">Email and website applications</span>
        <button className={primary} disabled={collect.isPending || !data.config.collection_enabled} onClick={() => { setNotice(""); collect.mutate(); }}><RefreshCw className={`h-4 w-4 ${collect.isPending ? "animate-spin" : ""}`} />{collect.isPending ? "Queuing…" : "Sync now"}</button></div>
    </header>
    <ErrorBox error={overview.error || collect.error} />
    {notice && <div role="status" className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"><Check className="mt-0.5 h-4 w-4 shrink-0" />{notice}</div>}
    <section className="rounded-xl border border-sky-200 bg-sky-50/60 p-4" aria-labelledby="add-job-by-link-title">
      <div className="flex items-start gap-3">
        <span className="rounded-lg border border-sky-200 bg-white p-2 text-sky-700"><Link2 className="h-4 w-4" /></span>
        <div className="min-w-0 flex-1">
          <h2 id="add-job-by-link-title" className="text-sm font-semibold text-neutral-950">Add jobs and start applications</h2>
          <p className="mt-1 text-xs leading-relaxed text-neutral-600">Paste one or more LinkedIn or public job-posting URLs, one per line. One action verifies each job, saves or reuses it, selects the best resume, and starts its website application.</p>
          <ol className="mt-3 grid gap-2 text-xs text-neutral-700 sm:grid-cols-4" aria-label="Application workflow">
            {['Verify job', 'Save or reuse', 'Select resume', 'Start application'].map((step, index) => <li key={step} className="flex items-center gap-2 rounded-lg border border-sky-100 bg-white/70 px-2.5 py-2"><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-100 text-[11px] font-semibold text-sky-800">{index + 1}</span>{step}</li>)}
          </ol>
          <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={event => { event.preventDefault(); void runImports(); }}>
            <label className="min-w-0 flex-1"><span className="sr-only">Job post links</span><textarea aria-label="Job post links" className={`${input} min-h-28 resize-y`} inputMode="url" placeholder={"Paste job posting links…\nhttps://company.example/jobs/role-1\nhttps://www.linkedin.com/jobs/view/123"} value={jobUrl} disabled={importBusy} onChange={event => { setJobUrl(event.target.value); setImportMessage(""); }} /></label>
            <button type="submit" className={`${primary} self-start sm:min-w-44`} disabled={!publicJobUrls(jobUrl).valid.length || importBusy}>{importBusy ? <><Loader2 className="h-4 w-4 animate-spin" />Starting…</> : <><Plus className="h-4 w-4" />Add and start</>}</button>
          </form>
          <label className="mt-3 block text-sm font-medium text-neutral-800">Verification AI provider<select className={`${input} mt-2`} value={importProvider} disabled={importBusy} onChange={event => setImportProvider(event.target.value as "gateway" | "openai")}><option value="gateway">OpenClaw gateway · queued</option><option value="openai">OpenAI API · up to 3 in parallel · gpt-5.6-luna</option></select><span className="mt-1 block text-xs font-normal leading-relaxed text-neutral-500">Each link is saved immediately, so you can add more while earlier jobs are still processing. OpenAI verifies up to three distinct links concurrently. OpenClaw processes one at a time to avoid contention on its interactive lane. Website applications use their own provider setting.</span></label>
          <label className="mt-3 block text-sm font-medium text-neutral-800">Resume for these applications<select className={`${input} mt-2`} value={importResumePath} disabled={importBusy || resumeLibrary.isPending} onChange={event => setImportResumePath(event.target.value)}><option value="">Automatic — select the best category resume</option>{resumeLibrary.data?.items.filter((file, index, items) => items.findIndex(other => other.path === file.path) === index).map(file => <option key={file.path} value={file.path}>{file.filename}</option>)}</select><span className="mt-1 block text-xs font-normal leading-relaxed text-neutral-500">Choose a PDF to pin it to every link in this batch. Automatic selection remains the default.</span></label>
          <p className="mt-3 rounded-lg border border-sky-200 bg-white/80 p-3 text-xs leading-relaxed text-neutral-600"><span className="font-medium text-neutral-800">Runs automatically after verification.</span> Each job gets its own durable application run. When companion email is enabled in Settings, the same operation also starts one Zoho email workflow if a verified contact is found.</p>
          {jobUrl.trim() && publicJobUrls(jobUrl).invalid.length > 0 && <p className="mt-2 text-xs text-red-700">{publicJobUrls(jobUrl).invalid.length} value{publicJobUrls(jobUrl).invalid.length === 1 ? " is" : "s are"} not a complete public HTTP or HTTPS link and will be skipped.</p>}
          {importMessage && <p role="status" className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{importMessage}</p>}
          {!!importItems.length && <div className="mt-4 space-y-3" aria-live="polite"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-neutral-900">Import queue</p><p className="text-xs text-neutral-600">{importItems.length} remaining</p></div>{importItems.map(item => <BulkImportRow key={item.attemptId} item={item} onOpen={setSelected} onUpdate={updateImportItem} />)}</div>}
        </div>
      </div>
    </section>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{(Object.keys(labels) as ReviewStatus[]).map(status => <button key={status} onClick={() => { setFilter(status); setPage(1); setTab("queue"); }} className={`${panel} p-4 text-left transition-colors hover:border-neutral-400`}><p className="text-xs font-medium text-neutral-500">{labels[status]}</p><p className="mt-2 text-3xl font-semibold tracking-tight">{data.counts[status]}</p></button>)}</div>
    <div className="flex gap-1 overflow-x-auto border-b border-neutral-200" role="tablist" aria-label="Job agent sections">{[{ key: "queue", label: "Jobs", icon: BriefcaseBusiness }, { key: "searches", label: "Searches", icon: Search }, { key: "cvs", label: "CVs", icon: FileText }, { key: "profile", label: "Applicant profile", icon: ClipboardCheck }, { key: "settings", label: "Settings", icon: Settings2 }].map(({ key, label, icon: Icon }) => <button key={key} id={`tab-${key}`} role="tab" aria-controls={`panel-${key}`} aria-selected={tab === key} onClick={() => setTab(key)} className={`flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium ${tab === key ? "border-neutral-900 text-neutral-900" : "border-transparent text-neutral-500 hover:text-neutral-800"}`}><Icon className="h-4 w-4" />{label}</button>)}</div>
    {tab === "queue" && <div role="tabpanel" id="panel-queue" aria-labelledby="tab-queue" className="min-w-0">
      <section className={`${panel} min-w-0 overflow-hidden`}>
        <div className="grid gap-3 border-b border-neutral-200 p-4 sm:grid-cols-2"><select aria-label="Order jobs" className={input} value={order} onChange={e => { setOrder(e.target.value); setPage(1); }}><option value="updated_desc">Most recently updated</option><option value="posted_desc">Most recently posted</option><option value="contact_desc">Known contact email first</option><option value="posted_asc">Oldest posted first</option><option value="found_desc">Recently added</option></select><input aria-label="Search jobs" className={input} placeholder="Search company or role…" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /><select aria-label="Review status" className={input} value={filter} onChange={e => { setFilter(e.target.value as ReviewStatus | ""); setPage(1); }}><option value="">All decisions</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Filter by category" className={input} value={category} onChange={e => { setCategory(e.target.value); setPage(1); }}><option value="">All categories</option><option value="needs_review">Classification needs review</option>{data.config.resume_categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><select aria-label="Filter by job source" className={input} value={source} onChange={e => { setSource(e.target.value as JobSource | ""); setPage(1); }}><option value="">All sources</option><option value="external_search">Job Agent search</option><option value="possibleos">Possible OS</option><option value="manual">Manual</option></select><select aria-label="Filter by contract status" className={input} value={contract} onChange={e => { setContract(e.target.value as ContractFilter); setPage(1); }}><option value="all">All contract types</option><option value="contract">Contract roles</option><option value="non_contract">Non-contract roles</option><option value="unknown">Contract type unknown</option></select><select aria-label="Filter by legal degree requirement" className={input} value={legalDegree} onChange={e => { setLegalDegree(e.target.value as LegalDegreeFilter); setPage(1); }}><option value="exclude">Hide legal-degree roles</option><option value="all">Show all roles</option><option value="required">Legal-degree roles only</option></select></div>
        <ErrorBox error={jobs.error} />
        {jobs.isPending && <p className="p-6 text-sm text-neutral-500">Loading listings…</p>}
        {!jobs.isPending && !jobs.error && !jobs.data?.items.length && <div className="px-6 py-14 text-center"><ListFilter className="mx-auto mb-3 h-7 w-7 text-neutral-400" /><h2 className="font-medium">{total ? "No jobs match these filters" : "Start with the jobs already found"}</h2><p className="mx-auto mt-2 max-w-sm text-sm text-neutral-500">{total ? "Change your search or filters to see more jobs." : "Import existing Possible OS listings, then apply, shortlist, or record what needs checking."}</p>{!total && <button className={`${button} mt-5`} onClick={() => collect.mutate()} disabled={collect.isPending || !data.config.collection_enabled}>Sync now</button>}</div>}
        <div className="divide-y divide-neutral-100">{jobs.data?.items.map(job => {
          const workflow = jobWorkflowState(job);
          const emailStarted = !!job.application?.status && job.application.status !== "not_started";
          const websiteStarted = !!job.browser_application?.status && job.browser_application.status !== "not_started";
          return <button key={job.id} className="block w-full p-4 text-left hover:bg-neutral-50" onClick={() => setSelected(job)}>
            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-semibold">{job.posting.title || "Untitled role"}</p><p className="mt-1 break-words text-sm text-neutral-600">{job.posting.firm_name}</p></div><span className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold ${applicationTone(workflow)}`}>{applicationStateLabel[workflow] || readable(workflow)}</span></div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500"><span className="font-medium text-neutral-700">{sourceLabel(job)}</span><span>{job.posting.location || "Location not specified"}</span><span>{readable(job.posting.work_arrangement)}</span><span>{job.posting.contract_status === "contract" ? "Contract" : job.posting.contract_status === "non_contract" ? "Non-contract" : "Contract type unknown"}</span><span>Posted {job.posting.posted_date || "date unknown"}</span><span>Updated {date(job.application_updated_at || job.updated_at)}</span>{job.contact?.available && <span className="font-medium text-emerald-700">Contact: {job.contact.best?.email}</span>}{job.posting.legal_degree_requirement === "required" && <span className="font-medium text-amber-800">Legal degree required</span>}{job.posting.status === "closed" && <span className="text-amber-800">Closed at source</span>}</div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs"><span className={`rounded-full px-2 py-1 ${tones[job.status]}`}>Decision · {labels[job.status]}</span><span className="text-neutral-500">{job.classification?.category_name || readable(job.classification?.status || "pending")}</span>{websiteStarted && <span className={`rounded-full border px-2 py-1 ${applicationTone(job.browser_application!.status)}`}>Website · {readable(job.browser_application!.status)}</span>}{emailStarted && <span className={`rounded-full border px-2 py-1 ${applicationTone(job.application!.status)}`}>Email · {readable(job.application!.status)}</span>}</div>
            {(job.browser_application?.question?.text || job.browser_application?.error || job.application?.error) && <p className="mt-2 line-clamp-2 text-xs text-amber-800">{job.browser_application?.question?.text || job.browser_application?.error || job.application?.error}</p>}
            {job.note && <p className="mt-2 line-clamp-2 text-xs text-neutral-600">Your note: {job.note}</p>}
          </button>;
        })}</div>
        {!!jobs.data?.total && <div className="flex items-center justify-between gap-2 border-t border-neutral-200 p-3 text-xs text-neutral-500"><span>{jobs.data.total} listings · Page {page} of {jobs.data.total_pages}</span><div className="flex gap-2"><button className={button} disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><button className={button} disabled={page >= jobs.data.total_pages} onClick={() => setPage(p => p + 1)}>Next</button></div></div>}
      </section>
    </div>}
    {tab === "searches" && <JobSearches overview={data} onOpen={setSelected} />}
    {tab === "cvs" && <JobCvLibrary />}
    {tab === "profile" && <section role="tabpanel" id="panel-profile" aria-labelledby="tab-profile"><JobApplicantProfile /></section>}
    {tab === "settings" && <section role="tabpanel" id="panel-settings" aria-labelledby="tab-settings"><SettingsForm snapshot={data} onSaved={refresh} /></section>}
    <Dialog open={!!selected} onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className="max-h-[92dvh] w-[96vw] max-w-5xl overflow-y-auto">{selected && <ReviewForm key={selected.id} job={selected} categories={data.config.resume_categories} onSaved={() => { setSelected(null); refresh(); }} />}</DialogContent></Dialog>
  </div>;
}

function applicationTone(status: string) {
  if (["completed", "sent_verified", "submitted"].includes(status)) return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (["draft_ready", "ready", "ready_to_apply"].includes(status)) return "border-sky-200 bg-sky-50 text-sky-800";
  if (["in_progress", "queued", "running", "verifying", "preparing", "queued_send", "sending"].includes(status)) return "border-violet-200 bg-violet-50 text-violet-800";
  if (["needs_attention", "waiting_for_answer", "blocked", "submission_uncertain", "human_control", "paused", "needs_review", "delivery_unconfirmed", "failed"].includes(status)) return "border-amber-200 bg-amber-50 text-amber-900";
  return "border-neutral-200 bg-neutral-100 text-neutral-700";
}

const applicationStateLabel: Record<string, string> = {
  ready_to_apply: "Ready to apply",
  in_progress: "In progress", needs_attention: "Needs attention", completed: "Application completed",
  draft_ready: "Draft ready", stopped: "Stopped",
};

function ReviewForm({ job, categories, onSaved }: { job: Candidate; categories: JobAgentConfig["resume_categories"]; onSaved: () => void }) {
  const [status, setStatus] = useState(job.status);
  const [note, setNote] = useState(job.note);
  const save = useMutation({ mutationFn: () => jobAgentRequest(`/jobs/${job.id}/review`, { status, note, revision: job.revision }), onSuccess: onSaved });
  return <><DialogTitle className="pr-6 leading-snug">{job.posting.title}</DialogTitle><DialogDescription>{job.posting.firm_name} · {job.posting.location || "Location unknown"}</DialogDescription>
    <div className="space-y-4"><div className="flex flex-wrap gap-2 text-xs"><span className="rounded bg-neutral-100 px-2 py-1">Source: {sourceLabel(job)}</span><span className="rounded bg-neutral-100 px-2 py-1">{readable(job.posting.work_arrangement)}</span><span className="rounded bg-neutral-100 px-2 py-1">{job.posting.contract_status === "contract" ? "Contract" : job.posting.contract_status === "non_contract" ? "Non-contract" : "Contract type unknown"}</span><span className="rounded bg-neutral-100 px-2 py-1">Source status: {readable(job.posting.status)}</span>{job.posting.legal_degree_requirement === "required" && <span className="rounded bg-amber-100 px-2 py-1 font-medium text-amber-900">Legal degree required</span>}</div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-700">{job.posting.description_summary || "No description stored. Open the original listing to review the role."}</p>
      {job.posting.legal_degree_requirement === "required" && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">{job.posting.legal_degree_reason}{job.posting.legal_degree_evidence ? ` Evidence: “${job.posting.legal_degree_evidence}”` : ""}</p>}
      <div className="text-xs text-neutral-500">Last source check: {date(job.posting.last_checked_at)}. Location eligibility has not been assessed for you.</div>
      {safeUrl(job.posting.source_url) && <a href={safeUrl(job.posting.source_url)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-medium underline underline-offset-4">Open job listing <ArrowUpRight className="h-4 w-4" /></a>}
      <JobApplicationControls job={job} categories={categories} />
      <div className="border-t border-neutral-200 pt-4"><label htmlFor="job-decision" className="mb-2 block text-sm font-medium">Your decision</label><select id="job-decision" className={input} value={status} onChange={e => setStatus(e.target.value as ReviewStatus)}>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div>
      <label className="block text-sm font-medium">Notes<textarea className={`${input} mt-2 min-h-28`} maxLength={4000} value={note} onChange={e => setNote(e.target.value)} placeholder="Why this fits, what needs checking, or why you skipped it…" /></label>
      <p className="text-xs text-neutral-500">Saving a review decision does not send an application.</p><ErrorBox error={save.error} /><button className={`${primary} w-full`} disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save decision"}</button>
    </div></>;
}

function SettingsForm({ snapshot, onSaved }: { snapshot: Overview; onSaved: () => void }) {
  const [config, setConfig] = useState<JobAgentConfig>({ ...snapshot.config });
  const [revision, setRevision] = useState(snapshot.revision);
  const [saved, setSaved] = useState(false);
  const update = <K extends keyof JobAgentConfig>(key: K, value: JobAgentConfig[K]) => { setSaved(false); setConfig(c => ({ ...c, [key]: value })); };
  const toggleSource = (sourceId: string, enabled: boolean) => update("search_source_ids", enabled
    ? [...config.search_source_ids, sourceId]
    : config.search_source_ids.filter(id => id !== sourceId));
  const save = useMutation({ mutationFn: () => jobAgentRequest<{ revision: number; config: JobAgentConfig }>("/config", { config, revision }), onSuccess: result => { setRevision(result.revision); setConfig(result.config); setSaved(true); onSaved(); } });
  return <form onSubmit={e => { e.preventDefault(); save.mutate(); }} className="max-w-5xl space-y-6 pb-8">
    <header className="overflow-hidden rounded-2xl border border-neutral-800 bg-gradient-to-br from-neutral-950 via-neutral-900 to-neutral-800 p-6 text-white shadow-sm">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-neutral-300"><SlidersHorizontal className="h-4 w-4" /> Agent configuration</div>
          <h2 className="mt-3 text-xl font-semibold tracking-tight">Shape what the agent finds and how it applies</h2>
          <p className="mt-2 text-sm leading-relaxed text-neutral-300">These settings control listing collection, the daily and on-demand search, resume selection, and application writing.</p>
        </div>
        <span className="w-fit rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-medium text-neutral-200">Revision {revision}</span>
      </div>
      <div className="mt-5 grid gap-2 text-xs sm:grid-cols-4">
        {["Collection", "Search scope", "Resume routing", "Writing style"].map((label, index) => <div key={label} className="rounded-lg border border-white/10 bg-white/[0.06] px-3 py-2.5"><span className="mr-2 text-neutral-500">0{index + 1}</span>{label}</div>)}
      </div>
    </header>

    {snapshot.revision > revision && !save.isPending && <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 sm:flex-row sm:items-center sm:justify-between"><span>Preferences changed in another window. Your edits are preserved.</span><button type="button" className={button} onClick={() => { setConfig({ ...snapshot.config }); setRevision(snapshot.revision); setSaved(false); }}>Reload saved settings</button></div>}

    <section className="overflow-hidden rounded-2xl border border-sky-200/80 bg-sky-50/40 shadow-sm">
      <div className="flex items-start gap-3 border-b border-sky-200/70 bg-sky-100/70 p-5">
        <span className="rounded-xl border border-sky-200 bg-white/80 p-2.5 text-sky-700"><RefreshCw className="h-5 w-5" /></span>
        <div><p className="text-xs font-semibold uppercase tracking-wider text-sky-700">01 · Collection</p><h2 className="mt-1 font-semibold text-neutral-950">Listing collection</h2><p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-600">Choose which stored Possible OS listings enter the review queue. Existing decisions remain unchanged when these filters change.</p></div>
      </div>
      <div className="space-y-4 p-5">
        <label className="flex items-start gap-3 rounded-xl border border-sky-200/70 bg-white/90 p-4 shadow-sm"><input type="checkbox" className="mt-1 h-4 w-4 accent-sky-700" checked={config.collection_enabled} onChange={e => update("collection_enabled", e.target.checked)} /><span className="text-sm"><span className="font-medium text-neutral-900">Automatically sync stored listings</span><span className="mt-1 block text-xs leading-relaxed text-neutral-500">Check for stored listings every minute. Pausing does not lose progress. The daily Job Agent search continues on its own schedule.</span></span></label>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <label className="rounded-xl border border-sky-100 bg-white/80 p-4 text-sm font-medium text-neutral-800"><span className="flex items-center gap-2"><Search className="h-4 w-4 text-sky-700" />Title or company contains</span><input className={`${input} mt-3`} value={config.search} maxLength={255} onChange={e => update("search", e.target.value)} placeholder="Any title or company" /></label>
          <label className="rounded-xl border border-sky-100 bg-white/80 p-4 text-sm font-medium text-neutral-800"><span className="flex items-center gap-2"><Globe2 className="h-4 w-4 text-sky-700" />Work arrangement</span><select className={`${input} mt-3`} value={config.remote_scope} onChange={e => update("remote_scope", e.target.value as JobAgentConfig["remote_scope"])}><option value="any">All, including unknown</option><option value="remote">Remote roles</option><option value="global">Explicitly global remote</option></select></label>
          <label className="rounded-xl border border-sky-100 bg-white/80 p-4 text-sm font-medium text-neutral-800"><span className="flex items-center gap-2"><RefreshCw className="h-4 w-4 text-sky-700" />Posting age</span><select className={`${input} mt-3`} value={config.posted_within_days ?? ""} onChange={e => update("posted_within_days", e.target.value ? Number(e.target.value) : null)}><option value="">Any date, including unknown</option>{[7, 14, 30, 60, 90, 180, 365].map(days => <option key={days} value={days}>Last {days} days</option>)}</select><span className="mt-2 block text-xs font-normal leading-relaxed text-neutral-500">A date range excludes listings whose posting date cannot be verified.</span></label>
        </div>
      </div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-emerald-200/80 bg-emerald-50/40 shadow-sm">
      <div className="flex items-start gap-3 border-b border-emerald-200/70 bg-emerald-100/70 p-5">
        <span className="rounded-xl border border-emerald-200 bg-white/80 p-2.5 text-emerald-700"><Search className="h-5 w-5" /></span>
        <div><p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">02 · Search scope</p><h2 className="mt-1 font-semibold text-neutral-950">Roles, industries and location</h2><p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-600">These are defaults for creating new searches. Edit targeting and schedules for existing searches in the Searches tab.</p></div>
      </div>
      <div className="grid gap-4 p-5 lg:grid-cols-2">
        <label className="rounded-xl border border-emerald-100 bg-white/90 p-4 text-sm font-medium text-neutral-800"><span className="flex items-center gap-2"><Search className="h-4 w-4 text-emerald-700" />Roles you want</span><textarea className={`${input} mt-3 min-h-28`} value={config.target_roles} maxLength={2000} onChange={e => update("target_roles", e.target.value)} /><span className="mt-2 block text-xs font-normal leading-relaxed text-neutral-500">Separate role groups with commas, semicolons, or new lines.</span></label>
        <label className="rounded-xl border border-emerald-100 bg-white/90 p-4 text-sm font-medium text-neutral-800"><span className="flex items-center gap-2"><Building2 className="h-4 w-4 text-emerald-700" />Preferred industries</span><textarea className={`${input} mt-3 min-h-28`} value={config.preferred_industries} maxLength={2000} onChange={e => update("preferred_industries", e.target.value)} /><span className="mt-2 block text-xs font-normal leading-relaxed text-neutral-500">Each listed industry becomes an allowed employer category for verification.</span></label>
        <label className="rounded-xl border border-emerald-100 bg-white/90 p-4 text-sm font-medium text-neutral-800 lg:col-span-2"><span className="flex items-center gap-2"><MapPin className="h-4 w-4 text-emerald-700" />Location and eligibility notes</span><textarea className={`${input} mt-3 min-h-24`} value={config.location_preferences} maxLength={2000} onChange={e => update("location_preferences", e.target.value)} /><span className="mt-2 block text-xs font-normal leading-relaxed text-neutral-500">Used to assess remote scope and country eligibility without assuming work authorization.</span></label>
        <label className="flex items-start gap-3 rounded-xl border border-emerald-200/70 bg-white/90 p-4 text-sm lg:col-span-2"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-emerald-700" checked={config.prefer_overseas_employers} onChange={e => update("prefer_overseas_employers", e.target.checked)} /><span><span className="font-medium text-neutral-900">Prioritize companies based abroad</span><span className="mt-1 block text-xs text-neutral-500">Includes overseas companies hiring in India or other locations permitted by your location preferences.</span></span></label>
        <div className="rounded-xl border border-emerald-200/70 bg-white/90 p-4 lg:col-span-2">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><h3 className="text-sm font-medium text-neutral-900">Job-board sources</h3><p className="mt-1 max-w-3xl text-xs leading-relaxed text-neutral-500">Enabled sources rotate through daily and on-demand searches. Public feeds and APIs are preferred; public-page sources are searched without signing in. Every result is still verified against the employer and deduplicated before it reaches your queue.</p></div><span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800">{config.search_source_ids.length} enabled</span></div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {snapshot.search_sources.items.map(source => <label key={source.id} className={`flex items-start gap-3 rounded-lg border p-3 ${source.available ? "border-neutral-200 bg-white" : "border-neutral-100 bg-neutral-50 text-neutral-500"}`}>
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-emerald-700" disabled={!source.available} checked={config.search_source_ids.includes(source.id)} onChange={e => toggleSource(source.id, e.target.checked)} />
              <span className="min-w-0 text-sm"><span className="flex flex-wrap items-center gap-2"><span className="font-medium">{source.name}</span><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-neutral-600">{readable(source.method)}</span></span><span className="mt-1 block text-xs leading-relaxed text-neutral-500">{source.note}</span>{source.aliases.length > 0 && <span className="mt-1 block text-[11px] text-neutral-400">Also listed as {source.aliases.join(", ")}</span>}</span>
            </label>)}
          </div>
        </div>
      </div>
    </section>

    <ResumeSettings config={config} onChange={value => { setConfig(value); setSaved(false); }} />

    <section className="overflow-hidden rounded-2xl border border-amber-200/80 bg-amber-50/40 shadow-sm">
      <div className="flex items-start gap-3 border-b border-amber-200/70 bg-amber-100/70 p-5">
        <span className="rounded-xl border border-amber-200 bg-white/80 p-2.5 text-amber-700"><FileText className="h-5 w-5" /></span>
        <div><p className="text-xs font-semibold uppercase tracking-wider text-amber-700">04 · Writing style</p><h2 className="mt-1 font-semibold text-neutral-950">Resume and application preferences</h2><p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-600">Give the application agent standing instructions for resume reuse, tone, positioning, and wording.</p></div>
      </div>
      <div className="p-5"><label className="block rounded-xl border border-amber-100 bg-white/90 p-4 text-sm font-medium text-neutral-800">Application instructions<textarea className={`${input} mt-3 min-h-32`} value={config.application_notes} maxLength={4000} onChange={e => update("application_notes", e.target.value)} /><span className="mt-2 block text-xs font-normal text-neutral-500">These instructions guide preparation. Factual claims still require resume or source evidence.</span></label></div>
    </section>

    <section className="overflow-hidden rounded-2xl border border-indigo-200 bg-indigo-50/50 shadow-sm">
      <div className="border-b border-indigo-200 bg-indigo-100/70 p-5"><p className="text-xs font-semibold uppercase tracking-wider text-indigo-700">05 · Website applications</p><h2 className="mt-1 font-semibold text-neutral-950">Browser agent AI provider</h2><p className="mt-1 text-sm text-neutral-600">Choose how the browser agent makes decisions, audits actions, and checks submission confirmation.</p></div>
      <div className="grid gap-4 p-5 sm:grid-cols-2">
        <label className="flex items-start gap-3 rounded-xl border border-indigo-100 bg-white p-4 text-sm sm:col-span-2"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-indigo-700" checked={config.auto_email_with_website_application} onChange={e => update("auto_email_with_website_application", e.target.checked)} /><span><span className="font-medium text-neutral-900">Also apply by email when a verified contact is found</span><span className="mt-1 block text-xs leading-relaxed text-neutral-500">Starting a website application also authorizes one evidence-checked Zoho email with the selected resume. If no suitable address is found, the website application continues and no email is sent. Duplicate and Zoho Sent checks remain independent.</span></span></label>
        <label className="rounded-xl border border-indigo-100 bg-white p-4 text-sm font-medium">Default provider<select aria-label="Default browser AI provider" className={`${input} mt-3`} value={config.browser_ai_provider || "gateway"} onChange={e => update("browser_ai_provider", e.target.value as JobAgentConfig["browser_ai_provider"])}><option value="gateway">OpenClaw gateway</option><option value="openai">Direct OpenAI API</option></select></label>
        <label className="rounded-xl border border-indigo-100 bg-white p-4 text-sm font-medium">OpenAI API model<select aria-label="Browser OpenAI API model" className={`${input} mt-3`} value={config.browser_openai_model || "gpt-5.6-luna"} onChange={e => update("browser_openai_model", e.target.value)}><option value="gpt-5.6-luna">GPT-5.6 Luna</option><option value="gpt-6-astra">GPT-6 Astra</option></select><span className="mt-2 block text-xs font-normal text-neutral-500">Luna is the faster default. Astra is available for harder forms and decisions. Used only with direct API.</span></label>
        <p className="text-xs leading-relaxed text-neutral-600 sm:col-span-2">Direct API uses the server’s OPENAI_API_KEY and incurs API charges. The key is never sent to this page. Defaults apply to new runs; use the provider selector in a paused application to switch when resuming. Search and email preparation keep their existing providers.</p>
      </div>
    </section>

    <ErrorBox error={save.error} />
    <div className="sticky bottom-3 z-10 flex flex-col gap-3 rounded-2xl border border-neutral-200 bg-white/95 p-4 shadow-lg shadow-neutral-900/10 backdrop-blur sm:flex-row sm:items-center sm:justify-between">
      <div><p className="text-sm font-medium text-neutral-900">Save the complete configuration</p><p className="mt-0.5 text-xs text-neutral-500">Changes take effect on the next collection, search, classification, or application action.</p></div>
      <div className="flex items-center gap-3"><button className={`${primary} min-w-36`} type="submit" disabled={save.isPending || snapshot.revision > revision}>{save.isPending ? <><Loader2 className="h-4 w-4 animate-spin" />Saving…</> : <><Save className="h-4 w-4" />Save settings</>}</button>{saved && <span role="status" className="flex items-center gap-1.5 text-sm font-medium text-emerald-700"><Check className="h-4 w-4" />Saved</span>}</div>
    </div>
  </form>;
}
