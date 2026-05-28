"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  ClipboardCheck,
  Eye,
  Loader2,
  MailPlus,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  approveLeadGenBatch,
  classifyLeadGenObservation,
  createLeadGenBatch,
  createLeadGenProposal,
  getContactDetail,
  getLeadGenBatch,
  getLeadGenPolicy,
  listLeadGenBatches,
  listSequenceTemplates,
  previewSequence,
  type LeadGenBatch,
  type LeadGenBatchItem,
  type LeadGenObservation,
  type RenderedSequenceStep,
  type SequenceTemplate,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULT_TEMPLATE = "possible_minds_dynamic";
const CALIFORNIA_TIME_ZONE = "America/Los_Angeles";

export default function LeadGenPage() {
  const [batchId, setBatchId] = useState<string>("");

  return (
    <div className="mx-auto max-w-[1500px] px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">
          Cybernetic Lead Gen
        </h1>
        <span className="text-xs text-neutral-400">
          recommend, approve, observe, learn
        </span>
      </div>

      <SafetyBand />

      <div className="grid grid-cols-12 gap-4">
        <aside className="col-span-12 space-y-3 lg:col-span-4 xl:col-span-3">
          <PolicyPanel />
          <NewBatchPanel onCreated={(id) => setBatchId(id)} />
          <BatchList selectedId={batchId} onSelect={setBatchId} />
        </aside>
        <main className="col-span-12 lg:col-span-8 xl:col-span-9">
          {batchId ? (
            <BatchDetail batchId={batchId} />
          ) : (
            <div className="rounded-xl border border-dashed border-neutral-200 bg-white px-6 py-16 text-center text-sm text-neutral-500">
              Create or select a batch. The system will show recommended
              contacts, approval state, observations, and learning proposals.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function SafetyBand() {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <ShieldCheck className="h-4 w-4" />
      <span className="font-medium">Human approval stays in the loop.</span>
      <span className="text-amber-800">
        Approving can queue sequence rows, but email sending still requires
        ALLOW_SEQUENCE_SEND=true on the backend.
      </span>
    </div>
  );
}

function PolicyPanel() {
  const q = useQuery({
    queryKey: ["lead-gen-policy"],
    queryFn: getLeadGenPolicy,
  });

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <BrainCircuit className="h-4 w-4 text-neutral-500" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Active policy
        </h2>
        {q.isFetching && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-neutral-400" />}
      </div>
      <div className="space-y-2 px-4 py-3 text-sm">
        {q.data ? (
          <>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-neutral-900">{q.data.version}</span>
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                active
              </span>
            </div>
            <div className="text-xs text-neutral-500">{q.data.label}</div>
            <div className="rounded-md bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
              Target: {q.data.target_metric.replaceAll("_", " ")}
            </div>
          </>
        ) : q.isLoading ? (
          <div className="text-xs text-neutral-400">Loading policy...</div>
        ) : (
          <div className="text-xs text-red-600">Policy unavailable.</div>
        )}
      </div>
    </section>
  );
}

function NewBatchPanel({ onCreated }: { onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const [templateKey, setTemplateKey] = useState(DEFAULT_TEMPLATE);
  const [limit, setLimit] = useState(50);
  const [name, setName] = useState("");

  const templates = useQuery({
    queryKey: ["sequence-templates"],
    queryFn: listSequenceTemplates,
  });

  const create = useMutation({
    mutationFn: () =>
      createLeadGenBatch({
        name: name.trim() || undefined,
        template_key: templateKey,
        limit,
        created_by: "operator",
      }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      onCreated(data.batch.id);
    },
  });

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <MailPlus className="h-4 w-4 text-neutral-500" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          New recommendation batch
        </h2>
      </div>
      <div className="space-y-3 px-4 py-3">
        <label className="block text-xs font-medium text-neutral-600">
          Sequence template
          <select
            value={templateKey}
            onChange={(e) => setTemplateKey(e.target.value)}
            className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm text-neutral-900"
          >
            {(templates.data ?? []).map((t: SequenceTemplate) => (
              <option key={t.template_key} value={t.template_key}>
                {t.label}
              </option>
            ))}
            {templates.data?.length === 0 && (
              <option value={DEFAULT_TEMPLATE}>Records audit</option>
            )}
          </select>
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Batch name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Optional"
            className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-900"
          />
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Contacts
          <input
            type="number"
            min={1}
            max={200}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="mt-1 w-28 rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-900"
          />
        </label>
        <button
          type="button"
          onClick={() => create.mutate()}
          disabled={create.isPending}
          className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
        >
          {create.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          Recommend next batch
        </button>
        {create.isError && (
          <div className="text-xs text-red-600">
            Could not create batch. Check backend logs.
          </div>
        )}
      </div>
    </section>
  );
}

function BatchList({
  selectedId,
  onSelect,
}: {
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const [status, setStatus] = useState("all");
  const q = useQuery({
    queryKey: ["lead-gen-batches", status],
    queryFn: () => listLeadGenBatches({ status, limit: 50 }),
    refetchInterval: 30_000,
  });
  const batches = q.data?.batches ?? [];

  useEffect(() => {
    const firstBatchId = batches[0]?.id;
    if (!selectedId && firstBatchId) {
      onSelect(firstBatchId);
    }
  }, [batches, onSelect, selectedId]);

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Batches
        </h2>
        {q.isFetching && <RefreshCw className="h-3.5 w-3.5 animate-spin text-neutral-400" />}
      </div>
      <div className="border-b border-neutral-100 px-4 py-2">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-xs text-neutral-700"
        >
          <option value="all">All statuses</option>
          <option value="recommended">Recommended</option>
          <option value="approved">Approved</option>
          <option value="sequencing">Sequencing</option>
          <option value="observing">Observing</option>
          <option value="completed">Completed</option>
          <option value="archived">Archived</option>
        </select>
      </div>
      <div className="max-h-[520px] overflow-y-auto">
        {batches.map((b: LeadGenBatch) => (
          <button
            key={b.id}
            type="button"
            onClick={() => onSelect(b.id)}
            className={cn(
              "block w-full border-b border-neutral-100 px-4 py-3 text-left hover:bg-neutral-50",
              selectedId === b.id && "bg-neutral-50",
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="truncate text-sm font-medium text-neutral-900">{b.name}</span>
              <StatusPill status={b.status} />
            </div>
            <div className="mt-1 flex items-center justify-between text-xs text-neutral-500">
              <span>{b.template_key}</span>
              <span>{b.counts?.returned ?? 0} contacts</span>
            </div>
            <div className="mt-1 text-[11px] text-neutral-400">{formatDate(b.created_at)}</div>
          </button>
        ))}
        {batches.length === 0 && (
          <div className="px-4 py-6 text-center text-xs text-neutral-400">
            No batches yet.
          </div>
        )}
      </div>
    </section>
  );
}

function BatchDetail({ batchId }: { batchId: string }) {
  const qc = useQueryClient();
  const [observeItem, setObserveItem] = useState<LeadGenBatchItem | null>(null);
  const [previewItem, setPreviewItem] = useState<LeadGenBatchItem | null>(null);
  const [scheduledStartAt, setScheduledStartAt] = useState(() =>
    defaultCaliforniaDateTimeLocal(),
  );

  const q = useQuery({
    queryKey: ["lead-gen-batch", batchId],
    queryFn: () => getLeadGenBatch(batchId, true),
    refetchInterval: 30_000,
  });

  const approve = useMutation({
    mutationFn: (startSequences: boolean) =>
      approveLeadGenBatch(batchId, {
        approved_by: "operator",
        start_sequences: startSequences,
        stagger_minutes: 60,
        scheduled_start_at: startSequences ? scheduledStartAt : undefined,
        scheduled_timezone: CALIFORNIA_TIME_ZONE,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", batchId] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
    },
  });

  const propose = useMutation({
    mutationFn: () => createLeadGenProposal(batchId, "operator"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", batchId] });
    },
  });

  const data = q.data;
  const counts = useMemo(() => summarizeItems(data?.items ?? []), [data?.items]);

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-neutral-200 bg-white px-6 py-8 text-sm text-neutral-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading batch...
      </div>
    );
  }
  if (!data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-8 text-sm text-red-700">
        Batch unavailable.
      </div>
    );
  }

  const canApprove = data.batch.status === "recommended";
  const canQueue =
    data.batch.status === "approved" &&
    data.items.some((item) => item.approval_status === "approved" && !item.sequence_id);

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-neutral-900">{data.batch.name}</h2>
            <div className="mt-1 text-xs text-neutral-500">
              {data.batch.id} - {data.batch.template_key} - {data.batch.policy_version}
            </div>
          </div>
          <StatusPill status={data.batch.status} className="ml-auto" />
        </div>
        <div className="grid gap-3 px-4 py-3 md:grid-cols-4">
          <Metric label="Recommended" value={String(data.items.length)} />
          <Metric label="Approved" value={String(counts.approved)} />
          <Metric label="Started" value={String(counts.started)} />
          <Metric label="Observed" value={String(counts.observed)} />
        </div>
        <div className="border-t border-neutral-100 px-4 py-3">
          <label className="block max-w-xs text-xs font-medium text-neutral-600">
            Start sending (California)
            <input
              type="datetime-local"
              value={scheduledStartAt}
              onChange={(e) => setScheduledStartAt(e.target.value)}
              className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-900"
            />
          </label>
          <div className="mt-1 text-xs text-neutral-400">
            Interpreted as America/Los_Angeles, then staggered over 60 minutes.
          </div>
        </div>
        <div className="flex flex-wrap gap-2 border-t border-neutral-100 px-4 py-3">
          <button
            type="button"
            onClick={() => approve.mutate(false)}
            disabled={!canApprove || approve.isPending}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
          >
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
            Approve only
          </button>
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Queue sequence rows for every approved item starting ${scheduledStartAt || "now"} California time, staggered over a 60-minute sending window? Email sending still requires ALLOW_SEQUENCE_SEND=true.`)) {
                approve.mutate(true);
              }
            }}
            disabled={!(canApprove || canQueue) || approve.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {canQueue ? "Queue approved over 1 hour" : "Approve and queue over 1 hour"}
          </button>
          <button
            type="button"
            onClick={() => propose.mutate()}
            disabled={propose.isPending}
            className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
          >
            {propose.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BrainCircuit className="h-4 w-4" />}
            Generate learning proposal
          </button>
          {propose.data && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Proposal {propose.data.id.slice(0, 8)} created
            </span>
          )}
        </div>
      </section>

      <ItemsTable
        items={data.items}
        onObserve={setObserveItem}
        onPreview={setPreviewItem}
      />
      <ObservationsPanel observations={data.observations} />

      {previewItem && (
        <PreviewModal
          item={previewItem}
          onClose={() => setPreviewItem(null)}
        />
      )}

      {observeItem && (
        <ObservationModal
          batchId={batchId}
          item={observeItem}
          onClose={() => setObserveItem(null)}
          onSaved={() => {
            setObserveItem(null);
            qc.invalidateQueries({ queryKey: ["lead-gen-batch", batchId] });
          }}
        />
      )}
    </div>
  );
}

function ItemsTable({
  items,
  onObserve,
  onPreview,
}: {
  items: LeadGenBatchItem[];
  onObserve: (item: LeadGenBatchItem) => void;
  onPreview: (item: LeadGenBatchItem) => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Recommended contacts
        </h2>
        <span className="text-xs text-neutral-400">{items.length} rows</span>
      </div>
      <div className="divide-y divide-neutral-100">
        {items.map((item) => (
          <article
            key={item.id}
            className="grid min-w-0 gap-3 px-4 py-3 text-sm lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1.35fr)_minmax(180px,0.9fr)_minmax(130px,auto)]"
          >
            <div className="min-w-0">
              <div className="font-medium text-neutral-900">{item.firm_name}</div>
              <div className="mt-1 break-all text-xs text-neutral-400">{item.pif_id}</div>
            </div>

            <div className="min-w-0">
              <div className="font-medium text-neutral-800">
                {item.contact_name || "Unknown"}
              </div>
              <div className="text-xs text-neutral-500">{item.contact_title || "No title"}</div>
              <div className="mt-1 break-all text-xs text-neutral-500">
                {item.contact_email}
              </div>
              <button
                type="button"
                onClick={() => onPreview(item)}
                className="mt-2 inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
              >
                <MailPlus className="h-3.5 w-3.5" />
                Preview email
              </button>
            </div>

            <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
              <MiniField label="Persona" value={item.persona || "-"} />
              <MiniField label="Score" value={String(item.score)} mono />
              <div>
                <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
                  State
                </div>
                <div className="mt-1">
                  <StatusPill status={item.approval_status} />
                  {item.sequence_id && (
                    <div className="mt-1 text-[11px] text-neutral-400">
                      seq {item.sequence_id.slice(0, 8)}
                    </div>
                  )}
                </div>
              </div>
              <MiniField
                label="Outcome"
                value={
                  item.outcome
                    ? `${item.outcome}${item.outcome_confidence !== null ? ` ${item.outcome_confidence}%` : ""}`
                    : "None"
                }
              />
            </div>

            <div className="flex items-start justify-start lg:justify-end">
              <button
                type="button"
                onClick={() => onObserve(item)}
                className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
              >
                <Eye className="h-3.5 w-3.5" />
                Observe
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function MiniField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 break-words text-xs text-neutral-600",
          mono && "font-mono text-neutral-700",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function PreviewModal({
  item,
  onClose,
}: {
  item: LeadGenBatchItem;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["sequence-preview", item.contact_id, item.template_key],
    queryFn: () => previewSequence(item.contact_id, item.template_key),
  });
  const detail = useQuery({
    queryKey: ["contact-detail", item.contact_id, item.template_key],
    queryFn: () => getContactDetail(item.contact_id, item.template_key),
  });
  const nextStep = useMemo(() => {
    const steps = q.data ?? [];
    const sequence = detail.data?.sequence;
    if (sequence && sequence.current_step >= sequence.steps_total) return undefined;
    const nextStepNumber = sequence ? sequence.current_step + 1 : 1;
    return steps.find((step) => step.step === nextStepNumber) ?? steps[0];
  }, [detail.data?.sequence, q.data]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
        <div className="border-b border-neutral-100 px-5 py-4">
          <h3 className="text-sm font-semibold text-neutral-900">
            Email preview for {item.contact_name || item.firm_name}
          </h3>
          <p className="mt-1 text-xs text-neutral-500">
            {item.contact_email} - {item.firm_name} - {item.template_key}
          </p>
        </div>
        <div className="overflow-y-auto px-5 py-4">
          {q.isLoading || detail.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Rendering preview...
            </div>
          ) : q.isError || detail.isError ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              Could not render this email preview.
            </div>
          ) : (
            <div className="space-y-4">
              <section className="rounded-lg border border-neutral-200">
                <div className="border-b border-neutral-100 bg-neutral-50 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
                  Next email to send
                </div>
                {nextStep ? (
                  <RenderedEmail step={nextStep} />
                ) : (
                  <div className="px-3 py-4 text-sm text-neutral-500">
                    No remaining email for this sequence.
                  </div>
                )}
              </section>
              <section className="rounded-lg border border-neutral-200">
                <div className="border-b border-neutral-100 bg-neutral-50 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
                  Full sequence
                </div>
                <div className="divide-y divide-neutral-100">
                  {(q.data ?? []).map((step) => (
                    <RenderedEmail key={step.step} step={step} compact />
                  ))}
                </div>
              </section>
            </div>
          )}
        </div>
        <div className="flex justify-end border-t border-neutral-100 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function RenderedEmail({
  step,
  compact = false,
}: {
  step: RenderedSequenceStep;
  compact?: boolean;
}) {
  return (
    <div className="space-y-2 px-3 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
          Step {step.step}
        </span>
        <span className="text-xs text-neutral-400">{step.message_type}</span>
      </div>
      <div>
        <div className="text-xs font-medium uppercase tracking-wider text-neutral-400">
          Subject
        </div>
        <div className="mt-1 font-medium text-neutral-900">{step.subject}</div>
      </div>
      <div>
        <div className="text-xs font-medium uppercase tracking-wider text-neutral-400">
          Body
        </div>
        <pre
          className={cn(
            "mt-1 whitespace-pre-wrap rounded-md bg-neutral-50 p-3 font-sans text-sm leading-6 text-neutral-700",
            compact && "max-h-48 overflow-y-auto",
          )}
        >
          {step.body}
        </pre>
      </div>
    </div>
  );
}

function ObservationsPanel({ observations }: { observations: LeadGenObservation[] }) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Feedback observations
        </h2>
        <span className="text-xs text-neutral-400">{observations.length} events</span>
      </div>
      {observations.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-neutral-400">
          No feedback classified yet.
        </div>
      ) : (
        <div className="divide-y divide-neutral-100">
          {observations.map((obs) => (
            <div key={obs.id} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[160px_180px_1fr]">
              <div className="text-xs text-neutral-400">{formatDate(obs.created_at)}</div>
              <div>
                <div className="font-medium text-neutral-900">{obs.classified_outcome || "unclassified"}</div>
                <div className="text-xs text-neutral-500">
                  {obs.event_type} - {obs.confidence ?? 0}%
                </div>
              </div>
              <div className="text-neutral-600">{obs.llm_reasoning || "No reasoning stored."}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ObservationModal({
  batchId,
  item,
  onClose,
  onSaved,
}: {
  batchId: string;
  item: LeadGenBatchItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [eventType, setEventType] = useState("manual_note");
  const [text, setText] = useState("");

  const save = useMutation({
    mutationFn: () =>
      classifyLeadGenObservation({
        event_type: eventType,
        raw_event: { text },
        batch_id: batchId,
        contact_id: item.contact_id,
        batch_item_id: item.id,
      }),
    onSuccess: onSaved,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="w-full max-w-xl rounded-xl bg-white shadow-xl">
        <div className="border-b border-neutral-100 px-5 py-4">
          <h3 className="text-sm font-semibold text-neutral-900">
            Classify feedback for {item.contact_name || item.firm_name}
          </h3>
          <p className="mt-1 text-xs text-neutral-500">
            This calls the OpenClaw feedback classifier and stores the outcome.
          </p>
        </div>
        <div className="space-y-3 px-5 py-4">
          <label className="block text-xs font-medium text-neutral-600">
            Event type
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-2 text-sm text-neutral-900"
            >
              <option value="manual_note">Manual note</option>
              <option value="email_reply">Email reply</option>
              <option value="email_bounce">Email bounce</option>
              <option value="booking">Booking</option>
              <option value="call_summary">Call summary</option>
              <option value="sms_reply">SMS reply</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="block text-xs font-medium text-neutral-600">
            Raw feedback text
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={7}
              placeholder="Paste the reply, note, or booking context."
              className="mt-1 w-full rounded-md border border-neutral-200 px-3 py-2 text-sm text-neutral-900"
            />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-neutral-100 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={!text.trim() || save.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            Classify and store
          </button>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-neutral-900">{value}</div>
    </div>
  );
}

function StatusPill({ status, className }: { status: string; className?: string }) {
  const styles: Record<string, string> = {
    recommended: "bg-blue-50 text-blue-700",
    approved: "bg-emerald-50 text-emerald-700",
    sequencing: "bg-purple-50 text-purple-700",
    observing: "bg-amber-50 text-amber-700",
    completed: "bg-neutral-100 text-neutral-700",
    archived: "bg-neutral-100 text-neutral-500",
    pending: "bg-blue-50 text-blue-700",
    started: "bg-emerald-50 text-emerald-700",
    skipped: "bg-neutral-100 text-neutral-500",
    rejected: "bg-red-50 text-red-700",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        styles[status] ?? "bg-neutral-100 text-neutral-600",
        className,
      )}
    >
      {status}
    </span>
  );
}

function summarizeItems(items: LeadGenBatchItem[]) {
  return items.reduce(
    (acc, item) => {
      if (item.approval_status === "approved") acc.approved += 1;
      if (item.approval_status === "started") acc.started += 1;
      if (item.outcome) acc.observed += 1;
      return acc;
    },
    { approved: 0, started: 0, observed: 0 },
  );
}

function defaultCaliforniaDateTimeLocal() {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 15);
  now.setSeconds(0, 0);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: CALIFORNIA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}T${byType.hour}:${byType.minute}`;
}

function formatDate(value: string | null) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 19);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
