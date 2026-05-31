"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Inbox,
  Loader2,
  Mail,
  RefreshCw,
  Send,
} from "lucide-react";
import {
  acknowledgeOperatorNotification,
  getPendingOperatorNotifications,
  newProductTraceId,
  previewSequence,
  recordProductTrace,
  sendOperatorNotificationDraft,
  type OperatorNotification,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const ACTIONS_QUERY_KEY = ["operator-notifications-pending"] as const;

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function shortDate(value: string | null | undefined) {
  if (!value) return "";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function actionCategory(notification: OperatorNotification) {
  if (notification.notification_type === "seo_action") {
    return "SEO/AEO";
  }
  if (notification.notification_type === "lead_sequence_email_approval") {
    return "Email approval";
  }
  if (notification.notification_type === "lead_email_reply") {
    return "Email reply";
  }
  return stringValue(notification.suggested_action?.kind) || "Manual action";
}

function linkedHref(notification: OperatorNotification) {
  return stringValue(notification.suggested_action?.href) || "/lead-gen";
}

function isEmailAction(notification: OperatorNotification) {
  return (
    notification.notification_type === "lead_sequence_email_approval" ||
    notification.notification_type === "lead_email_reply" ||
    Boolean(notification.suggested_action?.draft_body)
  );
}

function actionTraceContext(notification: OperatorNotification) {
  return {
    notification_id: notification.id,
    notification_type: notification.notification_type,
    source_type: notification.source_type,
    source_id: notification.source_id,
    priority: notification.priority,
    title: notification.title,
    status: notification.status,
    contact_id: stringValue(notification.context?.contact_id),
    contact_name: stringValue(notification.context?.contact_name),
    contact_email:
      stringValue(notification.context?.contact_email) ||
      stringValue(notification.stimulus?.from_email),
    firm_name: stringValue(notification.context?.firm_name),
    page_url: stringValue(notification.context?.page_url || notification.stimulus?.page_url),
    action_kind: stringValue(notification.suggested_action?.kind),
  };
}

export default function ActionsPage() {
  return (
    <Suspense fallback={<ActionsPageShell />}>
      <ActionsPageContent />
    </Suspense>
  );
}

function ActionsPageShell() {
  return (
    <div className="mx-auto min-w-0 max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-900">Actions</h1>
        <span className="text-xs text-neutral-400">
          review, edit, send, mark done
        </span>
      </div>
      <section className="rounded-xl border border-neutral-200 bg-white px-4 py-10 text-sm text-neutral-500">
        Loading actions...
      </section>
    </div>
  );
}

function ActionsPageContent() {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const requestedId = Number(searchParams.get("notification") || 0) || null;
  const [selectedId, setSelectedId] = useState<number | null>(requestedId);
  const [removedIds, setRemovedIds] = useState<Set<number>>(() => new Set());
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const viewedActionIds = useRef<Set<number>>(new Set());
  const generatedDraftKeys = useRef<Set<string>>(new Set());
  const draftBaseline = useRef<{ id: number; subject: string; body: string } | null>(null);

  const pending = useQuery({
    queryKey: ACTIONS_QUERY_KEY,
    queryFn: () => getPendingOperatorNotifications(50),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const queue = useMemo(
    () => (pending.data?.pending ?? []).filter((item) => !removedIds.has(item.id)),
    [pending.data?.pending, removedIds],
  );
  const current = useMemo(() => {
    if (queue.length === 0) return undefined;
    return queue.find((item) => item.id === selectedId) ?? queue[0];
  }, [queue, selectedId]);

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

  useEffect(() => {
    if (requestedId) setSelectedId(requestedId);
  }, [requestedId]);

  useEffect(() => {
    if (!current && queue.length > 0) {
      setSelectedId(queue[0].id);
    }
  }, [current, queue]);

  useEffect(() => {
    if (!current) {
      setDraftSubject("");
      setDraftBody("");
      draftBaseline.current = null;
      return;
    }
    const subject =
      stringValue(current.suggested_action?.draft_subject) ||
      stringValue(current.stimulus?.subject);
    const body = stringValue(current.suggested_action?.draft_body);
    setDraftSubject(subject);
    setDraftBody(body);
    draftBaseline.current = { id: current.id, subject, body };
  }, [current?.id]);

  useEffect(() => {
    if (!draftPreview.data || !current) return;
    const generatedKey = `${current.id}:${draftPreview.data.subject}:${draftPreview.data.body}`;
    setDraftSubject(draftPreview.data.subject);
    setDraftBody(draftPreview.data.body);
    draftBaseline.current = {
      id: current.id,
      subject: draftPreview.data.subject,
      body: draftPreview.data.body,
    };
    if (generatedDraftKeys.current.has(generatedKey)) return;
    generatedDraftKeys.current.add(generatedKey);
    recordProductTrace({
      event_type: "email_draft_generated",
      surface: "actions",
      entity_type: "operator_notification",
      entity_id: String(current.id),
      output: {
        subject: draftPreview.data.subject,
        body: draftPreview.data.body,
        reasoning: draftPreview.data.reasoning,
        angle: draftPreview.data.angle,
        cta: draftPreview.data.cta,
        blog_link_used: draftPreview.data.blog_link_used,
        model: draftPreview.data.model,
      },
      context: actionTraceContext(current),
      metadata: { source: "previewSequence" },
    });
  }, [current, draftPreview.data]);

  useEffect(() => {
    if (!current || viewedActionIds.current.has(current.id)) return;
    viewedActionIds.current.add(current.id);
    recordProductTrace({
      event_type: "action_opened",
      surface: "actions",
      entity_type: "operator_notification",
      entity_id: String(current.id),
      input: {
        stimulus: current.stimulus ?? {},
        suggested_action: current.suggested_action ?? {},
      },
      context: actionTraceContext(current),
    });
  }, [current]);

  const recordDraftEdited = () => {
    if (!current || !isEmailAction(current)) return;
    const baseline = draftBaseline.current;
    if (!baseline || baseline.id !== current.id) return;
    if (baseline.subject === draftSubject && baseline.body === draftBody) return;
    recordProductTrace({
      event_type: "email_draft_edited",
      surface: "actions",
      entity_type: "operator_notification",
      entity_id: String(current.id),
      input: {
        subject: baseline.subject,
        body: baseline.body,
      },
      output: {
        subject: draftSubject,
        body: draftBody,
      },
      diff: {
        subject_changed: baseline.subject !== draftSubject,
        body_changed: baseline.body !== draftBody,
        subject_length_before: baseline.subject.length,
        subject_length_after: draftSubject.length,
        body_length_before: baseline.body.length,
        body_length_after: draftBody.length,
      },
      context: actionTraceContext(current),
    });
    draftBaseline.current = { id: current.id, subject: draftSubject, body: draftBody };
  };

  const removeFromList = (id: number) => {
    setRemovedIds((prev) => new Set([...Array.from(prev), id]));
    const next = queue.find((item) => item.id !== id);
    setSelectedId(next?.id ?? null);
  };

  const acknowledge = useMutation({
    mutationFn: (args: { id: number; traceId: string }) =>
      acknowledgeOperatorNotification(args.id, { traceId: args.traceId }),
    onSuccess: (_data, args) => {
      recordProductTrace({
        trace_id: args.traceId,
        event_type: "action_marked_done",
        surface: "actions",
        entity_type: "operator_notification",
        entity_id: String(args.id),
        output: { status: "acknowledged" },
      });
      removeFromList(args.id);
      qc.invalidateQueries({ queryKey: ACTIONS_QUERY_KEY });
    },
    onError: (error, args) => {
      recordProductTrace({
        trace_id: args.traceId,
        event_type: "action_mark_done_failed",
        surface: "actions",
        entity_type: "operator_notification",
        entity_id: String(args.id),
        output: { error: error instanceof Error ? error.message : String(error) },
      });
    },
  });
  const sendDraft = useMutation({
    mutationFn: (args: { id: number; subject: string; body: string; traceId: string }) =>
      sendOperatorNotificationDraft(
        args.id,
        {
          subject: args.subject,
          body: args.body,
          sent_by: "operator",
        },
        { traceId: args.traceId },
      ),
    onSuccess: (_data, args) => {
      recordProductTrace({
        trace_id: args.traceId,
        event_type: "email_sent",
        surface: "actions",
        entity_type: "operator_notification",
        entity_id: String(args.id),
        input: {
          subject: args.subject,
          body: args.body,
        },
        output: { status: "sent" },
      });
      removeFromList(args.id);
      qc.invalidateQueries({ queryKey: ACTIONS_QUERY_KEY });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
    },
    onError: (error, args) => {
      recordProductTrace({
        trace_id: args.traceId,
        event_type: "email_send_failed",
        surface: "actions",
        entity_type: "operator_notification",
        entity_id: String(args.id),
        input: {
          subject: args.subject,
          body: args.body,
        },
        output: { error: error instanceof Error ? error.message : String(error) },
      });
    },
  });

  const markDone = () => {
    if (!current) return;
    const traceId = newProductTraceId();
    recordProductTrace({
      trace_id: traceId,
      event_type: "action_mark_done_requested",
      surface: "actions",
      entity_type: "operator_notification",
      entity_id: String(current.id),
      context: actionTraceContext(current),
    });
    acknowledge.mutate({ id: current.id, traceId });
  };

  const requestSendDraft = () => {
    if (!current) return;
    recordDraftEdited();
    const traceId = newProductTraceId();
    recordProductTrace({
      trace_id: traceId,
      event_type: "email_send_requested",
      surface: "actions",
      entity_type: "operator_notification",
      entity_id: String(current.id),
      input: {
        subject: draftSubject,
        body: draftBody,
      },
      context: actionTraceContext(current),
    });
    sendDraft.mutate({
      id: current.id,
      subject: draftSubject,
      body: draftBody,
      traceId,
    });
  };

  return (
    <div className="mx-auto min-w-0 max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">Actions</h1>
        <span className="text-xs text-neutral-400">
          review, edit, send, mark done
        </span>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <Inbox className="h-4 w-4 text-neutral-500" />
            <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
              Pending actions
            </h2>
          </div>
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
            {queue.length}
          </span>
          <button
            type="button"
            onClick={() => pending.refetch()}
            disabled={pending.isFetching}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60 sm:ml-auto"
          >
            {pending.isFetching ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Refresh
          </button>
        </div>

        {pending.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-10 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading actions...
          </div>
        ) : queue.length === 0 ? (
          <div className="px-4 py-12 text-center text-sm text-neutral-500">
            No pending actions.
          </div>
        ) : (
          <div className="grid min-h-[640px] min-w-0 grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)]">
            <ActionList
              queue={queue}
              selectedId={current?.id ?? null}
              onSelect={setSelectedId}
            />
            {current && (
              <ActionDetail
                notification={current}
                draftSubject={draftSubject}
                draftBody={draftBody}
                draftLoading={draftPreview.isFetching}
                draftFailed={draftPreview.isError}
                sendPending={sendDraft.isPending}
                sendFailed={sendDraft.isError}
                acknowledgePending={acknowledge.isPending}
                onDraftSubjectChange={setDraftSubject}
                onDraftBodyChange={setDraftBody}
                onDraftBlur={recordDraftEdited}
                onOpenLinkedPage={() =>
                  recordProductTrace({
                    event_type: "action_link_opened",
                    surface: "actions",
                    entity_type: "operator_notification",
                    entity_id: String(current.id),
                    output: { href: linkedHref(current) },
                    context: actionTraceContext(current),
                  })
                }
                onSendDraft={requestSendDraft}
                onMarkDone={markDone}
              />
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function ActionList({
  queue,
  selectedId,
  onSelect,
}: {
  queue: OperatorNotification[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="border-b border-neutral-100 bg-neutral-50 p-2 lg:border-b-0 lg:border-r">
      <div className="space-y-1">
        {queue.map((notification) => (
          <button
            key={notification.id}
            type="button"
            onClick={() => onSelect(notification.id)}
            className={cn(
              "w-full rounded-lg border px-3 py-3 text-left transition",
              notification.id === selectedId
                ? "border-neutral-900 bg-white shadow-sm"
                : "border-transparent hover:border-neutral-200 hover:bg-white",
            )}
          >
            <div className="flex min-w-0 items-start gap-2">
              <span className="mt-0.5 rounded-md bg-neutral-900 p-1.5 text-white">
                {isEmailAction(notification) ? (
                  <Mail className="h-3.5 w-3.5" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="line-clamp-2 text-sm font-semibold text-neutral-900">
                  {notification.title}
                </div>
                <div className="mt-1 truncate text-xs text-neutral-500">
                  {stringValue(notification.context?.firm_name) ||
                    stringValue(notification.context?.contact_email) ||
                    stringValue(notification.context?.page_url) ||
                    stringValue(notification.stimulus?.from_email) ||
                    notification.source_type}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-neutral-600">
                    {actionCategory(notification)}
                  </span>
                  {notification.priority !== "normal" && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                      {notification.priority}
                    </span>
                  )}
                  <span className="text-[11px] text-neutral-400">
                    {shortDate(notification.created_at)}
                  </span>
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function ActionDetail({
  notification,
  draftSubject,
  draftBody,
  draftLoading,
  draftFailed,
  sendPending,
  sendFailed,
  acknowledgePending,
  onDraftSubjectChange,
  onDraftBodyChange,
  onDraftBlur,
  onOpenLinkedPage,
  onSendDraft,
  onMarkDone,
}: {
  notification: OperatorNotification;
  draftSubject: string;
  draftBody: string;
  draftLoading: boolean;
  draftFailed: boolean;
  sendPending: boolean;
  sendFailed: boolean;
  acknowledgePending: boolean;
  onDraftSubjectChange: (value: string) => void;
  onDraftBodyChange: (value: string) => void;
  onDraftBlur: () => void;
  onOpenLinkedPage: () => void;
  onSendDraft: () => void;
  onMarkDone: () => void;
}) {
  const stimulus = notification.stimulus ?? {};
  const context = notification.context ?? {};
  const action = notification.suggested_action ?? {};
  const canSendDraft = isEmailAction(notification) && Boolean(draftBody.trim()) && !draftLoading;
  const fromLine =
    stimulus.from_name && stimulus.from_email
      ? `${stimulus.from_name} <${stimulus.from_email}>`
      : stringValue(stimulus.from_email || stimulus.from_name);
  const actionAngle = stringValue(action.angle);
  const actionCta = stringValue(action.cta);
  const actionBlogLink = stringValue(action.blog_link_used);
  const actionComposerModel = stringValue(action.composer_model);
  const pageUrl = stringValue(context.page_url || stimulus.page_url);
  const suggestedChange = stringValue(action.suggested_change);

  return (
    <div className="min-w-0">
      <div className="border-b border-neutral-100 px-4 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
            {actionCategory(notification)}
          </span>
          <span className="text-xs text-neutral-400">
            Created {shortDate(notification.created_at) || "unknown"}
          </span>
        </div>
        <h2 className="mt-2 text-lg font-semibold text-neutral-950">
          {notification.title}
        </h2>
        {notification.body && (
          <p className="mt-1 text-sm leading-relaxed text-neutral-600">
            {notification.body}
          </p>
        )}
      </div>

      <div className="space-y-4 px-4 py-4">
        <section className="grid gap-3 xl:grid-cols-2">
          <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Lead or Stimulus
            </div>
            <dl className="grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-neutral-500">Firm</dt>
              <dd className="font-medium text-neutral-900">
                {context.firm_name || "Unknown"}
              </dd>
              <dt className="text-neutral-500">Contact</dt>
              <dd className="text-neutral-900">
                {context.contact_name || stimulus.from_name || "Unknown"}
              </dd>
              <dt className="text-neutral-500">Email</dt>
              <dd className="break-all font-mono text-neutral-800">
                {context.contact_email || stimulus.from_email || "Unknown"}
              </dd>
              {fromLine && (
                <>
                  <dt className="text-neutral-500">From</dt>
                  <dd className="break-all text-neutral-800">{fromLine}</dd>
                </>
              )}
              {stimulus.subject && (
                <>
                  <dt className="text-neutral-500">Subject</dt>
                  <dd className="text-neutral-800">{stimulus.subject}</dd>
                </>
              )}
              {pageUrl && (
                <>
                  <dt className="text-neutral-500">Page</dt>
                  <dd className="break-all text-neutral-800">{pageUrl}</dd>
                </>
              )}
            </dl>
            {(stimulus.text_excerpt || notification.body) && (
              <blockquote className="mt-3 max-h-44 overflow-y-auto whitespace-pre-wrap rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-800">
                {stimulus.text_excerpt || notification.body}
              </blockquote>
            )}
          </div>

          <div className="rounded-lg border border-neutral-200 p-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              Suggested Action
            </div>
            <div className="text-sm font-semibold text-neutral-900">
              {action.label || action.kind || "Review and complete"}
            </div>
            {(action.outcome || action.confidence) && (
              <div className="mt-1 text-xs text-neutral-600">
                Outcome: {action.outcome || "unknown"}
                {typeof action.confidence === "number" ? ` (${action.confidence}%)` : ""}
              </div>
            )}
            {typeof action.reasoning === "string" && action.reasoning && (
              <p className="mt-2 text-xs leading-relaxed text-neutral-700">
                {action.reasoning}
              </p>
            )}
            {suggestedChange && (
              <p className="mt-2 rounded-md border border-neutral-200 bg-neutral-50 p-2 text-xs leading-relaxed text-neutral-800">
                {suggestedChange}
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

        {isEmailAction(notification) && (
          <section className="rounded-lg border border-neutral-200 p-3">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
              <Mail className="h-3.5 w-3.5" />
              Draft
            </div>
            {draftLoading ? (
              <div className="flex items-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-4 text-xs text-neutral-600">
                <Loader2 className="h-4 w-4 animate-spin" />
                Generating draft...
              </div>
            ) : draftFailed ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                Could not generate this draft. Check backend logs.
              </div>
            ) : (
              <>
                <label className="block text-xs font-medium uppercase tracking-wide text-neutral-500">
                  Subject
                  <input
                    value={draftSubject}
                    onChange={(event) => onDraftSubjectChange(event.target.value)}
                    onBlur={onDraftBlur}
                    className="mt-1 w-full rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm font-medium normal-case tracking-normal text-neutral-900 outline-none focus:border-neutral-400"
                  />
                </label>
                <label className="mt-3 block text-xs font-medium uppercase tracking-wide text-neutral-500">
                  Body
                  <textarea
                    value={draftBody}
                    onChange={(event) => onDraftBodyChange(event.target.value)}
                    onBlur={onDraftBlur}
                    rows={14}
                    className="mt-1 w-full resize-y rounded-md border border-neutral-200 bg-white p-3 font-sans text-sm normal-case leading-6 tracking-normal text-neutral-800 outline-none focus:border-neutral-400"
                  />
                </label>
              </>
            )}
          </section>
        )}

        {sendFailed && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            Could not send this email. Check backend logs.
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t border-neutral-100 pt-4">
          <Link
            href={linkedHref(notification)}
            onClick={onOpenLinkedPage}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            <ExternalLink className="h-4 w-4" />
            Open linked page
          </Link>
          <button
            type="button"
            onClick={onMarkDone}
            disabled={acknowledgePending || sendPending}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {acknowledgePending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Mark done
          </button>
          {canSendDraft && (
            <button
              type="button"
              onClick={onSendDraft}
              disabled={sendPending || acknowledgePending || !draftBody.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              {sendPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Send email
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
