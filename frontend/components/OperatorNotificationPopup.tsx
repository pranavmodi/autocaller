"use client";

/**
 * Global persisted operator notifications.
 *
 * This mirrors the consult-booking popup pattern: poll pending rows, show one
 * modal at a time, and acknowledge server-side so the popup does not repeat
 * after refreshes or daemon restarts.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, ExternalLink, Mail, PauseCircle, Send } from "lucide-react";
import {
  acknowledgeOperatorNotification,
  getPendingOperatorNotifications,
  sendOperatorNotificationDraft,
  type OperatorNotification,
} from "@/lib/api";

export function OperatorNotificationPopup() {
  const qc = useQueryClient();
  const pending = useQuery({
    queryKey: ["operator-notifications-pending"],
    queryFn: getPendingOperatorNotifications,
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const ack = useMutation({
    mutationFn: (id: number) => acknowledgeOperatorNotification(id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["operator-notifications-pending"] }),
  });
  const sendDraft = useMutation({
    mutationFn: (args: { id: number; subject: string; body: string }) =>
      sendOperatorNotificationDraft(args.id, {
        subject: args.subject,
        body: args.body,
        sent_by: "operator",
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["operator-notifications-pending"] }),
  });

  const queue = pending.data?.pending ?? [];
  const current: OperatorNotification | undefined = queue[0];
  const remaining = queue.length - 1;
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");

  const lastChimedId = useRef<number | null>(null);
  useEffect(() => {
    if (!current) return;
    if (lastChimedId.current === current.id) return;
    lastChimedId.current = current.id;
    try {
      const Ctx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new Ctx();
      const beep = (freq: number, startOffset: number, dur: number) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = "triangle";
        o.frequency.value = freq;
        o.connect(g);
        g.connect(ctx.destination);
        const t0 = ctx.currentTime + startOffset;
        g.gain.setValueAtTime(0, t0);
        g.gain.linearRampToValueAtTime(0.22, t0 + 0.02);
        g.gain.linearRampToValueAtTime(0, t0 + dur);
        o.start(t0);
        o.stop(t0 + dur + 0.02);
      };
      beep(740, 0, 0.13);
      beep(988, 0.16, 0.18);
    } catch {
      // AudioContext may be blocked before user gesture.
    }
  }, [current]);

  useEffect(() => {
    if (!current) {
      setDraftSubject("");
      setDraftBody("");
      return;
    }
    setDraftSubject(String(current.suggested_action?.draft_subject || current.stimulus?.subject || ""));
    setDraftBody(String(current.suggested_action?.draft_body || ""));
  }, [current?.id]);

  if (!current) return null;

  const stimulus = current.stimulus ?? {};
  const context = current.context ?? {};
  const action = current.suggested_action ?? {};
  const priorityClass =
    current.priority === "high"
      ? "border-amber-300 bg-amber-600"
      : "border-sky-300 bg-sky-600";
  const fromLine =
    stimulus.from_name && stimulus.from_email
      ? `${stimulus.from_name} <${stimulus.from_email}>`
      : String(stimulus.from_email || stimulus.from_name || "");
  const receivedAt = stimulus.received_at
    ? new Date(String(stimulus.received_at)).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : null;

  const acknowledge = () => ack.mutate(current.id);
  const sendCurrentDraft = () =>
    sendDraft.mutate({
      id: current.id,
      subject: draftSubject,
      body: draftBody,
    });
  const openAction = () => {
    const href = typeof action.href === "string" ? action.href : "/lead-gen";
    window.location.assign(href);
  };

  return (
    <div
      className="fixed inset-0 z-[990] flex items-center justify-center bg-black/60 px-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="operator-notification-title"
    >
      <div className="max-h-[88vh] w-full max-w-2xl overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-2xl">
        <div className={`border-b px-5 py-3 text-white ${priorityClass}`}>
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <BellRing className="h-4 w-4 flex-none" />
              <h2
                id="operator-notification-title"
                className="truncate text-sm font-semibold uppercase tracking-wide"
              >
                {current.title}
              </h2>
            </div>
            {remaining > 0 && (
              <span className="flex-none rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-medium">
                +{remaining} more
              </span>
            )}
          </div>
        </div>

        <div className="max-h-[calc(88vh-116px)] space-y-4 overflow-y-auto px-5 py-4 text-sm">
          <section className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-neutral-500">
              <Mail className="h-3.5 w-3.5" />
              Stimulus
            </div>
            <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-neutral-500">From</dt>
              <dd className="break-all font-medium text-neutral-900">
                {fromLine || stimulus.from_email || "Unknown"}
              </dd>
              <dt className="text-neutral-500">Subject</dt>
              <dd className="text-neutral-900">{stimulus.subject || "No subject"}</dd>
              {receivedAt && (
                <>
                  <dt className="text-neutral-500">Received</dt>
                  <dd className="text-neutral-900">{receivedAt}</dd>
                </>
              )}
            </dl>
            <blockquote className="mt-3 max-h-32 overflow-y-auto whitespace-pre-wrap rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-800">
              {stimulus.text_excerpt || current.body || "No message excerpt available."}
            </blockquote>
          </section>

          <section className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-neutral-200 p-3">
              <div className="mb-2 text-xs font-semibold uppercase text-neutral-500">
                Lead Context
              </div>
              <dl className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
                <dt className="text-neutral-500">Firm</dt>
                <dd className="font-medium text-neutral-900">
                  {context.firm_name || "Unknown"}
                </dd>
                <dt className="text-neutral-500">Contact</dt>
                <dd className="text-neutral-900">{context.contact_name || "Unknown"}</dd>
                <dt className="text-neutral-500">Email</dt>
                <dd className="break-all font-mono text-neutral-800">
                  {context.contact_email || "Unknown"}
                </dd>
                <dt className="text-neutral-500">Sequence</dt>
                <dd className="inline-flex items-center gap-1 text-neutral-900">
                  <PauseCircle className="h-3.5 w-3.5 text-amber-600" />
                  {context.sequence_status || "unknown"}
                </dd>
              </dl>
            </div>

            <div className="rounded-lg border border-neutral-200 p-3">
              <div className="mb-2 text-xs font-semibold uppercase text-neutral-500">
                Suggested Action
              </div>
              <div className="text-sm font-semibold text-neutral-900">
                {action.label || action.kind || "Review manually"}
              </div>
              <div className="mt-1 text-xs text-neutral-600">
                Outcome: {action.outcome || "unknown"}
                {typeof action.confidence === "number" ? ` (${action.confidence}%)` : ""}
              </div>
              {typeof action.reasoning === "string" && action.reasoning && (
                <p className="mt-2 text-xs leading-relaxed text-neutral-700">
                  {action.reasoning}
                </p>
              )}
            </div>
          </section>

          {(action.draft_subject || action.draft_body) && (
            <section className="rounded-lg border border-neutral-200 p-3">
              <div className="mb-2 text-xs font-semibold uppercase text-neutral-500">
                Draft Response
              </div>
              <input
                value={draftSubject}
                onChange={(e) => setDraftSubject(e.target.value)}
                className="mb-2 w-full rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium text-neutral-900 outline-none focus:border-neutral-400"
              />
              <textarea
                value={draftBody}
                onChange={(e) => setDraftBody(e.target.value)}
                className="min-h-40 w-full resize-y rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-800 outline-none focus:border-neutral-400"
              />
              <p className="mt-2 text-[11px] leading-relaxed text-neutral-500">
                Sends to the inbound sender in the same email thread using reply headers.
              </p>
            </section>
          )}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-neutral-200 bg-neutral-50 px-5 py-3">
          {sendDraft.isError && (
            <div className="mr-auto max-w-xs text-xs text-red-600">
              Send failed. Check Resend/SMTP settings or try from Zoho manually.
            </div>
          )}
          <button
            type="button"
            onClick={acknowledge}
            disabled={ack.isPending}
            className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 transition hover:bg-neutral-100 disabled:opacity-60"
          >
            {ack.isPending ? "Acknowledging..." : "Acknowledge"}
          </button>
          <button
            type="button"
            onClick={openAction}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-neutral-800"
          >
            <ExternalLink className="h-4 w-4" />
            Open action
          </button>
          {draftBody && (
            <button
              type="button"
              onClick={sendCurrentDraft}
              disabled={sendDraft.isPending || ack.isPending || !draftBody.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
            >
              <Send className="h-4 w-4" />
              {sendDraft.isPending ? "Sending..." : "Send draft"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
