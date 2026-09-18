"use client";

import { useState } from "react";
import { JobApplicationControls, ResumeSettings } from "@/components/JobApplicationControls";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, ArrowUpRight, Check, ListFilter, Loader2, RefreshCw, Settings2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { jobAgentRequest, type Candidate, type CollectionRun, type JobAgentConfig, type Overview, type ReviewStatus } from "@/lib/job-agent";

const labels: Record<ReviewStatus, string> = { new: "To review", shortlisted: "Shortlisted", needs_info: "Needs information", skipped: "Skipped" };
const tones: Record<ReviewStatus, string> = { new: "bg-sky-50 text-sky-700", shortlisted: "bg-emerald-50 text-emerald-700", needs_info: "bg-amber-50 text-amber-800", skipped: "bg-neutral-100 text-neutral-600" };
const input = "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-900";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50";
const primary = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50";
const panel = "rounded-xl border border-neutral-200 bg-white";
const date = (value?: string | null) => value ? new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Not yet";
const readable = (value?: string | null) => value ? value.replaceAll("_", " ") : "Unknown";
function safeUrl(value: string) { try { const u = new URL(value); return ["https:", "http:"].includes(u.protocol) ? u.href : undefined; } catch { return undefined; } }
function ErrorBox({ error }: { error: Error | null }) { return error ? <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error.message}</div> : null; }

export default function JobAgentPage() {
  const client = useQueryClient();
  const [tab, setTab] = useState("queue");
  const [filter, setFilter] = useState<ReviewStatus | "">("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [order, setOrder] = useState("posted_desc");
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [notice, setNotice] = useState("");
  const overview = useQuery({ queryKey: ["job-agent", "overview"], queryFn: () => jobAgentRequest<Overview>("/overview"), refetchInterval: 15000 });
  const jobs = useQuery({ queryKey: ["job-agent", "jobs", filter, search, page, order, category], queryFn: () => jobAgentRequest<{ items: Candidate[]; total: number; total_pages: number }>(`/jobs?${new URLSearchParams({ status: filter, search, page: String(page), order, category }).toString().replace("status=&", "")}`), refetchInterval: 15000 });
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
      <div className="flex flex-wrap items-center gap-2"><span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800">Applications by email</span>
        <button className={primary} disabled={collect.isPending || !data.config.collection_enabled} onClick={() => { setNotice(""); collect.mutate(); }}><RefreshCw className={`h-4 w-4 ${collect.isPending ? "animate-spin" : ""}`} />{collect.isPending ? "Queuing…" : "Sync now"}</button></div>
    </header>
    <ErrorBox error={overview.error || collect.error} />
    {notice && <div role="status" className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"><Check className="mt-0.5 h-4 w-4 shrink-0" />{notice}</div>}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{(Object.keys(labels) as ReviewStatus[]).map(status => <button key={status} onClick={() => { setFilter(status); setPage(1); setTab("queue"); }} className={`${panel} p-4 text-left transition-colors hover:border-neutral-400`}><p className="text-xs font-medium text-neutral-500">{labels[status]}</p><p className="mt-2 text-3xl font-semibold tracking-tight">{data.counts[status]}</p></button>)}</div>
    <div className="flex gap-1 border-b border-neutral-200" role="tablist" aria-label="Job agent sections">{[{ key: "queue", label: "Review queue", icon: BriefcaseBusiness }, { key: "settings", label: "Settings", icon: Settings2 }].map(({ key, label, icon: Icon }) => <button key={key} id={`tab-${key}`} role="tab" aria-controls={`panel-${key}`} aria-selected={tab === key} onClick={() => setTab(key)} className={`flex min-h-11 items-center gap-2 border-b-2 px-3 text-sm font-medium ${tab === key ? "border-neutral-900 text-neutral-900" : "border-transparent text-neutral-500 hover:text-neutral-800"}`}><Icon className="h-4 w-4" />{label}</button>)}</div>
    {tab === "queue" && <div role="tabpanel" id="panel-queue" aria-labelledby="tab-queue" className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className={`${panel} min-w-0 overflow-hidden`}>
        <div className="grid gap-3 border-b border-neutral-200 p-4 sm:grid-cols-2"><select aria-label="Order jobs" className={input} value={order} onChange={e => { setOrder(e.target.value); setPage(1); }}><option value="posted_desc">Most recently posted</option><option value="posted_asc">Oldest posted first</option><option value="found_desc">Recently added to queue</option></select><input aria-label="Search review queue" className={input} placeholder="Search company or role…" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} /><select aria-label="Review status" className={`${input} sm:max-w-48`} value={filter} onChange={e => { setFilter(e.target.value as ReviewStatus | ""); setPage(1); }}><option value="">All decisions</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Filter by category" className={input} value={category} onChange={e => { setCategory(e.target.value); setPage(1); }}><option value="">All categories</option><option value="needs_review">Classification needs review</option>{data.config.resume_categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
        <ErrorBox error={jobs.error} />
        {jobs.isPending && <p className="p-6 text-sm text-neutral-500">Loading listings…</p>}
        {!jobs.isPending && !jobs.error && !jobs.data?.items.length && <div className="px-6 py-14 text-center"><ListFilter className="mx-auto mb-3 h-7 w-7 text-neutral-400" /><h2 className="font-medium">{total ? "No listings match these filters" : "Start with the jobs already found"}</h2><p className="mx-auto mt-2 max-w-sm text-sm text-neutral-500">{total ? "Change your search or review status to see more jobs." : "Import existing Possible OS listings, then shortlist roles or record what needs checking."}</p>{!total && <button className={`${button} mt-5`} onClick={() => collect.mutate()} disabled={collect.isPending || !data.config.collection_enabled}>Sync now</button>}</div>}
        <div className="divide-y divide-neutral-100">{jobs.data?.items.map(job => <button key={job.id} className="block w-full p-4 text-left hover:bg-neutral-50" onClick={() => setSelected(job)}>
          <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-sm font-semibold">{job.posting.title || "Untitled role"}</p><p className="mt-1 break-words text-sm text-neutral-600">{job.posting.firm_name}</p></div><span className={`shrink-0 rounded-full px-2 py-1 text-[11px] font-medium ${tones[job.status]}`}>{labels[job.status]}</span></div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500"><span>{job.posting.location || "Location not specified"}</span><span>{readable(job.posting.work_arrangement)}</span><span>Posted {job.posting.posted_date || "date unknown"}</span>{job.posting.status === "closed" && <span className="text-amber-800">Closed at source</span>}</div>
          <p className="mt-2 text-xs text-neutral-500">{job.classification?.category_name || readable(job.classification?.status || "pending")}{job.application?.status && job.application.status !== "not_started" ? ` · ${readable(job.application.status)}` : ""}</p>
          {job.note && <p className="mt-2 line-clamp-2 text-xs text-neutral-600">Your note: {job.note}</p>}
        </button>)}</div>
        {!!jobs.data?.total && <div className="flex items-center justify-between gap-2 border-t border-neutral-200 p-3 text-xs text-neutral-500"><span>{jobs.data.total} listings · Page {page} of {jobs.data.total_pages}</span><div className="flex gap-2"><button className={button} disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button><button className={button} disabled={page >= jobs.data.total_pages} onClick={() => setPage(p => p + 1)}>Next</button></div></div>}
      </section>
      <aside className="space-y-4"><CollectionProgress data={data} total={total} /><section className={`${panel} p-4`}><h2 className="text-sm font-semibold">Operating status</h2><p className="mt-2 text-sm text-neutral-600">New jobs are classified into your resume categories. Open a job to review its match, prepare an email, or apply through Zoho.</p><dl className="mt-4 space-y-3 text-xs"><div className="flex justify-between"><dt className="text-neutral-500">Collection</dt><dd>{data.config.collection_enabled ? "Automatic · every minute" : "Paused"}</dd></div><div className="flex justify-between"><dt className="text-neutral-500">Last completed sync</dt><dd>{date(data.last_collected_at)}</dd></div><div className="flex justify-between"><dt className="text-neutral-500">Decisions</dt><dd>Reviewed by you</dd></div></dl><p className="mt-4 border-t border-neutral-100 pt-3 text-xs leading-relaxed text-neutral-500">Applications send only when you choose Apply via Zoho. Portal submissions are separate. Previous application packets and Zoho mail are checked before sending.</p></section>
        <SearchSource data={data} />
        <section className={`${panel} p-4`}><h2 className="text-sm font-semibold">Your focus</h2><p className="mt-2 text-sm leading-relaxed text-neutral-600">{data.config.target_roles}</p><p className="mt-2 text-xs leading-relaxed text-neutral-500">{data.config.preferred_industries}</p><button onClick={() => setTab("settings")} className="mt-3 text-xs font-medium underline underline-offset-4">Edit preferences</button></section>
      </aside>
    </div>}
    {tab === "settings" && <section role="tabpanel" id="panel-settings" aria-labelledby="tab-settings"><SettingsForm snapshot={data} onSaved={refresh} /></section>}
    <Dialog open={!!selected} onOpenChange={open => { if (!open) setSelected(null); }}><DialogContent className="max-h-[88dvh] max-w-2xl overflow-y-auto">{selected && <ReviewForm key={selected.id} job={selected} categories={data.config.resume_categories} onSaved={() => { setSelected(null); refresh(); }} />}</DialogContent></Dialog>
  </div>;
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

function SearchSource({ data }: { data: Overview }) {
  return <section className={`${panel} p-4`}><h2 className="text-sm font-semibold">Discovery source</h2>{data.source ? <><p className="mt-2 text-sm text-neutral-600">Daily PI technology search</p><p className="mt-2 text-xs text-neutral-500">{data.source.schedule_enabled ? `${data.source.config.local_time} · ${data.source.config.timezone}` : "Schedule disabled"}</p><p className="mt-2 text-xs text-neutral-500">Next due: {date(data.source.next_due_at)} (your local time)</p><p className="mt-3 text-xs text-neutral-500">Schedule from saved search settings; this does not confirm timer health. Automatic sync brings its stored listings into your review queue.</p></> : <p className="mt-2 text-sm text-amber-800">{data.source_error}</p>}</section>;
}

function ReviewForm({ job, categories, onSaved }: { job: Candidate; categories: JobAgentConfig["resume_categories"]; onSaved: () => void }) {
  const [status, setStatus] = useState(job.status);
  const [note, setNote] = useState(job.note);
  const save = useMutation({ mutationFn: () => jobAgentRequest(`/jobs/${job.id}/review`, { status, note, revision: job.revision }), onSuccess: onSaved });
  return <><DialogTitle className="pr-6 leading-snug">{job.posting.title}</DialogTitle><DialogDescription>{job.posting.firm_name} · {job.posting.location || "Location unknown"}</DialogDescription>
    <div className="space-y-4"><div className="flex flex-wrap gap-2 text-xs"><span className="rounded bg-neutral-100 px-2 py-1">{readable(job.posting.work_arrangement)}</span><span className="rounded bg-neutral-100 px-2 py-1">Source status: {readable(job.posting.status)}</span></div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-neutral-700">{job.posting.description_summary || "No description stored. Open the original listing to review the role."}</p>
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
  const save = useMutation({ mutationFn: () => jobAgentRequest<{ revision: number; config: JobAgentConfig }>("/config", { config, revision }), onSuccess: result => { setRevision(result.revision); setConfig(result.config); setSaved(true); onSaved(); } });
  return <form onSubmit={e => { e.preventDefault(); save.mutate(); }} className="max-w-4xl space-y-5">
    {snapshot.revision > revision && !save.isPending && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Preferences changed in another window. Your edits are preserved. Reload the saved settings before editing again.<button type="button" className={`${button} ml-2`} onClick={() => { setConfig({ ...snapshot.config }); setRevision(snapshot.revision); setSaved(false); }}>Reload saved settings</button></p>}
    <section className={`${panel} space-y-5 p-5`}><div><h2 className="font-semibold">Listing collection</h2><p className="mt-1 text-sm text-neutral-500">All matching listings are synced automatically, with no total limit. Filter changes apply to the next sync; an in-progress sync keeps its original filters. Existing decisions are preserved.</p></div>
      <label className="flex items-start gap-3"><input type="checkbox" className="mt-1 h-4 w-4 accent-neutral-900" checked={config.collection_enabled} onChange={e => update("collection_enabled", e.target.checked)} /><span className="text-sm"><span className="font-medium">Automatically sync listings</span><span className="mt-1 block text-xs text-neutral-500">Check for stored listings every minute. Pause between batches without losing progress. The separate daily job search is unaffected.</span></span></label>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium">Title or company contains<input className={`${input} mt-2`} value={config.search} maxLength={255} onChange={e => update("search", e.target.value)} placeholder="Any title or company" /></label><label className="text-sm font-medium">Work arrangement<select className={`${input} mt-2`} value={config.remote_scope} onChange={e => update("remote_scope", e.target.value as JobAgentConfig["remote_scope"])}><option value="any">All, including unknown</option><option value="remote">Remote roles</option><option value="global">Explicitly global remote</option></select></label><label className="text-sm font-medium">Posting age<select className={`${input} mt-2`} value={config.posted_within_days ?? ""} onChange={e => update("posted_within_days", e.target.value ? Number(e.target.value) : null)}><option value="">Any date, including unknown</option>{[7, 14, 30, 60, 90, 180, 365].map(days => <option key={days} value={days}>Last {days} days</option>)}</select><span className="mt-1 block text-xs font-normal text-neutral-500">Choosing a date range excludes listings with unknown dates.</span></label></div>
    </section>
    <ResumeSettings config={config} onChange={value => { setConfig(value); setSaved(false); }} />
    <section className={`${panel} space-y-4 p-5`}><div><h2 className="font-semibold">Your application preferences</h2><p className="mt-1 text-sm text-neutral-500">Guidance used when researching and composing your application. Category definitions control resume selection.</p></div>
      {([{ key: "target_roles", label: "Roles you want", limit: 2000 }, { key: "preferred_industries", label: "Preferred industries", limit: 2000 }, { key: "location_preferences", label: "Location and eligibility notes", limit: 2000 }, { key: "application_notes", label: "Resume and writing preferences", limit: 4000 }] as const).map(field => <label key={field.key} className="block text-sm font-medium">{field.label}<textarea className={`${input} mt-2 min-h-20`} value={config[field.key]} maxLength={field.limit} onChange={e => update(field.key, e.target.value)} /></label>)}
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="h-4 w-4 accent-neutral-900" checked={config.prefer_overseas_employers} onChange={e => update("prefer_overseas_employers", e.target.checked)} />Prioritize companies based abroad, including those hiring in India</label>
    </section>
    <ErrorBox error={save.error} /><div className="flex items-center gap-3"><button className={primary} type="submit" disabled={save.isPending || snapshot.revision > revision}>{save.isPending ? "Saving…" : "Save settings"}</button>{saved && <span role="status" className="text-sm text-emerald-700">Settings saved</span>}</div>
  </form>;
}
