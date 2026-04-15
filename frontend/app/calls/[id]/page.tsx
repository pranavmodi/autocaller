"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, formatDistanceToNow } from "date-fns";
import { ArrowLeft, Calendar, Mail, ExternalLink, RefreshCw, Phone } from "lucide-react";
import { getCall, recordingUrl, apiUrl, retryLead, startCall } from "@/lib/api";
import { OutcomePill } from "@/components/OutcomePill";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  params: { id: string };
}

export default function CallDetailPage({ params }: Props) {
  const callId = params.id;
  const qc = useQueryClient();
  const { data: call, isLoading } = useQuery({
    queryKey: ["call", callId],
    queryFn: () => getCall(callId),
    refetchInterval: (q) => {
      const d = q.state.data as any;
      // Poll every 10s while judge hasn't run yet
      return d?.ended_at && !d?.judged_at ? 10_000 : false;
    },
  });

  const judgeNow = useMutation({
    mutationFn: async () => {
      const res = await fetch(apiUrl(`/api/calls/${callId}/judge`), { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["call", callId] }),
  });

  const retry = useMutation({
    mutationFn: () => retryLead((call as any)?.patient_id as string),
  });

  const callNow = useMutation({
    mutationFn: () => startCall((call as any)?.patient_id as string, "twilio"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["call", callId] }),
  });

  const audioRef = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    const handler = () => setCurrentTime(el.currentTime);
    el.addEventListener("timeupdate", handler);
    return () => el.removeEventListener("timeupdate", handler);
  }, [call?.recording_path]);

  const seekTo = (seconds: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = seconds;
    void el.play();
  };

  if (isLoading) {
    return <p className="text-sm text-neutral-400">loading call…</p>;
  }
  if (!call) {
    return <p className="text-sm text-rose-600">Call not found.</p>;
  }

  const recUrl = recordingUrl(call.recording_path);
  const startedAt = call.started_at ? new Date(call.started_at) : null;

  // Transcript entries have timestamps. Compute each entry's offset from the
  // call start (seconds) so clicking a line seeks the audio.
  const baseMs = startedAt ? startedAt.getTime() : null;
  const transcriptWithOffsets = call.transcript.map((t) => {
    let offset: number | null = null;
    if (baseMs && t.timestamp) {
      const diff = (new Date(t.timestamp).getTime() - baseMs) / 1000;
      if (!Number.isNaN(diff) && diff >= 0) offset = diff;
    }
    return { ...t, offset };
  });

  return (
    <div className="space-y-6">
      <Link
        href="/calls"
        className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-800"
      >
        <ArrowLeft className="h-3 w-3" />
        back to call history
      </Link>

      {/* Header */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold">{call.patient_name || "(unknown)"}</h1>
              {call.mock_mode ? (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-inset ring-amber-200">
                  MOCK
                </span>
              ) : (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
                  REAL
                </span>
              )}
            </div>
            <p className="text-sm text-neutral-500">
              {call.firm_name || "—"}
              {call.lead_state ? ` · ${call.lead_state}` : ""}
              {" · "}
              {call.phone}
            </p>
            <p className="mt-1 text-xs text-neutral-400">
              {startedAt ? format(startedAt, "PPp") : "—"} · {call.duration_seconds}s
              {call.prompt_version ? ` · prompt ${call.prompt_version}` : ""}
              {call.voice_provider ? ` · voice ${call.voice_provider}` : ""}
              {call.voice_model ? ` (${call.voice_model})` : ""}
              {call.ivr_detected
                ? ` · IVR ${call.ivr_outcome ?? "detected"}`
                : ""}
            </p>
          </div>
          <OutcomePill outcome={call.outcome} />
        </div>

        {/* Audio */}
        {recUrl && (
          <audio
            ref={audioRef}
            controls
            preload="metadata"
            src={recUrl}
            className="mt-4 w-full"
          >
            Your browser does not support audio playback.
          </audio>
        )}
        {!recUrl && (
          <p className="mt-4 rounded-md bg-neutral-50 px-3 py-2 text-xs text-neutral-500">
            No recording for this call.
          </p>
        )}
      </section>

      {/* GTM disposition + Judge score */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
              Review
            </h2>
            {call.judged_at ? (
              <p className="text-[11px] text-neutral-400">
                judged {formatDistanceToNow(new Date(call.judged_at), { addSuffix: true })}
              </p>
            ) : (
              <p className="text-[11px] text-neutral-400">not yet judged</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => callNow.mutate()}
              disabled={callNow.isPending || !call.patient_id}
              title="Place a Twilio call to this lead immediately. Requires no active call + safety gates passing."
              className="gap-1.5 bg-emerald-600 text-white hover:bg-emerald-700"
            >
              <Phone className={cn("h-3.5 w-3.5", callNow.isPending && "animate-pulse")} />
              {callNow.isSuccess ? "Dialing…" : callNow.isError ? "Call failed" : "Call now"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => retry.mutate()}
              disabled={retry.isPending || !call.patient_id}
              title="Clear cooldown on this lead so the dispatcher re-picks it on its next tick"
              className="gap-1.5"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", retry.isPending && "animate-spin")} />
              {retry.isSuccess ? "Queued for retry" : "Retry this lead"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => judgeNow.mutate()}
              disabled={judgeNow.isPending || !call.ended_at}
              className="gap-1.5"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", judgeNow.isPending && "animate-spin")} />
              {call.judged_at ? "Re-judge" : "Judge now"}
            </Button>
          </div>
        </div>

        {call.judged_at ? (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-xs uppercase text-neutral-500">Overall score</span>
                <span
                  className={cn(
                    "rounded-full px-2.5 py-0.5 text-sm font-bold",
                    (call.judge_score ?? 0) >= 8 ? "bg-emerald-50 text-emerald-700" :
                    (call.judge_score ?? 0) >= 5 ? "bg-amber-50 text-amber-700" :
                    "bg-rose-50 text-rose-700"
                  )}
                >
                  {call.judge_score ?? "—"} / 10
                </span>
              </div>
              {call.judge_scores && (
                <div className="mt-3 space-y-1.5 text-xs">
                  <ScoreRow label="Opening" v={call.judge_scores.opening_quality} />
                  <ScoreRow label="Discovery" v={call.judge_scores.discovery_quality} />
                  <ScoreRow label="Tools" v={call.judge_scores.tool_use_correctness} />
                  <ScoreRow label="Objections" v={call.judge_scores.objection_handling} />
                  <ScoreRow label="Closing" v={call.judge_scores.closing_quality} />
                </div>
              )}
            </div>
            <div>
              <span className="text-xs uppercase text-neutral-500">GTM disposition</span>
              <div className="mt-1 font-mono text-sm font-semibold text-neutral-900">
                {call.gtm_disposition || "—"}
              </div>
              {call.follow_up_action && (
                <div className="mt-1 text-xs text-neutral-600">
                  next: <span className="font-medium">{call.follow_up_action}</span>
                  {call.follow_up_when && (
                    <span className="ml-1 text-neutral-400">
                      · {format(new Date(call.follow_up_when), "PP")}
                    </span>
                  )}
                  {call.follow_up_owner && (
                    <span className="ml-1 text-neutral-400">· {call.follow_up_owner}</span>
                  )}
                </div>
              )}
              {call.call_summary && (
                <p className="mt-2 text-sm text-neutral-700">{call.call_summary}</p>
              )}
              {call.follow_up_note && (
                <p className="mt-2 rounded-md bg-neutral-50 px-2 py-1.5 text-xs text-neutral-700">
                  💡 {call.follow_up_note}
                </p>
              )}
              {call.dnc_reason && (
                <p className="mt-2 rounded-md bg-rose-50 px-2 py-1.5 text-xs text-rose-700 ring-1 ring-inset ring-rose-200">
                  DNC: {call.dnc_reason}
                </p>
              )}
              {call.signal_flags && call.signal_flags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {call.signal_flags.map((s) => (
                    <span key={s} className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] text-neutral-600">
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Missed ops / errors (span full width) */}
            {(call.judge_notes?.missed_opportunities?.length ||
              call.judge_notes?.ai_errors?.length ||
              call.judge_notes?.recommended_prompt_edits?.length) ? (
              <div className="md:col-span-2 space-y-2 border-t border-neutral-100 pt-3">
                {call.judge_notes?.missed_opportunities?.length ? (
                  <NoteList label="Missed opportunities" items={call.judge_notes.missed_opportunities} tone="amber" />
                ) : null}
                {call.judge_notes?.ai_errors?.length ? (
                  <NoteList label="AI errors" items={call.judge_notes.ai_errors} tone="rose" />
                ) : null}
                {call.judge_notes?.recommended_prompt_edits?.length ? (
                  <NoteList label="Recommended prompt edits" items={call.judge_notes.recommended_prompt_edits} tone="blue" />
                ) : null}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="mt-3 text-xs text-neutral-500">
            {call.ended_at
              ? "Waiting for the judge — runs every 60s, or click Judge now."
              : "Still in progress — review runs after the call ends."}
          </p>
        )}
      </section>

      {/* Structured capture + Demo booking */}
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg border border-neutral-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
            Capture
          </h2>
          <dl className="mt-3 space-y-2 text-sm">
            <Field label="Pain" value={call.pain_point_summary} />
            <Field
              label="Interest"
              value={
                call.interest_level != null ? `${call.interest_level}/5` : null
              }
            />
            <Field
              label="Decision maker"
              value={
                call.is_decision_maker == null
                  ? null
                  : call.is_decision_maker
                    ? "yes"
                    : "no"
              }
            />
            <Field
              label="Gatekeeper"
              value={
                call.was_gatekeeper
                  ? call.gatekeeper_contact
                    ? JSON.stringify(call.gatekeeper_contact)
                    : "yes"
                  : "no"
              }
            />
            <Field
              label="Status / Disposition"
              value={`${call.call_status} / ${call.call_disposition}`}
            />
            {call.error_code && (
              <Field
                label="Error"
                value={`${call.error_code}${call.error_message ? ` — ${call.error_message}` : ""}`}
                valueClassName="text-rose-600"
              />
            )}
          </dl>
        </section>

        <section className="rounded-lg border border-neutral-200 bg-white p-5">
          <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
            Demo
          </h2>
          {call.outcome === "demo_scheduled" && call.demo_booking_id ? (
            <div className="mt-3 space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <Calendar className="h-4 w-4 text-emerald-600" />
                <span className="font-medium">
                  {call.demo_scheduled_at
                    ? format(new Date(call.demo_scheduled_at), "PPPp")
                    : "(time not parsed)"}
                </span>
              </div>
              <div className="text-xs text-neutral-500">
                booking id: <code className="font-mono">{call.demo_booking_id}</code>
              </div>
              {call.demo_meeting_url && (
                <a
                  href={call.demo_meeting_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                >
                  <ExternalLink className="h-3 w-3" />
                  meeting link
                </a>
              )}
            </div>
          ) : call.followup_email_sent ? (
            <p className="mt-3 flex items-center gap-2 text-sm text-neutral-700">
              <Mail className="h-4 w-4" />
              Follow-up email sent.
            </p>
          ) : (
            <p className="mt-3 text-sm text-neutral-400">No demo booked.</p>
          )}
        </section>
      </div>

      {/* Transcript */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Transcript
        </h2>
        {transcriptWithOffsets.length === 0 ? (
          <p className="mt-3 text-xs text-neutral-400">No transcript captured.</p>
        ) : (
          <ol className="mt-3 space-y-2">
            {transcriptWithOffsets.map((t, i) => {
              const active =
                t.offset != null &&
                Math.abs(currentTime - t.offset) < 2;
              const speakerColor =
                t.speaker === "ai"
                  ? "bg-white text-neutral-800 ring-1 ring-neutral-200"
                  : t.speaker === "patient"
                    ? "bg-emerald-600 text-white"
                    : "bg-neutral-200 text-neutral-600 text-[11px]";
              return (
                <li
                  key={i}
                  className={cn(
                    "flex",
                    t.speaker === "ai"
                      ? "justify-start"
                      : t.speaker === "patient"
                        ? "justify-end"
                        : "justify-center",
                  )}
                >
                  <button
                    onClick={() => t.offset != null && seekTo(t.offset)}
                    disabled={t.offset == null || !recUrl}
                    className={cn(
                      "max-w-[78%] rounded-lg px-3 py-1.5 text-sm text-left",
                      speakerColor,
                      active && "ring-2 ring-amber-400",
                      t.offset != null && recUrl && "cursor-pointer",
                    )}
                  >
                    {t.text}
                    {t.offset != null && (
                      <span className="ml-2 text-[10px] opacity-60">
                        {formatOffset(t.offset)}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string | null | undefined;
  valueClassName?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <dt className="min-w-[120px] text-xs uppercase text-neutral-500">{label}</dt>
      <dd
        className={cn(
          "flex-1 text-sm text-neutral-800",
          !value && "text-neutral-400",
          valueClassName,
        )}
      >
        {value ?? "—"}
      </dd>
    </div>
  );
}

function formatOffset(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function ScoreRow({ label, v }: { label: string; v: number }) {
  const color =
    v >= 8 ? "bg-emerald-500" : v >= 5 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2 text-neutral-600">
      <span className="w-24 text-[11px] uppercase">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-100">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${v * 10}%` }} />
      </div>
      <span className="w-6 text-right tabular-nums">{v}</span>
    </div>
  );
}

function NoteList({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: "amber" | "rose" | "blue";
}) {
  const accent = {
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    rose: "border-rose-200 bg-rose-50 text-rose-900",
    blue: "border-blue-200 bg-blue-50 text-blue-900",
  }[tone];
  return (
    <div>
      <div className="mb-1 text-[11px] uppercase text-neutral-500">{label}</div>
      <ul className={cn("space-y-1 rounded-md border px-3 py-2 text-xs", accent)}>
        {items.map((t, i) => (
          <li key={i}>• {t}</li>
        ))}
      </ul>
    </div>
  );
}
