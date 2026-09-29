"use client";

import { MousePointer2, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "@/lib/api";
import { jobAgentRequest } from "@/lib/job-agent";

type Run = {
  status: string;
  revision: number;
  session_available?: boolean;
  browser_closed?: boolean;
  human_control_expires_at?: string;
  submit_started_at?: string;
};

type Props = {
  jobId: string;
  run: Run;
  active: boolean;
  busy: boolean;
  refreshStatus: () => Promise<unknown> | void;
};

const button = "inline-flex items-center justify-center gap-2 rounded-lg border border-violet-200 bg-white px-3 py-2 text-sm font-medium text-violet-950 disabled:opacity-50";

async function responseError(response: Response) {
  const raw = await response.text();
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch { /* The proxy can return HTML while restarting. */ }
  return `Human-control request failed (HTTP ${response.status}).`;
}

export function JobHumanControl({ jobId, run, active, busy, refreshStatus }: Props) {
  const storageKey = `job-browser-handoff:${jobId}`;
  const [token, setToken] = useState("");
  const [frameUrl, setFrameUrl] = useState("");
  const [observationId, setObservationId] = useState("");
  const [currentUrl, setCurrentUrl] = useState("");
  const [text, setText] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const frameRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const saved = window.sessionStorage.getItem(storageKey) || "";
    setToken(saved);
  }, [storageKey]);

  useEffect(() => () => {
    if (frameUrl) URL.revokeObjectURL(frameUrl);
  }, [frameUrl]);

  const rememberToken = (value: string) => {
    setToken(value);
    if (value) window.sessionStorage.setItem(storageKey, value);
    else window.sessionStorage.removeItem(storageKey);
  };

  const acquire = async () => {
    setWorking(true); setError("");
    try {
      let revision = run.revision;
      if (active) {
        const paused = await jobAgentRequest<Run>(`/jobs/${jobId}/browser/control`, {
          action: "pause", revision,
        });
        revision = paused.revision;
      }
      const result = await jobAgentRequest<Run & { handoff_token: string }>(
        `/jobs/${jobId}/browser/handoff/start`, { revision });
      rememberToken(result.handoff_token);
      await refreshStatus();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not take control of this browser.");
    } finally { setWorking(false); }
  };

  const fetchFrame = async () => {
    if (!token) return;
    setWorking(true); setError("");
    try {
      const response = await fetch(apiUrl(`/api/job-agent/jobs/${jobId}/browser/handoff/frame?v=${Date.now()}`), {
        credentials: "include", headers: { "X-Human-Control-Token": token }, cache: "no-store",
      });
      if (!response.ok) throw new Error(await responseError(response));
      const nextObservation = response.headers.get("x-browser-observation-id") || "";
      if (!nextObservation) throw new Error("The live browser frame did not include a control handle.");
      const blobUrl = URL.createObjectURL(await response.blob());
      setFrameUrl(previous => { if (previous) URL.revokeObjectURL(previous); return blobUrl; });
      setObservationId(nextObservation);
      setCurrentUrl(response.headers.get("x-browser-current-url") || "");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not refresh the live browser.");
    } finally { setWorking(false); }
  };

  useEffect(() => {
    if (run.status === "human_control" && token && !frameUrl && !working) void fetchFrame();
  // fetchFrame intentionally runs only when a lease first becomes usable.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.status, token]);

  const act = async (payload: Record<string, unknown>) => {
    if (!token || !observationId) return;
    setWorking(true); setError("");
    try {
      const response = await fetch(apiUrl(`/api/job-agent/jobs/${jobId}/browser/handoff/action`), {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", "X-Human-Control-Token": token },
        body: JSON.stringify({
          observation_id: observationId,
          action_id: crypto.randomUUID().replaceAll("-", ""), ...payload,
        }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      setObservationId("");
      if ("value" in payload) setText("");
      await fetchFrame();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The browser action did not complete.");
      setObservationId("");
    } finally { setWorking(false); }
  };

  const finish = async (outcome: "resume_agent" | "may_have_submitted" | "keep_paused") => {
    if (!token) return;
    setWorking(true); setError("");
    try {
      const response = await fetch(apiUrl(`/api/job-agent/jobs/${jobId}/browser/handoff/finish`), {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", "X-Human-Control-Token": token },
        body: JSON.stringify({ revision: run.revision, outcome }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      rememberToken(""); setObservationId("");
      setFrameUrl(previous => { if (previous) URL.revokeObjectURL(previous); return ""; });
      await refreshStatus();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not return control.");
    } finally { setWorking(false); }
  };

  const controlling = run.status === "human_control";
  if (!controlling) {
    if (!run.session_available || run.browser_closed || ["submitted", "cancelled"].includes(run.status)) return null;
    return <div className="rounded-xl border border-violet-200 bg-violet-50 p-4">
      <p className="text-sm font-semibold text-violet-950">Need to complete something yourself?</p>
      <p className="mt-1 text-xs leading-5 text-violet-900">Take over the agent’s exact browser. The filled form, uploaded resume, cookies and current page remain in place.</p>
      <button className={`${button} mt-3`} disabled={busy || working} onClick={() => void acquire()}><MousePointer2 className="h-4 w-4" />{working ? "Preparing handoff…" : active ? "Pause and take control" : "Take control of this browser"}</button>
      {error && <p role="alert" className="mt-2 text-xs text-red-800">{error}</p>}
    </div>;
  }

  if (!token) return <div className="rounded-xl border-2 border-violet-300 bg-violet-50 p-4">
    <h4 className="font-semibold text-violet-950">This browser is in human-control mode</h4>
    <p className="mt-1 text-sm text-violet-900">Reconnect from this tab to rotate the private control lease. The page and everything already entered will remain unchanged.</p>
    <button className={`${button} mt-3`} disabled={working} onClick={() => void acquire()}>{working ? "Reconnecting…" : "Reconnect human control"}</button>
    {error && <p role="alert" className="mt-2 text-xs text-red-800">{error}</p>}
  </div>;

  return <section aria-label="Human browser control" className="space-y-3 rounded-xl border-2 border-violet-400 bg-violet-50 p-4 shadow-sm">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h4 className="flex items-center gap-2 font-semibold text-violet-950"><ShieldCheck className="h-4 w-4" />You control the agent’s browser</h4>
        <p className="mt-1 text-xs text-violet-900">The AI is paused. Click the image, type into the focused field, or use the keys below. No form state is copied to another browser.</p></div>
      <button className={button} disabled={working} onClick={() => void fetchFrame()}><RefreshCw className={`h-4 w-4 ${working ? "animate-spin" : ""}`} />Refresh view</button>
    </div>
    {currentUrl && <p className="break-all text-xs text-violet-800">Current page: {currentUrl}</p>}
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"><p>{error} Refresh the view before trying the action again.</p><button className={`${button} mt-2`} disabled={working} onClick={() => void acquire()}>Reconnect control lease</button></div>}
    <div className="overflow-hidden rounded-lg border border-violet-200 bg-neutral-900">
      {frameUrl ? <img ref={frameRef} src={frameUrl} alt="Interactive view of the preserved application browser" className={`block h-auto w-full ${working || !observationId ? "cursor-wait opacity-80" : "cursor-crosshair"}`} onClick={event => {
        if (working || !observationId) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const x = (event.clientX - rect.left) * 1280 / rect.width;
        const y = (event.clientY - rect.top) * 900 / rect.height;
        void act({ kind: "click", x, y });
      }} /> : <div className="flex aspect-[1280/900] items-center justify-center text-sm text-white">Loading the preserved page…</div>}
    </div>
    <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
      <input aria-label="Text to enter in the focused browser field" type="text" className="rounded-lg border border-violet-200 bg-white px-3 py-2 text-sm" value={text} onChange={event => setText(event.target.value)} placeholder="Click a field above, then type here" />
      <button className={button} disabled={working || !observationId || !text} onClick={() => void act({ kind: "type", value: text })}>Type</button>
      <button className={button} disabled={working || !observationId || !text} onClick={() => void act({ kind: "replace", value: text })}>Replace field</button>
    </div>
    <div className="flex flex-wrap gap-2">{["Tab", "Shift+Tab", "Enter", "Escape", "Backspace", "ArrowUp", "ArrowDown", "Space"].map(key => <button key={key} className={button} disabled={working || !observationId} onClick={() => void act({ kind: "press", key })}>{key}</button>)}
      <button className={button} disabled={working || !observationId} onClick={() => void act({ kind: "scroll", delta_y: -650 })}>Scroll up</button>
      <button className={button} disabled={working || !observationId} onClick={() => void act({ kind: "scroll", delta_y: 650 })}>Scroll down</button>
    </div>
    <div className="rounded-lg border border-violet-200 bg-white p-3">
      <p className="text-xs font-semibold text-violet-950">When you’re done</p>
      <p className="mt-1 text-xs text-neutral-600">Choose the accurate outcome. If an earlier submit attempt was recorded and you choose “did not submit,” the agent first confirms that this same form still has an enabled Submit button. If it cannot prove that, it will require verification-only mode.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={button} disabled={working} onClick={() => void finish("resume_agent")}>{run.submit_started_at ? "Return to agent — page shows it was not submitted" : "Return to agent — I did not submit"}</button>
        <button className={button} disabled={working} onClick={() => void finish("may_have_submitted")}>I may have submitted — verify only</button>
        <button className={button} disabled={working} onClick={() => void finish("keep_paused")}>Keep paused</button>
      </div>
    </div>
    <p className="text-xs text-neutral-500">The private control lease expires after 30 minutes. Text entered here is sent only to the open browser and is not saved in Job Agent history.</p>
  </section>;
}
