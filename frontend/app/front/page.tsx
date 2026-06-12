"use client";

import Link from "next/link";
import { Fragment, type ReactNode } from "react";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  RefreshCw,
  Signal,
  Users,
} from "lucide-react";
import {
  createFrontWarmBatch,
  getFrontSignals,
  getFrontStatus,
  getFrontWarmList,
  type FrontWarmFirm,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type SortKey = "warm_score" | "last_seen_at" | "last_referral_at" | "contact_count";

export default function FrontPage() {
  const qc = useQueryClient();
  const [selectedDomains, setSelectedDomains] = useState<Set<string>>(new Set());
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("warm_score");
  const [createdBatch, setCreatedBatch] = useState<{ id: string; link: string } | null>(null);

  const status = useQuery({
    queryKey: ["front-status"],
    queryFn: getFrontStatus,
    refetchInterval: 60_000,
  });
  const warmList = useQuery({
    queryKey: ["front-warm-list", 75],
    queryFn: () => getFrontWarmList(75),
    refetchInterval: 60_000,
  });
  const signals = useQuery({
    queryKey: ["front-signals"],
    queryFn: getFrontSignals,
    refetchInterval: 60_000,
  });

  const rows = useMemo(() => {
    const source = warmList.data?.warm_list ?? [];
    return [...source].sort((a, b) => {
      if (sortKey === "warm_score" || sortKey === "contact_count") {
        return Number(b[sortKey] || 0) - Number(a[sortKey] || 0);
      }
      return Date.parse(b[sortKey] || "") - Date.parse(a[sortKey] || "");
    });
  }, [sortKey, warmList.data?.warm_list]);

  const createBatch = useMutation({
    mutationFn: () =>
      createFrontWarmBatch({
        domains: Array.from(selectedDomains),
        created_by: "front-dashboard",
      }),
    onSuccess: (data) => {
      const id = data.batch.id;
      setCreatedBatch({ id, link: data.link || `/lead-gen?batch=${id}` });
      setSelectedDomains(new Set());
      qc.invalidateQueries({ queryKey: ["lead-gen-batches"] });
    },
  });

  const toggleSelected = (domain: string) => {
    setSelectedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain);
      else next.add(domain);
      return next;
    });
  };

  const toggleExpanded = (domain: string) => {
    setExpandedDomains((prev) => {
      const next = new Set(prev);
      if (next.has(domain)) next.delete(domain);
      else next.add(domain);
      return next;
    });
  };

  return (
    <div className="mx-auto min-w-0 max-w-[1500px] space-y-5">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">Front</h1>
        <span className="text-xs text-neutral-400">lead engine observability</span>
      </div>

      <SyncHealthStrip
        loading={status.isLoading}
        error={status.isError}
        health={status.data?.sync_health}
        states={status.data?.states ?? []}
        onRefresh={() => {
          status.refetch();
          warmList.refetch();
          signals.refetch();
        }}
      />

      <FunnelZone funnel={status.data?.funnel ?? []} loading={status.isLoading} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
        <WarmListZone
          rows={rows}
          loading={warmList.isLoading}
          error={warmList.isError}
          sortKey={sortKey}
          onSort={setSortKey}
          selectedDomains={selectedDomains}
          expandedDomains={expandedDomains}
          onToggleSelected={toggleSelected}
          onToggleExpanded={toggleExpanded}
          onCreateBatch={() => createBatch.mutate()}
          createPending={createBatch.isPending}
          createError={createBatch.isError ? String(createBatch.error?.message || "Could not create batch") : ""}
          createdBatch={createdBatch}
        />

        <div className="space-y-4">
          <TimingFeedZone
            loading={status.isLoading}
            rows={status.data?.timing_feed ?? []}
          />
          <SignalsZone
            loading={signals.isLoading}
            error={signals.isError}
            data={signals.data}
          />
        </div>
      </div>
    </div>
  );
}

function SyncHealthStrip({
  loading,
  error,
  health,
  states,
  onRefresh,
}: {
  loading: boolean;
  error: boolean;
  health: Awaited<ReturnType<typeof getFrontStatus>>["sync_health"] | undefined;
  states: Awaited<ReturnType<typeof getFrontStatus>>["states"];
  onRefresh: () => void;
}) {
  const stale = Boolean(health?.stale);
  return (
    <section
      className={cn(
        "rounded-lg border bg-white p-4",
        stale ? "border-red-200 bg-red-50" : "border-neutral-200",
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          {stale ? (
            <AlertTriangle className="h-5 w-5 text-red-600" />
          ) : (
            <Signal className="h-5 w-5 text-emerald-600" />
          )}
          <div>
            <div className="text-sm font-semibold text-neutral-900">Sync health</div>
            <div className="text-xs text-neutral-500">
              {loading ? "Loading..." : error ? "Unavailable" : stale ? "Stale" : "Current"}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="ml-auto inline-flex h-9 items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <HealthMetric label="Last run" value={formatDate(health?.last_run_at)} sub={formatAge(health?.last_run_age_hours)} />
        <HealthMetric label="Calls" value={`${health?.calls_used ?? "?"} / ${health?.call_budget ?? "?"}`} sub="used / budget" />
        <HealthMetric label="Watermark" value={formatDate(health?.latest_watermark)} sub={formatAge(health?.latest_watermark_age_hours)} />
        <HealthMetric label="Next run" value={formatDate(health?.next_daily_run_at)} sub="daily sync" />
        <HealthMetric label="Last error" value={health?.last_error || "None"} sub={states.length ? `${states.length} cursors` : "no cursors"} danger={Boolean(health?.last_error)} />
      </div>
    </section>
  );
}

function HealthMetric({ label, value, sub, danger = false }: { label: string; value: string; sub: string; danger?: boolean }) {
  return (
    <div className="min-w-0 rounded-md border border-neutral-200 bg-white px-3 py-2">
      <div className="text-xs font-medium text-neutral-500">{label}</div>
      <div className={cn("mt-1 truncate text-sm font-semibold", danger ? "text-red-700" : "text-neutral-900")}>{value}</div>
      <div className="mt-0.5 truncate text-xs text-neutral-400">{sub}</div>
    </div>
  );
}

function FunnelZone({ funnel, loading }: { funnel: Array<{ key: string; label: string; total: number; delta: number; last_24h: number }>; loading: boolean }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <Users className="h-4 w-4 text-neutral-500" />
        <h2 className="text-sm font-semibold text-neutral-900">Funnel</h2>
      </div>
      <div className="grid gap-3 md:grid-cols-5">
        {(loading ? [] : funnel).map((step) => (
          <div key={step.key} className="rounded-md border border-neutral-200 px-3 py-3">
            <div className="truncate text-xs font-medium text-neutral-500">{step.label}</div>
            <div className="mt-1 text-2xl font-semibold text-neutral-900">{step.total.toLocaleString()}</div>
            <div className={cn("mt-1 text-xs", step.delta >= 0 ? "text-emerald-700" : "text-red-700")}>
              {step.delta >= 0 ? "+" : ""}{step.delta.toLocaleString()} vs prior day
            </div>
          </div>
        ))}
        {loading && <div className="col-span-full text-sm text-neutral-500">Loading funnel...</div>}
      </div>
    </section>
  );
}

function WarmListZone({
  rows,
  loading,
  error,
  sortKey,
  onSort,
  selectedDomains,
  expandedDomains,
  onToggleSelected,
  onToggleExpanded,
  onCreateBatch,
  createPending,
  createError,
  createdBatch,
}: {
  rows: FrontWarmFirm[];
  loading: boolean;
  error: boolean;
  sortKey: SortKey;
  onSort: (key: SortKey) => void;
  selectedDomains: Set<string>;
  expandedDomains: Set<string>;
  onToggleSelected: (domain: string) => void;
  onToggleExpanded: (domain: string) => void;
  onCreateBatch: () => void;
  createPending: boolean;
  createError: string;
  createdBatch: { id: string; link: string } | null;
}) {
  return (
    <section className="min-w-0 rounded-lg border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-center gap-3 border-b border-neutral-200 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-neutral-900">Warm list</h2>
          <div className="text-xs text-neutral-500">{rows.length.toLocaleString()} synced firms</div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <SortButton active={sortKey === "warm_score"} onClick={() => onSort("warm_score")}>Score</SortButton>
          <SortButton active={sortKey === "last_referral_at"} onClick={() => onSort("last_referral_at")}>Referral</SortButton>
          <SortButton active={sortKey === "last_seen_at"} onClick={() => onSort("last_seen_at")}>Seen</SortButton>
          <button
            type="button"
            onClick={onCreateBatch}
            disabled={!selectedDomains.size || createPending}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-neutral-900 px-3 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create batch
          </button>
        </div>
        {(createError || createdBatch) && (
          <div className="basis-full text-xs">
            {createError ? (
              <span className="text-red-700">{createError}</span>
            ) : createdBatch ? (
              <Link className="font-medium text-emerald-700 hover:text-emerald-800" href={createdBatch.link}>
                Created {createdBatch.id.slice(0, 8)} in Lead Gen
              </Link>
            ) : null}
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-neutral-200 text-sm">
          <thead className="bg-neutral-50 text-left text-xs font-semibold uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="w-10 px-4 py-3" />
              <th className="px-4 py-3">Firm</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">Referral</th>
              <th className="px-4 py-3">Seen</th>
              <th className="px-4 py-3">Contacts</th>
              <th className="px-4 py-3">Signals</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {rows.map((row) => {
              const expanded = expandedDomains.has(row.domain);
              return (
                <Fragment key={row.domain}>
                  <tr className="hover:bg-neutral-50">
                    <td className="px-4 py-3 align-top">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selectedDomains.has(row.domain)}
                          onChange={() => onToggleSelected(row.domain)}
                          aria-label={`Select ${row.domain}`}
                          className="h-4 w-4 rounded border-neutral-300"
                        />
                        <button
                          type="button"
                          onClick={() => onToggleExpanded(row.domain)}
                          className="inline-flex h-6 w-6 items-center justify-center rounded-md text-neutral-500 hover:bg-neutral-100"
                          aria-label={`Toggle ${row.domain}`}
                        >
                          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                        </button>
                      </div>
                    </td>
                    <td className="max-w-[260px] px-4 py-3 align-top">
                      <div className="font-medium text-neutral-900">{row.firm_name || row.domain}</div>
                      <div className="truncate text-xs text-neutral-500">{row.domain} · {row.pif_id || "unmatched"}</div>
                    </td>
                    <td className="px-4 py-3 align-top font-semibold text-neutral-900">{row.warm_score}</td>
                    <td className="px-4 py-3 align-top text-neutral-600">{formatDate(row.last_referral_at)}</td>
                    <td className="px-4 py-3 align-top text-neutral-600">{formatDate(row.last_seen_at)}</td>
                    <td className="px-4 py-3 align-top text-neutral-600">
                      {row.eligible_contact_count} / {row.named_contacts.length}
                    </td>
                    <td className="max-w-[240px] px-4 py-3 align-top text-xs text-neutral-500">
                      {signalSummary(row.tech_signals)}
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="bg-neutral-50/70">
                      <td />
                      <td colSpan={6} className="px-4 py-3">
                        <div className="grid gap-2 md:grid-cols-2">
                          {row.named_contacts.map((contact) => (
                            <div key={contact.id} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="truncate text-sm font-medium text-neutral-900">{contact.name}</span>
                                {contact.emailed_before && (
                                  <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">emailed</span>
                                )}
                              </div>
                              <div className="mt-0.5 truncate text-xs text-neutral-500">{contact.title || "No title"} · {contact.email}</div>
                            </div>
                          ))}
                          {!row.named_contacts.length && (
                            <div className="text-sm text-neutral-500">No named contacts.</div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {loading && <div className="px-4 py-8 text-sm text-neutral-500">Loading warm list...</div>}
      {error && <div className="px-4 py-8 text-sm text-red-700">Could not load warm list.</div>}
    </section>
  );
}

function SortButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium",
        active ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-50",
      )}
    >
      {children}
    </button>
  );
}

function TimingFeedZone({
  loading,
  rows,
}: {
  loading: boolean;
  rows: NonNullable<Awaited<ReturnType<typeof getFrontStatus>>["timing_feed"]>;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <CalendarClock className="h-4 w-4 text-neutral-500" />
        <h2 className="text-sm font-semibold text-neutral-900">Timing feed</h2>
      </div>
      <div className="space-y-2">
        {rows.slice(0, 12).map((row) => (
          <div key={`${row.domain}-${row.kind}-${row.event_at}`} className="rounded-md border border-neutral-200 px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-medium text-neutral-900">{row.firm_name || row.domain}</span>
              <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-600">
                {row.kind === "weekly_referrer" ? "referrer" : "new"}
              </span>
            </div>
            <div className="mt-0.5 truncate text-xs text-neutral-500">{row.domain} · {formatDate(row.event_at)}</div>
          </div>
        ))}
        {!loading && !rows.length && <div className="text-sm text-neutral-500">No timing signals.</div>}
        {loading && <div className="text-sm text-neutral-500">Loading timing feed...</div>}
      </div>
    </section>
  );
}

function SignalsZone({
  loading,
  error,
  data,
}: {
  loading: boolean;
  error: boolean;
  data: Awaited<ReturnType<typeof getFrontSignals>> | undefined;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <Signal className="h-4 w-4 text-neutral-500" />
        <h2 className="text-sm font-semibold text-neutral-900">Signals</h2>
      </div>
      {loading ? (
        <div className="text-sm text-neutral-500">Loading signals...</div>
      ) : error ? (
        <div className="text-sm text-red-700">Could not load signals.</div>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Tech stack</div>
            <div className="space-y-2">
              {(data?.tech_stack_counts ?? []).slice(0, 6).map((signal) => (
                <div key={signal.signal} className="rounded-md border border-neutral-200 px-3 py-2">
                  <div className="text-sm font-medium text-neutral-900">{signal.signal}</div>
                  <div className="mt-1 text-xs text-neutral-500">
                    {signal.values.slice(0, 4).map((value) => `${value.value}: ${value.count}`).join(" · ") || "None"}
                  </div>
                </div>
              ))}
              {!data?.tech_stack_counts?.length && <div className="text-sm text-neutral-500">No tech signals.</div>}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Inbox mix</div>
            <div className="space-y-2">
              {(data?.inbox_activity_mix ?? []).slice(0, 5).map((inbox) => (
                <div key={inbox.inbox_id} className="flex items-center justify-between gap-3 rounded-md border border-neutral-200 px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-neutral-900">{inbox.name}</div>
                    <div className="truncate text-xs text-neutral-500">{formatDate(inbox.last_seen_at)}</div>
                  </div>
                  <div className="text-right text-sm font-semibold text-neutral-900">{inbox.conversation_count}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Suppress flags</div>
            <div className="space-y-2">
              {(data?.suppress_flagged_firms ?? []).slice(0, 6).map((row) => (
                <div key={row.domain} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
                  <div className="truncate text-sm font-medium text-amber-950">{row.domain}</div>
                  <div className="truncate text-xs text-amber-800">{row.reasons.join(", ")}</div>
                </div>
              ))}
              {!data?.suppress_flagged_firms?.length && <div className="text-sm text-neutral-500">No suppress flags.</div>}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "None";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "None";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatAge(hours?: number | null) {
  if (hours === null || hours === undefined) return "age unknown";
  if (hours < 1) return "<1h ago";
  if (hours < 48) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function signalSummary(value: Record<string, unknown>) {
  const entries = Object.entries(value || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!entries.length) return "None";
  return entries
    .slice(0, 3)
    .map(([key, v]) => `${key}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" · ");
}
