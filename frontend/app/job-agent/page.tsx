"use client";

import { useState } from "react";
import { JobApplicationControls, ResumeSettings } from "@/components/JobApplicationControls";
import { JobApplicantProfile } from "@/components/JobApplicantProfile";
import { JobCvLibrary } from "@/components/JobCvLibrary";
import { JobBrowserApplications } from "@/components/JobBrowserApplication";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, ArrowUpRight, Building2, Check, ClipboardCheck, FileText, Globe2, ListFilter, Loader2, MapPin, RefreshCw, Save, Search, Settings2, SlidersHorizontal } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { apiUrl } from "@/lib/api";
import { jobAgentRequest, type ApplicationsResponse, type Candidate, type CollectionRun, type JobAgentConfig, type JobSource, type Overview, type ReviewStatus } from "@/lib/job-agent";

const labels: Record<ReviewStatus, string> = { new: "To review", shortlisted: "Shortlisted", needs_info: "Needs information", skipped: "Skipped" };
const tones: Record<ReviewStatus, string> = { new: "bg-sky-50 text-sky-700", shortlisted: "bg-emerald-50 text-emerald-700", needs_info: "bg-amber-50 text-amber-800", skipped: "bg-neutral-100 text-neutral-600" };
type LegalDegreeFilter = "exclude" | "all" | "required";
type ContractFilter = "all" | "contract" | "non_contract" | "unknown";
const input = "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-900";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50";
const primary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50";
const panel = "rounded-xl border border-neutral-200 bg-white";
const date = (value?: string | null) => value ? new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Not yet";
const readable = (value?: string | null) => value ? value.replaceAll("_", " ") : "Unknown";
function safeUrl(value: string) { try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } }
function sourceOf(job: Candidate): JobSource { return job.posting.job_source === "external_search" || job.posting.discovery_provider === "possibleos_daily_career_search" ? "external_search" : "possibleos"; }
function sourceLabel(job: Candidate) { return sourceOf(job) === "external_search" ? "Job Agent search" : "Possible OS"; }
function queueQuery(status: ReviewStatus | "", search: string, page: number, order: string, category: string, source: JobSource | "", legalDegree: LegalDegreeFilter, contract: ContractFilter) {
  const params = new URLSearchParams({ search, page: String(page), order, category, legal_degree: legalDegree, contract });
  if (status) params.set("status", status);
  if (source) params.set("source", source);
  return params.toString();
}
function ErrorBox({ error }: { error: Error | null }) { return error ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error.message}</div> : null; }

export default function JobAgentPage() {
  const client = useQueryClient();
  const [tab, setTab] = useState("queue");
  const [filter, setFilter] = useState<ReviewStatus | "">("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [source, setSource] = useState<JobSource | "">("");
  const [legalDegree, setLegalDegree] = useState<LegalDegreeFilter>("exclude");
  const [contract, setContract] = useState<ContractFilter>("all");
  const [page, setPage] = useState(1);
  const [order, setOrder] = useState("posted_desc");
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [applicationSearch, setApplicationSearch] = useState("");
  const [applicationStatus, setApplicationStatus] = useState("");
  const [applicationOrder, setApplicationOrder] = useState("updated_desc");
  const [applicationPage, setApplicationPage] = useState(1);
  const [notice, setNotice] = useState("");
  const overview = useQuery({ queryKey: ["job-agent", "overview"], queryFn: () => jobAgentRequest<Overview>("/overview"), refetchInterval: 15000 });
  const jobs = useQuery({ queryKey: ["job-agent", "jobs", filter, search, page, order, category, source, legalDegree, contract], queryFn: () => jobAgentRequest<{ items: Candidate[]; total: number; total_pages: number }>(`/jobs?${queueQuery(filter, search, page, order, category, source, legalDegree, contract)}`), refetchInterval: 15000 });
  const applications = useQuery({
    queryKey: ["job-agent", "applications", applicationSearch, applicationStatus, applicationPage, applicationOrder],
    queryFn: () => { const params = new URLSearchParams({ search: applicationSearch, status: applicationStatus, page: String(applicationPage), order: applicationOrder }); return jobAgentRequest<ApplicationsResponse>(`/applications?${params}`); },
    enabled: tab === "applications",
    refetchInterval: tab === "applications" ? 5000 : false,
  });
  const refresh = () => client.invalidateQueries({ queryKey: ["job-agent"] });
  const collect = useMutation({ mutationFn: () => jobAgentRequest<CollectionRun>("/collect", {}),
    onSuccess: () => { setNotice(`Sync queued. Progress is saved automatically; all matching listings will be processed.`); refresh(); }, onError: () => refresh() });
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
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{(Object.keys(labels) as ReviewStatus[]).map(status => <button key={status} onClick={() => { setFilter(status); setPage(1); setTab("queue"); }} className={`${panel} p-4 text-left transition-colors hover:border-neutral-400`}><p className="text-xs font-medium text-neutral-500">{labels[status]}</p><p className="mt-2 text-3xl font-semibold tracking-tight">{data.counts[status]}</p></button>)}</div>
    <div className="flex gap-1 overflow-x-auto border-b border-neutral-200" role="tablist" aria-label="Job agent sections">{[{ key: "queue", label: "Review queue", icon: BriefcaseBusiness }, { key: "applications", label: "Applications", icon: ClipboardCheck }, { key: "cvs", label: "CVs", icon: FileText }, { key: "profile", label: "Applicant profile", icon: ClipboardCheck }, { key: "settings", label: "Settings", icon: Settings2 }].map(({ key, label, icon: Icon }) => <button key={key} id={`tab-${key}`} role="tab" aria-controls={`panel-${key}`} aria-selected={tab === key} onClick={() => setTab(key)} className={`flex min-h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-sm font-medium ${tab === key ? "border-neutral-900 text-neutral-900" : "border-transparent text-neutral-500 hover:text-neutral-800"}`}><Icon className="h-4 w-4" />{label}</button>)}</div>
    {tab === "queue" && <div role="tabpanel" id="panel-queue" aria-labelledby="tab-queue" className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className={`${panel} min-w-0 overflow-hidden`}>
        <div className="grid gap-3 border-b border-neutral-200 p-4 sm:grid-cols-2"><select aria-label="Order jobs" className={input} value={order} onChange={e => { setOrder(e.target.value); setPage(1); }}><option value="posted_desc">Most recently posted</option><option value="contact_desc">Known contact email first</option><option value="posted_asc">Oldest posted first</option><option value="found_desc">Recently added to queue</option></select><input aria-label="Search review queue" className={input} placeholder="Search company or role…" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /><select aria-label="Review status" className={input} value={filter} onChange={e => { setFilter(e.target.value as ReviewStatus | ""); setPage(1); }}><option value="">All decisions</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Filter by category" className={input} value={category} onChange={e => { setCategory(e.target.value); setPage(1); }}><option value="">All categories</option><option value="needs_review">Classification needs review</option>{data.config.resume_categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select><select aria-label="Filter by job source" className={input} value={source} onChange={e => { setSource(e.target.value as JobSource | ""); setPage(1); }}><option value="">All sources</option><option value="external_search">Job Agent search</option><option value="possibleos">Possible OS</option></select><select aria-label="Filter by contract status" className={input} value={contract} onChange={e => { setContract(e.target.value as ContractFilter); setPage(1); }}><option value="all">All contract types</option><option value="contract">Contract roles</option><option value="non_contract">Non-contract roles</option><option value="unknown">Contract type unknown</option></select><select aria-label="Filter by legal degree requirement" className={input} value={legalDegree} onChange={e => { setLegalDegree(e.target.value as LegalDegreeFilter); setPage(1); }}><option value="exclude">Hide legal-degree roles</option><option value="all">Show all roles</option><option value="required">Legal-degree roles only</option></select></div>
        <ErrorBox error={jobs.error} />
        {jobs.isPending && <p className="p-6 text-sm text-neutral-500">Loading listings…</p>}
        {!jobs.isPending && !jobs.error && !jobs.data?.items.length && <div className="px-6 py-14 text-center"><ListFilter className="mx-auto mb-3 h-7 w-7 text-neutral-400" /><h2 className="font-medium">{total ? "No listings match these filters" : "Start with the jobs already found"}</h2><p className="mx-auto mt-2 max-w-sm text-sm text-neutral-500">{total ? "Change your search or review status to see more jobs." : "Import existing Possible OS listings, then shortlist roles or record what needs checking."}</p>{!total && <button className={`${button} mt-5`} onClick={() => collect.mutate()} disabled={collect.isPending || !data.config.collection_enabled}>Sync now</button>}</div>}
        <div className="divide-y divide-neutral-100">{jobs.data?.items.map(job => <button key={job.id} className="block w-full p-4 text-left hover:bg-neutral-50" onClick={() => setSelected(job)}>
          <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-semibold">{job.posting.title || "Untitled role"}</p><p className="mt-1 break-words text-sm text-neutral-600">{job.posting.firm_name}</p></div><span className={`shrink-0 rounded-full px-2 py-1 text-[11px] font-medium ${tones[job.status]}`}>{labels[job.status]}</span></div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500"><span className="font-medium text-neutral-700">{sourceLabel(job)}</span><span>{job.posting.location || "Location not specified"}</span><span>{readable(job.posting.work_arrangement)}</span><span>{job.posting.contract_status === "contract" ? "Contract" : job.posting.contract_status === "non_contract" ? "Non-contract" : "Contract type unknown"}</span><span>Posted {job.posting.posted_date || "date unknown"}</span>{job.contact?.available && <span className="font-medium text-emerald-700">Contact: {job.contact.best?.email}</span>}{job.posting.legal_degree_requirement === "required" && <span className="font-medium text-amber-800">Legal degree required</span>}{job.posting.status === "closed" && <span className="text-amber-800">Closed at source</span>}</div>
          <p className="mt-2 text-xs text-neutral-500">{job.classification?.category_name || readable(job.classification?.status || "pending")}{job.application?.status && job.application.status !== "not_started" ? ` · ${readable(job.application.status)}` : ""}</p>
          {job.note && <p className="mt-2 line-clamp-2 text-xs text-neutral-600">Your note: {job.note}</p>}
        </button>)}</div>
        {!!jobs.data?.total && <div className="flex items-center justify-between gap-2 border-t border-neutral-200 p-3 text-xs text-neutral-500"><span>{jobs.data.total} listings · Page {page} of {jobs.data.total_pages}</span><div className="flex gap-2"><button className={button} disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><button className={button} disabled={page >= jobs.data.total_pages} onClick={() => setPage(p => p + 1)}>Next</button></div></div>}
      </section>
      <aside className="space-y-4"><CollectionProgress data={data} total={total} /><section className={`${panel} p-4`}><h2 className="text-sm font-semibold">Operating status</h2><p className="mt-2 text-sm text-neutral-600">Open a job when you want to classify it, review its match, prepare an email, apply through Zoho, or apply on the employer website.</p><dl className="mt-4 space-y-3 text-xs"><div className="flex justify-between"><dt className="text-neutral-500">Collection</dt><dd>{data.config.collection_enabled ? "Automatic · every minute" : "Paused"}</dd></div><div className="flex justify-between"><dt className="text-neutral-500">Last completed sync</dt><dd>{date(data.last_collected_at)}</dd></div><div className="flex justify-between"><dt className="text-neutral-500">Decisions</dt><dd>Reviewed by you</dd></div></dl><p className="mt-4 border-t border-neutral-100 pt-3 text-xs leading-relaxed text-neutral-500">Choose Apply via Zoho for email or Start website application for the employer form. Each has separate progress and confirmation. Previous application packets and Zoho mail are checked before sending.</p></section>
        <SearchSource data={data} onRefresh={refresh} />
        <section className={`${panel} p-4`}><h2 className="text-sm font-semibold">Your focus</h2><p className="mt-2 text-sm leading-relaxed text-neutral-600">{data.config.target_roles}</p><p className="mt-2 text-xs leading-relaxed text-neutral-500">{data.config.preferred_industries}</p><button onClick={() => setTab("settings")} className="mt-3 text-xs font-medium underline underline-offset-4">Edit preferences</button></section>
      </aside>
    </div>}
    {tab === "applications" && <ApplicationsPanel data={applications.data} loading={applications.isPending} error={applications.error} search={applicationSearch} status={applicationStatus} order={applicationOrder} page={applicationPage} onSearch={value => { setApplicationSearch(value); setApplicationPage(1); }} onStatus={value => { setApplicationStatus(value); setApplicationPage(1); }} onOrder={value => { setApplicationOrder(value); setApplicationPage(1); }} onPage={setApplicationPage} onOpen={setSelected} />}
    {tab === "cvs" && <JobCvLibrary />}
    {tab === "profile" && <section role="tabpanel" id="panel-profile" aria-labelledby="tab-profile"><JobApplicantProfile /></section>}
    {tab === "settings" && <section role="tabpanel" id="panel-settings" aria-labelledby="tab-settings"><SettingsForm snapshot={data} onSaved={refresh} /></section>}
    <Dialog open={!!selected} onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className="max-h-[92dvh] w-[96vw] max-w-5xl overflow-y-auto">{selected && <ReviewForm key={selected.id} job={selected} categories={data.config.resume_categories} onSaved={() => { setSelected(null); refresh(); }} />}</DialogContent></Dialog>
  </div>;
}

const applicationStatusOrder = ["queued", "preparing", "needs_review", "ready", "queued_send", "sending", "delivery_unconfirmed", "sent_verified"];
function applicationTone(status: string) {
  if (status === "sent_verified") return "bg-emerald-50 text-emerald-800";
  if (status === "ready") return "bg-sky-50 text-sky-800";
  if (["queued", "preparing", "queued_send", "sending"].includes(status)) return "bg-violet-50 text-violet-800";
  if (["needs_review", "delivery_unconfirmed", "failed"].includes(status)) return "bg-amber-50 text-amber-900";
  return "bg-neutral-100 text-neutral-700";
}

function ApplicationsPanel({ data, loading, error, search, status, order, page, onSearch, onStatus, onOrder, onPage, onOpen }: {
  data?: ApplicationsResponse; loading: boolean; error: Error | null; search: string; status: string; order: string; page: number;
  onSearch: (value: string) => void; onStatus: (value: string) => void; onOrder: (value: string) => void; onPage: (value: number) => void; onOpen: (job: Candidate) => void;
}) {
  const counts = data?.counts || {};
  const all = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const active = ["queued", "preparing", "queued_send", "sending"].reduce((sum, key) => sum + (counts[key] || 0), 0);
  const attention = (counts.needs_review || 0) + (counts.delivery_unconfirmed || 0) + (counts.failed || 0);
  const statuses = Array.from(new Set([...applicationStatusOrder, ...Object.keys(counts)])).filter(key => counts[key]);
  return <section role="tabpanel" id="panel-applications" aria-labelledby="tab-applications" className="space-y-4">
    <JobBrowserApplications onOpen={onOpen} />
    <h2 className="font-semibold">Email applications</h2>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {[{ label: "Started", value: all }, { label: "In progress", value: active }, { label: "Drafts ready", value: counts.ready || 0 }, { label: "Needs attention", value: attention }, { label: "Sent verified", value: counts.sent_verified || 0 }].map(item => <div key={item.label} className="rounded-lg border border-neutral-200 bg-white p-4"><p className="text-xs font-medium text-neutral-500">{item.label}</p><p className="mt-1 text-2xl font-semibold text-neutral-950">{item.value}</p></div>)}
    </div>
    <div className={`${panel} overflow-hidden`}>
      <div className="grid gap-3 border-b border-neutral-200 p-4 md:grid-cols-[minmax(0,1fr)_220px_220px]">
        <label className="relative"><span className="sr-only">Search applications</span><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-neutral-400" /><input className={`${input} pl-9`} placeholder="Search firm, role, or recipient…" value={search} onChange={event => onSearch(event.target.value)} /></label>
        <select aria-label="Application status" className={input} value={status} onChange={event => onStatus(event.target.value)}><option value="">All application states</option>{statuses.map(key => <option key={key} value={key}>{readable(key)} ({counts[key]})</option>)}</select>
        <select aria-label="Order applications" className={input} value={order} onChange={event => onOrder(event.target.value)}><option value="updated_desc">Most recently updated</option><option value="firm_asc">Firm name</option><option value="role_asc">Role title</option></select>
      </div>
      <ErrorBox error={error} />
      {loading && <p className="p-6 text-sm text-neutral-500">Loading applications…</p>}
      {!loading && !error && !data?.items.length && <div className="px-6 py-14 text-center"><ClipboardCheck className="mx-auto h-7 w-7 text-neutral-400" /><h2 className="mt-3 font-medium">No applications match</h2><p className="mt-1 text-sm text-neutral-500">Started preparations, stopped attempts, ready drafts, and sent applications appear here.</p></div>}
      <div className="divide-y divide-neutral-100">{data?.items.map(job => {
        const application = job.application || { status: "not_started" };
        const sourceUrl = safeUrl(job.posting.source_url);
        const attachment = application.attachment;
        return <article key={job.id} className="p-4 hover:bg-neutral-50/70">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h2 className="break-words text-sm font-semibold text-neutral-950">{job.posting.title}</h2><span className={`rounded-full px-2 py-1 text-[11px] font-medium ${applicationTone(application.status)}`}>{readable(application.status)}</span></div><p className="mt-1 text-sm text-neutral-600">{job.posting.firm_name}</p><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500"><span>Attempt {application.attempt || 1}</span><span>{application.stage || readable(application.phase)}</span><span>Updated {date(job.processing_updated_at)}</span>{application.recipient?.email && <span className="font-medium text-neutral-700">{application.recipient.email}</span>}</div>{application.error && <p className="mt-2 line-clamp-2 text-xs text-amber-800">{application.error}</p>}</div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">{sourceUrl && <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={button}>Job <ArrowUpRight className="h-4 w-4" /></a>}{attachment?.path && <a href={apiUrl(`/api/job-agent/resume?path=${encodeURIComponent(attachment.path)}`)} target="_blank" rel="noopener noreferrer" className={button}>PDF <FileText className="h-4 w-4" /></a>}<button className={primary} onClick={() => onOpen(job)}>View application</button></div>
          </div>
        </article>;
      })}</div>
      {!!data?.total && <div className="flex items-center justify-between gap-3 border-t border-neutral-200 p-3 text-xs text-neutral-500"><span>{data.total} applications · Page {page} of {data.total_pages}</span><div className="flex gap-2"><button className={button} disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button><button className={button} disabled={page >= data.total_pages} onClick={() => onPage(page + 1)}>Next</button></div></div>}
    </div>
  </section>;
}

function CollectionProgress({ data, total }: { data: Overview; total: number }) {
  const run = data.collection;
  return <section className={`${panel} p-4`}><h2 className="text-sm font-semibold">Collection progress</h2>
    <p className="mt-2 text-2xl font-semibold">{total.toLocaleString()} <span className="text-sm font-normal text-neutral-500">jobs in your queue</span></p>
    <p className="mt-2 text-xs text-neutral-500">{data.processing_counts.classified || 0} categorized · {data.processing_counts.needs_review || 0} need review · {(data.processing_counts.pending || 0) + (data.processing_counts.classifying || 0)} awaiting classification</p><p className="mt-2 text-xs text-neutral-500">Newest posting dates first by default. Unknown dates appear last.</p>
    {run ? <div className="mt-4 space-y-2 text-xs"><p className="font-medium">{!data.config.collection_enabled && !run.completed_at ? "Paused" : readable(run.status)}</p>
      <progress aria-label="Collection progress" className="h-2 w-full accent-neutral-900" max={Math.max(1, run.total)} value={run.processed} />
      <p>{run.processed.toLocaleString()} of {run.total.toLocaleString()} source listings checked · {run.remaining.toLocaleString()} remaining</p>
      <p className="text-neutral-500">{run.added} added · {run.updated} refreshed · {run.invalid} invalid</p>
      {!!run.invalid && <p className="text-amber-800">Some source listings could not be imported.</p>}
      {run.error && <p role="alert" className="text-red-700">{run.error}</p>}
      {run.config_revision !== data.revision && !run.completed_at && <p className="text-amber-800">This sync uses earlier settings. Your new settings apply to the next sync.</p>}
      <p className="text-neutral-500">Updated {date(run.updated_at)}</p>
    </div> : <p className="mt-4 text-xs text-neutral-500">{data.config.collection_enabled ? "Waiting for the first automatic sync…" : "Collection paused"}</p>}
  </section>;
}

function SearchSource({ data, onRefresh }: { data: Overview; onRefresh: () => void }) {
  const search = useMutation({
    mutationFn: () => jobAgentRequest<{ status: string; message?: string }>("/search", {}),
    onSuccess: onRefresh,
  });
  const latest = data.source?.runs.find(run => run.result.job_agent_search || run.result.manual_search);
  const running = data.source?.runs.some(run => run.status === "running") || false;
  const errors = Array.isArray(latest?.result.errors) ? latest.result.errors.length : 0;
  const interrupted = latest?.status === "interrupted";
  const restarted = interrupted && latest?.result.interrupted_reason === "backend_restart";
  const failed = latest?.status === "failed";
  const consulted = Array.isArray(latest?.result.search_sources_consulted) ? latest.result.search_sources_consulted.length : 0;
  return <section className={`${panel} p-4`}>
    <h2 className="text-sm font-semibold">Find target jobs</h2>
    <p className="mt-2 text-sm leading-relaxed text-neutral-600">Search public sources using your configured target roles, industries and location preferences, then verify jobs and application contacts. The daily run uses these same settings.</p>
    <p className="mt-2 text-xs text-neutral-500">{data.search_sources.enabled_count} sources enabled · up to {data.source?.config.max_sources || 6} rotate into each run</p>
    <button className={`${primary} mt-4 w-full`} disabled={search.isPending || running} onClick={() => search.mutate()}>
      <RefreshCw className={`h-4 w-4 ${search.isPending || running ? "animate-spin" : ""}`} />
      {search.isPending ? "Starting…" : running ? "Search in progress" : "Search now"}
    </button>
    <ErrorBox error={search.error} />
    {latest && <div className="mt-4 space-y-1 border-t border-neutral-100 pt-3 text-xs text-neutral-500">
      <p className="font-medium text-neutral-700">Latest search: {readable(latest.status)}</p>
      <p>{latest.result.verified || 0} verified · {latest.result.new_jobs || 0} new · {latest.result.duplicates_skipped || 0} duplicates skipped</p>
      {!!consulted && <p>{consulted} configured source{consulted === 1 ? "" : "s"} consulted in this run, alongside targeted web queries.</p>}
      {interrupted && <p className="text-amber-800">{restarted ? "The backend restarted before this search finished." : "The search worker stopped before completion."} No replacement search was started. Choose Search now to retry.</p>}
      {failed && <p className="text-red-700">The search stopped before completion. Choose Search now to retry.</p>}
      {!!errors && !interrupted && !failed && <p className="text-amber-800">{errors} result{errors === 1 ? "" : "s"} could not be verified. Verified jobs were still saved.</p>}
      {!!latest.result.contacts_found && <p className="text-emerald-700">{latest.result.contacts_found} verified application contact{latest.result.contacts_found === 1 ? "" : "s"} saved and shared across the firm&apos;s roles.</p>}
      <p>Started {date(latest.started_at)}</p>
    </div>}
    {!latest && <p className="mt-3 text-xs text-neutral-500">No Job Agent search has run yet.</p>}
    <p className="mt-3 text-xs leading-relaxed text-neutral-500">Results are checked against employer and job sources, deduplicated, and added to this review queue. Searching never classifies or applies.</p>
    {data.source ? <p className="mt-3 border-t border-neutral-100 pt-3 text-xs text-neutral-500">Daily Job Agent search: {data.source.schedule_enabled ? `${data.source.config.local_time} · ${data.source.config.timezone}` : "disabled"}. Next due: {date(data.source.next_due_at)}.</p> : <p className="mt-3 text-xs text-amber-800">{data.source_error}</p>}
  </section>;
}

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
        <div><p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">02 · Search scope</p><h2 className="mt-1 font-semibold text-neutral-950">Roles, industries and location</h2><p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-600">The daily search and Search now use this same scope. The verifier only accepts employers and roles supported by these settings.</p></div>
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
        <label className="rounded-xl border border-indigo-100 bg-white p-4 text-sm font-medium">Default provider<select aria-label="Default browser AI provider" className={`${input} mt-3`} value={config.browser_ai_provider || "gateway"} onChange={e => update("browser_ai_provider", e.target.value as JobAgentConfig["browser_ai_provider"])}><option value="gateway">OpenClaw gateway</option><option value="openai">Direct OpenAI API</option></select></label>
        <label className="rounded-xl border border-indigo-100 bg-white p-4 text-sm font-medium">OpenAI API model<input aria-label="Browser OpenAI API model" className={`${input} mt-3`} value={config.browser_openai_model || "gpt-5-mini"} maxLength={120} onChange={e => update("browser_openai_model", e.target.value)} /><span className="mt-2 block text-xs font-normal text-neutral-500">Used only with direct API. Must support Responses structured outputs.</span></label>
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
