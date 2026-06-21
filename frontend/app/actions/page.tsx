"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Clock3,
  ExternalLink,
  Inbox,
  Loader2,
  Mail,
  RefreshCw,
} from "lucide-react";
import {
  getPendingOperatorNotifications,
  listAgentActions,
  recordProductTrace,
  type AgentAction,
  type OperatorNotification,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const ACTIONS_PENDING_LIMIT = 50;
const ACTIONS_QUERY_KEY = ["operator-notifications-pending", ACTIONS_PENDING_LIMIT] as const;
const SCHEDULED_ACTIONS_LIMIT = 50;
const SCHEDULED_ACTIONS_QUERY_KEY = ["agent-actions-scheduled", SCHEDULED_ACTIONS_LIMIT] as const;

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

function istDate(value: string | null | undefined) {
  if (!value) return "";
  return new Date(value).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function relativeSchedule(value: string | null | undefined) {
  if (!value) return "";
  const ms = new Date(value).getTime() - Date.now();
  const absMinutes = Math.max(0, Math.round(Math.abs(ms) / 60_000));
  const hours = Math.floor(absMinutes / 60);
  const minutes = absMinutes % 60;
  const compact = hours ? `${hours}h ${minutes}m` : `${minutes}m`;
  return ms >= 0 ? `in ${compact}` : `${compact} late`;
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
  const searchParams = useSearchParams();
  const requestedId = Number(searchParams.get("notification") || 0) || null;
  const [selectedId, setSelectedId] = useState<number | null>(requestedId);
  const [selectedScheduledId, setSelectedScheduledId] = useState<string | null>(null);
  const viewedActionIds = useRef<Set<number>>(new Set());

  const pending = useQuery({
    queryKey: ACTIONS_QUERY_KEY,
    queryFn: () => getPendingOperatorNotifications(ACTIONS_PENDING_LIMIT),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const scheduled = useQuery({
    queryKey: SCHEDULED_ACTIONS_QUERY_KEY,
    queryFn: () => listAgentActions({ scheduled: true, limit: SCHEDULED_ACTIONS_LIMIT }),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const queue = useMemo(() => pending.data?.pending ?? [], [pending.data?.pending]);
  const scheduledQueue = useMemo(() => scheduled.data?.actions ?? [], [scheduled.data?.actions]);
  const current = useMemo(() => {
    if (queue.length === 0) return undefined;
    return queue.find((item) => item.id === selectedId) ?? queue[0];
  }, [queue, selectedId]);
  const currentScheduled = useMemo(() => {
    if (scheduledQueue.length === 0) return undefined;
    return scheduledQueue.find((item) => item.id === selectedScheduledId) ?? scheduledQueue[0];
  }, [scheduledQueue, selectedScheduledId]);

  useEffect(() => {
    if (requestedId) setSelectedId(requestedId);
  }, [requestedId]);

  useEffect(() => {
    if (!current && queue.length > 0) {
      setSelectedId(queue[0].id);
    }
  }, [current, queue]);

  useEffect(() => {
    if (!currentScheduled && scheduledQueue.length > 0) {
      setSelectedScheduledId(scheduledQueue[0].id);
    }
  }, [currentScheduled, scheduledQueue]);

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
          pointers to the right execution surface
        </span>
      </div>

      <ScheduledActionsPanel
        actions={scheduledQueue}
        selectedId={currentScheduled?.id ?? null}
        selectedAction={currentScheduled}
        isLoading={scheduled.isLoading}
        isFetching={scheduled.isFetching}
        onRefresh={() => scheduled.refetch()}
        onSelect={setSelectedScheduledId}
      />

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

function ScheduledActionsPanel({
  actions,
  selectedId,
  selectedAction,
  isLoading,
  isFetching,
  onRefresh,
  onSelect,
}: {
  actions: AgentAction[];
  selectedId: string | null;
  selectedAction: AgentAction | undefined;
  isLoading: boolean;
  isFetching: boolean;
  onRefresh: () => void;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <Clock3 className="h-4 w-4 text-sky-700" />
          <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Scheduled sends
          </h2>
        </div>
        <span className="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-800">
          {actions.length}
        </span>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isFetching}
          className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60 sm:ml-auto"
        >
          {isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh
        </button>
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading scheduled sends...
        </div>
      ) : actions.length === 0 ? (
        <div className="px-4 py-8 text-sm text-neutral-500">
          No scheduled sends.
        </div>
      ) : (
        <div className="grid min-w-0 grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="border-b border-neutral-100 bg-neutral-50 p-2 lg:border-b-0 lg:border-r">
            <div className="space-y-1">
              {actions.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  onClick={() => onSelect(action.id)}
                  className={cn(
                    "w-full rounded-lg border px-3 py-3 text-left transition",
                    action.id === selectedId
                      ? "border-sky-700 bg-white shadow-sm"
                      : "border-transparent hover:border-neutral-200 hover:bg-white",
                  )}
                >
                  <div className="flex min-w-0 items-start gap-2">
                    <span className="mt-0.5 rounded-md bg-sky-700 p-1.5 text-white">
                      <Clock3 className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-semibold text-neutral-900">
                        {stringValue(action.input.subject) || action.action_type}
                      </div>
                      <div className="mt-1 truncate text-xs text-neutral-500">
                        {stringValue(action.input.to) ||
                          stringValue(action.input.batch_item_id) ||
                          action.entity_id ||
                          "Scheduled action"}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-800">
                          {istDate(action.scheduled_for)}
                        </span>
                        <span className="text-[11px] font-medium text-neutral-500">
                          {relativeSchedule(action.scheduled_for)}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
          {selectedAction && <ScheduledActionDetail action={selectedAction} />}
        </div>
      )}
    </section>
  );
}

function ScheduledActionDetail({ action }: { action: AgentAction }) {
  const subject = stringValue(action.input.subject);
  const body = stringValue(action.input.body);
  const recipient = stringValue(action.input.to);
  const batchItemId = stringValue(action.input.batch_item_id);
  const policyReason = stringValue(action.policy_result.reason);
  return (
    <div className="min-w-0 px-4 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-800">
          <Clock3 className="h-3 w-3" />
          Scheduled pending
        </span>
        <span className="text-xs text-neutral-500">
          {istDate(action.scheduled_for)} - {relativeSchedule(action.scheduled_for)}
        </span>
      </div>
      <h3 className="mt-2 text-base font-semibold text-neutral-950">
        {subject || action.action_type}
      </h3>
      <dl className="mt-3 grid grid-cols-[92px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
        <dt className="text-neutral-500">Action</dt>
        <dd className="break-all text-neutral-800">{action.id}</dd>
        <dt className="text-neutral-500">Status</dt>
        <dd className="text-neutral-800">{action.status}</dd>
        <dt className="text-neutral-500">Recipient</dt>
        <dd className="break-all text-neutral-800">{recipient || "From batch item"}</dd>
        {batchItemId && (
          <>
            <dt className="text-neutral-500">Batch item</dt>
            <dd className="break-all text-neutral-800">{batchItemId}</dd>
          </>
        )}
        {policyReason && (
          <>
            <dt className="text-neutral-500">Policy</dt>
            <dd className="text-neutral-800">{policyReason}</dd>
          </>
        )}
      </dl>
      {(subject || body) && (
        <div className="mt-4 rounded-lg border border-neutral-200 bg-neutral-50 p-3">
          {subject && (
            <div className="text-sm font-medium text-neutral-900">{subject}</div>
          )}
          {body && (
            <pre className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap font-sans text-xs leading-relaxed text-neutral-700">
              {body}
            </pre>
          )}
        </div>
      )}
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
