"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  BrainCircuit,
  ChevronDown,
  CheckCircle2,
  FileCode2,
  GitBranch,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  XCircle,
} from "lucide-react";
import {
  analyzeLearningFindings,
  createEvalCaseForFinding,
  createTaskPacketForFinding,
  getEvalCases,
  getImprovementFindings,
  getLearningMeasurements,
  getProductTraces,
  getTaskPackets,
  reviewImprovementFinding,
  syncLearningOutcomes,
  type CodexTaskPacket,
  type EvalCase,
  type ImprovementFinding,
  type LearningMeasurementWindow,
  type ProductTrace,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const TRACE_LIMIT = 120;

function shortDate(value: string | null | undefined) {
  if (!value) return "";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function toneForSeverity(value: string) {
  if (value === "high") return "border-red-200 bg-red-50 text-red-700";
  if (value === "low") return "border-neutral-200 bg-neutral-50 text-neutral-600";
  return "border-amber-200 bg-amber-50 text-amber-700";
}

function toneForStatus(value: string) {
  if (value === "accepted" || value === "implemented" || value === "exported") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (value === "rejected") return "border-red-200 bg-red-50 text-red-700";
  return "border-neutral-200 bg-neutral-50 text-neutral-700";
}

function jsonPreview(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function formatRate(value: number | null) {
  if (value === null || Number.isNaN(value)) return "n/a";
  return `${Math.round(value * 1000) / 10}%`;
}

export default function TracesPage() {
  const qc = useQueryClient();
  const [selectedTraceId, setSelectedTraceId] = useState<string>("");
  const [recentTracesOpen, setRecentTracesOpen] = useState(false);

  const traces = useQuery({
    queryKey: ["product-traces", TRACE_LIMIT],
    queryFn: () => getProductTraces({ limit: TRACE_LIMIT }),
    refetchInterval: 10_000,
  });
  const measurements = useQuery({
    queryKey: ["learning-measurements"],
    queryFn: getLearningMeasurements,
    refetchInterval: 60_000,
  });
  const findings = useQuery({
    queryKey: ["improvement-findings"],
    queryFn: () => getImprovementFindings({ status: "all", limit: 100 }),
  });
  const evalCases = useQuery({
    queryKey: ["eval-cases"],
    queryFn: () => getEvalCases(100),
  });
  const taskPackets = useQuery({
    queryKey: ["task-packets"],
    queryFn: () => getTaskPackets(100),
  });

  const syncOutcomes = useMutation({
    mutationFn: () => syncLearningOutcomes(200),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-traces"] });
      qc.invalidateQueries({ queryKey: ["improvement-findings"] });
      qc.invalidateQueries({ queryKey: ["learning-measurements"] });
    },
  });
  const analyze = useMutation({
    mutationFn: () => analyzeLearningFindings(700),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-traces"] });
      qc.invalidateQueries({ queryKey: ["improvement-findings"] });
      qc.invalidateQueries({ queryKey: ["learning-measurements"] });
    },
  });
  const review = useMutation({
    mutationFn: (args: { id: string; status: "accepted" | "rejected" | "implemented" | "proposed" }) =>
      reviewImprovementFinding(args.id, args.status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["improvement-findings"] }),
  });
  const createEval = useMutation({
    mutationFn: (id: string) => createEvalCaseForFinding(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["eval-cases"] });
      qc.invalidateQueries({ queryKey: ["improvement-findings"] });
    },
  });
  const createPacket = useMutation({
    mutationFn: (id: string) => createTaskPacketForFinding(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["task-packets"] });
      qc.invalidateQueries({ queryKey: ["eval-cases"] });
    },
  });

  const allTraces = traces.data?.traces ?? [];
  const groupedTraceIds = useMemo(() => {
    const ids = Array.from(new Set(allTraces.map((trace) => trace.trace_id))).filter(Boolean);
    return ids.slice(0, 40);
  }, [allTraces]);
  const visibleTraces = selectedTraceId
    ? allTraces.filter((trace) => trace.trace_id === selectedTraceId)
    : allTraces;

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-900">Traces & Learning</h1>
        <span className="text-xs text-neutral-400">
          inspect memory, generate findings, export Codex tasks
        </span>
        <button
          type="button"
          onClick={() => traces.refetch()}
          disabled={traces.isFetching}
          className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          {traces.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-start gap-4">
          <span className="rounded-lg bg-neutral-900 p-2 text-white">
            <BrainCircuit className="h-5 w-5" />
          </span>
          <div className="min-w-[260px] flex-1">
            <h2 className="text-sm font-semibold text-neutral-950">Learning loop controls</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-neutral-600">
              Sync existing outcomes into traces, analyze repeated patterns, review findings,
              create eval cases, then export focused Codex task packets.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => syncOutcomes.mutate()}
              disabled={syncOutcomes.isPending}
              className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
            >
              {syncOutcomes.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />}
              Sync outcomes
            </button>
            <button
              type="button"
              onClick={() => analyze.mutate()}
              disabled={analyze.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
            >
              {analyze.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Analyze traces
            </button>
          </div>
        </div>
        {(syncOutcomes.isSuccess || analyze.isSuccess) && (
          <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {syncOutcomes.data ? `Synced ${syncOutcomes.data.created_count} outcome traces. ` : ""}
            {analyze.data ? `Created or updated ${analyze.data.created_or_updated_count} findings.` : ""}
          </div>
        )}
        {(syncOutcomes.isError || analyze.isError) && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Learning operation failed. Check backend logs.
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Post-change measurements</h2>
          <span className="text-xs text-neutral-400">
            1, 7, 30, and 90 day learning windows
          </span>
          <button
            type="button"
            onClick={() => measurements.refetch()}
            disabled={measurements.isFetching}
            className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
          >
            {measurements.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh metrics
          </button>
        </div>
        {measurements.isLoading ? (
          <LoadingRow label="Loading measurements..." />
        ) : measurements.isError ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Could not load measurements.
          </div>
        ) : (
          <div className="grid gap-3 p-4 md:grid-cols-2 2xl:grid-cols-4">
            {(measurements.data?.windows ?? []).map((window) => (
              <MeasurementCard key={window.days} window={window} />
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_460px]">
        <div className="space-y-4">
          <div className="rounded-xl border border-neutral-200 bg-white">
            <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
              <button
                type="button"
                onClick={() => setRecentTracesOpen((value) => !value)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                <Search className="h-4 w-4 flex-none text-neutral-500" />
                <h2 className="text-sm font-semibold text-neutral-950">Recent traces</h2>
                <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600">
                  {visibleTraces.length}
                </span>
                <ChevronDown
                  className={cn(
                    "ml-auto h-4 w-4 flex-none text-neutral-500 transition-transform",
                    recentTracesOpen && "rotate-180",
                  )}
                />
              </button>
              {recentTracesOpen && (
                <select
                  value={selectedTraceId}
                  onChange={(event) => setSelectedTraceId(event.target.value)}
                  className="rounded-md border border-neutral-200 bg-white px-3 py-1.5 text-xs text-neutral-700 outline-none"
                >
                  <option value="">All trace IDs</option>
                  {groupedTraceIds.map((traceId) => (
                    <option key={traceId} value={traceId}>
                      {traceId}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {recentTracesOpen && (
              <>
                {traces.isLoading ? (
                  <LoadingRow label="Loading traces..." />
                ) : visibleTraces.length === 0 ? (
                  <EmptyRow label="No traces found." />
                ) : (
                  <div className="divide-y divide-neutral-100">
                    {visibleTraces.map((trace) => (
                      <TraceRow key={trace.id} trace={trace} />
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="rounded-xl border border-neutral-200 bg-white">
            <div className="border-b border-neutral-100 px-4 py-3">
              <h2 className="text-sm font-semibold text-neutral-950">Eval cases</h2>
            </div>
            {evalCases.isLoading ? (
              <LoadingRow label="Loading eval cases..." />
            ) : (evalCases.data?.eval_cases ?? []).length === 0 ? (
              <EmptyRow label="No eval cases yet." />
            ) : (
              <div className="divide-y divide-neutral-100">
                {(evalCases.data?.eval_cases ?? []).map((item) => (
                  <EvalCaseRow key={item.id} item={item} />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-neutral-200 bg-white">
            <div className="border-b border-neutral-100 px-4 py-3">
              <h2 className="text-sm font-semibold text-neutral-950">Improvement findings</h2>
            </div>
            {findings.isLoading ? (
              <LoadingRow label="Loading findings..." />
            ) : (findings.data?.findings ?? []).length === 0 ? (
              <EmptyRow label="No findings yet. Run Analyze traces." />
            ) : (
              <div className="divide-y divide-neutral-100">
                {(findings.data?.findings ?? []).map((finding) => (
                  <FindingRow
                    key={finding.id}
                    finding={finding}
                    reviewPending={review.isPending}
                    evalPending={createEval.isPending}
                    packetPending={createPacket.isPending}
                    onAccept={() => review.mutate({ id: finding.id, status: "accepted" })}
                    onReject={() => review.mutate({ id: finding.id, status: "rejected" })}
                    onImplemented={() => review.mutate({ id: finding.id, status: "implemented" })}
                    onCreateEval={() => createEval.mutate(finding.id)}
                    onCreatePacket={() => createPacket.mutate(finding.id)}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-neutral-200 bg-white">
            <div className="border-b border-neutral-100 px-4 py-3">
              <h2 className="text-sm font-semibold text-neutral-950">Codex task packets</h2>
            </div>
            {taskPackets.isLoading ? (
              <LoadingRow label="Loading packets..." />
            ) : (taskPackets.data?.task_packets ?? []).length === 0 ? (
              <EmptyRow label="No task packets exported yet." />
            ) : (
              <div className="divide-y divide-neutral-100">
                {(taskPackets.data?.task_packets ?? []).map((packet) => (
                  <TaskPacketRow key={packet.id} packet={packet} />
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function LoadingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

function EmptyRow({ label }: { label: string }) {
  return <div className="px-4 py-8 text-sm text-neutral-500">{label}</div>;
}

function MeasurementCard({ window }: { window: LearningMeasurementWindow }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-neutral-950">
          Last {window.days} {window.days === 1 ? "day" : "days"}
        </h3>
        <span className="text-[11px] text-neutral-400">
          since {shortDate(window.since)}
        </span>
      </div>
      <div className="mt-3 grid gap-2">
        <MeasurementLine
          label="Manual edit rate"
          value={formatRate(window.manual_edit_rate)}
          detail={`${window.edited_draft_count}/${window.reviewed_draft_count} reviewed drafts`}
        />
        <MeasurementLine
          label="Bounce rate"
          value={formatRate(window.bounce_rate)}
          detail={`${window.bounced_email_count}/${window.sent_email_count} sent emails`}
        />
        <MeasurementLine
          label="Reply rate"
          value={formatRate(window.reply_rate)}
          detail={`${window.matched_reply_count}/${window.sent_email_count} sent emails`}
        />
        <MeasurementLine
          label="Booked qualified"
          value={String(window.booked_qualified_conversation_count)}
          detail={`${window.consult_booking_count} consults, ${window.qualified_observation_count} qualified observations`}
        />
      </div>
      {window.failed_email_count > 0 && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
          {window.failed_email_count} transport failures are tracked separately from bounces.
        </div>
      )}
    </div>
  );
}

function MeasurementLine({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-neutral-200 bg-white px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-neutral-600">{label}</span>
        <span className="text-sm font-semibold text-neutral-950">{value}</span>
      </div>
      <div className="mt-0.5 text-[11px] text-neutral-400">{detail}</div>
    </div>
  );
}

function TraceRow({ trace }: { trace: ProductTrace }) {
  const contextLabel =
    String(trace.context?.firm_name || trace.context?.contact_email || trace.entity_id || "") ||
    trace.entity_type ||
    "trace";
  return (
    <details className="group px-4 py-3">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
        <span className="rounded-md bg-neutral-900 px-2 py-1 font-mono text-[11px] text-white">
          {trace.event_type}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-neutral-900">
          {contextLabel}
        </span>
        <span className="text-xs text-neutral-400">{trace.surface}</span>
        <span className="font-mono text-[11px] text-neutral-400">{shortDate(trace.created_at)}</span>
      </summary>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <JsonBlock label="Input" value={trace.input} />
        <JsonBlock label="Output" value={trace.output} />
        <JsonBlock label="Diff" value={trace.diff} />
        <JsonBlock label="Context" value={trace.context} />
      </div>
      <div className="mt-2 font-mono text-[11px] text-neutral-400">
        trace {trace.trace_id} · request {trace.request_id || "none"}
      </div>
    </details>
  );
}

function FindingRow({
  finding,
  reviewPending,
  evalPending,
  packetPending,
  onAccept,
  onReject,
  onImplemented,
  onCreateEval,
  onCreatePacket,
}: {
  finding: ImprovementFinding;
  reviewPending: boolean;
  evalPending: boolean;
  packetPending: boolean;
  onAccept: () => void;
  onReject: () => void;
  onImplemented: () => void;
  onCreateEval: () => void;
  onCreatePacket: () => void;
}) {
  return (
    <div className="space-y-3 px-4 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", toneForSeverity(finding.severity))}>
          {finding.severity}
        </span>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", toneForStatus(finding.status))}>
          {finding.status}
        </span>
        <span className="text-[11px] text-neutral-400">
          confidence {finding.confidence ?? 0}%
        </span>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-neutral-950">{finding.summary}</h3>
        <p className="mt-1 text-xs leading-5 text-neutral-600">{finding.details}</p>
      </div>
      <details>
        <summary className="cursor-pointer text-xs font-medium text-neutral-500">
          Evidence and suggested change
        </summary>
        <div className="mt-2 space-y-2">
          <JsonBlock label="Evidence" value={finding.evidence} />
          <JsonBlock label="Suggested change" value={finding.suggested_change} />
        </div>
      </details>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onAccept}
          disabled={reviewPending}
          className="inline-flex items-center gap-1 rounded-md border border-emerald-200 px-2.5 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          Accept
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={reviewPending}
          className="inline-flex items-center gap-1 rounded-md border border-red-200 px-2.5 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
        >
          <XCircle className="h-3.5 w-3.5" />
          Reject
        </button>
        <button
          type="button"
          onClick={onImplemented}
          disabled={reviewPending}
          className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          Implemented
        </button>
        <button
          type="button"
          onClick={onCreateEval}
          disabled={evalPending}
          className="inline-flex items-center gap-1 rounded-md border border-neutral-200 px-2.5 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          <FileCode2 className="h-3.5 w-3.5" />
          Eval
        </button>
        <button
          type="button"
          onClick={onCreatePacket}
          disabled={packetPending}
          className="inline-flex items-center gap-1 rounded-md bg-neutral-900 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
        >
          Packet
        </button>
      </div>
    </div>
  );
}

function EvalCaseRow({ item }: { item: EvalCase }) {
  return (
    <details className="px-4 py-3">
      <summary className="cursor-pointer text-sm font-medium text-neutral-900">
        {item.name}
        <span className="ml-2 text-xs text-neutral-400">{item.workflow}</span>
      </summary>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <JsonBlock label="Input" value={item.input} />
        <JsonBlock label="Expected" value={item.expected} />
      </div>
    </details>
  );
}

function TaskPacketRow({ packet }: { packet: CodexTaskPacket }) {
  return (
    <details className="px-4 py-3">
      <summary className="cursor-pointer text-sm font-medium text-neutral-900">
        {packet.title}
        <span className="ml-2 text-xs text-neutral-400">{packet.status}</span>
      </summary>
      <div className="mt-2 space-y-2 text-xs text-neutral-600">
        {packet.packet_path && (
          <div className="break-all font-mono text-[11px] text-neutral-500">
            {packet.packet_path}
          </div>
        )}
        <JsonBlock label="Validation commands" value={packet.validation_commands} />
      </div>
    </details>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <pre className="max-h-72 overflow-auto rounded-md border border-neutral-200 bg-neutral-50 p-3 text-[11px] leading-5 text-neutral-800">
        {jsonPreview(value)}
      </pre>
    </div>
  );
}
