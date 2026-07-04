"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  AlertTriangle,
  BrainCircuit,
  CalendarDays,
  ChevronDown,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Eye,
  ExternalLink,
  Loader2,
  MailPlus,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  approveLeadGenBatch,
  approveLeadGenBatchActions,
  classifyLeadGenObservation,
  createLeadGenBatch,
  createLeadGenEmailAgentSlice,
  createLeadGenProposal,
  getContactDetail,
  getComposerVariants,
  getLeadGenBatch,
  getLeadGenDailyEnabled,
  getLeadGenPolicy,
  getLeadGenSendPlan,
  getLeadGenThroughput,
  listLeadGenBatches,
  listLeadGenDailyRuns,
  previewSequence,
  putFirmReviews,
  recomposeLeadGenBatchItemDraft,
  runLeadGenDaily,
  sendLeadGenBatchItemDraft,
  composeBatchItemVariants,
  selectBatchItemVariant,
  type BatchItemVariantDraft,
  setLeadGenDailyEnabled,
  updateLeadGenDailySendBudget,
  type LeadGenPolicy,
  type LeadGenBatch,
  type LeadGenBatchItem,
  type LeadGenDailyRun,
  type LeadGenObservation,
  type LeadGenSendPlan,
  type LeadGenSendPlanItem,
  type LeadGenThroughput,
  type LeadGenThroughputHeldFirm,
  type RenderedSequenceStep,
  type ComposerSkillVariant,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULT_TEMPLATE = "possible_minds_dynamic";
// Operator is in India: all displayed dates/times and day-boundary logic use IST.
// The US-recipient send window (when firms are at their desks) is enforced in the
// backend; here we only convert what the operator sees and the times they pick.
const DISPLAY_TIME_ZONE = "Asia/Kolkata";
const SEND_TIME_ZONE = "America/Los_Angeles";
const DEFAULT_DAILY_EMAIL_BUDGET = 50;
const ZOHO_DAILY_EMAIL_CAP = 20;
type DraftGenerationStatus = "generating" | "completed" | "failed";
type LeadGenWorkspaceView = "queue" | "batches";
type QueuePreviewTarget = { batchId: string; batchItemId: string };

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
  const router = useRouter();
  const searchParams = useSearchParams();
  const [batchId, setBatchId] = useState<string>("");
  const [dailyEmailBudget, setDailyEmailBudget] = useState(DEFAULT_DAILY_EMAIL_BUDGET);
  const [resendDailyEmailBudget, setResendDailyEmailBudget] = useState(
    DEFAULT_DAILY_EMAIL_BUDGET - ZOHO_DAILY_EMAIL_CAP,
  );
  const [selectedSendDate, setSelectedSendDate] = useState(() => sendDateKey(new Date()));
  const [queuePreviewTarget, setQueuePreviewTarget] = useState<QueuePreviewTarget | null>(null);
  const requestedBatchId = searchParams.get("batch") || "";
  const requestedItemId = searchParams.get("item") || "";
  const requestedContactId = searchParams.get("contact") || "";
  const requestedNotificationId = searchParams.get("notification") || "";
  const hasBatchRequest = Boolean(
    requestedBatchId || requestedItemId || requestedContactId || requestedNotificationId,
  );
  const requestedWorkspaceView: LeadGenWorkspaceView =
    searchParams.get("view") === "batches" || hasBatchRequest ? "batches" : "queue";
  const policy = useQuery({
    queryKey: ["lead-gen-policy"],
    queryFn: getLeadGenPolicy,
  });
  const batches = useQuery({
    queryKey: ["lead-gen-batches", "history"],
    queryFn: () => listLeadGenBatches({ limit: 100 }),
    refetchInterval: 30_000,
  });
  const dailyRuns = useQuery({
    queryKey: ["lead-gen-daily-runs"],
    queryFn: () => listLeadGenDailyRuns(5),
    // Poll fast while a run is in flight so stage progress shows live.
    refetchInterval: (query) => {
      const runs = (query.state.data as { runs?: LeadGenDailyRun[] } | undefined)?.runs ?? [];
      const inFlight = runs.some((r) => r.status === "running" || r.status === "pending");
      return inFlight ? 2_500 : 30_000;
    },
  });
  const dailyEnabled = useQuery({
    queryKey: ["lead-gen-daily-enabled"],
    queryFn: getLeadGenDailyEnabled,
    refetchInterval: 30_000,
  });
  const throughput = useQuery({
    queryKey: ["lead-gen-throughput"],
    queryFn: () => getLeadGenThroughput(),
    refetchInterval: 15_000,
  });
  const sendPlan = useQuery({
    queryKey: ["lead-gen-send-plan", selectedSendDate],
    queryFn: () => getLeadGenSendPlan(selectedSendDate),
    refetchInterval: 15_000,
  });

  useEffect(() => {
    if (policy.data?.daily_send_budget) {
      setDailyEmailBudget(clampDailyEmailBudget(policy.data.daily_send_budget));
      setResendDailyEmailBudget(resendBudgetFromPolicy(policy.data));
    }
  }, [policy.data]);

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
    mutationFn: () => updateLeadGenDailySendBudget(
      ZOHO_DAILY_EMAIL_CAP + resendDailyEmailBudget,
      resendDailyEmailBudget,
    ),
    onSuccess: (data) => {
      setDailyEmailBudget(clampDailyEmailBudget(data.daily_send_budget));
      setResendDailyEmailBudget(resendBudgetFromWeights(data.weights));
      qc.invalidateQueries({ queryKey: ["lead-gen-policy"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-throughput"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
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
        scheduled_timezone: DISPLAY_TIME_ZONE,
      });
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
      qc.invalidateQueries({ queryKey: ["operator-notifications-pending"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      setBatchId(data.batch.id);
      router.replace(`/lead-gen?view=batches&batch=${encodeURIComponent(data.batch.id)}`, { scroll: false });
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
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
      setBatchId(data.batch.id);
      router.replace(`/lead-gen?view=batches&batch=${encodeURIComponent(data.batch.id)}`, { scroll: false });
    },
  });
  const runDaily = useMutation({
    mutationFn: ({ dryRun, force, composerVariantKey }: { dryRun: boolean; force: boolean; composerVariantKey?: string }) =>
      runLeadGenDaily({ dry_run: dryRun, force, composer_variant_key: composerVariantKey }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["lead-gen-daily-runs"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-throughput"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
      if (data.batch_id) {
        setBatchId(data.batch_id);
        router.replace(`/lead-gen?view=batches&batch=${encodeURIComponent(data.batch_id)}`, { scroll: false });
      }
    },
  });
  const toggleDaily = useMutation({
    mutationFn: (enabled: boolean) => setLeadGenDailyEnabled(enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-daily-enabled"] });
    },
  });

  const todayDailyRun =
    (dailyRuns.data?.runs ?? []).find((run) => run.run_date === istDateKey(new Date())) ??
    (dailyRuns.data?.runs ?? [])[0] ??
    null;
  const selectBatch = (nextBatchId: string) => {
    setBatchId(nextBatchId);
    router.replace(`/lead-gen?view=batches&batch=${encodeURIComponent(nextBatchId)}`, { scroll: false });
  };
  const openQueue = () => router.replace("/lead-gen", { scroll: false });
  const openBatches = () => {
    router.replace(
      batchId ? `/lead-gen?view=batches&batch=${encodeURIComponent(batchId)}` : "/lead-gen?view=batches",
      { scroll: false },
    );
  };

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
      <ThroughputPanel throughput={throughput.data ?? null} loading={throughput.isLoading} error={throughput.isError} />
      {throughput.data && throughput.data.funnel.sending_today < throughput.data.target && (
        <UnblockPanel
          throughput={throughput.data}
          onRerun={() => runDaily.mutate({ dryRun: false, force: true })}
          rerunning={runDaily.isPending}
        />
      )}
      <LeadGenWorkspaceTabs
        activeView={requestedWorkspaceView}
        onOpenQueue={openQueue}
        onOpenBatches={openBatches}
      />

      {requestedWorkspaceView === "queue" ? (
        <>
          <SelectedDateSendPlanPanel
            selectedDate={selectedSendDate}
            onDateChange={setSelectedSendDate}
            plan={sendPlan.data ?? null}
            loading={sendPlan.isLoading}
            error={sendPlan.isError}
            onOpenDraft={(item) =>
              setQueuePreviewTarget({
                batchId: item.batch_id,
                batchItemId: item.batch_item_id,
              })
            }
          />
          {queuePreviewTarget && (
            <QueueDraftModal
              target={queuePreviewTarget}
              onClose={() => {
                setQueuePreviewTarget(null);
                qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
              }}
            />
          )}
        </>
      ) : (
        <>
          <RunsAndDraftsHeader />
          <div className="grid gap-4 lg:grid-cols-12">
            <aside className="col-span-12 space-y-3 lg:col-span-4 xl:col-span-3">
              <BatchHistoryPanel
                batches={batches.data?.batches ?? []}
                selectedBatchId={batchId}
                loading={batches.isLoading}
                error={batches.isError}
                onSelect={selectBatch}
              />
              <DailyRunPanel
                run={todayDailyRun}
                enabled={Boolean(dailyEnabled.data?.enabled)}
                loading={dailyRuns.isLoading || dailyEnabled.isLoading}
                onToggle={(enabled) => toggleDaily.mutate(enabled)}
                toggling={toggleDaily.isPending}
                onRun={(dryRun, force = false, composerVariantKey) => runDaily.mutate({ dryRun, force, composerVariantKey })}
                running={runDaily.isPending}
                error={runDaily.isError || toggleDaily.isError}
                lastRun={runDaily.data ?? null}
                throughput={throughput.data ?? null}
              />
              <DailySendBudgetPanel
                dailyEmailBudget={dailyEmailBudget}
                resendDailyEmailBudget={resendDailyEmailBudget}
                onResendDailyEmailBudgetChange={(value) => {
                  const resendBudget = clampResendDailyEmailBudget(value);
                  setResendDailyEmailBudget(resendBudget);
                  setDailyEmailBudget(clampDailyEmailBudget(ZOHO_DAILY_EMAIL_CAP + resendBudget));
                }}
                onSave={() => saveBudget.mutate()}
                isSaving={saveBudget.isPending}
                saveError={saveBudget.isError}
                onGenerate={() => createToday.mutate()}
                isGenerating={createToday.isPending}
                generateError={createToday.isError}
              />
              <ManualAgentSlicePanel
                onCreate={() => createAgentSlice.mutate()}
                creating={createAgentSlice.isPending}
                error={createAgentSlice.isError}
              />
            </aside>
            <main className="col-span-12 space-y-4 lg:col-span-8 xl:col-span-9">
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
          <LeadGenProcessExplanation />
        </>
      )}
    </div>
  );
}

function LeadGenWorkspaceTabs({
  activeView,
  onOpenQueue,
  onOpenBatches,
}: {
  activeView: LeadGenWorkspaceView;
  onOpenQueue: () => void;
  onOpenBatches: () => void;
}) {
  const tabs: Array<{
    key: LeadGenWorkspaceView;
    label: string;
    description: string;
    onClick: () => void;
  }> = [
    {
      key: "queue",
      label: "Send Queue",
      description: "Review what is scheduled or sent by PT date.",
      onClick: onOpenQueue,
    },
    {
      key: "batches",
      label: "Runs & Drafts",
      description: "Inspect generated runs, drafts, composer variants, and controls.",
      onClick: onOpenBatches,
    },
  ];
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-1">
      <div className="grid gap-1 sm:grid-cols-2">
        {tabs.map((tab) => {
          const active = tab.key === activeView;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={tab.onClick}
              className={cn(
                "rounded-lg px-4 py-3 text-left transition",
                active
                  ? "bg-neutral-900 text-white shadow-sm"
                  : "text-neutral-700 hover:bg-neutral-50",
              )}
            >
              <div className="text-sm font-semibold">{tab.label}</div>
              <div className={cn("mt-1 text-xs", active ? "text-neutral-300" : "text-neutral-500")}>
                {tab.description}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function RunsAndDraftsHeader() {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-neutral-900">Runs &amp; Drafts</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-neutral-500">
            Review generated runs, inspect drafts, change composer variants, and open the trace when something needs debugging.
          </p>
        </div>
        <Link
          href="/lead-gen"
          className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-600 hover:bg-neutral-50"
        >
          <CalendarDays className="h-4 w-4" />
          Send Queue
        </Link>
      </div>
    </section>
  );
}

// OPERATOR-FACING DESCRIPTION OF THE LIVE PIPELINE. Keep "current" text in sync
// with the actual code whenever the pipeline changes — these are the files that
// back each step:
//   1-2 selection/batch  app/services/lead_gen_daily.py (_select_daily_contacts,
//        _select_contacts, _select_by_persona_quota, _create_daily_batch),
//        app/services/sequence_recommendations.py (recommend_sequence_contacts),
//        app/services/contact_selection.py (score_contact_selection)
//   3   queue/approve     lead_gen_daily.py (_schedule_drafted_items, spread_schedule_times)
//   4   compose           lead_gen_email_agent.py (_compose_batch_items + review-evidence gate),
//        lead_email_composer.py (compose_lead_email),
//        lead_email_composer_variants.py (choose_composer_skill_variant, rendezvous A/B)
//   6   send              action_execution.py / scheduled_action_loop + PHI guard
type LoopBullet = { k?: string; v: string };
type LoopStep = {
  step: string;
  title: string;
  summary: string;
  current: LoopBullet[];
  ideal: string[];
};

const leadGenProcessSteps: LoopStep[] = [
  {
    step: "1",
    title: "Select daily actions",
    summary: "Spend the budget on due follow-ups first, then the best fresh first-touch firms.",
    current: [
      { k: "Trigger", v: "Fires 8 AM IST. Weekdays only (IST); weekends skip unless an operator forces a run." },
      { k: "Fill order", v: "Due sequence follow-ups first (oldest-due first), then fresh first-touch contacts top up the remaining slots." },
      { k: "Candidate pool", v: "recommend_sequence_contacts returns one founder/COO-style contact per untouched firm (pool = budget×10, min 200)." },
      { k: "Suppression", v: "Drops any contact ever sent to or already in a send batch; firms emailed/batched within 14 days (EMAIL_FIRM_COOLDOWN_DAYS); firms with an existing sequence or prior call/SMS; collections/non-payment Front flags; non-law and hard-excluded domains." },
      { k: "Scoring", v: "score_contact_selection — additive, policy-weighted over persona, email quality (direct-named > role > generic), firm fit (PI/legal marker, state), lead source, history (no prior comms, no existing sequence), and capped Front warm-score; risk flags apply large negatives." },
      { k: "Quota + evidence", v: "Persona quotas fill first, then relax. Evidence-aware selection prefers firms with usable Yelp evidence, reserving 3 slots (LEAD_GEN_NO_EVIDENCE_RESERVE) for top no-evidence firms to feed the paste-reviews loop." },
      { k: "Trace", v: "Each item stores its score breakdown, features, signals, suppressions, policy version, and reason." },
    ],
    ideal: [
      "Add Front relationship signals, booked-consult patterns, firm size, website/leadership context, and inferred operational pain.",
      "Rank directly by likelihood of a booked qualified conversation rather than proxy features.",
    ],
  },
  {
    step: "2",
    title: "Create the batch",
    summary: "Persist the ranked plan with full traces; nothing can send yet.",
    current: [
      { k: "Storage", v: "_create_daily_batch writes lead_gen_batches + lead_gen_batch_items as the ranked daily plan." },
      { k: "Per item", v: "Carries an action type — reply_to_inbound, approve_existing_draft, follow_up, or first_touch — plus the full selection trace (score breakdown, features, signals, suppressions, persona, policy version)." },
      { k: "Safety", v: "No email can be sent at this stage; the batch is just the explained plan." },
    ],
    ideal: [
      "Attach a recommendation-evidence packet per firm.",
      "Separate eligible, suppressed, already-contacted, and needs-review candidates as first-class buckets.",
    ],
  },
  {
    step: "3",
    title: "Queue and approve",
    summary: "Spread sends across the window; auto-approve when enabled.",
    current: [
      { k: "Scheduling", v: "_schedule_drafted_items spreads drafts across the US-morning window (9:30 PM–12 AM IST / 9–11:30 AM PT) via spread_schedule_times — one send_email action per draft." },
      { k: "Autonomous ON", v: "Writes the hash-bound approval block via approve_lead_gen_batch_send_actions (same path as the manual Approve & send), so each action is created already-approved and fires without a click." },
      { k: "Autonomous OFF", v: "Actions wait for operator approval." },
      { k: "Always", v: "The send still passes the execution-time policy and PHI egress guard." },
    ],
    ideal: [
      "A versioned daily operating policy that decides auto-create vs. manual approval per batch.",
      "Enforce daily caps, sender/domain limits, cooldowns, and suppressions as explicit gates before queueing.",
    ],
  },
  {
    step: "4",
    title: "Compose each email",
    summary: "Gate on review evidence, pick the skill variant, draft subject/body.",
    current: [
      { k: "Evidence gate", v: "First-touch items with no outreach-usable Yelp evidence of the allowed kinds (default complaint/praise/fact) are HELD (awaiting_review_evidence) and stay selected so the Unblock panel prompts for reviews — no draft until evidence lands." },
      { k: "Default variant", v: "First-touch drafts use the angle-aware review-evidence variant (LEAD_GEN_FIRST_TOUCH_VARIANT), framing the hook by the primary evidence kind; falls back to baseline when none. Follow-ups keep their sequence variant." },
      { k: "Skill selection", v: "An explicit composer_variant_key (preview Compare-variants) always wins; otherwise choose_composer_skill_variant assigns an A/B arm by rendezvous hashing over active variants with allocation_weight > 0, weighted and keyed by contact — stable as variants are added (weight-0 = forcible by key, excluded from random A/B)." },
      { k: "Context", v: "compose_lead_email builds context from the contact, firm, prior outbound + inbound emails, booked-consult patterns, optional blog links, the selected review-evidence quote, and the selection trace, then calls the chosen SKILL.md for subject/body JSON." },
      { k: "Resilience", v: "A compose failure is caught and held (compose_error) so one bad item never strands the rest of the batch." },
    ],
    ideal: [
      "Feed the composer Front workflow signals, CRM state, firm-size/leadership intelligence, and website evidence.",
      "Let reviewed outcomes update the SKILL.md examples and variant weights over time.",
    ],
  },
  {
    step: "5",
    title: "Review before send",
    summary: "Inspect, edit, or unblock before anything goes out.",
    current: [
      { k: "When", v: "Available for edited/manual drafts and for any run with autonomous send off." },
      { k: "Shows", v: "Firm + contact context, editable subject/body, rationale, angle, CTA, blog link, the selected review-evidence quote, and model/variant metadata." },
      { k: "Unblock", v: "The Unblock panel surfaces held firms with their evidence status so reviews can be pasted inline." },
    ],
    ideal: [
      "Also show the exact evidence packet, policy constraints, risk flags, prior touches, deliverability warnings, and alternate drafts.",
      "Turn every approval, edit, and rejection reason into a learning observation.",
    ],
  },
  {
    step: "6",
    title: "Send and advance",
    summary: "The scheduler fires approved sends and logs everything.",
    current: [
      { k: "Daemon", v: "scheduled_action_loop (~30s tick) picks up approved actions whose scheduled time has arrived." },
      { k: "Guard", v: "Re-runs the policy + PHI egress guard at execution time, then sends through the configured email transport." },
      { k: "Records", v: "Writes email_logs, records action-execution evidence, advances the sequence step, and emits a send observation." },
      { k: "Stamping", v: "Each action carries its composer experiment + variant key, skill path/sha, and brief version." },
    ],
    ideal: [
      "Also attach policy version, sender identity, and full render metadata so each outcome traces to the exact decision behind it.",
    ],
  },
  {
    step: "7",
    title: "Observe feedback",
    summary: "Pull replies and events back into the loop.",
    current: [
      { k: "Sources", v: "Zoho inbound replies, Resend delivery events (when configured), manual observations, operator notifications, and booked consults." },
      { k: "Effect", v: "Replies pause the outreach run and create a review task; observations link back to the batch item and its composer variant." },
    ],
    ideal: [
      "Add automated polling, a production Resend webhook, Front read-only ingestion, calendar lifecycle events, CRM/deal outcomes, and landing-page analytics.",
      "Normalize into one observation record across all sources.",
    ],
  },
  {
    step: "8",
    title: "Learn and update policy",
    summary: "Feedback informs proposals; updates stay operator-driven.",
    current: [
      { k: "Exists", v: "Observations, proposal generation, and a composer A/B report (beta-binomial P(beats baseline) on opens/replies per variant×persona)." },
      { k: "Gap", v: "Scoring weights, copy doctrine, skill examples, sender strategy, suppression rules, and policy versions are not yet auto-updated — changes are operator-driven." },
    ],
    ideal: [
      "Aggregate feedback into human-reviewed proposals adjusting weights, suppressions, cadence, blog-link choices, composer instructions/examples, and policy versions.",
      "Apply only after approval until there's enough evidence for low-risk automation.",
    ],
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
              className="grid gap-3 px-4 py-4 text-sm xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]"
            >
              <div className="flex min-w-0 items-start gap-3">
                <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-neutral-900 text-xs font-semibold text-white">
                  {item.step}
                </span>
                <div className="min-w-0">
                  <div className="font-medium text-neutral-900">{item.title}</div>
                  <p className="mt-0.5 text-xs leading-snug text-neutral-500">{item.summary}</p>
                </div>
              </div>
              <div className="min-w-0 rounded-md bg-neutral-50 px-3 py-2.5">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
                  Now
                </div>
                <LoopBulletList bullets={item.current} tone="now" />
              </div>
              <div className="min-w-0 rounded-md bg-emerald-50 px-3 py-2.5">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-emerald-700">
                  Ideal
                </div>
                <LoopBulletList
                  bullets={item.ideal.map((v) => ({ v }))}
                  tone="ideal"
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function LoopBulletList({
  bullets,
  tone,
}: {
  bullets: LoopBullet[];
  tone: "now" | "ideal";
}) {
  return (
    <ul className="space-y-1.5">
      {bullets.map((bullet, index) => (
        <li
          key={index}
          className={cn(
            "flex gap-2 text-xs leading-relaxed",
            tone === "ideal" ? "text-emerald-900" : "text-neutral-700",
          )}
        >
          <span
            className={cn(
              "mt-[6px] h-1 w-1 flex-none rounded-full",
              tone === "ideal" ? "bg-emerald-500" : "bg-neutral-400",
            )}
          />
          <span>
            {bullet.k && (
              <span
                className={cn(
                  "font-semibold",
                  tone === "ideal" ? "text-emerald-950" : "text-neutral-900",
                )}
              >
                {bullet.k}:{" "}
              </span>
            )}
            {bullet.v}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SafetyBand() {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <ShieldCheck className="h-4 w-4" />
      <span className="font-medium">Autonomous send is ON.</span>
      <span className="text-amber-800">
        Composed first-touch drafts auto-approve and send in the US-morning
        window (9:30 PM–12 AM IST / 9–11:30 AM PT). Guards still apply:
        deterministic PHI patterns, send window, deliverability breaker.
      </span>
    </div>
  );
}

function ThroughputPanel({
  throughput,
  loading,
  error,
}: {
  throughput: LeadGenThroughput | null;
  loading: boolean;
  error: boolean;
}) {
  const funnel = throughput?.funnel;
  const target = throughput?.target ?? DEFAULT_DAILY_EMAIL_BUDGET;
  const stages = [
    { key: "selected", label: "Selected", value: funnel?.selected ?? 0 },
    { key: "with_evidence", label: "With evidence", value: funnel?.with_evidence ?? 0 },
    { key: "composed", label: "Composed", value: funnel?.composed ?? 0 },
    { key: "sending_today", label: "Sending today", value: funnel?.sending_today ?? 0 },
    { key: "target", label: "Target", value: target },
  ];
  const collapseKey = firstCollapseStage(stages);
  const verdict = throughput?.verdict;
  const onTrack = Boolean(verdict?.will_hit_target);
  const sentLine = throughput
    ? `Yesterday: ${throughput.history.yesterday_sent} sent · 7-day: ${throughput.history.seven_day_sent} / ${throughput.target * 7}`
    : "Yesterday: - sent · 7-day: -";
  const providerLine = throughput?.provider_transport?.providers
    ?.map((provider) => `${transportLabel(provider.transport)} ${provider.sent_today}/${provider.cap}`)
    .join(" · ");

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-4 py-3">
        <div>
          <h2 className="text-base font-semibold text-neutral-900">Daily throughput</h2>
          <div className="mt-0.5 text-xs text-neutral-500">
            {throughput?.run_date ?? istDateKey(new Date())} · run {throughput?.run_status ?? "loading"}
          </div>
        </div>
        <span
          className={cn(
            "ml-auto inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
            throughput?.auto_send_on ? "bg-emerald-100 text-emerald-800" : "bg-neutral-100 text-neutral-600",
          )}
        >
          Auto-send: {throughput?.auto_send_on ? "ON" : "OFF"}
        </span>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-neutral-400" />}
      </div>
      <div className="space-y-4 px-4 py-4">
        <div className="grid gap-2 md:grid-cols-5">
          {stages.map((stage, index) => (
            <div
              key={stage.key}
              className={cn(
                "rounded-lg border px-3 py-3",
                collapseKey === stage.key
                  ? "border-red-200 bg-red-50"
                  : onTrack && stage.key === "sending_today"
                    ? "border-emerald-200 bg-emerald-50"
                    : "border-neutral-200 bg-neutral-50",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
                  {stage.label}
                </div>
                {index < stages.length - 1 && (
                  <span className="text-xs text-neutral-300">→</span>
                )}
              </div>
              <div
                className={cn(
                  "mt-2 text-2xl font-semibold",
                  collapseKey === stage.key ? "text-red-700" : "text-neutral-900",
                )}
              >
                {stage.value}
              </div>
            </div>
          ))}
        </div>
        {error ? (
          <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            Could not load the throughput funnel.
          </div>
        ) : onTrack ? (
          <div className="flex flex-wrap items-center gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            <CheckCircle2 className="h-4 w-4" />
            On track. {funnel?.sending_today ?? 0} sending today.
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
            <AlertTriangle className="h-4 w-4" />
            {(funnel?.sending_today ?? 0)} of {target} will send today. Blocker: {blockerText(verdict?.blocker)}.
          </div>
        )}
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-neutral-500">
          <span>{sentLine}</span>
          {providerLine && <span>{providerLine}</span>}
        </div>
      </div>
    </section>
  );
}

function transportLabel(value: string) {
  if (value === "zoho_api") return "Zoho";
  if (value === "resend") return "Resend";
  return value;
}

function ChannelBadge({
  item,
  className,
}: {
  item: LeadGenBatchItem;
  className?: string;
}) {
  const plan = item.predicted_transport;
  if (!plan?.channel) return null;
  const channel = plan.channel;
  let label = "";
  let tone = "bg-neutral-100 text-neutral-600";
  if (channel.startsWith("sent:")) {
    label = `sent via ${transportLabel(channel.slice("sent:".length))}`;
    tone = "bg-neutral-100 text-neutral-500";
  } else if (channel === "zoho_api" || channel === "resend") {
    label = transportLabel(channel);
    tone = channel === "zoho_api"
      ? "bg-sky-100 text-sky-800"
      : "bg-emerald-100 text-emerald-800";
  } else if (channel === "over_budget") {
    label = "over budget";
    tone = "bg-amber-100 text-amber-800";
  } else {
    label = transportLabel(channel);
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        tone,
        className,
      )}
      title={plan.scheduled_for ? `Scheduled ${formatDate(plan.scheduled_for)}` : undefined}
    >
      {label}
    </span>
  );
}

function UnblockPanel({
  throughput,
  onRerun,
  rerunning,
}: {
  throughput: LeadGenThroughput;
  onRerun: () => void;
  rerunning: boolean;
}) {
  const held = throughput.held_firms;
  return (
    <section className="rounded-xl border border-red-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-red-100 bg-red-50 px-4 py-3">
        <div>
          <h2 className="text-base font-semibold text-red-950">Unblock today</h2>
          <div className="mt-0.5 text-sm text-red-800">
            Paste reviews for not-yet-covered firms.
          </div>
        </div>
        <div className="ml-auto text-xs font-medium text-red-900">
          Est. sends after re-run: {throughput.funnel.with_evidence}
        </div>
        <button
          type="button"
          onClick={onRerun}
          disabled={rerunning}
          className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
        >
          {rerunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Re-run now
        </button>
      </div>
      <div className="divide-y divide-neutral-100">
        {held.length === 0 ? (
          <div className="px-4 py-4 text-sm text-neutral-500">
            No held firms in the current run.
          </div>
        ) : (
          held.slice(0, 20).map((firm) => (
            <UnblockFirmRow key={`${firm.pif_id}:${firm.contact_email}`} firm={firm} />
          ))
        )}
      </div>
    </section>
  );
}

type ReviewSaveStatus =
  | "idle"
  | "extracting"
  | "evidence"
  | "no_usable"
  | "still_extracting"
  | "error";

function UnblockFirmRow({ firm }: { firm: LeadGenThroughputHeldFirm }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [yelp, setYelp] = useState("");
  const [status, setStatus] = useState<ReviewSaveStatus>("idle");
  const [detail, setDetail] = useState("");
  const saveReviews = useMutation({
    mutationFn: async () => {
      setStatus("extracting");
      setDetail("");
      await putFirmReviews(firm.pif_id, { yelp });
      // Extraction is a background gateway call; long reviews can take 20-30s.
      // Poll evidence_status (not just has_usable_evidence) so we report the
      // true terminal state instead of a premature "no usable quote".
      for (let attempt = 0; attempt < 14; attempt += 1) {
        await sleep(2500);
        const fresh = await qc.fetchQuery({
          queryKey: ["lead-gen-throughput"],
          queryFn: () => getLeadGenThroughput(),
        });
        const updated = fresh.held_firms.find((row) => row.pif_id === firm.pif_id);
        // No longer held -> it composed; treat as success.
        if (!updated) return { status: "evidence" as const, detail: "" };
        if (updated.evidence_status === "usable" || updated.has_usable_evidence) {
          return { status: "evidence" as const, detail: "" };
        }
        if (updated.evidence_status === "extracted_no_usable") {
          return { status: "no_usable" as const, detail: updated.evidence_detail || "" };
        }
        // "extracting" / "none" -> extraction still in flight; keep polling.
      }
      return { status: "still_extracting" as const, detail: "" };
    },
    onSuccess: (result) => {
      setStatus(result.status);
      setDetail(result.detail);
      qc.invalidateQueries({ queryKey: ["lead-gen-throughput"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-daily-runs"] });
      if (result.status === "evidence") setOpen(false);
    },
    onError: () => setStatus("error"),
  });

  return (
    <div className="px-4 py-3">
      <div className="grid gap-3 text-sm lg:grid-cols-[64px_minmax(0,1.2fr)_90px_160px_auto] lg:items-center">
        <div className="text-xs font-mono text-neutral-500">#{firm.rank}</div>
        <div className="min-w-0">
          <div className="truncate font-medium text-neutral-900">{firm.firm_name}</div>
          <div className="mt-0.5 truncate text-xs text-neutral-500">
            {firm.persona || "unknown"} · {firm.contact_name || "Unknown"} · {firm.contact_email || "no email"}
          </div>
        </div>
        <div className="text-xs text-neutral-600">
          warm {firm.warm_score ?? "-"}
        </div>
        <ReviewEvidenceBadge firm={firm} />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="inline-flex items-center justify-center rounded-md border border-neutral-200 px-3 py-2 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
        >
          Paste reviews
        </button>
      </div>
      {open && (
        <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
          <textarea
            value={yelp}
            onChange={(event) => setYelp(event.target.value)}
            rows={5}
            placeholder="Paste Yelp review text for this firm"
            className="min-h-32 w-full rounded-md border border-neutral-200 px-3 py-2 text-sm text-neutral-900 placeholder:text-neutral-400"
          />
          <div className="flex flex-col items-start gap-2">
            <button
              type="button"
              onClick={() => saveReviews.mutate()}
              disabled={!yelp.trim() || saveReviews.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {saveReviews.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </button>
            <div className={cn("text-xs", status === "error" ? "text-red-600" : status === "no_usable" ? "text-amber-700" : "text-neutral-500")}>
              {reviewSaveStatusText(status, detail)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ReviewEvidenceBadge({ firm }: { firm: LeadGenThroughputHeldFirm }) {
  const status =
    firm.evidence_status ||
    (firm.has_usable_evidence
      ? "usable"
      : firm.has_raw_reviews
        ? "extracted_no_usable"
        : "none");
  if (status === "usable") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-800">
        <CheckCircle2 className="h-3.5 w-3.5" />
        evidence
      </span>
    );
  }
  if (status === "extracting") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-1 text-xs font-medium text-sky-800">
        <Clock className="h-3.5 w-3.5" />
        extracting...
      </span>
    );
  }
  if (status === "extracted_no_usable") {
    return (
      <span
        title={firm.evidence_detail || "Extracted, but no quote is usable for outreach."}
        className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-800"
      >
        <AlertTriangle className="h-3.5 w-3.5" />
        extracted · no usable quote
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-1 text-xs font-medium text-red-800">
      <AlertTriangle className="h-3.5 w-3.5" />
      no reviews
    </span>
  );
}

function blockerText(blocker: string | undefined) {
  if (blocker === "no_review_evidence") return "no selected firm has usable reviews";
  if (blocker === "below_target") return "below target";
  return "none";
}

function firstCollapseStage(stages: Array<{ key: string; value: number }>) {
  for (let i = 1; i < stages.length; i += 1) {
    const prev = stages[i - 1];
    const current = stages[i];
    if (current.key === "target") continue;
    if (prev.value > 0 && current.value < prev.value) return current.key;
  }
  return "";
}

function reviewSaveStatusText(status: ReviewSaveStatus, detail?: string) {
  if (status === "extracting") return "extracting...";
  if (status === "evidence") return "evidence found - will compose on next run";
  if (status === "no_usable") return `extracted, no usable quote${detail ? `: ${detail}` : ""}`;
  if (status === "still_extracting") return "still extracting - refresh in a moment";
  if (status === "error") return "could not save reviews";
  return "";
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function BatchHistoryPanel({
  batches,
  selectedBatchId,
  loading,
  error,
  onSelect,
}: {
  batches: LeadGenBatch[];
  selectedBatchId: string;
  loading: boolean;
  error: boolean;
  onSelect: (batchId: string) => void;
}) {
  const groups = useMemo(() => groupBatchesByDate(batches), [batches]);

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-3">
        <CalendarDays className="h-4 w-4 text-neutral-500" />
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Run history
          </div>
          <div className="mt-0.5 text-xs text-neutral-400">
            Generated runs by date
          </div>
        </div>
        {loading && <Loader2 className="ml-auto h-4 w-4 animate-spin text-neutral-400" />}
      </div>
      {error ? (
        <div className="px-4 py-4 text-sm text-red-700">
          Could not load batch history.
        </div>
      ) : groups.length === 0 ? (
        <div className="px-4 py-4 text-sm text-neutral-500">
          No generated batches yet.
        </div>
      ) : (
        <div className="max-h-[520px] overflow-y-auto px-2 py-2">
          {groups.map((group) => (
            <div key={group.dateKey} className="py-1">
              <div className="sticky top-0 z-10 bg-white/95 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-400 backdrop-blur">
                {group.label}
              </div>
              <div className="space-y-1">
                {group.batches.map((batch) => {
                  const selected = batch.id === selectedBatchId;
                  return (
                    <button
                      key={batch.id}
                      type="button"
                      onClick={() => onSelect(batch.id)}
                      className={cn(
                        "w-full rounded-md px-2.5 py-2 text-left transition",
                        selected
                          ? "bg-neutral-900 text-white"
                          : "text-neutral-700 hover:bg-neutral-50",
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="min-w-0 flex-1 truncate text-sm font-medium">
                          {batch.name || "Untitled batch"}
                        </div>
                        <StatusPill
                          status={batch.status}
                          className={cn(
                            "text-[10px]",
                            selected && "bg-white/15 text-white",
                          )}
                        />
                      </div>
                      <div
                        className={cn(
                          "mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]",
                          selected ? "text-neutral-300" : "text-neutral-500",
                        )}
                      >
                        <span>{batchItemCountLabel(batch)}</span>
                        <span>{batchVariantLabel(batch)}</span>
                        <span>{formatHistoryTime(batch.created_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
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
  lastRun,
  throughput,
}: {
  run: LeadGenDailyRun | null;
  enabled: boolean;
  loading: boolean;
  onToggle: (enabled: boolean) => void;
  toggling: boolean;
  onRun: (dryRun: boolean, force?: boolean, composerVariantKey?: string) => void;
  running: boolean;
  error: boolean;
  lastRun: LeadGenDailyRun | null;
  throughput: LeadGenThroughput | null;
}) {
  const [confirmForce, setConfirmForce] = useState(false);
  const [composerVariant, setComposerVariant] = useState("");
  const composerVariants = useQuery({
    queryKey: ["composer-variants"],
    queryFn: getComposerVariants,
    staleTime: 60_000,
  });
  const activeVariants = (composerVariants.data?.variants ?? []).filter((v) => v.active);
  const variantArg = composerVariant || undefined;
  const stages = run?.stages ?? {};
  const selectCounts = (stages.select?.counts ?? {}) as Record<string, unknown>;
  const composeCounts = (stages.compose?.counts ?? {}) as Record<string, unknown>;
  const selectedCount = typeof selectCounts.selected === "number" ? selectCounts.selected : null;
  const draftedCount = throughput ? throughput.funnel.composed : typeof composeCounts.drafted === "number" ? composeCounts.drafted : null;
  const heldCount = throughput ? throughput.funnel.held : typeof composeCounts.held === "number" ? composeCounts.held : null;
  // Prefer the live-polled run, fall back to the just-finished mutation result.
  const outcome = dailyRunOutcome(running ? run : (lastRun ?? run), running, throughput);

  return (
    <section className="rounded-xl border border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-2.5">
        <Clock className="h-4 w-4 text-neutral-500" />
        <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
          Run controls
        </h2>
        {loading && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-neutral-400" />}
      </div>
      <div className="space-y-3 px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-neutral-900">
              {run?.run_date ?? istDateKey(new Date())}
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
        <div className="grid grid-cols-4 gap-2 text-center">
          <Metric label="Selected" value={selectedCount === null ? "-" : String(selectedCount)} />
          <Metric label="Drafted" value={draftedCount === null ? "-" : String(draftedCount)} />
          <Metric label="Held" value={heldCount === null ? "-" : String(heldCount)} />
          <Metric label="Batch" value={run?.batch_id ? "Yes" : "-"} />
        </div>
        {run?.batch_id && (
          <Link
            href={`/lead-gen?view=batches&batch=${encodeURIComponent(run.batch_id)}`}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            <Eye className="h-4 w-4" />
            Open batch
          </Link>
        )}
        <label className="block text-xs font-medium text-neutral-600">
          Composer variant (this run)
          <select
            value={composerVariant}
            onChange={(e) => setComposerVariant(e.target.value)}
            disabled={composerVariants.isLoading || running}
            className="mt-1 w-full rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm font-medium text-neutral-800 disabled:opacity-60"
          >
            <option value="">Default (per-item A/B)</option>
            {activeVariants.map((v) => (
              <option key={v.key} value={v.key}>{v.label}</option>
            ))}
          </select>
          <span className="mt-1 block font-normal text-neutral-400">
            {composerVariant
              ? `Pins ${composerVariant} on every email (first-touch + follow-up) this run.`
              : "Each email keeps its default / A/B variant."}
          </span>
        </label>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => onRun(true, false, variantArg)}
            disabled={running}
            className="inline-flex items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Dry run
          </button>
          <button
            type="button"
            onClick={() => {
              if (isIstWeekend()) setConfirmForce(true);
              else onRun(false, false, variantArg);
            }}
            disabled={running}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run now
          </button>
        </div>
        {/* Live progress + outcome (skips and failures no longer silent) */}
        {(outcome || running) && (
          <div
            className={cn(
              "flex items-start gap-2 rounded-md px-3 py-2 text-xs",
              outcome?.tone === "ok" && "bg-emerald-50 text-emerald-800",
              outcome?.tone === "warn" && "bg-amber-50 text-amber-900",
              outcome?.tone === "err" && "bg-red-50 text-red-700",
              (!outcome || outcome.tone === "run") && "bg-neutral-50 text-neutral-600",
            )}
          >
            {(running || outcome?.tone === "run") && <Loader2 className="mt-0.5 h-3.5 w-3.5 animate-spin" />}
            <span>{outcome?.text ?? "Running… this can take a few minutes."}</span>
          </div>
        )}
        {error && !outcome && (
          <div className="text-xs text-red-600">Daily run request failed.</div>
        )}
      </div>

      {confirmForce && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-sm rounded-xl border border-neutral-200 bg-white p-5 shadow-xl">
            <h3 className="text-sm font-semibold text-neutral-900">Run on a weekend?</h3>
            <p className="mt-2 text-sm text-neutral-600">
              The daily pipeline normally runs Monday-Friday, so a normal run today
              would be skipped at the weekday gate. Run it anyway?
            </p>
            <p className="mt-2 text-xs text-neutral-400">
              This composes drafts and, when autonomous send is enabled, schedules
              approved send actions inside the US-morning send window (9:30 PM–12 AM IST).
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmForce(false)}
                className="rounded-md border border-neutral-200 px-3 py-1.5 text-sm font-medium text-neutral-600 hover:bg-neutral-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  onRun(false, true, variantArg);
                  setConfirmForce(false);
                }}
                className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-800"
              >
                Run anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function dailyRunOutcome(
  run: LeadGenDailyRun | null,
  running: boolean,
  throughput?: LeadGenThroughput | null,
): { tone: "ok" | "warn" | "err" | "run"; text: string } | null {
  if (running) {
    return { tone: "run", text: run?.stage ? `Running… ${run.stage}` : "Running…" };
  }
  if (!run) return null;
  const stages = run.stages ?? {};
  if (run.status === "completed") {
    if (throughput) {
      const composed = throughput.funnel.composed;
      const held = throughput.funnel.held;
      if (held > 0) {
        return {
          tone: composed > 0 ? "warn" : "err",
          text: `${composed} drafted · ${held} held (awaiting reviews)`,
        };
      }
    }
    const drafted = (stages.compose?.counts as Record<string, unknown> | undefined)?.drafted;
    // "drafts" only — whether they still await review vs. already sent is the
    // batch's state (shown on the batch card), not the run record's.
    return {
      tone: "ok",
      text: typeof drafted === "number" ? `Completed · ${drafted} drafts` : "Completed",
    };
  }
  if (run.status === "skipped") {
    let reason = "";
    for (const stage of Object.values(stages)) {
      const r =
        (stage as { counts?: { reason?: unknown }; reason?: unknown })?.counts?.reason ??
        (stage as { reason?: unknown })?.reason;
      if (r) {
        reason = String(r);
        break;
      }
    }
    return { tone: "warn", text: `Skipped${reason ? `: ${reason.replace(/_/g, " ")}` : ""}` };
  }
  if (run.status === "partial" || run.status === "failed") {
    let stageName = run.stage || "";
    let err = "";
    for (const [name, stage] of Object.entries(stages)) {
      const e = (stage as { error?: unknown })?.error;
      if (e) {
        stageName = name;
        err = String(e);
        break;
      }
    }
    return {
      tone: "err",
      text: `Failed at ${stageName || "run"}${err ? `: ${err.slice(0, 120)}` : ""}`,
    };
  }
  return null;
}

function DailySendBudgetPanel({
  dailyEmailBudget,
  resendDailyEmailBudget,
  onResendDailyEmailBudgetChange,
  onSave,
  isSaving,
  saveError,
  onGenerate,
  isGenerating,
  generateError,
}: {
  dailyEmailBudget: number;
  resendDailyEmailBudget: number;
  onResendDailyEmailBudgetChange: (value: number) => void;
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
        <div className="grid gap-2">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-md border border-neutral-200 bg-neutral-50 px-2 py-2">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
                Zoho
              </div>
              <div className="mt-1 text-lg font-semibold text-neutral-900">
                {ZOHO_DAILY_EMAIL_CAP}
              </div>
            </div>
            <label
              htmlFor="resend-daily-email-budget"
              className="block rounded-md border border-neutral-200 px-2 py-2 text-xs font-medium text-neutral-600"
            >
              <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
                Resend
              </span>
              <input
                id="resend-daily-email-budget"
                type="number"
                min={0}
                max={200}
                value={resendDailyEmailBudget}
                onChange={(e) => onResendDailyEmailBudgetChange(Number(e.target.value))}
                className="mt-1 w-full border-0 p-0 text-lg font-semibold text-neutral-900 outline-none"
              />
            </label>
          </div>
          <label
            htmlFor="daily-email-budget"
            className="block flex-1 text-xs font-medium text-neutral-600"
          >
            Total emails per day
            <input
              id="daily-email-budget"
              type="number"
              readOnly
              value={dailyEmailBudget}
              className="mt-1 w-full rounded-md border border-neutral-200 bg-neutral-50 px-2 py-1.5 text-sm text-neutral-900"
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

function ManualAgentSlicePanel({
  onCreate,
  creating,
  error,
}: {
  onCreate: () => void;
  creating: boolean;
  error: boolean;
}) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
        Test slice
      </div>
      <p className="mt-2 text-sm leading-6 text-neutral-600">
        Create three draft actions for a quick composer and workflow check.
      </p>
      <button
        type="button"
        onClick={onCreate}
        disabled={creating}
        className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
      >
        {creating ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Sparkles className="h-4 w-4" />
        )}
        Create 3 drafts
      </button>
      {error && (
        <div className="mt-2 text-xs text-red-600">
          Could not create the test slice.
        </div>
      )}
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
  const [showAllDrafts, setShowAllDrafts] = useState(false);
  const [draftStatuses, setDraftStatuses] = useState<Record<string, DraftGenerationStatus>>({});
  const [isGeneratingAllDrafts, setIsGeneratingAllDrafts] = useState(false);
  const [bulkDraftError, setBulkDraftError] = useState<string | null>(null);
  const [selectedComposerVariantKey, setSelectedComposerVariantKey] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const openedRequestKey = useRef("");
  const [scheduledStartAt, setScheduledStartAt] = useState(() =>
    defaultIstDateTimeLocal(),
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
        scheduled_timezone: DISPLAY_TIME_ZONE,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", batchId] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
    },
  });

  // Primary "Approve & send": approves the reviewed send_email actions so the
  // scheduler sends the exact drafts on screen at their slots — NOT the legacy
  // sequence flow (which `approve` above drives, kept under Advanced).
  const approveActions = useMutation({
    mutationFn: () => approveLeadGenBatchActions(batchId, { approved_by: "operator" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", batchId] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
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
  const composedItemCount = useMemo(
    () => (data?.items ?? []).filter((item) => Boolean(storedAgentDraftStep(item))).length,
    [data?.items],
  );
  const heldItemCount = useMemo(
    () => (data?.items ?? []).filter((item) => Boolean(reasonValue(item, "held_reason"))).length,
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
  const isOlderPlan = !isIstToday(data.batch.created_at);
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
    // Force-recompose every unsent previewable item server-side so the new draft
    // is persisted (and its send action rescheduled), honoring the variant picked
    // in the "Composer variant" dropdown. Unlike the old preview-cache approach,
    // this overwrites already-composed drafts — which is the whole point of
    // re-running the batch through a different variant (e.g. ai-audit).
    const remaining = previewableItems.filter((item) => !isEmailSent(item));
    if (remaining.length === 0) return;
    setIsGeneratingAllDrafts(true);
    setBulkDraftError(null);
    let failed = 0;
    let nextIndex = 0;
    const workerCount = Math.min(3, remaining.length);
    const generateOne = async (item: LeadGenBatchItem) => {
      setDraftStatuses((prev) => ({ ...prev, [item.id]: "generating" }));
      // Retry transient composer/gateway failures so a single hiccup doesn't
      // silently leave an item on its old draft (the bug that left 3/20 items
      // unconverted on the 2026-06-22 ai-audit regenerate). 3 attempts w/ backoff.
      const maxAttempts = 3;
      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
          await recomposeLeadGenBatchItemDraft(item.id, {
            actor: "operator",
            composer_variant_key: selectedComposerVariantKey || null,
          });
          setDraftStatuses((prev) => ({ ...prev, [item.id]: "completed" }));
          return;
        } catch {
          if (attempt < maxAttempts) {
            await new Promise((resolve) => setTimeout(resolve, 800 * attempt));
            continue;
          }
          failed += 1;
          setDraftStatuses((prev) => ({ ...prev, [item.id]: "failed" }));
        }
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
    // Pull the freshly persisted drafts back into the batch view.
    await qc.invalidateQueries({ queryKey: ["lead-gen-batch", batchId] });
    if (failed > 0) {
      setBulkDraftError(`${failed} draft${failed === 1 ? "" : "s"} could not be regenerated.`);
    }
    setIsGeneratingAllDrafts(false);
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-4 py-3">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
              Selected run
            </div>
            <h2 className="mt-1 truncate text-base font-semibold text-neutral-900">{data.batch.name}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
              <span>{formatComposerKey(data.batch.template_key)}</span>
              <span className="text-neutral-300">·</span>
              <span>{formatIstDate(data.batch.created_at)}</span>
              <details className="relative">
                <summary className="cursor-pointer font-medium text-neutral-500 hover:text-neutral-800">
                  Details
                </summary>
                <div className="absolute left-0 z-20 mt-2 w-80 rounded-lg border border-neutral-200 bg-white p-3 text-xs shadow-lg">
                  <div className="font-medium text-neutral-800">Run metadata</div>
                  <div className="mt-2 space-y-1 text-neutral-500">
                    <div className="break-all">Batch ID: {data.batch.id}</div>
                    <div>Policy: {data.batch.policy_version}</div>
                    <div>Status: {data.batch.status}</div>
                  </div>
                </div>
              </details>
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
                  Completed · {formatIstDate(data.batch.created_at)}
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
            <span className="font-semibold">{composedItemCount}</span> drafted
            {heldItemCount > 0 && (
              <span className="text-red-700"> · {heldItemCount} held (awaiting reviews)</span>
            )}
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
              if (window.confirm("Approve the reviewed drafts in this batch? Each will send at its scheduled slot (the times shown on each draft). This sends exactly what's on screen.")) {
                approveActions.mutate();
              }
            }}
            disabled={approveActions.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {approveActions.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
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
          {approveActions.data && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {approveActions.data.approved_count} approved, sending at scheduled slots
            </span>
          )}
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
                Start sending (IST)
                <input
                  type="datetime-local"
                  value={scheduledStartAt}
                  onChange={(e) => setScheduledStartAt(e.target.value)}
                  className="mt-1 w-full rounded-md border border-neutral-200 px-2 py-1.5 text-sm text-neutral-900"
                />
                <span className="mt-1 block font-normal text-neutral-400">
                  Asia/Kolkata, staggered over 60 minutes.
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
                onClick={() => setShowAllDrafts(true)}
                disabled={composedItemCount === 0}
                className="inline-flex items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                <Eye className="h-4 w-4" />
                View all drafts
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

      {showAllDrafts && (
        <AllDraftsModal
          items={data.items}
          onClose={() => setShowAllDrafts(false)}
          onOpenOne={(item) => {
            setShowAllDrafts(false);
            setPreviewItem(item);
          }}
        />
      )}

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
    const key = keyFn(item) || "-";
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

function SelectedDateSendPlanPanel({
  selectedDate,
  onDateChange,
  plan,
  loading,
  error,
  onOpenDraft,
}: {
  selectedDate: string;
  onDateChange: (value: string) => void;
  plan: LeadGenSendPlan | null;
  loading: boolean;
  error: boolean;
  onOpenDraft: (item: LeadGenSendPlanItem) => void;
}) {
  const items = plan?.items ?? [];
  const sent = plan?.summary.sent ?? 0;
  const scheduled = plan?.summary.scheduled ?? 0;
  const channelRows = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      const key = item.channel || item.transport || "unassigned";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [items]);
  const selectedIsToday = selectedDate === sendDateKey(new Date());
  return (
    <section className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-neutral-100 px-5 py-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-neutral-900">
            Send Queue
          </h2>
          <p className="mt-1 text-xs text-neutral-500">
            Sent and scheduled emails for the selected Pacific date.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs font-medium text-neutral-500">
            <CalendarDays className="h-3.5 w-3.5" />
            <input
              type="date"
              value={selectedDate}
              onChange={(event) => onDateChange(event.target.value || sendDateKey(new Date()))}
              className="rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm font-medium text-neutral-800 shadow-sm"
            />
          </label>
          {!selectedIsToday && (
            <button
              type="button"
              onClick={() => onDateChange(sendDateKey(new Date()))}
              className="rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
            >
              Today
            </button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 bg-neutral-50/70 px-5 py-3 text-sm">
        <span className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-neutral-900 ring-1 ring-neutral-200">
          <span className="font-semibold">{scheduled}</span> scheduled
        </span>
        <span className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-neutral-900 ring-1 ring-neutral-200">
          <span className="font-semibold">{sent}</span> sent
        </span>
        <span className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-neutral-500 ring-1 ring-neutral-200">
          {plan?.timezone || SEND_TIME_ZONE}
        </span>
        {channelRows.map(([channel, count]) => (
          <span
            key={channel}
            className="inline-flex items-center rounded-full bg-white px-2.5 py-1 text-neutral-500 ring-1 ring-neutral-200"
          >
            {channel}: <span className="ml-1 font-semibold text-neutral-800">{count}</span>
          </span>
        ))}
        {loading && (
          <span className="inline-flex items-center gap-1 text-xs text-neutral-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading
          </span>
        )}
        {error && (
          <span className="text-xs font-medium text-red-600">
            Could not load send plan.
          </span>
        )}
      </div>
      {!loading && !error && items.length === 0 && (
        <div className="px-4 py-6 text-sm text-neutral-500">
          No emails sent or scheduled for this date.
        </div>
      )}
      {items.length > 0 && (
        <div>
          <div className="hidden grid-cols-[88px_minmax(0,1.05fr)_minmax(0,1.1fr)_minmax(0,1.35fr)_180px_230px] gap-3 border-b border-neutral-100 px-5 py-2 text-[11px] font-semibold uppercase tracking-wider text-neutral-400 xl:grid">
            <div>Time</div>
            <div>Firm</div>
            <div>Contact</div>
            <div>Draft</div>
            <div>Status</div>
            <div className="text-right">Actions</div>
          </div>
          <div className="divide-y divide-neutral-100">
          {items.map((item) => (
            <SelectedDateSendPlanRow key={item.action_id} item={item} onOpenDraft={onOpenDraft} />
          ))}
          </div>
        </div>
      )}
    </section>
  );
}

function SelectedDateSendPlanRow({
  item,
  onOpenDraft,
}: {
  item: LeadGenSendPlanItem;
  onOpenDraft: (item: LeadGenSendPlanItem) => void;
}) {
  const sent = item.action_status === "succeeded";
  const timeLabel = sent
    ? item.sent_at_pt || item.scheduled_for_pt || "-"
    : item.scheduled_for_pt || "-";
  const linkedInUrl = sendPlanLinkedInUrl(item);
  const searchUrl = sendPlanLinkedInSearchUrl(item);
  const batchHref = sendPlanBatchHref(item);
  return (
    <article className="grid min-w-0 gap-3 px-5 py-4 text-sm xl:grid-cols-[88px_minmax(0,1.05fr)_minmax(0,1.1fr)_minmax(0,1.35fr)_180px_230px]">
      <div className="text-xs font-medium text-neutral-600 xl:pt-0.5">
        {shortPtTime(timeLabel)}
      </div>
      <div className="min-w-0">
        <div className="truncate font-medium text-neutral-900">{item.firm_name}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-neutral-500">
          <Link
            href={batchHref}
            className="font-medium text-neutral-600 hover:text-neutral-900"
          >
            {cleanBatchName(item.batch_name)}
          </Link>
          <span className="text-neutral-300">·</span>
          <span>{sendPlanActionLabel(item)}</span>
        </div>
      </div>
      <div className="min-w-0">
        <div className="truncate font-medium text-neutral-800">
          {item.contact_name || "Unknown"}
        </div>
        <div className="truncate text-xs text-neutral-500">{item.contact_title || item.persona || "-"}</div>
        <div className="mt-1 truncate text-xs text-neutral-500">{item.contact_email}</div>
      </div>
      <div className="min-w-0">
        <div className="line-clamp-2 text-xs font-medium text-neutral-800">
          {item.subject || "-"}
        </div>
        <div className="mt-1 text-[11px] text-neutral-400">
          {item.composer_variant_key || "baseline"} · {item.channel || "-"}
        </div>
      </div>
      <div className="flex flex-col items-start gap-1">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
            sent ? "bg-sky-100 text-sky-800" : "bg-violet-100 text-violet-800",
          )}
        >
          {sent ? <CheckCircle2 className="h-3 w-3" /> : <Clock className="h-3 w-3" />}
          {sent ? "Sent" : "Scheduled"}
        </span>
        <span className="text-xs text-neutral-500">{timeLabel}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
        <button
          type="button"
          onClick={() => onOpenDraft(item)}
          className="inline-flex items-center gap-1 rounded-md border border-neutral-900 bg-neutral-900 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-neutral-800"
        >
          <MailPlus className="h-3.5 w-3.5" />
          {sent ? "Open record" : "View draft"}
        </button>
        <button
          type="button"
          onClick={() => onOpenDraft(item)}
          className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Compose
        </button>
        {linkedInUrl ? (
          <a
            href={linkedInUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            LinkedIn
          </a>
        ) : (
          <a
            href={searchUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
          >
            <Search className="h-3.5 w-3.5" />
            Find LinkedIn
          </a>
        )}
      </div>
    </article>
  );
}

function QueueDraftModal({
  target,
  onClose,
}: {
  target: QueuePreviewTarget;
  onClose: () => void;
}) {
  const q = useQuery({
    queryKey: ["lead-gen-batch", target.batchId],
    queryFn: () => getLeadGenBatch(target.batchId, true),
    refetchInterval: 30_000,
  });
  const item = q.data?.items.find((candidate) => candidate.id === target.batchItemId) ?? null;

  if (q.isLoading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
        <div className="flex w-full max-w-sm items-center gap-2 rounded-xl bg-white px-5 py-4 text-sm text-neutral-500 shadow-xl">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading draft...
        </div>
      </div>
    );
  }

  if (q.isError || !item) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
        <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
          <h3 className="text-sm font-semibold text-neutral-900">Draft unavailable</h3>
          <p className="mt-2 text-sm text-neutral-600">
            The queue row could not load its draft. The run may have changed.
          </p>
          <div className="mt-4 flex justify-end">
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

  return <PreviewModal item={item} composerVariantKey="" onClose={onClose} />;
}

function sendPlanBatchHref(item: LeadGenSendPlanItem) {
  return `/lead-gen?view=batches&batch=${encodeURIComponent(item.batch_id)}`;
}

function sendPlanLinkedInUrl(item: LeadGenSendPlanItem) {
  const value = item.linkedin_url || "";
  return isLinkedInUrl(value) ? value : "";
}

function sendPlanLinkedInSearchUrl(item: LeadGenSendPlanItem) {
  const parts = [
    item.contact_name,
    item.contact_title,
    item.firm_name,
    "LinkedIn",
  ].filter(Boolean);
  return `https://www.google.com/search?q=${encodeURIComponent(parts.join(" "))}`;
}

function sendPlanActionLabel(item: LeadGenSendPlanItem) {
  const labels: Record<string, string> = {
    reply_to_inbound: "Reply",
    approve_existing_draft: "Approve draft",
    follow_up: "Follow-up",
    first_touch: "First touch",
  };
  const action = item.action_type || "first_touch";
  return labels[action] ?? action.replaceAll("_", " ");
}

function cleanBatchName(value: string) {
  if (!value) return "Batch";
  return value.replace(/^Daily run\s+/i, "Run ");
}

function shortPtTime(value: string) {
  const match = value.match(/\b(\d{1,2}:\d{2})\s+(PDT|PST)\b/);
  return match ? `${match[1]} ${match[2]}` : value;
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
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-neutral-900">Drafts</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            Contacts and emails generated for this run.
          </p>
        </div>
        <span className="text-xs text-neutral-400">{items.length} draft{items.length === 1 ? "" : "s"}</span>
      </div>
      <div className="divide-y divide-neutral-100">
        {items.map((item) => {
          const linkedInUrl = founderLinkedInUrl(item);
          const searchUrl = founderLinkedInSearchUrl(item);
          return (
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
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-neutral-500">
                <span>{actionLabel(item)}</span>
                <span className="text-neutral-300">·</span>
                <span>{item.persona || "Unknown persona"}</span>
              </div>
              <SelectionDetails item={item} />
            </div>

            <div className="min-w-0">
              <div className="font-medium text-neutral-800">
                {item.contact_name || "Unknown"}
              </div>
              <div className="text-xs text-neutral-500">{item.contact_title || "No title"}</div>
              <div className="mt-1 break-all text-xs text-neutral-500">
                {item.contact_email}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {linkedInUrl ? (
                  <a
                    href={linkedInUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    LinkedIn
                  </a>
                ) : (
                  <a
                    href={searchUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
                  >
                    <Search className="h-3.5 w-3.5" />
                    Find LinkedIn
                  </a>
                )}
              </div>
              {isEmailSent(item) ? (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-800">
                    <CheckCircle2 className="h-3 w-3" />
                    Email sent
                  </span>
                  <ChannelBadge item={item} />
                </div>
              ) : canPreviewItem(item) ? (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => onPreview(item)}
                    className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
                  >
                    <MailPlus className="h-3.5 w-3.5" />
                    {previewButtonLabel(item)}
                  </button>
                  <ChannelBadge item={item} />
                </div>
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
                  Scheduled, sends {scheduledSendPt(item)}
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

            <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2">
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
          );
        })}
      </div>
    </section>
  );
}

function SelectionDetails({ item }: { item: LeadGenBatchItem }) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer font-medium text-neutral-500 hover:text-neutral-800">
        Selection details
      </summary>
      <div className="mt-2 rounded-md border border-neutral-200 bg-neutral-50 p-2 text-neutral-600">
        <div className="leading-relaxed">{reasonText(item)}</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <MiniField label="Score" value={String(item.score)} mono />
          <MiniField label="Firm ID" value={item.pif_id || "-"} mono />
        </div>
        <ScoreBreakdown item={item} />
      </div>
    </details>
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

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function founderLinkedInUrl(item: LeadGenBatchItem): string {
  const direct = stringValue(item.reason?.contact_linkedin_url);
  if (isLinkedInUrl(direct)) return direct;

  const draft = objectValue(item.reason?.agent_draft);
  const draftResearch = objectValue(draft?.research);
  const reasonResearch = objectValue(item.reason?.research_evidence);
  const researchSources = [
    ...(Array.isArray(draftResearch?.source_urls) ? draftResearch.source_urls : []),
    ...(Array.isArray(reasonResearch?.source_urls) ? reasonResearch.source_urls : []),
  ];
  for (const source of researchSources) {
    const entry = objectValue(source);
    const url = stringValue(entry?.url);
    const label = stringValue(entry?.label).toLowerCase();
    if (isLinkedInUrl(url) || (label.includes("linkedin") && url)) return url;
  }

  const candidateKeys = ["linkedin_url", "linkedin", "contact_linkedin"];
  for (const key of candidateKeys) {
    const value = stringValue(item.reason?.[key]);
    if (isLinkedInUrl(value)) return value;
  }
  return "";
}

function isLinkedInUrl(value: string) {
  if (!value) return false;
  try {
    return new URL(value).hostname.toLowerCase().includes("linkedin.");
  } catch {
    return value.toLowerCase().includes("linkedin.com/");
  }
}

function founderLinkedInSearchUrl(item: LeadGenBatchItem): string {
  const parts = [
    item.contact_name,
    item.contact_title,
    item.firm_name,
    "LinkedIn",
  ].filter(Boolean);
  return `https://www.google.com/search?q=${encodeURIComponent(parts.join(" "))}`;
}

function storedAgentDraftStep(item: LeadGenBatchItem): RenderedSequenceStep | null {
  const draft = objectValue(item.reason?.agent_draft);
  return draftPayloadToRenderedStep(draft);
}

function draftPayloadToRenderedStep(draft: Record<string, unknown> | null): RenderedSequenceStep | null {
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

function AllDraftsModal({
  items,
  onClose,
  onOpenOne,
}: {
  items: LeadGenBatchItem[];
  onClose: () => void;
  onOpenOne: (item: LeadGenBatchItem) => void;
}) {
  // Read-only quick-review of every composed (or already-sent) email in the
  // batch, so the operator can scan the day's drafts in one place instead of
  // opening each preview. All data comes from the already-loaded batch
  // (reason.agent_draft / last_sent_*), so there are no extra fetches.
  const drafted = useMemo(
    () => items.filter((it) => storedAgentDraftStep(it) || isEmailSent(it)),
    [items],
  );
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-neutral-900">
              All drafted emails ({drafted.length})
            </h3>
            <p className="mt-1 text-xs text-neutral-500">
              Read-only review of this selected batch. Click Open on any one to edit or send it.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-neutral-200 px-3 py-1.5 text-sm font-medium text-neutral-600 hover:bg-neutral-50"
          >
            Close
          </button>
        </div>
        <div className="space-y-4 overflow-y-auto px-5 py-4">
          {drafted.length === 0 && (
            <p className="text-sm text-neutral-500">No drafts composed yet.</p>
          )}
          {drafted.map((item, idx) => {
            const step = storedAgentDraftStep(item);
            const sent = isEmailSent(item);
            const subject =
              step?.subject || reasonValue(item, "last_sent_subject") || "(no subject)";
            const body = step?.body || reasonValue(item, "last_sent_body") || "";
            const variant =
              step?.composer_variant_key ||
              reasonValue(item, "last_sent_composer_variant_key") ||
              "—";
            const scheduled = scheduledSendPt(item);
            const words = body.trim() ? body.trim().split(/\s+/).length : 0;
            return (
              <div key={item.id} className="rounded-lg border border-neutral-200">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-neutral-100 bg-neutral-50 px-3 py-2 text-xs">
                  <span className="font-semibold text-neutral-700">{idx + 1}.</span>
                  <span className="font-medium text-neutral-800">{item.firm_name}</span>
                  <span className="text-neutral-500">
                    {item.contact_name || "—"}
                    {item.contact_title ? ` (${item.contact_title})` : ""} ·{" "}
                    {item.contact_email || "no email"}
                  </span>
                  <span className="ml-auto rounded bg-neutral-200 px-1.5 py-0.5 text-[11px] text-neutral-700">
                    {variant}
                  </span>
                  <ChannelBadge item={item} className="rounded px-1.5" />
                  {sent ? (
                    <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] text-sky-800">
                      sent
                    </span>
                  ) : scheduled ? (
                    <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[11px] text-violet-800">
                      sends {scheduled}
                    </span>
                  ) : null}
                  <span className="text-[11px] text-neutral-400">{words}w</span>
                  <button
                    type="button"
                    onClick={() => onOpenOne(item)}
                    className="rounded border border-neutral-200 bg-white px-2 py-0.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
                  >
                    Open
                  </button>
                </div>
                <div className="px-3 py-2">
                  <p className="text-sm font-semibold text-neutral-900">{subject}</p>
                  <pre className="mt-1 whitespace-pre-wrap font-sans text-sm text-neutral-700">
                    {body}
                  </pre>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
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
  const [recomposedStep, setRecomposedStep] = useState<RenderedSequenceStep | null>(null);
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
    if (recomposedStep) return recomposedStep;
    if (storedDraft) return storedDraft;
    const steps = q.data ?? [];
    const sequence = detail.data?.sequence;
    if (sequence && sequence.current_step >= sequence.steps_total) return undefined;
    const nextStepNumber = sequence ? sequence.current_step + 1 : 1;
    return steps.find((step) => step.step === nextStepNumber) ?? steps[0];
  }, [detail.data?.sequence, q.data, recomposedStep, storedDraft]);
  useEffect(() => {
    setRecomposedStep(null);
  }, [item.id]);
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
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
      qc.invalidateQueries({ queryKey: ["all-sequences"] });
      onClose();
    },
  });
  const recomposeDraft = useMutation({
    mutationFn: () =>
      recomposeLeadGenBatchItemDraft(item.id, {
        actor: "operator",
        composer_variant_key: composerVariantKey || undefined,
      }),
    onSuccess: (data) => {
      const freshStep = draftPayloadToRenderedStep(objectValue(data.draft));
      if (freshStep) {
        setRecomposedStep(freshStep);
        setDraftSubject(freshStep.subject);
        setDraftBody(freshStep.body);
        setDraftTouched(false);
      }
      setVariants(null);
      setSelectedVariantKey(null);
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", item.batch_id] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-throughput"] });
    },
  });
  const redoCompose = () => {
    if (
      draftTouched &&
      !window.confirm("Redo compose and replace your current edits?")
    ) {
      return;
    }
    const scheduledAt = scheduledSendPt(item);
    if (
      scheduledAt &&
      !window.confirm(`Redo this scheduled email compose? The queued send stays scheduled for ${scheduledAt}, but its subject/body and approval hash will be replaced.`)
    ) {
      return;
    }
    recomposeDraft.mutate();
  };

  // Multi-variant compare: generate all composer variants on-demand, pick one to send.
  const [variants, setVariants] = useState<BatchItemVariantDraft[] | null>(null);
  const [selectedVariantKey, setSelectedVariantKey] = useState<string | null>(null);
  const composeVariants = useMutation({
    mutationFn: () => composeBatchItemVariants(item.id),
    onSuccess: (data) => {
      setVariants(data.variants);
      setSelectedVariantKey(data.selected_variant_key);
    },
  });
  const selectVariant = useMutation({
    mutationFn: (key: string) => selectBatchItemVariant(item.id, key),
    onSuccess: (data) => {
      setSelectedVariantKey(data.selected_variant_key);
      const v = variants?.find((x) => x.variant_key === data.selected_variant_key);
      if (v?.subject) setDraftSubject(v.subject);
      if (v?.body) setDraftBody(v.body);
      setDraftTouched(false);
      qc.invalidateQueries({ queryKey: ["lead-gen-batch", item.batch_id] });
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
      qc.invalidateQueries({ queryKey: ["lead-gen-send-plan"] });
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
          <div className="mt-2">
            <ChannelBadge item={item} />
          </div>
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
                  <code>actions reschedule</code> / <code>actions cancel</code> or the /actions page.
                  Manual send is disabled to prevent a duplicate.
                </div>
              </div>
            </div>
          )}
          {alreadySent ? (
            <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-3 text-sm text-sky-900">
              <div className="flex flex-wrap items-center gap-2">
                <div className="font-medium">This email has already been sent.</div>
                <ChannelBadge item={item} />
              </div>
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
              {isDynamic && (
                <section className="rounded-lg border border-neutral-200">
                  <div className="flex items-center justify-between border-b border-neutral-100 bg-neutral-50 px-3 py-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
                      Compare variants
                    </span>
                    <button
                      type="button"
                      onClick={() => composeVariants.mutate()}
                      disabled={composeVariants.isPending}
                      className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
                    >
                      {composeVariants.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      {variants ? "Regenerate variants" : "Generate all variants"}
                    </button>
                  </div>
                  {composeVariants.isPending ? (
                    <div className="flex items-center gap-2 px-3 py-3 text-xs text-neutral-500">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Composing every active variant through the gateway. This takes ~1-2 min.
                    </div>
                  ) : composeVariants.isError ? (
                    <div className="px-3 py-2 text-xs text-red-700">Could not generate variants.</div>
                  ) : !variants ? (
                    <div className="px-3 py-3 text-xs text-neutral-500">
                      Generate every active composer variant for this email (~1-2 min), then pick which
                      one to send. Default is the experiment-assigned variant.
                    </div>
                  ) : (
                    <div className="divide-y divide-neutral-100">
                      {variants.map((v) => {
                        const isSelected = selectedVariantKey === v.variant_key;
                        return (
                          <div key={v.variant_key} className={cn("px-3 py-3", isSelected && "bg-emerald-50")}>
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className="text-xs font-semibold text-neutral-800">
                                  {v.label}
                                  {v.is_baseline ? " · default" : ""}
                                  {isSelected ? " · selected" : ""}
                                </div>
                                {v.error ? (
                                  <div className="mt-0.5 text-xs text-red-600">failed: {v.error}</div>
                                ) : (
                                  <div className="mt-0.5 truncate text-xs text-neutral-500">
                                    Subject: {v.subject}
                                  </div>
                                )}
                              </div>
                              {!v.error && (
                                <button
                                  type="button"
                                  onClick={() => selectVariant.mutate(v.variant_key)}
                                  disabled={selectVariant.isPending || isSelected}
                                  className="shrink-0 rounded-md bg-neutral-900 px-2 py-1 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
                                >
                                  {isSelected ? "Selected" : "Use this to send"}
                                </button>
                              )}
                            </div>
                            {!v.error && v.body && (
                              <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-neutral-700">
                                {v.body}
                              </pre>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>
              )}
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
          {storedDraft && !alreadySent && (
            <button
              type="button"
              onClick={redoCompose}
              disabled={
                recomposeDraft.isPending ||
                sendDraft.isPending ||
                composeVariants.isPending ||
                selectVariant.isPending
              }
              className="mr-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {recomposeDraft.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Redo compose
            </button>
          )}
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
          {recomposeDraft.isError && (
            <div className="basis-full text-right text-xs text-red-600">
              {recomposeDraft.error instanceof Error
                ? recomposeDraft.error.message
                : "Could not redo compose for this email."}
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

function clampResendDailyEmailBudget(value: number) {
  if (!Number.isFinite(value)) return DEFAULT_DAILY_EMAIL_BUDGET - ZOHO_DAILY_EMAIL_CAP;
  return Math.max(0, Math.min(200, Math.trunc(value)));
}

function resendBudgetFromPolicy(policy: LeadGenPolicy) {
  return resendBudgetFromWeights(policy.weights, policy.daily_send_budget);
}

function resendBudgetFromWeights(
  weights: Record<string, unknown> | undefined,
  totalBudget = DEFAULT_DAILY_EMAIL_BUDGET,
) {
  const caps = weights?.provider_daily_caps;
  if (caps && typeof caps === "object" && "resend" in caps) {
    const value = Number((caps as Record<string, unknown>).resend);
    return clampResendDailyEmailBudget(value);
  }
  return clampResendDailyEmailBudget(clampDailyEmailBudget(totalBudget) - ZOHO_DAILY_EMAIL_CAP);
}

function defaultDailyPlanName(dailyEmailBudget: number) {
  return `Daily action plan - ${clampDailyEmailBudget(dailyEmailBudget)} emails`;
}

function istDateKey(value: Date | string | null | undefined) {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}

function sendDateKey(value: Date | string | null | undefined) {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: SEND_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}

function groupBatchesByDate(batches: LeadGenBatch[]) {
  const map = new Map<string, LeadGenBatch[]>();
  const sorted = [...batches].sort(
    (a, b) => dateTimeMs(b.created_at) - dateTimeMs(a.created_at),
  );
  for (const batch of sorted) {
    const dateKey = batchOperationalDateKey(batch);
    const rows = map.get(dateKey) ?? [];
    rows.push(batch);
    map.set(dateKey, rows);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => {
      if (a === "unknown") return 1;
      if (b === "unknown") return -1;
      return b.localeCompare(a);
    })
    .map(([dateKey, rows]) => ({
      dateKey,
      label: batchHistoryDateLabel(dateKey),
      batches: rows,
    }));
}

function batchOperationalDateKey(batch: LeadGenBatch) {
  const runDate = stringCountValue(batch.counts, "run_date");
  if (/^\d{4}-\d{2}-\d{2}$/.test(runDate)) return runDate;
  return istDateKey(batch.created_at) || "unknown";
}

function batchHistoryDateLabel(dateKey: string) {
  if (dateKey === "unknown") return "Unknown date";
  const today = istDateKey(new Date());
  const yesterday = istDateKey(new Date(Date.now() - 24 * 60 * 60 * 1000));
  if (dateKey === today) return "Today";
  if (dateKey === yesterday) return "Yesterday";
  const parsed = new Date(`${dateKey}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return dateKey;
  return parsed.toLocaleDateString("en-IN", {
    timeZone: DISPLAY_TIME_ZONE,
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatHistoryTime(value: string | null | undefined) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleTimeString("en-IN", {
    timeZone: DISPLAY_TIME_ZONE,
    hour: "numeric",
    minute: "2-digit",
  });
}

function batchItemCountLabel(batch: LeadGenBatch) {
  const count =
    numberCountValue(batch.counts, "selected") ??
    numberCountValue(batch.counts, "returned") ??
    numberCountValue(batch.counts, "recommended") ??
    numberCountValue(batch.counts, "approved") ??
    numberCountValue(batch.counts, "requested");
  if (count === null) return "items -";
  return `${count} item${count === 1 ? "" : "s"}`;
}

function batchVariantLabel(batch: LeadGenBatch) {
  const variant =
    stringCountValue(batch.counts, "composer_variant_override") ||
    stringCountValue(batch.counts, "composer_variant");
  if (variant) return variant;
  return formatComposerKey(batch.template_key);
}

function stringCountValue(counts: Record<string, unknown> | undefined, key: string) {
  const value = counts?.[key];
  return typeof value === "string" ? value : "";
}

function numberCountValue(counts: Record<string, unknown> | undefined, key: string) {
  const value = counts?.[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return null;
}

function selectBatchForDisplay(batches: LeadGenBatch[]) {
  const sorted = [...batches].sort(
    (a, b) => dateTimeMs(b.created_at) - dateTimeMs(a.created_at),
  );
  return (
    sorted.find((batch) => batch.template_key === DEFAULT_TEMPLATE && isIstToday(batch.created_at)) ??
    sorted.find((batch) => isIstToday(batch.created_at)) ??
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

function isIstToday(value: string | null | undefined) {
  return istDateKey(value) === istDateKey(new Date());
}

function isIstWeekend() {
  const weekday = new Date().toLocaleDateString("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
    weekday: "short",
  });
  return weekday === "Sat" || weekday === "Sun";
}

function formatIstDate(value: string | null | undefined) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString("en-IN", {
    timeZone: DISPLAY_TIME_ZONE,
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

function defaultIstDateTimeLocal() {
  const now = new Date();
  now.setMinutes(now.getMinutes() + 15);
  now.setSeconds(0, 0);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TIME_ZONE,
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
  return d.toLocaleString("en-IN", {
    timeZone: DISPLAY_TIME_ZONE,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
