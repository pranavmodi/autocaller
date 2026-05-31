"use client";

/**
 * Global persisted operator notifications.
 *
 * Polls durable notification rows and exposes them as a non-blocking action
 * center so the operator can keep using the app while reviewing drafts.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BellRing,
  CheckCircle2,
  ExternalLink,
  Inbox,
  Mail,
  PanelRightClose,
  PanelRightOpen,
  PauseCircle,
  Send,
  X,
} from "lucide-react";
import {
  acknowledgeOperatorNotification,
  getPendingOperatorNotifications,
  previewSequence,
  sendOperatorNotificationDraft,
  type OperatorNotification,
} from "@/lib/api";

const notificationQueryKey = ["operator-notifications-pending"] as const;

function shortDate(value: string | null | undefined) {
  if (!value) return null;
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

export function OperatorNotificationPopup() {
  const qc = useQueryClient();
  const pending = useQuery({
    queryKey: notificationQueryKey,
    queryFn: () => getPendingOperatorNotifications(),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const ack = useMutation({
    mutationFn: (id: number) => acknowledgeOperatorNotification(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: notificationQueryKey }),
  });
  const sendDraft = useMutation({
    mutationFn: (args: { id: number; subject: string; body: string }) =>
      sendOperatorNotificationDraft(args.id, {
        subject: args.subject,
        body: args.body,
        sent_by: "operator",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: notificationQueryKey }),
  });

  const queue = pending.data?.pending ?? [];
  const [isOpen, setIsOpen] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [dismissedToastId, setDismissedToastId] = useState<number | null>(null);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");

  const current = useMemo(() => {
    if (queue.length === 0) return undefined;
    return queue.find((item) => item.id === activeId) ?? queue[0];
  }, [activeId, queue]);
  const shouldComposeDraft = Boolean(
    current?.notification_type === "lead_sequence_email_approval" &&
      !stringValue(current.suggested_action?.draft_body) &&
      stringValue(current.context?.contact_id),
  );
  const draftPreview = useQuery({
    queryKey: [
      "operator-notification-draft-preview",
      current?.id,
      current?.context?.contact_id,
      current?.context?.template_key,
    ],
    queryFn: async () => {
      const steps = await previewSequence(
        stringValue(current?.context?.contact_id),
        stringValue(current?.context?.template_key) || undefined,
      );
      return steps[0];
    },
    enabled: shouldComposeDraft,
    staleTime: 0,
    retry: false,
  });

  const latest = queue[0];
  const showToast = Boolean(latest && !isOpen && dismissedToastId !== latest.id);

  useEffect(() => {
    if (queue.length === 0) {
      setActiveId(null);
      setIsOpen(false);
      return;
    }
    if (!current) {
      setActiveId(queue[0].id);
    }
  }, [current, queue]);

  const lastChimedId = useRef<number | null>(null);
  useEffect(() => {
    if (!latest) return;
    if (lastChimedId.current === latest.id) return;
    lastChimedId.current = latest.id;
    setDismissedToastId(null);
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
  }, [latest]);

  useEffect(() => {
    if (!current) {
      setDraftSubject("");
      setDraftBody("");
      return;
    }
    setDraftSubject(
      stringValue(current.suggested_action?.draft_subject) ||
        stringValue(current.stimulus?.subject),
    );
    setDraftBody(stringValue(current.suggested_action?.draft_body));
  }, [current?.id]);

  useEffect(() => {
    if (!draftPreview.data || !current) return;
    if (current.id !== activeId) return;
    setDraftSubject(draftPreview.data.subject);
    setDraftBody(draftPreview.data.body);
  }, [activeId, current, draftPreview.data]);

  if (queue.length === 0 || !latest) return null;

  return (
    <>
      {showToast && (
        <div className="fixed bottom-24 right-4 z-[980] w-[calc(100vw-2rem)] max-w-sm rounded-lg border border-neutral-200 bg-white shadow-xl md:bottom-24 md:right-6">
          <div className="flex items-start gap-3 p-4">
            <span className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700">
              <BellRing className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="line-clamp-2 text-sm font-semibold text-neutral-900">
                {latest.title}
              </div>
              <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-neutral-600">
                {latest.body}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Link
                  href={`/actions?notification=${latest.id}`}
                  onClick={() => setDismissedToastId(latest.id)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-neutral-800"
                >
                  <PanelRightOpen className="h-3.5 w-3.5" />
                  Review
                </Link>
                <button
                  type="button"
                  onClick={() => setDismissedToastId(latest.id)}
                  className="rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-50"
                >
                  Later
                </button>
              </div>
            </div>
            <button
              type="button"
              aria-label="Dismiss notification toast"
              onClick={() => setDismissedToastId(latest.id)}
              className="rounded-md p-1 text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-900"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      <Link
        href="/actions"
        onClick={() => setDismissedToastId(latest.id)}
        className="fixed bottom-4 right-4 z-[970] inline-flex h-12 items-center gap-2 rounded-full border border-neutral-200 bg-white px-4 text-sm font-semibold text-neutral-900 shadow-xl transition hover:bg-neutral-50 md:bottom-6 md:right-6"
        aria-label="Open operator action center"
      >
        <span className="relative rounded-full bg-neutral-900 p-2 text-white">
          <Inbox className="h-4 w-4" />
          <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-amber-500 px-1 text-center text-[10px] font-bold leading-5 text-white">
            {queue.length}
          </span>
        </span>
        Actions
      </Link>
    </>
  );
}

function OperatorActionDrawer({
  queue,
  current,
  draftSubject,
  draftBody,
  ackPending,
  sendPending,
  sendFailed,
  draftLoading,
  draftFailed,
  onClose,
  onSelect,
  onDraftSubjectChange,
  onDraftBodyChange,
  onAcknowledge,
  onSendDraft,
}: {
  queue: OperatorNotification[];
  current: OperatorNotification;
  draftSubject: string;
  draftBody: string;
  ackPending: boolean;
  sendPending: boolean;
  sendFailed: boolean;
  draftLoading: boolean;
  draftFailed: boolean;
  onClose: () => void;
  onSelect: (notification: OperatorNotification) => void;
  onDraftSubjectChange: (value: string) => void;
  onDraftBodyChange: (value: string) => void;
  onAcknowledge: () => void;
  onSendDraft: () => void;
}) {
  const stimulus = current.stimulus ?? {};
  const context = current.context ?? {};
  const action = current.suggested_action ?? {};
  const fromLine =
    stimulus.from_name && stimulus.from_email
      ? `${stimulus.from_name} <${stimulus.from_email}>`
      : String(stimulus.from_email || stimulus.from_name || "");
  const receivedAt = shortDate(stringValue(stimulus.received_at));
  const createdAt = shortDate(current.created_at);
  const isSequenceApproval =
    current.notification_type === "lead_sequence_email_approval";
  const actionAngle = stringValue(action.angle);
  const actionCta = stringValue(action.cta);
  const actionBlogLink = stringValue(action.blog_link_used);
  const actionComposerModel = stringValue(action.composer_model);
  const canSendDraft = Boolean(draftBody.trim()) && !draftLoading;
  const openAction = () => {
    const href = stringValue(action.href) || "/lead-gen";
    window.location.assign(href);
  };

  return (
    <aside
      className="fixed bottom-0 right-0 top-0 z-[990] flex w-full max-w-[680px] flex-col border-l border-neutral-200 bg-white shadow-2xl sm:w-[92vw] lg:w-[680px]"
      aria-label="Operator action center"
    >
      <div className="flex items-center justify-between gap-3 border-b border-neutral-200 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            <BellRing className="h-3.5 w-3.5" />
            Operator Actions
          </div>
          <h2 className="mt-1 truncate text-base font-semibold text-neutral-950">
            {current.title}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-neutral-200 text-neutral-600 transition hover:bg-neutral-50 hover:text-neutral-950"
          aria-label="Close operator action center"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[220px_minmax(0,1fr)]">
        <div className="max-h-44 overflow-y-auto border-b border-neutral-200 bg-neutral-50 p-2 lg:max-h-none lg:border-b-0 lg:border-r">
          <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
            Pending {queue.length}
          </div>
          <div className="flex gap-2 overflow-x-auto lg:block lg:space-y-1 lg:overflow-visible">
            {queue.map((notification) => (
              <button
                key={notification.id}
                type="button"
                onClick={() => onSelect(notification)}
                className={`min-w-52 rounded-md border px-3 py-2 text-left transition lg:w-full ${
                  notification.id === current.id
                    ? "border-neutral-900 bg-white shadow-sm"
                    : "border-transparent bg-transparent hover:border-neutral-200 hover:bg-white"
                }`}
              >
                <div className="truncate text-xs font-semibold text-neutral-900">
                  {notification.title}
                </div>
                <div className="mt-1 truncate text-[11px] text-neutral-500">
                  {stringValue(notification.context?.firm_name) ||
                    stringValue(notification.context?.contact_email) ||
                    stringValue(notification.stimulus?.from_email) ||
                    notification.notification_type}
                </div>
                <div className="mt-1 text-[10px] uppercase tracking-wide text-neutral-400">
                  {notification.priority || "normal"}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 overflow-y-auto">
          <div className="space-y-4 px-4 py-4 text-sm">
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
                <dd className="text-neutral-900">
                  {stimulus.subject || "No subject"}
                </dd>
                {(receivedAt || createdAt) && (
                  <>
                    <dt className="text-neutral-500">
                      {receivedAt ? "Received" : "Created"}
                    </dt>
                    <dd className="text-neutral-900">{receivedAt || createdAt}</dd>
                  </>
                )}
              </dl>
              <blockquote className="mt-3 max-h-36 overflow-y-auto whitespace-pre-wrap rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-800">
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
                  <dd className="text-neutral-900">
                    {context.contact_name || "Unknown"}
                  </dd>
                  <dt className="text-neutral-500">Email</dt>
                  <dd className="break-all font-mono text-neutral-800">
                    {context.contact_email || stimulus.from_email || "Unknown"}
                  </dd>
                  <dt className="text-neutral-500">Status</dt>
                  <dd className="inline-flex items-center gap-1 text-neutral-900">
                    <PauseCircle className="h-3.5 w-3.5 text-amber-600" />
                    {context.sequence_status || current.status || "unknown"}
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
                {(actionAngle || actionCta || actionBlogLink || actionComposerModel) && (
                  <dl className="mt-3 grid grid-cols-[72px_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
                    {actionAngle && (
                      <>
                        <dt className="text-neutral-500">Angle</dt>
                        <dd className="break-words text-neutral-800">{actionAngle}</dd>
                      </>
                    )}
                    {actionCta && (
                      <>
                        <dt className="text-neutral-500">CTA</dt>
                        <dd className="break-words text-neutral-800">{actionCta}</dd>
                      </>
                    )}
                    {actionBlogLink && (
                      <>
                        <dt className="text-neutral-500">Blog</dt>
                        <dd className="break-all text-neutral-800">{actionBlogLink}</dd>
                      </>
                    )}
                    {actionComposerModel && (
                      <>
                        <dt className="text-neutral-500">Model</dt>
                        <dd className="break-all text-neutral-800">
                          {actionComposerModel}
                        </dd>
                      </>
                    )}
                  </dl>
                )}
              </div>
            </section>

            {(isSequenceApproval || action.draft_subject || action.draft_body || draftBody) && (
              <section className="rounded-lg border border-neutral-200 p-3">
                <div className="mb-2 text-xs font-semibold uppercase text-neutral-500">
                  Draft
                </div>
                {draftLoading ? (
                  <div className="flex items-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-4 text-xs text-neutral-600">
                    <PauseCircle className="h-4 w-4 animate-pulse" />
                    Generating draft...
                  </div>
                ) : draftFailed ? (
                  <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                    Could not generate this draft. Check backend logs.
                  </div>
                ) : (
                  <>
                    <input
                      value={draftSubject}
                      onChange={(e) => onDraftSubjectChange(e.target.value)}
                      className="mb-2 w-full rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium text-neutral-900 outline-none focus:border-neutral-400"
                    />
                    <textarea
                      value={draftBody}
                      onChange={(e) => onDraftBodyChange(e.target.value)}
                      className="min-h-48 w-full resize-y rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-800 outline-none focus:border-neutral-400"
                    />
                  </>
                )}
                <p className="mt-2 text-[11px] leading-relaxed text-neutral-500">
                  {isSequenceApproval
                    ? "Opening the action generates the draft; approval sends the edited draft and advances the paused outreach run."
                    : "Sends to the inbound sender in the same email thread using reply headers."}
                </p>
              </section>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap justify-end gap-2 border-t border-neutral-200 bg-neutral-50 px-4 py-3">
        {sendFailed && (
          <div className="mr-auto max-w-xs text-xs text-red-600">
            Send failed. Check Resend/SMTP settings or try from Zoho manually.
          </div>
        )}
        <button
          type="button"
          onClick={onAcknowledge}
          disabled={ackPending}
          className="inline-flex items-center gap-2 rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 transition hover:bg-neutral-100 disabled:opacity-60"
        >
          <CheckCircle2 className="h-4 w-4" />
          {ackPending ? "Acknowledging..." : "Acknowledge"}
        </button>
        <button
          type="button"
          onClick={openAction}
          className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-neutral-800"
        >
          <ExternalLink className="h-4 w-4" />
          Open action
        </button>
        {canSendDraft && (
          <button
            type="button"
            onClick={onSendDraft}
            disabled={sendPending || ackPending || !canSendDraft}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-60"
          >
            <Send className="h-4 w-4" />
            {sendPending ? "Sending..." : isSequenceApproval ? "Approve & send" : "Send draft"}
          </button>
        )}
      </div>
    </aside>
  );
}
