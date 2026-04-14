"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import { ArrowLeft, Calendar, Mail, ExternalLink } from "lucide-react";
import { getCall, recordingUrl } from "@/lib/api";
import { OutcomePill } from "@/components/OutcomePill";
import { cn } from "@/lib/utils";

interface Props {
  params: { id: string };
}

export default function CallDetailPage({ params }: Props) {
  const callId = params.id;
  const { data: call, isLoading } = useQuery({
    queryKey: ["call", callId],
    queryFn: () => getCall(callId),
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
            <h1 className="text-xl font-semibold">{call.patient_name || "(unknown)"}</h1>
            <p className="text-sm text-neutral-500">
              {call.firm_name || "—"}
              {call.lead_state ? ` · ${call.lead_state}` : ""}
              {" · "}
              {call.phone}
            </p>
            <p className="mt-1 text-xs text-neutral-400">
              {startedAt ? format(startedAt, "PPp") : "—"} · {call.duration_seconds}s
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
