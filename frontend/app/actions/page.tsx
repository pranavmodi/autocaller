"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Inbox,
  Loader2,
  Mail,
  RefreshCw,
} from "lucide-react";
import {
  getPendingOperatorNotifications,
  recordProductTrace,
  type OperatorNotification,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const ACTIONS_PENDING_LIMIT = 50;
const ACTIONS_QUERY_KEY = ["operator-notifications-pending", ACTIONS_PENDING_LIMIT] as const;

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
  const explicitHref = stringValue(notification.suggested_action?.href);
  if (
    notification.notification_type === "lead_sequence_email_approval" ||
    notification.notification_type === "lead_email_reply"
  ) {
    const params = new URLSearchParams();
    params.set("notification", String(notification.id));
    const batchId = stringValue(notification.context?.batch_id);
    const batchItemId = stringValue(notification.context?.batch_item_id);
    const contactId = stringValue(notification.context?.contact_id);
    if (batchId) params.set("batch", batchId);
    if (batchItemId) params.set("item", batchItemId);
    if (contactId) params.set("contact", contactId);
    return `/lead-gen?${params.toString()}`;
  }
  return explicitHref || "/lead-gen";
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
    <Suspense
      fallback={
        <div className="flex items-center gap-2 px-4 py-10 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading actions...
        </div>
      }
    >
      <ActionsPageContent />
    </Suspense>
  );
}

function ActionsPageContent() {
  const searchParams = useSearchParams();
  const requestedId = Number(searchParams.get("notification") || 0) || null;
  const [selectedId, setSelectedId] = useState<number | null>(requestedId);
  const viewedActionIds = useRef<Set<number>>(new Set());

  const pending = useQuery({
    queryKey: ACTIONS_QUERY_KEY,
    queryFn: () => getPendingOperatorNotifications(ACTIONS_PENDING_LIMIT),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const queue = useMemo(() => pending.data?.pending ?? [], [pending.data?.pending]);
  const current = useMemo(() => {
    if (queue.length === 0) return undefined;
    return queue.find((item) => item.id === selectedId) ?? queue[0];
  }, [queue, selectedId]);

  useEffect(() => {
    if (requestedId) setSelectedId(requestedId);
  }, [requestedId]);

  useEffect(() => {
    if (!current && queue.length > 0) {
      setSelectedId(queue[0].id);
    }
  }, [current, queue]);

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

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
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
          pointers to the right execution surface
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
            className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
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
          <div className="grid min-h-[640px] grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)]">
            <ActionList
              queue={queue}
              selectedId={current?.id ?? null}
              onSelect={setSelectedId}
            />
            {current && (
              <ActionDetail
                notification={current}
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
  onOpenLinkedPage,
}: {
  notification: OperatorNotification;
  onOpenLinkedPage: () => void;
}) {
  const stimulus = notification.stimulus ?? {};
  const context = notification.context ?? {};
  const action = notification.suggested_action ?? {};
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
              Execution location
            </div>
            <p className="text-sm leading-relaxed text-neutral-700">
              Email review, editing, and sending happens in Cybernetic Lead Gen.
              This page only points to the work item so execution stays in the
              workflow that owns the outreach run.
            </p>
            {(action.draft_subject || action.draft_body || stimulus.text_excerpt) && (
              <div className="mt-3 rounded-md border border-neutral-200 bg-neutral-50 p-3">
                {stringValue(action.draft_subject || stimulus.subject) && (
                  <div className="text-sm font-medium text-neutral-900">
                    {stringValue(action.draft_subject || stimulus.subject)}
                  </div>
                )}
                {stringValue(action.draft_body || stimulus.text_excerpt) && (
                  <pre className="mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap font-sans text-xs leading-relaxed text-neutral-700">
                    {stringValue(action.draft_body || stimulus.text_excerpt)}
                  </pre>
                )}
              </div>
            )}
          </section>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t border-neutral-100 pt-4">
          <Link
            href={linkedHref(notification)}
            onClick={onOpenLinkedPage}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            <ExternalLink className="h-4 w-4" />
            Open where this is executed
          </Link>
        </div>
      </div>
    </div>
  );
}
