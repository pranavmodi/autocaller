"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, CheckCircle2, Circle, Clock3, ExternalLink, FileStack, Loader2, MailCheck, Plus, RotateCcw, ShieldCheck, Trash2 } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { jobAgentRequest, type Candidate, type JobAgentConfig } from "@/lib/job-agent";

const input = "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm";
const button = "rounded-lg border border-neutral-300 px-3 py-2 text-sm font-medium disabled:opacity-50";
const primary = "rounded-lg bg-neutral-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50";
const readable = (value: string) => value.replaceAll("_", " ");
const pdfUrl = (path: string) => apiUrl(`/api/job-agent/resume?path=${encodeURIComponent(path)}`);
function safeUrl(value?: string) { try { const url = new URL(value || ""); return url.protocol === "https:" ? url.href : undefined; } catch { return undefined; } }
const timestamp = (value?: string | null) => value ? new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : null;

type StepState = "complete" | "active" | "blocked" | "uncertain" | "pending";
type ProgressStep = { title: string; detail: string; state: StepState };

const phaseNames: Record<string, string> = {
  queued: "Waiting for the application worker",
  researching: "Company, role and contact research",
  auditing: "Email claim audit",
  checking_duplicates: "Previous-application check",
  packaging: "Application PDF creation",
  pre_send_checks: "Final send checks",
  sending: "Zoho send",
  verifying_sent: "Zoho Sent verification",
  verification_needed: "Zoho Sent verification",
  preparation: "Application preparation",
};

function applicationStatus(application: NonNullable<Candidate["application"]>) {
  const status = application.status || "not_started";
  if (status === "queued") return { title: "Preparation queued", detail: "Waiting for the job worker to start. No email has been sent.", tone: "sky" };
  if (status === "preparing") return { title: "Preparing application", detail: application.stage || "Research and drafting are in progress. No email has been sent.", tone: "sky" };
  if (status === "needs_review") return { title: "Preparation stopped", detail: application.send_started_at ? "A send may have started. Check the error before taking another action." : "The process stopped before any email was sent.", tone: "amber" };
  if (status === "ready") return { title: "Draft ready — not sent", detail: "Research, evidence checks and the application PDF are complete. Review the draft before sending.", tone: "emerald" };
  if (status === "queued_send") return { title: "Send authorized and queued", detail: "One Zoho send is authorized. The worker will run final checks before sending.", tone: "sky" };
  if (status === "sending") return { title: "Send in progress", detail: "A Zoho send has started. Do not retry or send another copy while verification is pending.", tone: "sky" };
  if (status === "delivery_unconfirmed") return { title: "Send attempted — confirming Sent copy", detail: "Zoho accepted the send or returned an ambiguous result. The agent checks Sent automatically and will not resend the email.", tone: "amber" };
  if (status === "sent_verified") return { title: "Sent copy verified", detail: "The email and exact PDF were found in Zoho Sent. Recipient delivery and portal submission are not confirmed.", tone: "emerald" };
  return { title: "Application not started", detail: "Choose a resume category, then prepare a draft or authorize a Zoho send.", tone: "neutral" };
}

function applicationSteps(data: Candidate, ready: boolean): ProgressStep[] {
  const application: NonNullable<Candidate["application"]> = data.application || { status: "not_started" };
  const status = application.status || "not_started";
  const failed = status === "needs_review" ? application.failed_phase : undefined;
  const activePreparation = ["queued", "preparing"].includes(status);
  const sendAttempted = !!application.send_started_at || ["sending", "delivery_unconfirmed", "sent_verified"].includes(status);
  const duplicateComplete = !!application.duplicate_checked_at || !!application.attachment;
  const state = (complete: boolean, active: boolean, failurePhases: string[] = []): StepState => {
    if (complete) return "complete";
    if (failed && failurePhases.includes(failed)) return "blocked";
    if (active) return "active";
    return "pending";
  };
  return [
    { title: "Resume selected", detail: ready && data.classification?.resume ? data.classification.resume.filename : "Choose a category with a one-page PDF.", state: state(ready, data.classification?.status === "classifying") },
    { title: "Sources and contact verified", detail: application.recipient ? `${application.recipient.name} · ${application.recipient.email}${application.recipient.evidence.source_type === "possibleos_contact" ? " · Possible OS contact" : ""}` : "Confirm the employer and role, then check published and Possible OS contacts.", state: state(!!application.recipient, activePreparation && ["queued", "researching"].includes(application.phase || "queued"), ["researching", "preparation"]) },
    { title: "Email drafted and audited", detail: application.email ? application.email.subject : "Write the email and check every claim against the resume and sources.", state: state(!!application.email, activePreparation && application.phase === "auditing", ["auditing"]) },
    { title: "Previous applications checked", detail: application.duplicate_checked_at ? `Checked ${timestamp(application.duplicate_checked_at)}` : duplicateComplete ? "Completed before the application PDF was created." : "Check queued actions, application records and sent mail for duplicates.", state: state(duplicateComplete, activePreparation && application.phase === "checking_duplicates", ["checking_duplicates"]) },
    { title: "Application PDF created", detail: application.attachment ? application.attachment.filename : "Create the firm and role named one-page PDF.", state: state(!!application.attachment, activePreparation && application.phase === "packaging", ["packaging"]) },
    { title: "Email sent through Zoho", detail: sendAttempted ? "A send was attempted; wait for Sent verification." : "Requires an explicit Zoho send action.", state: status === "delivery_unconfirmed" ? "uncertain" : state(status === "sent_verified", ["queued_send", "sending"].includes(status), ["pre_send_checks"]) },
    { title: "Zoho Sent copy verified", detail: status === "sent_verified" ? `Verified${application.sent_at || application.verification_checked_at ? ` ${timestamp(application.sent_at || application.verification_checked_at)}` : ""}` : status === "delivery_unconfirmed" ? application.verification_next_at ? `No matching copy as of ${timestamp(application.verification_checked_at)}. Automatic recheck ${timestamp(application.verification_next_at)}; no resend.` : `No matching copy verified${application.verification_checked_at ? ` as of ${timestamp(application.verification_checked_at)}` : ""}; check again without resending.` : "Confirms the exact email and PDF in Sent, not recipient delivery.", state: status === "delivery_unconfirmed" ? application.phase === "verifying_sent" ? "active" : "uncertain" : state(status === "sent_verified", status === "sending" && application.phase === "verifying_sent") },
  ];
}

function StepIcon({ state }: { state: StepState }) {
  if (state === "complete") return <CheckCircle2 className="h-5 w-5 text-emerald-600" />;
  if (state === "active") return <Loader2 className="h-5 w-5 animate-spin text-sky-600" />;
  if (state === "blocked") return <AlertTriangle className="h-5 w-5 text-amber-600" />;
  if (state === "uncertain") return <Clock3 className="h-5 w-5 text-amber-600" />;
  return <Circle className="h-5 w-5 text-neutral-300" />;
}

export function ResumeSettings({ config, onChange }: { config: JobAgentConfig; onChange: (value: JobAgentConfig) => void }) {
  const library = useQuery({ queryKey: ["job-agent", "resumes"], queryFn: () => jobAgentRequest<{ items: { path: string; filename: string }[] }>("/resumes"), staleTime: 60000 });
  const change = (index: number, key: "name" | "description" | "resume_path", value: string) => onChange({ ...config, resume_categories: config.resume_categories.map((c, i) => i === index ? { ...c, [key]: value } : c) });
  return <section className="overflow-hidden rounded-2xl border border-violet-200/80 bg-violet-50/40 shadow-sm">
    <div className="flex items-start justify-between gap-4 border-b border-violet-200/70 bg-violet-100/70 p-5">
      <div className="flex items-start gap-3"><span className="rounded-xl border border-violet-200 bg-white/80 p-2.5 text-violet-700"><FileStack className="h-5 w-5" /></span><div><p className="text-xs font-semibold uppercase tracking-wider text-violet-700">03 · Resume routing</p><h2 className="mt-1 font-semibold text-neutral-950">Job categories and resumes</h2><p className="mt-1 max-w-3xl text-sm leading-relaxed text-neutral-600">Define how jobs are grouped and assign one reusable, one-page PDF to each category.</p></div></div>
      <span className="hidden rounded-full border border-violet-200 bg-white/70 px-3 py-1 text-xs font-medium text-violet-800 sm:block">{config.resume_categories.length} categories</span>
    </div>
    <div className="space-y-5 p-5">
      <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
        <label className="flex items-start gap-3 rounded-xl border border-violet-200/70 bg-white/90 p-4 text-sm shadow-sm"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-violet-700" checked={config.classification_enabled} onChange={e => onChange({ ...config, classification_enabled: e.target.checked })} /><span><span className="font-medium text-neutral-900">Automatically classify every queued job</span><span className="mt-1 block text-xs leading-relaxed text-neutral-500">When off, classification runs only when you request it for a specific job.</span></span></label>
        <label className="rounded-xl border border-violet-100 bg-white/90 p-4 text-sm font-medium text-neutral-800">Minimum confidence<select className={`${input} mt-3`} value={config.classification_threshold} onChange={e => onChange({ ...config, classification_threshold: Number(e.target.value) })}>{Array.from(new Set([0.6, 0.7, 0.8, 0.9, 1, config.classification_threshold])).sort().map(value => <option key={value} value={value}>{Math.round(value * 100)}%</option>)}</select></label>
      </div>
      {library.isPending && <p className="flex items-center gap-2 text-sm text-violet-700"><Loader2 className="h-4 w-4 animate-spin" />Loading resume library…</p>}
      {library.error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{library.error.message}</p>}
      <div className="space-y-4">
        {config.resume_categories.map((category, index) => <div key={category.id} className="overflow-hidden rounded-xl border border-violet-100 bg-white/90 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-violet-100 bg-violet-50/70 px-4 py-3"><div className="flex items-center gap-3"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-700 text-xs font-semibold text-white">{index + 1}</span><div><p className="text-sm font-semibold text-neutral-900">{category.name || "Untitled category"}</p><p className="text-xs text-neutral-500">{category.resume_path ? "Resume assigned" : "Needs a resume"}</p></div></div>{category.resume_path && <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">Ready</span>}</div>
          <div className="space-y-4 p-4">
            <div className="grid gap-4 lg:grid-cols-2"><label className="block text-sm font-medium text-neutral-800">Category name<input className={`${input} mt-2`} value={category.name} maxLength={120} required onChange={e => change(index, "name", e.target.value)} /></label><label className="block text-sm font-medium text-neutral-800">Assigned one-page resume<select aria-label={`Resume for ${category.name}`} className={`${input} mt-2`} value={category.resume_path} onChange={e => change(index, "resume_path", e.target.value)}><option value="">No resume assigned — needs review</option>{category.resume_path && !library.data?.items.some(file => file.path === category.resume_path) && <option value={category.resume_path}>{category.resume_path.split("/").pop()}</option>}{library.data?.items.map(file => <option key={file.path} value={file.path}>{file.filename} — {file.path.startsWith("job-agent/resumes/") ? "Category library" : file.path.split("/").slice(0, -1).join("/")}</option>)}</select></label></div>
            <label className="block text-sm font-medium text-neutral-800">Responsibilities and fit rules<textarea className={`${input} mt-2 min-h-24`} value={category.description} maxLength={2000} required onChange={e => change(index, "description", e.target.value)} /></label>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-neutral-100 pt-3">{category.resume_path ? <a className="inline-flex items-center gap-1.5 text-sm font-medium text-violet-700 hover:text-violet-900" href={pdfUrl(category.resume_path)} target="_blank" rel="noopener noreferrer">Preview resume <ExternalLink className="h-3.5 w-3.5" /></a> : <span className="text-xs text-amber-700">Assign a PDF before this category can be used automatically.</span>}<button type="button" className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50" onClick={() => onChange({ ...config, resume_categories: config.resume_categories.filter((_, i) => i !== index) })}><Trash2 className="h-3.5 w-3.5" />Remove</button></div>
          </div>
        </div>)}
      </div>
      <button type="button" className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-dashed border-violet-300 bg-white/60 px-4 py-3 text-sm font-medium text-violet-800 hover:border-violet-400 hover:bg-white" onClick={() => onChange({ ...config, resume_categories: [...config.resume_categories, { id: `category_${Date.now()}`, name: "New category", description: "", resume_path: "" }] })}><Plus className="h-4 w-4" />Add job category</button>
    </div>
  </section>;
}

export function JobApplicationControls({ job, categories }: { job: Candidate; categories: JobAgentConfig["resume_categories"] }) {
  const client = useQueryClient();
  const detail = useQuery({ queryKey: ["job-agent", "job", job.id], queryFn: () => jobAgentRequest<Candidate>(`/jobs/${job.id}`), initialData: job, refetchInterval: 5000 });
  const data = detail.data;
  const classification = data.classification;
  const application = data.application;
  const classificationStatus = classification?.status || "pending";
  const isClassifying = classificationStatus === "classifying";
  const classificationMessage = classification?.reason || (isClassifying
    ? "Analyzing this job’s responsibilities and requirements…"
    : classificationStatus === "pending" && classification?.requested
      ? "Queued for classification."
      : "Classify this job when you are considering an application, or choose a category manually.");
  const emptyCategoryLabel = isClassifying ? "Classifying…" : classificationStatus === "pending" ? "Not classified — choose a category" : "Needs review — choose a category";
  const status = application?.status || "not_started";
  const activelyProcessing = ["queued", "preparing", "queued_send", "sending"].includes(status);
  const locked = ["queued", "preparing", "queued_send", "sending", "sent_verified", "delivery_unconfirmed"].includes(status);
  const refresh = () => client.invalidateQueries({ queryKey: ["job-agent"] });
  const action = useMutation({ mutationFn: ({ endpoint, body }: { endpoint: string; body?: unknown }) => jobAgentRequest<Candidate>(`/jobs/${job.id}/${endpoint}`, body ?? {}), onSuccess: refresh });
  const send = (mode: "prepare" | "send") => action.mutate({ endpoint: "application", body: { mode, revision: data.processing_revision } });
  const ready = classification?.status === "classified" && !!classification.resume;
  const suggestedNeedsConfirmation = classificationStatus === "needs_review" && !!classification?.category_id && !!classification.resume;
  const summary = status === "not_started" && suggestedNeedsConfirmation
    ? { title: "Category confirmation needed", detail: "Jev suggested a category below the automatic confidence threshold. Confirm it or choose a different category before preparing the application.", tone: "amber" }
    : applicationStatus(application || { status: "not_started" });
  const steps = applicationSteps(data, ready);
  const canRetry = status === "needs_review" && application?.retryable !== false && !application?.send_started_at;
  const retryLabel = application?.failed_phase === "researching" ? "Retry source research" : "Retry preparation";
  const jobUrl = safeUrl(data.posting.source_url);
  const updateTime = timestamp(data.processing_updated_at);
  const statusTone = summary.tone === "emerald" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : summary.tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-950" : summary.tone === "sky" ? "border-sky-200 bg-sky-50 text-sky-950" : "border-neutral-200 bg-white text-neutral-900";
  return <section className="space-y-4 rounded-xl border border-neutral-200 bg-neutral-50 p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="font-semibold">Resume and application</h3><p className="mt-1 text-xs text-neutral-500">{classification ? readable(classification.status) : "Waiting for classification"}{classification?.confidence !== undefined ? ` · ${Math.round(classification.confidence * 100)}% confidence` : ""}</p></div><div className="flex items-center gap-2">{jobUrl && <a href={jobUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-300 bg-white px-2.5 py-1.5 text-xs font-medium text-neutral-800 hover:bg-neutral-50">Open job listing <ExternalLink className="h-3.5 w-3.5" /></a>}{activelyProcessing && <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-800"><Loader2 className="h-3.5 w-3.5 animate-spin" />Updates automatically</span>}</div></div>
    <p className="text-sm text-neutral-700">{classificationMessage}</p>
    <label className="block text-sm font-medium">Job category<select aria-label="Job category" className={`${input} mt-1`} disabled={locked || action.isPending || !data.processing_revision} value={classification?.category_id || ""} onChange={e => action.mutate({ endpoint: "category", body: { category_id: e.target.value || null, revision: data.processing_revision } })}><option value="">{emptyCategoryLabel}</option>{categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
    {suggestedNeedsConfirmation && !locked && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-950"><p className="text-sm">This is a model suggestion, not yet an approved resume choice.</p><button type="button" className="inline-flex items-center gap-1.5 rounded-lg bg-amber-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={action.isPending || !data.processing_revision} onClick={() => action.mutate({ endpoint: "category", body: { category_id: classification?.category_id, revision: data.processing_revision } })}><Check className="h-4 w-4" />{action.isPending ? "Confirming…" : "Confirm category"}</button></div>}
    {classification?.resume ? <div className="text-sm"><p className="break-words text-neutral-600">{classification.resume.filename}</p><a className="mt-1 inline-block underline" href={pdfUrl(classification.resume.path)} target="_blank" rel="noopener noreferrer">Preview selected resume</a></div> : classification?.category_id ? <p className="text-sm text-amber-800">Assign a one-page PDF to this category in Settings before applying.</p> : <p className="text-sm text-neutral-500">{isClassifying ? "The resume will appear after classification completes." : "A resume will be selected after classification or a manual category choice."}</p>}
    {!locked && <button className="text-xs underline" disabled={action.isPending || isClassifying} onClick={() => action.mutate({ endpoint: "classify" })}>{isClassifying ? "Classifying…" : classificationStatus === "pending" ? "Classify for application" : "Classify again"}</button>}
    <div className="border-t border-neutral-200 pt-4">
      <div aria-live="polite" className={`rounded-xl border p-4 ${statusTone}`}><div className="flex items-start gap-3">{summary.tone === "emerald" ? <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0" /> : summary.tone === "amber" ? <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" /> : summary.tone === "sky" ? <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin" /> : <Clock3 className="mt-0.5 h-5 w-5 shrink-0" />}<div><p className="text-sm font-semibold">{summary.title}</p><p className="mt-1 text-xs leading-relaxed opacity-80">{summary.detail}</p>{application?.attempt && <p className="mt-2 text-[11px] opacity-70">Preparation attempt {application.attempt}{updateTime ? ` · Updated ${updateTime}` : ""}</p>}</div></div></div>
      {application?.error && <div role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950"><p className="text-sm font-semibold">{status === "delivery_unconfirmed" ? "Verification status" : "Why it stopped"}</p><p className="mt-1 text-sm leading-relaxed">{application.error}</p>{application.failed_phase && <p className="mt-2 text-xs text-amber-800">Stopped during: {phaseNames[application.failed_phase] || readable(application.failed_phase)}.</p>}{canRetry && <p className="mt-2 text-xs text-amber-800">Retrying starts a new preparation attempt. It will not send an email.</p>}</div>}
      <ol aria-label="Application progress" className="mt-4 space-y-1 rounded-xl border border-neutral-200 bg-white p-3">{steps.map((step, index) => <li key={step.title} className="flex gap-3 rounded-lg px-2 py-2.5"><span className="mt-0.5 shrink-0"><StepIcon state={step.state} /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium text-neutral-900">{step.title}</p>{step.state === "active" && <span className="text-[11px] font-medium text-sky-700">In progress</span>}{step.state === "blocked" && <span className="text-[11px] font-medium text-amber-700">Stopped here</span>}{step.state === "complete" && <span className="text-[11px] font-medium text-emerald-700">Completed</span>}{step.state === "uncertain" && <span className="text-[11px] font-medium text-amber-700">Result uncertain</span>}</div><p className="mt-0.5 break-words text-xs leading-relaxed text-neutral-500">{step.detail}</p></div>{index < steps.length - 1 && null}</li>)}</ol>
      {application?.company_summary && <p className="mt-2 text-sm text-neutral-600">{application.company_summary}</p>}
      {application?.recipient && <div className="mt-3 text-sm"><p><strong>To:</strong> {application.recipient.name} · {application.recipient.email}</p><p className="mt-1 text-xs text-neutral-500">{application.recipient.reason}</p>{application.recipient.evidence.source_type === "possibleos_contact" ? <p className="mt-1 text-xs text-neutral-500">Possible OS contact{application.recipient.evidence.source_name ? ` · ${readable(application.recipient.evidence.source_name)}` : ""}{application.recipient.evidence.observed_at ? ` · observed ${timestamp(application.recipient.evidence.observed_at)}` : ""}</p> : safeUrl(application.recipient.evidence.source_url) && <a className="mt-1 inline-block text-xs underline" href={safeUrl(application.recipient.evidence.source_url)} target="_blank" rel="noopener noreferrer">Recipient source</a>}</div>}
      {application?.email && <details className="mt-3 rounded-lg border bg-white p-3 text-sm" open={status === "ready"}><summary className="cursor-pointer font-medium">Review email draft · {application.email.subject}</summary><p className="mt-3 whitespace-pre-wrap break-words border-t border-neutral-100 pt-3">{application.email.body_text}</p></details>}
      {!!application?.gaps?.length && <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-amber-800">{application.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul>}
      {application?.attachment && <a className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium underline" href={pdfUrl(application.attachment.path)} target="_blank" rel="noopener noreferrer"><Check className="h-4 w-4" />View application PDF</a>}
      {status === "sent_verified" && <p className="mt-3 flex items-start gap-2 text-sm text-emerald-700"><MailCheck className="mt-0.5 h-4 w-4 shrink-0" />Email and attached PDF verified in Zoho Sent. Recipient delivery and portal submission are separate.</p>}
    </div>
    {(action.error || detail.error) && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-900"><p className="text-sm font-semibold">The request could not be completed</p><p className="mt-1 text-sm">{(action.error || detail.error)?.message}</p>{detail.error && <button className={`${button} mt-3`} onClick={() => detail.refetch()}><RotateCcw className="h-4 w-4" />Reload status</button>}</div>}
    {!locked && <div className="flex flex-wrap gap-2">{canRetry ? <button className={primary} disabled={!ready || action.isPending || job.posting.status === "closed"} onClick={() => send("prepare")}><RotateCcw className={`h-4 w-4 ${action.isPending ? "animate-spin" : ""}`} />{action.isPending ? "Retrying…" : retryLabel}</button> : status === "ready" ? <><button className={button} disabled={!ready || action.isPending || job.posting.status === "closed"} onClick={() => send("prepare")}><RotateCcw className="h-4 w-4" />Rebuild draft</button><button className={primary} disabled={!ready || action.isPending || job.posting.status === "closed"} onClick={() => send("send")}><MailCheck className="h-4 w-4" />{action.isPending ? "Queuing send…" : "Send via Zoho"}</button></> : status !== "needs_review" && <><button className={button} disabled={!ready || action.isPending || job.posting.status === "closed"} onClick={() => send("prepare")}>{action.isPending ? "Starting…" : "Prepare draft"}</button><button className={primary} disabled={!ready || action.isPending || job.posting.status === "closed"} onClick={() => send("send")}>{action.isPending ? "Starting…" : "Prepare and send via Zoho"}</button></>}</div>}
    {status === "delivery_unconfirmed" && <button className={primary} disabled={action.isPending} onClick={() => action.mutate({ endpoint: "verify-sent" })}><RotateCcw className={`h-4 w-4 ${action.isPending ? "animate-spin" : ""}`} />{action.isPending ? "Checking Zoho Sent…" : "Check Zoho Sent again"}</button>}
    {!locked && status !== "needs_review" && <p className="text-xs leading-relaxed text-neutral-500">Prepare draft researches and composes without sending. Prepare and send via Zoho authorizes one email after all checks pass.</p>}
    {status === "needs_review" && application?.retryable === false && <p className="text-xs leading-relaxed text-amber-800">This issue needs manual review. Retrying is disabled because it could create a duplicate application.</p>}
    {job.posting.status === "closed" && <p className="text-xs text-amber-800">Application actions are disabled because the source marks this job closed.</p>}
  </section>;
}
