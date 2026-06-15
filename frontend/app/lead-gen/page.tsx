"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BrainCircuit,
  ChevronDown,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Eye,
  Loader2,
  MailPlus,
  Play,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  approveLeadGenBatch,
  classifyLeadGenObservation,
  createLeadGenBatch,
  createLeadGenEmailAgentSlice,
  createLeadGenProposal,
  getContactDetail,
  getComposerVariants,
  getLeadGenBatch,
  getLeadGenDailyEnabled,
  getLeadGenPolicy,
  listLeadGenBatches,
  listLeadGenDailyRuns,
  previewSequence,
  runLeadGenDaily,
  sendLeadGenBatchItemDraft,
  setLeadGenDailyEnabled,
  updateLeadGenDailySendBudget,
  type LeadGenBatch,
  type LeadGenBatchItem,
  type LeadGenDailyRun,
  type LeadGenObservation,
  type RenderedSequenceStep,
  type ComposerSkillVariant,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULT_TEMPLATE = "possible_minds_dynamic";
const CALIFORNIA_TIME_ZONE = "America/Los_Angeles";
const DEFAULT_DAILY_EMAIL_BUDGET = 50;
type DraftGenerationStatus = "generating" | "completed" | "failed";

export default function LeadGenPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center gap-2 px-6 py-16 text-center text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading lead generation...
        </div>
      }
    >
      <LeadGenPageContent />
    </Suspense>
  );
}

function LeadGenPageContent() {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const [batchId, setBatchId] = useState<string>("");
  const [dailyEmailBudget, setDailyEmailBudget] = useState(DEFAULT_DAILY_EMAIL_BUDGET);
  const requestedBatchId = searchParams.get("batch") || "";
  const requestedItemId = searchParams.get("item") || "";
  const requestedContactId = searchParams.get("contact") || "";
  const requestedNotificationId = searchParams.get("notification") || "";
  const policy = useQuery({
    queryKey: ["lead-gen-policy"],
    queryFn: getLeadGenPolicy,
  });
  const batches = useQuery({
    queryKey: ["lead-gen-batches", "recent"],
    queryFn: () => listLeadGenBatches({ limit: 20 }),
    refetchInterval: 30_000,
  });
  const dailyRuns = useQuery({
    queryKey: ["lead-gen-daily-runs"],
    queryFn: () => listLeadGenDailyRuns(5),
    refetchInterval: 30_000,
  });
  const dailyEnabled = useQuery({
    queryKey: ["lead-gen-daily-enabled"],
    queryFn: getLeadGenDailyEnabled,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (policy.data?.daily_send_budget) {
      setDailyEmailBudget(clampDailyEmailBudget(policy.data.daily_send_budget));
    }
  }, [policy.data?.daily_send_budget]);

  useEffect(() => {
    if (batchId) return;
    const availableBatches = batches.data?.batches ?? [];
    const selectedBatch =
      availableBatches.find((batch) => batch.id === requestedBatchId) ??
      selectBatchForDisplay(availableBatches);
    if (selectedBatch) {
      setBatchId(selectedBatch.id);
    }
  }, [batchId, batches.data?.batches, requestedBatchId]);

  useEffect(() => {
    if (requestedBatchId && requestedBatchId !== batchId) {
      setBatchId(requestedBatchId);
    }
  }, [batchId, requestedBatchId]);

  const saveBudget = useMutation({
    mutationFn: () => updateLeadGenDailySendBudget(dailyEmailBudget),
    onSuccess: (data) => {
      setDailyEmailBudget(clampDailyEmailBudget(data.daily_send_budget));
      qc.invalidateQueries({ queryKey: ["lead-gen-policy"] });
    },
  });

  const createToday = useMutation({
    mutationFn: async () => {
      const created = await createLeadGenBatch({
        name: defaultDailyPlanName(dailyEmailBudget),
        template_key: DEFAULT_TEMPLATE,
        limit: dailyEmailBudget,
        created_by: "operator",
      });
      return approveLeadGenBatch(created.batch.id, {
        approved_by: "operator",
        start_sequences: true,
        stagger_minutes: 60,
        scheduled_timezone: CALIFORNIA_TIME_ZONE,
      });
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["operator-notifications-pending"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      setBatchId(data.batch.id);
    },
  });
  const createAgentSlice = useMutation({
    mutationFn: () => createLeadGenEmailAgentSlice({
      limit: 3,
      template_key: DEFAULT_TEMPLATE,
      created_by: "operator",
      approve_actions: false,
      policy_check_first_action: false,
    }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      setBatchId(data.batch.id);
    },
  });
  const runDaily = useMutation({
    mutationFn: (dryRun: boolean) => runLeadGenDaily({ dry_run: dryRun }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["lead-gen-daily-runs"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      if (data.batch_id) setBatchId(data.batch_id);
    },
  });
  const toggleDaily = useMutation({
    mutationFn: (enabled: boolean) => setLeadGenDailyEnabled(enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-daily-enabled"] });
    },
  });

  const todayDailyRun =
    (dailyRuns.data?.runs ?? []).find((run) => run.run_date === californiaDateKey(new Date())) ??
    (dailyRuns.data?.runs ?? [])[0] ??
    null;

  return (
    <div className="mx-auto min-w-0 max-w-[1500px] space-y-6">
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
      <LeadGenProcessExplanation />

      <div className="grid gap-4 lg:grid-cols-12">
        <aside className="col-span-12 space-y-3 lg:col-span-4 xl:col-span-3">
          <DailyRunPanel
            run={todayDailyRun}
            enabled={Boolean(dailyEnabled.data?.enabled)}
            loading={dailyRuns.isLoading || dailyEnabled.isLoading}
            onToggle={(enabled) => toggleDaily.mutate(enabled)}
            toggling={toggleDaily.isPending}
            onRun={(dryRun) => runDaily.mutate(dryRun)}
            running={runDaily.isPending}
            error={runDaily.isError || toggleDaily.isError}
          />
          <DailySendBudgetPanel
            dailyEmailBudget={dailyEmailBudget}
            onDailyEmailBudgetChange={setDailyEmailBudget}
            onSave={() => saveBudget.mutate()}
            isSaving={saveBudget.isPending}
            saveError={saveBudget.isError}
            onGenerate={() => createToday.mutate()}
            isGenerating={createToday.isPending}
            generateError={createToday.isError}
          />
          <section className="rounded-xl border border-neutral-200 bg-white p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Agent slice
            </div>
            <p className="mt-2 text-sm leading-6 text-neutral-600">
              Selects 3 senior decision-maker contacts, adds internal evidence,
              composes drafts with the email skill, and creates approval-ready
              send actions. No email is sent.
            </p>
            <button
              type="button"
              onClick={() => createAgentSlice.mutate()}
              disabled={createAgentSlice.isPending}
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
            >
              {createAgentSlice.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              Create 3 approval-ready drafts
            </button>
            {createAgentSlice.isError && (
              <div className="mt-2 text-xs text-red-600">
                Could not create the agent slice.
              </div>
            )}
          </section>
        </aside>
        <main className="col-span-12 lg:col-span-8 xl:col-span-9">
          {batchId ? (
            <BatchDetail
              batchId={batchId}
              dailyEmailBudget={dailyEmailBudget}
              requestedItemId={requestedItemId}
              requestedContactId={requestedContactId}
              requestedNotificationId={requestedNotificationId}
            />
          ) : batches.isLoading ? (
            <div className="flex items-center justify-center gap-2 rounded-xl border border-neutral-200 bg-white px-6 py-16 text-center text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading the latest generated list...
            </div>
          ) : batches.isError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-16 text-center text-sm text-red-700">
              Could not load generated lead-gen lists.
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-neutral-200 bg-white px-6 py-16 text-center text-sm text-neutral-500">
              No generated list was found. Set the daily send budget, save it,
              then generate today's actions.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

const leadGenProcessSteps = [
  {
    step: "1",
    title: "Select daily actions",
    current:
      "Today the planner spends the daily budget across pending replies, already-composed drafts, due follow-ups, and new first-touch contacts. New starts come from firm_contacts, require a usable email, skip firms with prior call/email/SMS history, skip existing outreach runs, filter obvious non-law records, and run an explainable contact-selection scorer using persona, firm-fit, relationship, email-quality, and history components. The selected item stores the score breakdown, features, policy version, suppressions, and reason trace.",
    ideal:
      "Add Front read-only relationship signals, booked consult patterns, firm size, website/leadership context, inferred operational pain, prior engagement, and suppression history so the daily batch is selected by likelihood of booked qualified conversation with richer evidence.",
  },
  {
    step: "2",
    title: "Create the batch",
    current:
      "Creating a batch stores lead_gen_batches and lead_gen_batch_items as a ranked daily action plan. Items carry an action type such as reply_to_inbound, approve_existing_draft, follow_up, or first_touch plus the contact-selection trace used to rank that item. No email can be sent at this stage.",
    ideal:
      "The daily runner should create a policy-explained batch automatically, attach recommendation evidence for each firm, and separate eligible, suppressed, already-contacted, and needs-review candidates.",
  },
  {
    step: "3",
    title: "Approve and queue",
    current:
      "Approving a batch can mark items approved. Approve-and-queue creates outreach run state for the approved contacts and staggers their first due time over the configured California-time send window.",
    ideal:
      "A daily operating policy should decide whether a batch is auto-created but still keep send approval manual. It should enforce daily caps, sender/domain limits, cooldowns, and first-class suppressions before any outreach run is queued.",
  },
  {
    step: "4",
    title: "Compose each email",
    current:
      "All lead-gen batches use the possible_minds_dynamic composer. When an outreach step becomes due, the backend builds context from the contact, firm, prior outbound emails, inbound replies, booked consult patterns, optional blog links, and policy, then calls app/skills/possible-minds-lead-email-composer/SKILL.md to choose the strategy and draft plaintext copy.",
    ideal:
      "The composer should also receive Front-derived workflow signals, CRM state, firm-size/leadership intelligence, website evidence, experiment assignment, known winning consult patterns, and skill-version history. The skill should be updated from reviewed feedback over time.",
  },
  {
    step: "5",
    title: "Review before send",
    current:
      "Every generated outbound email creates an operator notification. The outreach run pauses as awaiting_operator_send_approval. The non-blocking action center shows firm/contact context, editable subject/body, rationale, angle, CTA, blog link when used, and model metadata.",
    ideal:
      "The action center should also show the exact evidence packet used, policy constraints, risk flags, prior touches, deliverability warnings, and alternate draft options. Approval, edits, and rejection reasons should become learning observations.",
  },
  {
    step: "6",
    title: "Send and advance",
    current:
      "Only Approve & send sends the edited draft through the configured email transport, writes email_logs, marks the notification actioned, advances the outreach step, and schedules the next due step by cadence.",
    ideal:
      "The send path should attach experiment IDs, composer skill version, policy version, sender identity, selected blog link, and full render metadata so every outcome can be traced back to the decision that produced it.",
  },
  {
    step: "7",
    title: "Observe feedback",
    current:
      "The loop can ingest Zoho inbound replies, Resend delivery events when configured, manual observations, operator notifications, and booked consults in the Possible OS database. Replies pause outreach runs and create review tasks.",
    ideal:
      "Add automated polling jobs, production Resend webhook config, Front read-only ingestion, calendar lifecycle events, CRM/deal outcomes, landing-page analytics, and normalized observation records across all feedback sources.",
  },
  {
    step: "8",
    title: "Learn and update policy",
    current:
      "Observations and proposal generation exist, but scoring, copy doctrine, skill examples, sender strategy, suppression rules, and policy versions are not automatically updated from feedback.",
    ideal:
      "Aggregate feedback into human-reviewed proposals: change targeting weights, suppressions, cadence, blog-link choices, composer instructions, examples, and policy versions. Apply changes only after approval until the loop has enough evidence for low-risk automation.",
  },
];

function LeadGenProcessExplanation() {
  const [open, setOpen] = useState(false);

  return (
    <section className="mb-4 overflow-hidden rounded-xl border border-neutral-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3 text-left hover:bg-neutral-50"
      >
        <BrainCircuit className="h-4 w-4 text-neutral-500" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
          Lead generation control loop
        </h2>
        <span className="text-xs text-neutral-400">
          current behavior and target state
        </span>
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-500">
          {open ? "Hide details" : "Show details"}
        </span>
        <ChevronDown
          className={cn(
            "ml-auto h-4 w-4 text-neutral-400 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div className="divide-y divide-neutral-100">
          {leadGenProcessSteps.map((item) => (
            <div
              key={item.step}
              className="grid gap-3 px-4 py-3 text-sm xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]"
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-neutral-900 text-xs font-semibold text-white">
                  {item.step}
                </span>
                <div className="min-w-0">
                  <div className="font-medium text-neutral-900">{item.title}</div>
                </div>
              </div>
              <div className="min-w-0 rounded-md bg-neutral-50 px-3 py-2">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
                  Now
                </div>
                <p className="text-xs leading-relaxed text-neutral-700">{item.current}</p>
              </div>
              <div className="min-w-0 rounded-md bg-emerald-50 px-3 py-2">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-emerald-700">
                  Ideal
                </div>
                <p className="text-xs leading-relaxed text-emerald-900">{item.ideal}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SafetyBand() {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <ShieldCheck className="h-4 w-4" />
      <span className="font-medium">Human approval stays in the loop.</span>
      <span className="text-amber-800">
        Approving can queue outreach runs, but email sending still requires
        ALLOW_SEQUENCE_SEND=true on the backend.
      </span>
    </div>
  );
}

function DailyRunPanel({
  run,
  enabled,
  loading,
  onToggle,
  toggling,
  onRun,
  running,
  error,
}: {
  run: LeadGenDailyRun | null;
  enabled: boolean;
  loading: boolean;
  onToggle: (enabled: boolean) => void;
  toggling: boolean;
  onRun: (dryRun: boolean) => void;
  running: boolean;
  error: boolean;
}) {
  const stages = run?.stages ?? {};
  const selectCounts = (stages.select?.counts ?? {}) as Record<string, unknown>;
  const composeCounts = (stages.compose?.counts ?? {}) as Record<string, unknown>;
  const selectedCount = typeof selectCounts.selected === "number" ? selectCounts.selected : null;
  const draftedCount = typeof composeCounts.drafted === "number" ? composeCounts.drafted : null;

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <Clock className="h-4 w-4 text-neutral-500" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Daily run
        </h2>
        {loading && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-neutral-400" />}
      </div>
      <div className="space-y-3 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-neutral-900">
              {run?.run_date ?? californiaDateKey(new Date())}
            </div>
            <div className="mt-0.5 text-xs text-neutral-500">
              {run ? `${run.status} at ${run.stage}` : "No run recorded today"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onToggle(!enabled)}
            disabled={toggling}
            className={cn(
              "inline-flex h-7 min-w-16 items-center justify-center rounded-full px-3 text-xs font-medium",
              enabled ? "bg-emerald-100 text-emerald-800" : "bg-neutral-100 text-neutral-600",
              toggling && "opacity-60",
            )}
          >
            {enabled ? "Enabled" : "Disabled"}
          </button>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <Metric label="Selected" value={selectedCount === null ? "-" : String(selectedCount)} />
          <Metric label="Drafted" value={draftedCount === null ? "-" : String(draftedCount)} />
          <Metric label="Batch" value={run?.batch_id ? "Yes" : "-"} />
        </div>
        {run?.batch_id && (
          <Link
            href={`/lead-gen?batch=${encodeURIComponent(run.batch_id)}`}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            <Eye className="h-4 w-4" />
            Open batch
          </Link>
        )}
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => onRun(true)}
            disabled={running}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Dry run
          </button>
          <button
            type="button"
            onClick={() => onRun(false)}
            disabled={running}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run now
          </button>
        </div>
        {error && (
          <div className="text-xs text-red-600">
            Daily run request failed.
          </div>
        )}
      </div>
    </section>
  );
}

function DailySendBudgetPanel({
  dailyEmailBudget,
  onDailyEmailBudgetChange,
  onSave,
  isSaving,
  saveError,
  onGenerate,
  isGenerating,
  generateError,
}: {
  dailyEmailBudget: number;
  onDailyEmailBudgetChange: (value: number) => void;
  onSave: () => void;
  isSaving: boolean;
  saveError: boolean;
  onGenerate: () => void;
  isGenerating: boolean;
  generateError: boolean;
}) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <MailPlus className="h-4 w-4 text-neutral-500" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Daily send budget
        </h2>
      </div>
      <div className="space-y-3 px-4 py-3">
        <div className="flex items-end gap-2">
          <label
            htmlFor="daily-email-budget"
            className="block flex-1 text-xs font-medium text-neutral-600"
          >
            Emails per day
            <input
              id="daily-email-budget"
              type="number"
              min={1}
              max={200}
              value={dailyEmailBudget}
              onChange={(e) => onDailyEmailBudgetChange(clampDailyEmailBudget(Number(e.target.value)))}
              className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-900"
            />
          </label>
          <button
            type="button"
            onClick={onSave}
            disabled={isSaving}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
            Save
          </button>
        </div>
        <button
          type="button"
          onClick={onGenerate}
          disabled={isGenerating}
          className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
        >
          {isGenerating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          Generate today's actions
        </button>
        {saveError && (
          <div className="text-xs text-red-600">
            Could not save the daily budget.
          </div>
        )}
        {generateError && (
          <div className="text-xs text-red-600">
            Could not generate today's list. Check backend logs.
          </div>
        )}
      </div>
    </section>
  );
}

function BatchDetail({
  batchId,
  dailyEmailBudget,
  requestedItemId,
  requestedContactId,
  requestedNotificationId,
}: {
  batchId: string;
  dailyEmailBudget: number;
  requestedItemId: string;
  requestedContactId: string;
  requestedNotificationId: string;
}) {
  const qc = useQueryClient();
  const [observeItem, setObserveItem] = useState<LeadGenBatchItem | null>(null);
  const [previewItem, setPreviewItem] = useState<LeadGenBatchItem | null>(null);
  const [draftStatuses, setDraftStatuses] = useState<Record<string, DraftGenerationStatus>>({});
  const [isGeneratingAllDrafts, setIsGeneratingAllDrafts] = useState(false);
  const [bulkDraftError, setBulkDraftError] = useState<string | null>(null);
  const [selectedComposerVariantKey, setSelectedComposerVariantKey] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const openedRequestKey = useRef("");
  const [scheduledStartAt, setScheduledStartAt] = useState(() =>
    defaultCaliforniaDateTimeLocal(),
  );

  const q = useQuery({
    queryKey: ["lead-gen-batch", batchId],
    queryFn: () => getLeadGenBatch(batchId, true),
    refetchInterval: 30_000,
  });
  const composerVariants = useQuery({
    queryKey: ["composer-variants"],
    queryFn: getComposerVariants,
    staleTime: 60_000,
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
  const previewableItems = useMemo(
    () => (data?.items ?? []).filter(canPreviewItem),
    [data?.items],
  );
  const sentItems = useMemo(
    () => (data?.items ?? []).filter(isEmailSent),
    [data?.items],
  );
  const activeComposerVariants = useMemo(
    () => (composerVariants.data?.variants ?? []).filter((variant) => variant.active),
    [composerVariants.data?.variants],
  );
  const selectedComposerVariant = useMemo(
    () => activeComposerVariants.find((variant) => variant.key === selectedComposerVariantKey),
    [activeComposerVariants, selectedComposerVariantKey],
  );
  const completedDraftCount = previewableItems.filter(
    (item) => draftStatuses[item.id] === "completed" || Boolean(storedAgentDraftStep(item)),
  ).length;
  const requestedPreviewKey = [
    batchId,
    requestedItemId,
    requestedContactId,
    requestedNotificationId,
  ].join(":");

  useEffect(() => {
    if (!data || !requestedPreviewKey || openedRequestKey.current === requestedPreviewKey) return;
    if (!requestedItemId && !requestedContactId && !requestedNotificationId) return;
    const item = data.items.find((candidate) => {
      if (requestedItemId && candidate.id === requestedItemId) return true;
      if (requestedContactId && candidate.contact_id === requestedContactId) return true;
      if (
        requestedNotificationId &&
        (
          String(candidate.reason?.operator_notification_id || "") === requestedNotificationId ||
          String(candidate.reason?.notification_id || "") === requestedNotificationId
        )
      ) {
        return true;
      }
      return false;
    });
    openedRequestKey.current = requestedPreviewKey;
    if (item && canPreviewItem(item)) {
      setPreviewItem(item);
    }
  }, [
    data,
    requestedContactId,
    requestedItemId,
    requestedNotificationId,
    requestedPreviewKey,
  ]);

  useEffect(() => {
    if (!data || !previewItem) return;
    const latestItem = data.items.find((candidate) => candidate.id === previewItem.id);
    if (!latestItem) return;
    if (latestItem !== previewItem) {
      setPreviewItem(latestItem);
    }
  }, [data, previewItem]);

  useEffect(() => {
    if (
      selectedComposerVariantKey &&
      activeComposerVariants.length > 0 &&
      !activeComposerVariants.some((variant) => variant.key === selectedComposerVariantKey)
    ) {
      setSelectedComposerVariantKey("");
    }
  }, [activeComposerVariants, selectedComposerVariantKey]);

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
  const isOlderPlan = !isCaliforniaToday(data.batch.created_at);
  const hasQueueableItems = data.items.some(canQueueItem);
  const canQueue =
    data.batch.status === "approved" &&
    data.items.some((item) => item.approval_status === "approved" && canQueueItem(item));
  // A run is "completed" once there is no further send action to take:
  // everything sent, or nothing left to queue and nothing left to approve.
  const isCompletedRun =
    data.items.length > 0 &&
    (sentItems.length === data.items.length || (!hasQueueableItems && !canApprove));
  const REPLY_OUTCOMES = new Set([
    "positive_reply",
    "reply",
    "referral",
    "forwarded_internally",
    "owner_introduction",
  ]);
  const bouncedCount = data.items.filter((item) => item.outcome === "bounce").length;
  const repliedCount = data.items.filter(
    (item) => item.outcome != null && REPLY_OUTCOMES.has(item.outcome),
  ).length;
  const generateAllDrafts = async () => {
    const remaining = previewableItems.filter(
      (item) => !isEmailSent(item) && !storedAgentDraftStep(item) && draftStatuses[item.id] !== "completed",
    );
    if (remaining.length === 0) return;
    setIsGeneratingAllDrafts(true);
    setBulkDraftError(null);
    let failed = 0;
    let nextIndex = 0;
    const workerCount = Math.min(3, remaining.length);
    const generateOne = async (item: LeadGenBatchItem) => {
      setDraftStatuses((prev) => ({ ...prev, [item.id]: "generating" }));
      try {
        await Promise.all([
          qc.fetchQuery({
            queryKey: sequencePreviewQueryKey(item, selectedComposerVariantKey),
            queryFn: () => previewSequence(
              item.contact_id,
              item.template_key,
              sequencePreviewOptions(item, selectedComposerVariantKey),
            ),
            staleTime: 5 * 60_000,
          }),
          qc.fetchQuery({
            queryKey: contactDetailQueryKey(item),
            queryFn: () => getContactDetail(item.contact_id, item.template_key),
            staleTime: 5 * 60_000,
          }),
        ]);
        setDraftStatuses((prev) => ({ ...prev, [item.id]: "completed" }));
      } catch {
        failed += 1;
        setDraftStatuses((prev) => ({ ...prev, [item.id]: "failed" }));
      }
    };
    const runWorker = async () => {
      while (nextIndex < remaining.length) {
        const item = remaining[nextIndex];
        nextIndex += 1;
        await generateOne(item);
      }
    };
    await Promise.all(Array.from({ length: workerCount }, runWorker));
    if (failed > 0) {
      setBulkDraftError(`${failed} draft${failed === 1 ? "" : "s"} could not be generated.`);
    }
    setIsGeneratingAllDrafts(false);
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-neutral-900">{data.batch.name}</h2>
            <div className="mt-1 text-xs text-neutral-500">
              {data.batch.id} - Composer: {formatComposerKey(data.batch.template_key)} - Policy: {data.batch.policy_version}
            </div>
          </div>
          <StatusPill status={data.batch.status} className="ml-auto" />
        </div>
        {isOlderPlan && !isCompletedRun && hasQueueableItems && (
          <div className="border-b border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            This is an older generated plan with {data.items.length} actions. The
            current daily send budget is {dailyEmailBudget}; generate today's
            action plan to create a fresh list for that budget.
          </div>
        )}
        {isCompletedRun ? (
          /* Completed run: read-only history summary + experiment rollup.
             Individual sent emails live in Comms, so we don't duplicate them. */
          <>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 text-sm">
              <span className="text-neutral-900">
                <span className="font-semibold">{counts.started}</span> sent
              </span>
              <span className="text-neutral-500">{bouncedCount} bounced</span>
              <span className={repliedCount > 0 ? "font-medium text-emerald-700" : "text-neutral-500"}>
                {repliedCount} replied
              </span>
              <span className="ml-auto flex items-center gap-3 text-xs">
                <span className="text-neutral-400">
                  Completed · {formatCaliforniaDate(data.batch.created_at)}
                </span>
                <Link href="/comms" className="font-medium text-neutral-600 hover:text-neutral-900">
                  View emails in Comms →
                </Link>
              </span>
            </div>
            <CompletedRunRollup items={data.items} />
          </>
        ) : (
          <>
        {/* Essential counts only */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 text-sm">
          <span className="text-neutral-900">
            <span className="font-semibold">{data.items.length}</span> drafts
          </span>
          <span className="text-neutral-900">
            <span className="font-semibold">{counts.started}</span> sent
          </span>
          <span className="text-neutral-500">
            {counts.observed} observed
          </span>
        </div>

        {/* Single primary action */}
        <div className="flex flex-wrap items-center gap-3 border-t border-neutral-100 px-4 py-3">
          <button
            type="button"
            onClick={() => {
              if (window.confirm(`Approve and send this batch starting ${scheduledStartAt || "now"} California time, staggered over 60 minutes? Email sending requires ALLOW_SEQUENCE_SEND=true.`)) {
                approve.mutate(true);
              }
            }}
            disabled={!((canApprove && hasQueueableItems) || canQueue) || approve.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Approve &amp; send
          </button>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="inline-flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-neutral-800"
          >
            Advanced
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
          </button>
          {sentItems.length > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-sky-700">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {sentItems.length} sent
            </span>
          )}
          {propose.data && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Proposal {propose.data.id.slice(0, 8)} created
            </span>
          )}
          {bulkDraftError && (
            <span className="inline-flex items-center text-xs text-red-600">
              {bulkDraftError}
            </span>
          )}
        </div>

        {/* Advanced: overrides the daily pipeline normally handles */}
        {showAdvanced && (
          <div className="space-y-3 border-t border-neutral-100 bg-neutral-50 px-4 py-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-xs font-medium text-neutral-600">
                Start sending (California)
                <input
                  type="datetime-local"
                  value={scheduledStartAt}
                  onChange={(e) => setScheduledStartAt(e.target.value)}
                  className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-900"
                />
                <span className="mt-1 block font-normal text-neutral-400">
                  America/Los_Angeles, staggered over 60 minutes.
                </span>
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-neutral-600">
                Composer variant (override A/B)
                <select
                  value={selectedComposerVariantKey}
                  onChange={(event) => {
                    setSelectedComposerVariantKey(event.target.value);
                    setBulkDraftError(null);
                  }}
                  disabled={composerVariants.isLoading}
                  className="rounded-md border border-neutral-200 bg-white px-2 py-2 text-sm font-medium text-neutral-800 disabled:opacity-60"
                >
                  <option value="">Auto A/B assignment</option>
                  {activeComposerVariants.map((variant) => (
                    <option key={variant.key} value={variant.key}>
                      {variant.label}
                    </option>
                  ))}
                </select>
                <span className="font-normal text-neutral-400">
                  {selectedComposerVariant
                    ? `Pins ${selectedComposerVariant.key}.`
                    : "Deterministic A/B per contact (default)."}
                </span>
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => approve.mutate(false)}
                disabled={!canApprove || approve.isPending}
                className="inline-flex items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
                Approve without sending
              </button>
              <button
                type="button"
                onClick={generateAllDrafts}
                disabled={isGeneratingAllDrafts || previewableItems.length === 0}
                className="inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
              >
                {isGeneratingAllDrafts ? <Loader2 className="h-4 w-4 animate-spin" /> : <MailPlus className="h-4 w-4" />}
                Regenerate drafts
              </button>
              <button
                type="button"
                onClick={() => propose.mutate()}
                disabled={propose.isPending}
                className="inline-flex items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                {propose.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BrainCircuit className="h-4 w-4" />}
                Generate learning proposal
              </button>
              {previewableItems.length > 0 && (
                <span className="inline-flex items-center text-xs text-neutral-500">
                  {completedDraftCount}/{previewableItems.length} drafts generated
                </span>
              )}
            </div>
          </div>
        )}
          </>
        )}
      </section>

      {!isCompletedRun && (
        <DailyActionPlan
          items={data.items}
          draftStatuses={draftStatuses}
          sentItems={sentItems}
          onObserve={setObserveItem}
          onPreview={setPreviewItem}
        />
      )}
      <ObservationsPanel observations={data.observations} />

      {previewItem && (
        <PreviewModal
          item={previewItem}
          composerVariantKey={selectedComposerVariantKey}
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

const ROLLUP_REPLY_OUTCOMES = new Set([
  "positive_reply",
  "reply",
  "referral",
  "forwarded_internally",
  "owner_introduction",
]);

type RollupRow = { key: string; sent: number; replied: number; bounced: number };

function rollupBy(
  items: LeadGenBatchItem[],
  keyFn: (item: LeadGenBatchItem) => string,
): RollupRow[] {
  const map = new Map<string, RollupRow>();
  for (const item of items) {
    const key = keyFn(item) || "—";
    const row = map.get(key) ?? { key, sent: 0, replied: 0, bounced: 0 };
    if (isEmailSent(item)) row.sent += 1;
    if (item.outcome === "bounce") row.bounced += 1;
    else if (item.outcome && ROLLUP_REPLY_OUTCOMES.has(item.outcome)) row.replied += 1;
    map.set(key, row);
  }
  return Array.from(map.values()).sort((a, b) => b.sent - a.sent);
}

function RollupTable({ title, rows }: { title: string; rows: RollupRow[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-neutral-500">{title}</div>
      <table className="w-full text-left text-xs">
        <thead className="text-neutral-400">
          <tr>
            <th className="py-1 font-normal">{title.replace("By ", "")}</th>
            <th className="py-1 text-right font-normal">sent</th>
            <th className="py-1 text-right font-normal">replied</th>
            <th className="py-1 text-right font-normal">bounced</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-neutral-100">
              <td className="py-1 font-medium text-neutral-800">{row.key}</td>
              <td className="py-1 text-right text-neutral-700">{row.sent}</td>
              <td className={`py-1 text-right ${row.replied > 0 ? "font-medium text-emerald-700" : "text-neutral-400"}`}>
                {row.replied}
              </td>
              <td className={`py-1 text-right ${row.bounced > 0 ? "font-medium text-rose-700" : "text-neutral-400"}`}>
                {row.bounced}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompletedRunRollup({ items }: { items: LeadGenBatchItem[] }) {
  const byVariant = rollupBy(items, (item) =>
    String(reasonValue(item, "last_sent_composer_variant_key") || "baseline"),
  );
  const byPersona = rollupBy(items, (item) => item.persona || "unknown");
  return (
    <div className="grid gap-5 border-t border-neutral-100 px-4 py-3 sm:grid-cols-2">
      <RollupTable title="By A/B variant" rows={byVariant} />
      <RollupTable title="By persona" rows={byPersona} />
    </div>
  );
}

function DailyActionPlan({
  items,
  draftStatuses,
  sentItems,
  onObserve,
  onPreview,
}: {
  items: LeadGenBatchItem[];
  draftStatuses: Record<string, DraftGenerationStatus>;
  sentItems: LeadGenBatchItem[];
  onObserve: (item: LeadGenBatchItem) => void;
  onPreview: (item: LeadGenBatchItem) => void;
}) {
  const sentItemIds = useMemo(() => new Set(sentItems.map((item) => item.id)), [sentItems]);
  return (
    <section className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-2.5">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Today's action plan
        </h2>
        <span className="text-xs text-neutral-400">{items.length} actions</span>
      </div>
      <div className="divide-y divide-neutral-100">
        {items.map((item) => (
          <article
            key={item.id}
            className={cn(
              "grid min-w-0 gap-3 px-4 py-3 text-sm lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1.35fr)_minmax(180px,0.9fr)_minmax(130px,auto)]",
              sentItemIds.has(item.id) && "bg-sky-50",
              !sentItemIds.has(item.id) && draftStatuses[item.id] === "completed" && "bg-emerald-50",
              !sentItemIds.has(item.id) && storedAgentDraftStep(item) && "bg-emerald-50",
              draftStatuses[item.id] === "generating" && "bg-amber-50",
              draftStatuses[item.id] === "failed" && "bg-red-50",
            )}
          >
            <div className="min-w-0">
              <div className="font-medium text-neutral-900">{item.firm_name}</div>
              <div className="mt-1 break-all text-xs text-neutral-400">{item.pif_id}</div>
              <div className="mt-2 text-xs leading-relaxed text-neutral-600">
                {reasonText(item)}
              </div>
              <ScoreBreakdown item={item} />
            </div>

            <div className="min-w-0">
              <div className="font-medium text-neutral-800">
                {item.contact_name || "Unknown"}
              </div>
              <div className="text-xs text-neutral-500">{item.contact_title || "No title"}</div>
              <div className="mt-1 break-all text-xs text-neutral-500">
                {item.contact_email}
              </div>
              {isEmailSent(item) ? (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800">
                  <CheckCircle2 className="h-3 w-3" />
                  Email sent
                </div>
              ) : canPreviewItem(item) ? (
                <button
                  type="button"
                  onClick={() => onPreview(item)}
                  className="mt-2 inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
                >
                  <MailPlus className="h-3.5 w-3.5" />
                  {previewButtonLabel(item)}
                </button>
              ) : (
                <div className="mt-2 text-xs text-neutral-400">
                  This action opens in its owning workflow.
                </div>
              )}
              {isEmailSent(item) && reasonValue(item, "last_sent_subject") && (
                <div className="mt-1 line-clamp-2 text-[11px] text-sky-700">
                  {reasonValue(item, "last_sent_subject")}
                </div>
              )}
              {!isEmailSent(item) && scheduledSendPt(item) && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-800">
                  <Clock className="h-3 w-3" />
                  Scheduled — sends {scheduledSendPt(item)}
                </div>
              )}
              {!isEmailSent(item) && !scheduledSendPt(item) && (draftStatuses[item.id] === "completed" || storedAgentDraftStep(item)) && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
                  <CheckCircle2 className="h-3 w-3" />
                  Draft generated
                </div>
              )}
              {draftStatuses[item.id] === "generating" && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Generating draft
                </div>
              )}
              {draftStatuses[item.id] === "failed" && (
                <div className="mt-2 inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-medium text-red-700">
                  Draft failed
                </div>
              )}
            </div>

            <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-2">
              <MiniField label="Action" value={actionLabel(item)} />
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
                      run {item.sequence_id.slice(0, 8)}
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

function ScoreBreakdown({ item }: { item: LeadGenBatchItem }) {
  const entries = scoreBreakdownEntries(item);
  if (entries.length === 0) return null;
  const features = selectionFeatures(item);
  const emailQuality = typeof features.email_quality === "string" ? features.email_quality : "";
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex flex-wrap gap-1">
        {entries.map(([key, value]) => (
          <span
            key={key}
            className={cn(
              "inline-flex max-w-full items-center rounded-md border px-1.5 py-0.5 text-[11px] leading-4",
              value >= 0
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-amber-200 bg-amber-50 text-amber-700",
            )}
            title={key}
          >
            <span className="truncate">{formatScoreKey(key)}</span>
            <span className="ml-1 font-mono">{value > 0 ? `+${value}` : value}</span>
          </span>
        ))}
      </div>
      {emailQuality && (
        <div className="text-[11px] text-neutral-400">
          Email quality: {formatScoreKey(emailQuality)}
        </div>
      )}
    </div>
  );
}

function reasonValue(item: LeadGenBatchItem, key: string) {
  const value = item.reason?.[key];
  return typeof value === "string" ? value : "";
}

function selectionFeatures(item: LeadGenBatchItem) {
  const value = item.reason?.selection_features;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function scoreBreakdownEntries(item: LeadGenBatchItem) {
  const value = item.reason?.score_breakdown;
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>)
    .filter((entry): entry is [string, number] => typeof entry[1] === "number")
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, 4);
}

function formatScoreKey(value: string) {
  const parts = value.split(":");
  const label = value ? parts[parts.length - 1] : value;
  return label.replaceAll("_", " ");
}

function actionLabel(item: LeadGenBatchItem) {
  const labels: Record<string, string> = {
    reply_to_inbound: "Reply",
    approve_existing_draft: "Approve draft",
    follow_up: "Follow-up",
    first_touch: "New start",
  };
  const action = actionType(item);
  return labels[action] ?? action.replaceAll("_", " ");
}

function actionType(item: LeadGenBatchItem) {
  return reasonValue(item, "action_type") || "first_touch";
}

function canQueueItem(item: LeadGenBatchItem) {
  const action = actionType(item);
  return action === "first_touch" || action === "follow_up";
}

function canPreviewItem(item: LeadGenBatchItem) {
  const action = actionType(item);
  if (isEmailSent(item)) return false;
  return action === "first_touch" || action === "follow_up" || action === "approve_existing_draft";
}

function previewButtonLabel(item: LeadGenBatchItem) {
  const action = actionType(item);
  if (action === "approve_existing_draft") return "Open draft";
  if (action === "follow_up") return "Open follow-up";
  if (isDynamicComposer(item.template_key)) return "Generate preview";
  return "Preview email";
}

function canSendFromPreview(item: LeadGenBatchItem) {
  const action = reasonValue(item, "action_type") || "first_touch";
  if (isEmailSent(item)) return false;
  if (scheduledSendPt(item)) return false;
  return action === "first_touch" || action === "follow_up" || action === "approve_existing_draft";
}

function isEmailSent(item: LeadGenBatchItem) {
  return Boolean(reasonValue(item, "last_sent_at") || reasonValue(item, "last_sent_message_id"));
}

function scheduledSendPt(item: LeadGenBatchItem): string {
  if (!reasonValue(item, "send_email_action_id")) return "";
  const draft = objectValue(item.reason?.agent_draft);
  const pt = draft && typeof draft.scheduled_for_pt === "string" ? draft.scheduled_for_pt : "";
  return pt;
}

function sequencePreviewQueryKey(item: LeadGenBatchItem, composerVariantKey = "") {
  return [
    "sequence-preview",
    item.contact_id,
    item.template_key,
    reasonValue(item, "notification_id") || reasonValue(item, "operator_notification_id") || "",
    reasonValue(item, "source_id") || "",
    composerVariantKey || "auto",
  ] as const;
}

function contactDetailQueryKey(item: LeadGenBatchItem) {
  return ["contact-detail", item.contact_id, item.template_key] as const;
}

function sequencePreviewOptions(item: LeadGenBatchItem, composerVariantKey = "") {
  return {
    notificationId: reasonValue(item, "notification_id") || reasonValue(item, "operator_notification_id"),
    sourceId: reasonValue(item, "source_id"),
    composerVariantKey: composerVariantKey || undefined,
  };
}

function isDynamicComposer(templateKey: string) {
  return templateKey === DEFAULT_TEMPLATE;
}

function reasonText(item: LeadGenBatchItem) {
  return reasonValue(item, "reason") || "Selected by the daily lead-gen planner.";
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function storedAgentDraftStep(item: LeadGenBatchItem): RenderedSequenceStep | null {
  const draft = objectValue(item.reason?.agent_draft);
  if (!draft) return null;
  const subject = typeof draft.subject === "string" ? draft.subject : "";
  const body = typeof draft.body === "string" ? draft.body : "";
  if (!subject.trim() || !body.trim()) return null;
  return {
    step: 1,
    subject,
    body,
    message_type: "dynamic_lead_email",
    reasoning: typeof draft.rationale === "string" ? draft.rationale : null,
    angle: typeof draft.angle === "string" ? draft.angle : null,
    cta: typeof draft.cta === "string" ? draft.cta : null,
    blog_link_used: typeof draft.blog_link_used === "string" ? draft.blog_link_used : null,
    composer_experiment_key: typeof draft.composer_experiment_key === "string" ? draft.composer_experiment_key : null,
    composer_variant_key: typeof draft.composer_variant_key === "string" ? draft.composer_variant_key : null,
    skill_path: typeof draft.skill_path === "string" ? draft.skill_path : null,
    skill_sha256: typeof draft.skill_sha256 === "string" ? draft.skill_sha256 : null,
    requires_human_review: true,
    risk_flags: Array.isArray(draft.risk_flags) ? draft.risk_flags.map(String) : [],
  };
}

function PreviewModal({
  item,
  composerVariantKey,
  onClose,
}: {
  item: LeadGenBatchItem;
  composerVariantKey: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isDynamic = isDynamicComposer(item.template_key);
  const alreadySent = isEmailSent(item);
  const storedDraft = useMemo(() => storedAgentDraftStep(item), [item]);
  const canSendDraft = canSendFromPreview(item);
  const [draftSubject, setDraftSubject] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [draftTouched, setDraftTouched] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const q = useQuery({
    queryKey: sequencePreviewQueryKey(item, composerVariantKey),
    queryFn: () => previewSequence(item.contact_id, item.template_key, sequencePreviewOptions(item, composerVariantKey)),
    enabled: !alreadySent && !storedDraft,
    staleTime: 5 * 60_000,
  });
  const detail = useQuery({
    queryKey: contactDetailQueryKey(item),
    queryFn: () => getContactDetail(item.contact_id, item.template_key),
    enabled: !alreadySent && !storedDraft,
    staleTime: 5 * 60_000,
  });
  const nextStep = useMemo(() => {
    if (storedDraft) return storedDraft;
    const steps = q.data ?? [];
    const sequence = detail.data?.sequence;
    if (sequence && sequence.current_step >= sequence.steps_total) return undefined;
    const nextStepNumber = sequence ? sequence.current_step + 1 : 1;
    return steps.find((step) => step.step === nextStepNumber) ?? steps[0];
  }, [detail.data?.sequence, q.data, storedDraft]);
  useEffect(() => {
    if (nextStep) {
      setDraftSubject(nextStep.subject);
      setDraftBody(nextStep.body);
      setDraftTouched(false);
    }
  }, [nextStep]);
  const regeneratePreview = async () => {
    if (
      isDynamic &&
      draftTouched &&
      !window.confirm("Regenerate this draft and replace your current edits?")
    ) {
      return;
    }
    setIsRegenerating(true);
    try {
      const [previewResult, detailResult] = await Promise.all([q.refetch(), detail.refetch()]);
      const steps = previewResult.data ?? q.data ?? [];
      const sequence = detailResult.data?.sequence ?? detail.data?.sequence;
      const nextStepNumber = sequence ? sequence.current_step + 1 : 1;
      const freshStep = steps.find((step) => step.step === nextStepNumber) ?? steps[0];
      if (freshStep) {
        setDraftSubject(freshStep.subject);
        setDraftBody(freshStep.body);
        setDraftTouched(false);
      }
    } finally {
      setIsRegenerating(false);
    }
  };
  const sendDraft = useMutation({
    mutationFn: () =>
      sendLeadGenBatchItemDraft(item.id, {
        subject: draftSubject,
        body: draftBody,
        sent_by: "operator",
        composer_experiment_key: nextStep?.composer_experiment_key,
        composer_variant_key: nextStep?.composer_variant_key,
        skill_path: nextStep?.skill_path,
        skill_sha256: nextStep?.skill_sha256,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", item.batch_id] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
        <div className="border-b border-neutral-100 px-5 py-4">
          <h3 className="text-sm font-semibold text-neutral-900">
            Email preview for {item.contact_name || item.firm_name}
          </h3>
          <p className="mt-1 text-xs text-neutral-500">
            {item.contact_email} - {item.firm_name} - Composer: {formatComposerKey(item.template_key)}
          </p>
          {nextStep?.composer_variant_key && (
            <p className="mt-1 text-xs text-neutral-400">
              Skill variant: {nextStep.composer_variant_key}
            </p>
          )}
        </div>
        <div className="overflow-y-auto px-5 py-4">
          {!alreadySent && scheduledSendPt(item) && (
            <div className="mb-3 flex items-center gap-2 rounded-md border border-violet-200 bg-violet-50 px-3 py-3 text-sm text-violet-900">
              <Clock className="h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">Scheduled for auto-send at {scheduledSendPt(item)}.</div>
                <div className="mt-0.5 text-xs">
                  The daemon will send this automatically. To change it, use{" "}
                  <code>actions reschedule</code> / <code>actions cancel</code> or the /actions page —
                  manual send is disabled to prevent a duplicate.
                </div>
              </div>
            </div>
          )}
          {alreadySent ? (
            <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-3 text-sm text-sky-900">
              <div className="font-medium">This email has already been sent.</div>
              {reasonValue(item, "last_sent_subject") && (
                <div className="mt-2 text-xs">
                  Subject: {reasonValue(item, "last_sent_subject")}
                </div>
              )}
              {reasonValue(item, "last_sent_at") && (
                <div className="mt-1 text-xs">
                  Sent at: {formatDate(reasonValue(item, "last_sent_at"))}
                </div>
              )}
            </div>
          ) : q.isLoading || detail.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              {isDynamic ? "Generating draft with composer skill..." : "Rendering preview..."}
            </div>
          ) : q.isError || detail.isError ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              Could not generate this email preview.
            </div>
          ) : (
            <div className="space-y-4">
              <section className="rounded-lg border border-neutral-200">
                <div className="border-b border-neutral-100 bg-neutral-50 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
                  {isDynamic ? "Generated draft" : "Next email to send"}
                </div>
                {nextStep ? (
                  isDynamic ? (
                    <EditableGeneratedDraft
                      step={nextStep}
                      subject={draftSubject}
                      body={draftBody}
                      onSubjectChange={(value) => {
                        setDraftSubject(value);
                        setDraftTouched(true);
                      }}
                      onBodyChange={(value) => {
                        setDraftBody(value);
                        setDraftTouched(true);
                      }}
                    />
                  ) : (
                    <RenderedEmail step={nextStep} />
                  )
                ) : (
                  <div className="px-3 py-4 text-sm text-neutral-500">
                    No remaining email for this outreach run.
                  </div>
                )}
              </section>
              {!isDynamic && (
                <section className="rounded-lg border border-neutral-200">
                  <div className="border-b border-neutral-100 bg-neutral-50 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-neutral-500">
                    Full outreach run
                  </div>
                  <div className="divide-y divide-neutral-100">
                    {(q.data ?? []).map((step) => (
                      <RenderedEmail key={step.step} step={step} compact />
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-neutral-100 px-5 py-3">
          {nextStep && !storedDraft && (
            <button
              type="button"
              onClick={regeneratePreview}
              disabled={isRegenerating || sendDraft.isPending}
              className="mr-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {isRegenerating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {isDynamic ? "Regenerate draft" : "Refresh preview"}
            </button>
          )}
          {canSendDraft && nextStep && (
            <button
              type="button"
              onClick={() => sendDraft.mutate()}
              disabled={!draftSubject.trim() || !draftBody.trim() || sendDraft.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {sendDraft.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              Send email
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            Close
          </button>
          {sendDraft.isError && (
            <div className="basis-full text-right text-xs text-red-600">
              {sendDraft.error instanceof Error
                ? sendDraft.error.message
                : "Could not send this email."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function EditableGeneratedDraft({
  step,
  subject,
  body,
  onSubjectChange,
  onBodyChange,
}: {
  step: RenderedSequenceStep;
  subject: string;
  body: string;
  onSubjectChange: (value: string) => void;
  onBodyChange: (value: string) => void;
}) {
  return (
    <div className="space-y-4 px-3 py-3 text-sm">
      <div className="rounded-md bg-neutral-50 px-3 py-2">
        <div className="text-xs font-medium uppercase tracking-wider text-neutral-400">
          Rationale
        </div>
        <p className="mt-1 text-sm leading-6 text-neutral-700">
          {step.reasoning || "No rationale was returned by the composer."}
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-neutral-500">
          {step.angle && <span>Angle: {step.angle}</span>}
          {step.cta && <span>CTA: {step.cta}</span>}
          {step.blog_link_used && <span>Blog: {step.blog_link_used}</span>}
        </div>
      </div>
      <label className="block text-xs font-medium uppercase tracking-wider text-neutral-400">
        Subject
        <input
          value={subject}
          onChange={(e) => onSubjectChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium normal-case tracking-normal text-neutral-900"
        />
      </label>
      <label className="block text-xs font-medium uppercase tracking-wider text-neutral-400">
        Body
        <textarea
          value={body}
          onChange={(e) => onBodyChange(e.target.value)}
          rows={12}
          className="mt-1 w-full rounded-md border border-neutral-200 px-3 py-2 font-sans text-sm normal-case leading-6 tracking-normal text-neutral-800"
        />
      </label>
    </div>
  );
}

function RenderedEmail({
  step,
  compact = false,
  hideMeta = false,
}: {
  step: RenderedSequenceStep;
  compact?: boolean;
  hideMeta?: boolean;
}) {
  return (
    <div className="space-y-2 px-3 py-3 text-sm">
      {!hideMeta && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
            Step {step.step}
          </span>
          <span className="text-xs text-neutral-400">{step.message_type}</span>
        </div>
      )}
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
    started: "bg-sky-50 text-sky-700",
    skipped: "bg-neutral-100 text-neutral-500",
    rejected: "bg-red-50 text-red-700",
  };
  const labels: Record<string, string> = {
    sequencing: "queued",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        styles[status] ?? "bg-neutral-100 text-neutral-600",
        className,
      )}
    >
      {labels[status] ?? status}
    </span>
  );
}

function formatComposerKey(value: string) {
  return value.replaceAll("_", " ");
}

function clampDailyEmailBudget(value: number) {
  if (!Number.isFinite(value)) return DEFAULT_DAILY_EMAIL_BUDGET;
  return Math.max(1, Math.min(200, Math.trunc(value)));
}

function defaultDailyPlanName(dailyEmailBudget: number) {
  return `Daily action plan - ${clampDailyEmailBudget(dailyEmailBudget)} emails`;
}

function californiaDateKey(value: Date | string | null | undefined) {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: CALIFORNIA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}

function selectBatchForDisplay(batches: LeadGenBatch[]) {
  const sorted = [...batches].sort(
    (a, b) => dateTimeMs(b.created_at) - dateTimeMs(a.created_at),
  );
  return (
    sorted.find((batch) => batch.template_key === DEFAULT_TEMPLATE && isCaliforniaToday(batch.created_at)) ??
    sorted.find((batch) => isCaliforniaToday(batch.created_at)) ??
    sorted.find((batch) => batch.template_key === DEFAULT_TEMPLATE) ??
    sorted[0] ??
    null
  );
}

function dateTimeMs(value: string | null | undefined) {
  if (!value) return 0;
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function isCaliforniaToday(value: string | null | undefined) {
  return californiaDateKey(value) === californiaDateKey(new Date());
}

function formatCaliforniaDate(value: string | null | undefined) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("en-US", {
    timeZone: CALIFORNIA_TIME_ZONE,
    month: "short",
    day: "numeric",
    year: "numeric",
  });
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
