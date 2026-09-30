"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Loader2, Pause, Play, Send, MessageCircle, CheckCircle2, RotateCcw } from "lucide-react";
import { JobApplicantProfile } from "@/components/JobApplicantProfile";
import { JobHumanControl } from "@/components/JobHumanControl";
import { apiUrl } from "@/lib/api";
import { jobAgentRequest, type Candidate, type JobAgentConfig } from "@/lib/job-agent";

type BrowserRun = {
  can_quit?: boolean; quit_reason?: string; browser_cleanup_error?: string;
  can_restart?: boolean; can_resume?: boolean; recoverable_input_interruption?: boolean;
  recoverable_source_navigation?: boolean;
  restart_blocked_reason?: string; attempt?: number;
  profile_count?: number;
  browser_transport?: string; browser_session_status?: string; browser_closed?: boolean;
  ai_provider?: "gateway" | "openai"; openai_model?: string;
  spam_protection?: { detected_at?: string; evidence?: string };
  status: string; revision: number; stage?: string; error?: string; steps?: number;
  current_url?: string; updated_at?: string; screenshot?: boolean; session_available?: boolean;
  resume_filename?: string; submit_started_at?: string; human_may_have_submitted_at?: string; interaction_started?: boolean;
  question?: { id: string; text: string; choices: string[] } | null;
  answers?: { question: string; answer: string; at: string }[];
  confirmation?: { quote: string; url: string; at: string };
  companion_email?: { requested: boolean; status: string; run_id?: string; error?: string };
  application_source?: { url: string; source_type: "employer" | "ats"; match_scope: "direct_role" | "official_jobs_portal"; reason: string; confidence: number; verified_at: string };
  source_recovery?: { status: "pending" | "completed"; requested_at?: string; verified_at?: string };
  failed_action?: { kind: string; summary: string } | null;
  failed_audit?: { effect?: string; reason?: string } | null;
  events?: { id: number; kind: string; message: string; at: string }[];
};
const button = "inline-flex items-center justify-center gap-2 rounded-lg border border-sky-200 bg-white px-3 py-2 text-sm font-medium text-sky-950 disabled:opacity-50";
type OpenAIModel = "gpt-5.6-luna" | "gpt-6-astra";
function link(value?: string) { try { const u = new URL(value || ""); return u.protocol === "https:" ? u.href : undefined; } catch { return undefined; } }

export function JobBrowserApplication({ job }: { job: Candidate }) {
  const client = useQueryClient();
  const [answer, setAnswer] = useState("");
  const [remember, setRemember] = useState(true);
  const [showProfile, setShowProfile] = useState(false);
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [confirmQuit, setConfirmQuit] = useState(false);
  const [quitReason, setQuitReason] = useState("");
  const [provider, setProvider] = useState<"gateway" | "openai" | "">("");
  const [model, setModel] = useState<OpenAIModel | "">("");
  const settings = useQuery({ queryKey: ["job-agent", "browser-config"],
    queryFn: () => jobAgentRequest<{ config: JobAgentConfig }>("/config") });
  const query = useQuery({ queryKey: ["job-agent", "browser", job.id],
    queryFn: () => jobAgentRequest<BrowserRun>(`/jobs/${job.id}/browser`),
    refetchInterval: 3000, refetchIntervalInBackground: true });
  const run = query.data;
  const selectedProvider = provider || (run && run.status !== "not_started" ? run.ai_provider || "openai" : settings.data?.config.browser_ai_provider || "openai");
  const selectedModel = model || (run && run.status !== "not_started" ? run.openai_model : settings.data?.config.browser_openai_model) || "gpt-5.6-luna";
  useEffect(() => { setAnswer(""); setRemember(true); }, [run?.question?.id]);
  const action = useMutation({
    mutationFn: ({ endpoint, body }: { endpoint: string; body: unknown }) =>
      jobAgentRequest<BrowserRun>(`/jobs/${job.id}/browser/${endpoint}`, body),
    onSuccess: () => { setConfirmRestart(false); setConfirmQuit(false); client.invalidateQueries({ queryKey: ["job-agent"] }); },
  });
  const control = (kind: string) => action.mutate({ endpoint: "control", body: {
    action: kind, revision: run?.revision, question_id: run?.question?.id, answer, remember,
    ...(kind === "quit" ? { reason: quitReason } : {}),
    ...(["resume", "answer", "verify", "restart", "resume_unsubmitted"].includes(kind) ? { provider: selectedProvider, model: selectedModel } : {}),
  } });
  const active = !!run && ["queued", "running", "verifying"].includes(run.status);
  const started = !!run && run.status !== "not_started";
  const canStart = !!job.processing_revision && job.posting.status !== "closed";
  const waiting = run?.status === "waiting_for_answer";
  const submitted = run?.status === "submitted";
  const cancelled = run?.status === "cancelled";
  const uncertain = run?.status === "submission_uncertain";
  const humanControl = run?.status === "human_control";
  const currentLink = link(run?.current_url);
  const error = action.error || query.error || settings.error;
  const quitSuggestions = useMutation({ mutationFn: () => jobAgentRequest<{ reasons: string[] }>(`/jobs/${job.id}/browser/quit-reasons`, {}) });
  const openQuit = () => { setConfirmRestart(false); setConfirmQuit(true); quitSuggestions.reset(); quitSuggestions.mutate(); };
  return <section aria-label="Website application" className="overflow-hidden rounded-2xl border border-sky-200 bg-sky-50/40 shadow-sm">
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-sky-200 bg-gradient-to-r from-sky-100 to-indigo-50 p-5">
      <div><h3 className="flex items-center gap-2 font-semibold text-sky-950"><Globe className="h-5 w-5" />Apply on website</h3>
        <p className="mt-1 text-xs text-sky-900">The agent selects a resume, fills the employer’s form and asks you for any missing answers.</p></div>
      {started && <span className="rounded-full border border-sky-200 bg-white px-3 py-1 text-xs font-medium">{cancelled ? "Quit by you" : run.spam_protection ? "Paused · spam protection" : run.status.replaceAll("_", " ")}</span>}
    </header>
    <div className="space-y-4 p-5">
      <ol aria-label="Website application stages" className="grid grid-cols-3 gap-2 text-xs">{["Select resume", "Complete form", "Confirm submission"].map((label, index) => <li key={label} className={`flex items-center gap-2 rounded-lg border px-2 py-3 ${submitted || (index === 0 && run?.resume_filename) ? "border-emerald-200 bg-emerald-50 text-emerald-800" : active && (run?.resume_filename ? index === 1 : index === 0) ? "border-sky-300 bg-sky-100 text-sky-950" : "border-neutral-200 bg-white text-neutral-500"}`}><span className="font-semibold">{index + 1}</span>{label}</li>)}</ol>
      <label className="block text-sm font-medium text-sky-950">AI provider
        <select aria-label="Website application AI provider" className="mt-2 block w-full rounded-lg border border-sky-200 bg-white p-2 text-sm disabled:opacity-60" value={selectedProvider} disabled={active || humanControl || submitted || action.isPending} onChange={e => setProvider(e.target.value as "gateway" | "openai")}>
          <option value="gateway">OpenClaw gateway</option><option value="openai">Direct OpenAI API</option>
        </select>
        <span className="mt-1 block text-xs font-normal text-neutral-600">{active ? "Pause before changing provider or model. The choice applies when you resume." : "Used when you start, resume, answer a question, or check confirmation."} {selectedProvider === "openai" && "Uses the server API key and API billing."}</span>
      </label>
      {selectedProvider === "openai" && <label className="block text-sm font-medium text-sky-950">OpenAI model
        <select aria-label="Website application OpenAI model" className="mt-2 block w-full rounded-lg border border-sky-200 bg-white p-2 text-sm disabled:opacity-60" value={selectedModel} disabled={active || humanControl || submitted || action.isPending} onChange={e => setModel(e.target.value as OpenAIModel)}>
          <option value="gpt-5.6-luna">GPT-5.6 Luna · faster</option><option value="gpt-6-astra">GPT-6 Astra · stronger reasoning</option>
        </select>
      </label>}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-600"><span>{run?.profile_count ? `${run.profile_count} saved answers available for this application` : "Saved applicant answers are checked before the agent asks you."}</span><button type="button" className="font-medium text-violet-700 underline" onClick={() => setShowProfile(!showProfile)}>{showProfile ? "Hide applicant profile" : "View / edit applicant profile"}</button></div>
      {showProfile && <JobApplicantProfile compact />}
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900">{error.message}<button className={`${button} ml-3`} onClick={() => query.refetch()}>Reload status</button></div>}
      {query.isPending && <p className="text-sm">Loading website application status…</p>}
      {run?.status === "not_started" && <>
        <p className="text-sm text-neutral-700">Start authorizes one website submission and, when enabled in Job Agent Settings, one Zoho application email if a verified contact is found. Each channel keeps separate duplicate checks and confirmation.</p>
        <button className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-sky-900 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-sky-800 disabled:opacity-50" disabled={!canStart || action.isPending || query.isError || settings.isPending || settings.isError} onClick={() => action.mutate({ endpoint: "start", body: { revision: job.processing_revision, authorize_submit: true, provider: selectedProvider, model: selectedModel } })}><Play className="h-4 w-4" />{action.isPending ? "Starting…" : "Start website application"}</button>
        {!canStart && <p className="text-xs text-amber-800">This job is closed or its details are still loading.</p>}
      </>}
      {started && <>
        {run && <JobHumanControl jobId={job.id} run={run} active={active} busy={action.isPending} refreshStatus={() => query.refetch()} />}
        <div aria-live="polite" className="rounded-lg border border-sky-100 bg-white p-3">
          <p className="flex items-center gap-2 text-sm font-semibold">{active && !query.isError && <Loader2 className="h-4 w-4 animate-spin" />}{submitted && <CheckCircle2 className="h-4 w-4 text-emerald-700" />}{run.stage}</p>
          <p className="mt-2 text-xs text-neutral-500">Attempt {run.attempt || 1} · {run.steps || 0} browser actions · {run.resume_filename}{run.updated_at ? ` · Updated ${new Date(run.updated_at).toLocaleTimeString()}` : ""}</p>
          <p className="mt-1 text-xs text-neutral-500">Run provider: {run.ai_provider === "openai" ? `OpenAI API · ${run.openai_model}` : "OpenClaw gateway"}</p>
          {run.companion_email?.requested && <p className={`mt-2 text-xs ${run.companion_email.status === "queue_failed" ? "text-amber-800" : "text-emerald-800"}`}>{run.companion_email.status === "queue_failed" ? `Email workflow could not start: ${run.companion_email.error || "retry from Apply by email"}` : "Email application authorized too. See Apply by email for recipient research, Zoho delivery and Sent verification."}</p>}
          {run.source_recovery?.status === "pending" && <p className="mt-2 text-xs text-violet-800">The original listing did not reach a form. The agent is finding and verifying the exact role on the employer site or its ATS.</p>}
          {run.application_source && <p className="mt-2 text-xs text-emerald-800">Applying on the verified official {run.application_source.match_scope === "official_jobs_portal" ? "jobs portal" : run.application_source.source_type === "ats" ? "ATS" : "employer page"}: <a className="underline" href={run.application_source.url} target="_blank" rel="noopener noreferrer">open page</a></p>}
          {currentLink && <a href={currentLink} target="_blank" rel="noopener noreferrer" className="mt-2 block break-all text-xs underline">Current application page</a>}
          {!submitted && !cancelled && <div className={`mt-3 rounded-lg border p-3 text-xs ${run.session_available ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
            {run.browser_transport === "broker" ? <>
              <p className="font-semibold">{run.session_available ? "Browser preserved in a separate service" : run.browser_session_status === "unreachable" ? "Browser service is unreachable" : run.browser_session_status === "lost" ? "Original browser session is no longer available" : run.browser_closed ? "Browser closed" : "Connecting to the browser"}</p>
              <p className="mt-1">{run.session_available ? "Worker restarts keep this form open. Resume continues on the same page; reconnect never submits." : run.browser_session_status === "unreachable" ? "The form may still be open. Check the connection before restarting the application." : "Saved answers and evidence remain available. A lost browser cannot be restored by reconnecting."}</p>
            </> : <p>{uncertain ? "The original browser is required to check confirmation. Reopening the job cannot verify a previous submission." : run.session_available ? "This older browser session is tied to the worker and will close if it restarts." : "The browser opens when processing resumes, using your saved answers."}</p>}
          </div>}
        </div>
        {run.error && <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950"><p className="font-medium">{run.spam_protection ? "Paused because the employer site detected spam protection." : run.error}</p>{run.spam_protection && <><p className="mt-2">{run.error}</p><p className="mt-2 text-xs">The agent will not retry Submit automatically. Take control of the preserved browser to complete any visible challenge, then return control to the agent.</p></>}{run.failed_action && <p className="mt-2 text-xs"><strong>Stopped before:</strong> {run.failed_action.summary} ({run.failed_action.kind})</p>}{run.failed_audit?.reason && <p className="mt-1 text-xs"><strong>Safety audit:</strong> {run.failed_audit.reason}{run.failed_audit.effect ? ` · Audited effect: ${run.failed_audit.effect}` : ""}</p>}</div>}
        {cancelled && <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-700"><p className="font-medium">You stopped this website application.</p>{run.quit_reason && <p className="mt-2">Reason: {run.quit_reason}</p>}<p className="mt-2 text-xs">Your history and saved answers are retained. This reason applies only to this application.</p></div>}
        {run.browser_cleanup_error && <p role="alert" className="text-sm text-amber-900">{run.browser_cleanup_error}</p>}
        {uncertain && <p className="text-sm text-amber-900">{run.recoverable_source_navigation ? "The job board did not reach an application form. Resume to find the exact official employer or ATS page and continue there." : run.recoverable_input_interruption ? "An ordinary form input was interrupted. The preserved page can be inspected and continued without replaying that action." : run.can_restart ? "The last action stopped before reaching the browser. You can restart safely with your saved answers." : "An action may have submitted the form. Automatic submission is locked. Check the saved page or employer portal before taking further action."}</p>}
        {waiting && run.question && <div className="space-y-3 rounded-xl border-2 border-amber-300 bg-amber-50 p-4">
          <h4 className="flex items-center gap-2 text-sm font-semibold"><MessageCircle className="h-4 w-4" />Your answer is needed</h4>
          <label className="block text-sm" htmlFor={`browser-answer-${job.id}`}>{run.question.text}</label>
          {!!run.question.choices.length && <div className="flex flex-wrap gap-2">{run.question.choices.map(choice => <button key={choice} className={button} onClick={() => setAnswer(choice)}>{choice}</button>)}</div>}
          <textarea id={`browser-answer-${job.id}`} className="min-h-24 w-full rounded-lg border border-amber-300 bg-white p-3 text-sm" value={answer} maxLength={8000} onChange={event => setAnswer(event.target.value)} placeholder="Your answer for this application…" />
          <p className="text-xs text-amber-900">The agent uses the question and job context to decide when an answer applies. Do not enter passwords, payment details, or authentication cookies.</p>
          <label className="flex items-start gap-2 text-xs text-amber-950"><input type="checkbox" className="mt-0.5" checked={remember} onChange={event => setRemember(event.target.checked)} />Remember this answer for future applications</label>
          <div className="flex flex-wrap gap-2"><button className={button} disabled={!answer.trim() || action.isPending || query.isError} onClick={() => control("answer")}><Send className="h-4 w-4" />Save answer and continue</button>{run.can_quit && <button className={button} disabled={action.isPending || query.isError} onClick={openQuit}>Quit application</button>}</div>
        </div>}
        {confirmQuit && run.can_quit && <div role="region" aria-label="Quit application" className="space-y-3 rounded-xl border border-neutral-300 bg-white p-4">
          <h4 className="font-semibold">Stop applying to this role?</h4>
          <p className="text-sm text-neutral-700">The agent will stop and close this browser. Your history and saved answers stay available.</p>
          <p className="text-xs text-neutral-600">Choose a suggested reason based on this question, or write your own.</p>
          {quitSuggestions.isPending && <p role="status" className="flex items-center gap-2 text-xs text-neutral-600"><Loader2 className="h-4 w-4 animate-spin" />Suggesting reasons… You can also enter your own now.</p>}
          {quitSuggestions.error && <p className="text-xs text-neutral-600">Suggestions couldn’t load. You can still enter a reason or quit without one.</p>}
          <div className="flex flex-wrap gap-2">{quitSuggestions.data?.reasons.map(reason => <button type="button" key={reason} className={`${button} text-left`} aria-pressed={quitReason === reason} onClick={() => setQuitReason(reason)}>{reason}</button>)}</div>
          <label className="block text-sm" htmlFor={`quit-reason-${job.id}`}>Reason (optional)</label>
          <textarea id={`quit-reason-${job.id}`} className="min-h-20 w-full rounded-lg border border-neutral-300 p-3 text-sm" value={quitReason} onChange={e => setQuitReason(e.target.value)} maxLength={1000} placeholder="For example: I’m not willing to relocate to Czechia or Slovakia." />
          <div className="flex flex-wrap gap-2"><button className={button} disabled={action.isPending || query.isError} onClick={() => control("quit")}>{action.isPending ? "Stopping…" : "Quit this application"}</button><button className={button} disabled={action.isPending} onClick={() => setConfirmQuit(false)}>Keep applying</button></div>
        </div>}
        <div className="flex flex-wrap gap-2">
          {!humanControl && !waiting && run.can_quit && <button className={button} disabled={action.isPending || query.isError} onClick={openQuit}>Quit application</button>}
          {!humanControl && !active && !submitted && !cancelled && run.browser_transport === "broker" && !run.browser_closed && <button className={button} disabled={action.isPending || query.isError} onClick={() => control("reconnect")}>Reconnect to existing browser</button>}
          {active && <button className={button} disabled={action.isPending} onClick={() => control("pause")}><Pause className="h-4 w-4" />Pause after current action</button>}
          {run.can_resume && <button className={button} disabled={action.isPending || query.isError} onClick={() => control("resume")}><Play className="h-4 w-4" />Resume application</button>}
          {uncertain && !!run.human_may_have_submitted_at && run.session_available && <button className={button} disabled={action.isPending || query.isError} onClick={() => control("resume_unsubmitted")}><Play className="h-4 w-4" />I did not submit — resume agent</button>}
          {!humanControl && !active && (run.session_available || run.browser_cleanup_error) && !submitted && <button className={button} disabled={action.isPending} onClick={() => control("release")}>Close browser, keep saved answers</button>}
          {uncertain && run.session_available && <button className={button} disabled={action.isPending} onClick={() => control("verify")}>Check confirmation only</button>}
          {!humanControl && !active && !submitted && <button className={button} disabled={!run.can_restart || action.isPending || query.isError} title={run.restart_blocked_reason || undefined} onClick={() => setConfirmRestart(true)}><RotateCcw className="h-4 w-4" />Restart from beginning</button>}
        </div>
        {!active && !submitted && !run.can_restart && run.restart_blocked_reason && <p className="text-xs text-amber-900">{run.restart_blocked_reason}</p>}
        {confirmRestart && run.can_restart && <div role="region" aria-label="Restart application" className="space-y-3 rounded-xl border border-sky-300 bg-white p-4">
          <h4 className="font-semibold text-sky-950">Start with a fresh browser?</h4>
          <p className="text-sm text-neutral-700">The agent will reopen the listing and fill the form again using your selected resume and saved answers. The previous attempt stays in the activity history. It will continue toward the submission you already authorized.</p>
          <div className="flex gap-2"><button className={button} disabled={action.isPending} onClick={() => control("restart")}>{action.isPending ? "Restarting…" : "Restart and continue"}</button><button className={button} disabled={action.isPending} onClick={() => setConfirmRestart(false)}>Cancel</button></div>
        </div>}
        {run.confirmation && <blockquote className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950"><strong>Website submission confirmed</strong><p className="mt-2 whitespace-pre-wrap">{run.confirmation.quote}</p></blockquote>}
        <div className="grid gap-4 lg:grid-cols-2">
          <details className="rounded-lg border border-sky-100 bg-white p-3" open><summary className="cursor-pointer text-sm font-medium">Recent browser activity</summary><ol className="mt-3 max-h-72 space-y-3 overflow-auto text-xs">{run.events?.map(event => <li key={event.id}><span className="text-neutral-400">{new Date(event.at).toLocaleTimeString()} · </span>{event.message}</li>)}</ol></details>
          {run.screenshot && <details className="rounded-lg border border-sky-100 bg-white p-3"><summary className="cursor-pointer text-sm font-medium">Latest browser screenshot</summary><a href={apiUrl(`/api/job-agent/jobs/${job.id}/browser/screenshot?v=${run.revision}`)} target="_blank" rel="noopener noreferrer"><img alt="Latest application browser page" className="mt-3 w-full rounded border" src={apiUrl(`/api/job-agent/jobs/${job.id}/browser/screenshot?v=${run.revision}`)} /></a></details>}
        </div>
        {!!run.answers?.length && <details className="text-sm"><summary className="cursor-pointer">Saved answers ({run.answers.length})</summary><dl className="mt-3 space-y-2">{run.answers.map((item, index) => <div key={index}><dt className="font-medium">{item.question}</dt><dd className="whitespace-pre-wrap text-neutral-600">{item.answer}</dd></div>)}</dl></details>}
        <p className="text-xs text-neutral-500">Use Take control to complete login, CAPTCHA, or other manual steps in the agent’s preserved browser without losing entered form data.</p>
      </>}
    </div>
  </section>;
}
