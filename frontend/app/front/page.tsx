"use client";

import Link from "next/link";
import { Fragment, type ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Signal,
  Users,
} from "lucide-react";
import {
  createFrontWarmBatch,
  getFrontCompetitorGraph,
  getFrontCompetitorSummary,
  getFrontCompetitors,
  getFrontSignals,
  getFrontStatus,
  getFrontWarmList,
  getResearchStatus,
  searchFrontCompetitors,
  type FrontCompetitorGraphLink,
  type FrontCompetitorGraphNode,
  type FrontCompetitorGraphResponse,
  type FrontWarmFirm,
  type FrontCompetitorSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type SortKey = "warm_score" | "last_seen_at" | "last_referral_at" | "contact_count";
type GraphFirm = {
  pif_id: string;
  firm_name: string;
  domain: string | null;
  metro?: string | null;
};

export default function FrontPage() {
  const qc = useQueryClient();
  const [selectedDomains, setSelectedDomains] = useState<Set<string>>(new Set());
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("warm_score");
  const [createdBatch, setCreatedBatch] = useState<{ id: string; link: string } | null>(null);
  const [graphFirm, setGraphFirm] = useState<GraphFirm | null>(null);

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
  const competitorSummary = useQuery({
    queryKey: ["front-competitor-summary"],
    queryFn: getFrontCompetitorSummary,
    refetchInterval: 60_000,
  });
  const researchStatus = useQuery({
    queryKey: ["research-status"],
    queryFn: getResearchStatus,
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
          competitorSummary.refetch();
          researchStatus.refetch();
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
          onViewGraph={setGraphFirm}
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
            researchStatus={researchStatus.data}
            researchStatusLoading={researchStatus.isLoading}
            competitorSummary={competitorSummary.data}
            competitorSummaryLoading={competitorSummary.isLoading}
            graphFirm={graphFirm}
            onGraphFirmChange={setGraphFirm}
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
  onViewGraph,
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
  onViewGraph: (firm: GraphFirm) => void;
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
                        <div className="grid gap-3 lg:grid-cols-2">
                          <div>
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Contacts</div>
                            <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-1">
                              {row.named_contacts.map((contact) => (
                                <div key={contact.id} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                                  <div className="flex min-w-0 items-center gap-2">
                                    <span className="truncate text-sm font-medium text-neutral-900">{contact.name}</span>
                                    {contact.persona && (
                                      <span className="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800">
                                        {contact.persona}
                                      </span>
                                    )}
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
                          </div>
                          <div>
                            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Competes with</div>
                            <CompetitorList row={row} onViewGraph={onViewGraph} />
                          </div>
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

function CompetitorList({ row, onViewGraph }: { row: FrontWarmFirm; onViewGraph: (firm: GraphFirm) => void }) {
  const competitors = useQuery({
    queryKey: ["front-competitors", row.pif_id || row.domain],
    queryFn: () =>
      getFrontCompetitors({
        domain: row.pif_id ? undefined : row.domain,
        pif_id: row.pif_id || undefined,
        limit: 5,
      }),
  });

  if (competitors.isLoading) {
    return <div className="text-sm text-neutral-500">Loading competitors...</div>;
  }
  if (competitors.isError) {
    return <div className="text-sm text-red-700">Could not load competitors.</div>;
  }
  const rows = competitors.data?.competitors ?? [];
  if (!rows.length) {
    return <div className="text-sm text-neutral-500">No graph neighbors yet.</div>;
  }
  const center = competitors.data?.firm;
  return (
    <div className="space-y-2">
      {center?.pif_id && (
        <button
          type="button"
          onClick={() =>
            onViewGraph({
              pif_id: center.pif_id,
              firm_name: center.firm_name,
              domain: center.domain,
              metro: center.metro,
            })
          }
          className="text-xs font-medium text-neutral-700 underline-offset-2 hover:text-neutral-950 hover:underline"
        >
          view graph
        </button>
      )}
      {rows.map((competitor) => (
        <div key={competitor.pif_id} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
          <div className="flex min-w-0 items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-neutral-900">{competitor.firm_name}</div>
              <div className="truncate text-xs text-neutral-500">{competitor.domain || competitor.metro || competitor.pif_id}</div>
            </div>
            <div className="shrink-0 text-sm font-semibold text-neutral-900">{Math.round(competitor.score * 100)}</div>
          </div>
          <button
            type="button"
            onClick={() =>
              onViewGraph({
                pif_id: competitor.pif_id,
                firm_name: competitor.firm_name,
                domain: competitor.domain,
                metro: competitor.metro,
              })
            }
            className="mt-1 text-xs font-medium text-neutral-700 underline-offset-2 hover:text-neutral-950 hover:underline"
          >
            view graph
          </button>
          <div className="mt-1 line-clamp-2 text-xs text-neutral-500">{competitor.evidence?.why || "Shared metro and case profile."}</div>
        </div>
      ))}
    </div>
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
  researchStatus,
  researchStatusLoading,
  competitorSummary,
  competitorSummaryLoading,
  graphFirm,
  onGraphFirmChange,
}: {
  loading: boolean;
  error: boolean;
  data: Awaited<ReturnType<typeof getFrontSignals>> | undefined;
  researchStatus: Awaited<ReturnType<typeof getResearchStatus>> | undefined;
  researchStatusLoading: boolean;
  competitorSummary: FrontCompetitorSummary | undefined;
  competitorSummaryLoading: boolean;
  graphFirm: GraphFirm | null;
  onGraphFirmChange: (firm: GraphFirm) => void;
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
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Research coverage</div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="rounded-md border border-neutral-200 px-3 py-2">
                <div className="text-sm font-medium text-neutral-900">
                  {researchStatusLoading
                    ? "Loading..."
                    : `${(researchStatus?.coverage.researched_firms ?? 0).toLocaleString()} / ${(researchStatus?.coverage.matched_firms ?? 0).toLocaleString()}`}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  firm research · {researchStatus?.coverage.research_percent ?? 0}%
                </div>
              </div>
              <div className="rounded-md border border-neutral-200 px-3 py-2">
                <div className="text-sm font-medium text-neutral-900">
                  {(researchStatus?.open_tasks.length ?? 0).toLocaleString()} open
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  staff {(researchStatus?.coverage.staff_researched_firms ?? 0).toLocaleString()} · behavior {(researchStatus?.coverage.behavior_analyzed_firms ?? 0).toLocaleString()}
                </div>
              </div>
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">Competitor graph</div>
            <CompetitorSearchBox onSelect={onGraphFirmChange} />
            <div className="rounded-md border border-neutral-200 px-3 py-2">
              <div className="text-sm font-medium text-neutral-900">
                {competitorSummaryLoading ? "Loading..." : `${(competitorSummary?.firms_with_metro ?? 0).toLocaleString()} firms / ${(competitorSummary?.edge_count ?? 0).toLocaleString()} edges`}
              </div>
              <div className="mt-1 truncate text-xs text-neutral-500">
                {competitorSummary?.last_computed_at ? `rebuilt ${formatDate(competitorSummary.last_computed_at)}` : "no rebuild yet"}
              </div>
            </div>
            <CompetitorGraphPanel selectedFirm={graphFirm} onSelectedFirmChange={onGraphFirmChange} />
          </div>
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

function CompetitorSearchBox({ onSelect }: { onSelect: (firm: GraphFirm) => void }) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timeout);
  }, [query]);

  const search = useQuery({
    queryKey: ["front-competitor-search", debouncedQuery],
    queryFn: () => searchFrontCompetitors({ q: debouncedQuery, limit: 8 }),
    enabled: debouncedQuery.length >= 2,
  });

  const results = search.data?.results ?? [];
  return (
    <div className="relative mb-2">
      <div className="flex h-10 items-center gap-2 rounded-md border border-neutral-200 bg-white px-3">
        <Search className="h-4 w-4 shrink-0 text-neutral-400" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Firm name or domain"
          className="min-w-0 flex-1 bg-transparent text-sm text-neutral-900 outline-none placeholder:text-neutral-400"
        />
        {search.isFetching && <Loader2 className="h-4 w-4 animate-spin text-neutral-400" />}
      </div>
      {debouncedQuery.length >= 2 && (
        <div className="absolute z-20 mt-1 max-h-80 w-full overflow-auto rounded-md border border-neutral-200 bg-white shadow-lg">
          {search.isError ? (
            <div className="px-3 py-2 text-sm text-red-700">Search unavailable.</div>
          ) : results.length ? (
            results.map((result) => (
              <button
                key={result.pif_id}
                type="button"
                onClick={() => {
                  onSelect({
                    pif_id: result.pif_id,
                    firm_name: result.firm_name,
                    domain: result.domain,
                    metro: result.metro,
                  });
                  setQuery(result.firm_name);
                  setDebouncedQuery("");
                }}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-neutral-50"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-neutral-900">{result.firm_name}</span>
                  <span className="block truncate text-xs text-neutral-500">{result.domain || result.metro || result.pif_id}</span>
                </span>
                <span className="shrink-0 text-xs text-neutral-500">{result.edge_count} edges</span>
              </button>
            ))
          ) : search.isFetching ? (
            <div className="px-3 py-2 text-sm text-neutral-500">Loading...</div>
          ) : (
            <div className="px-3 py-2 text-sm text-neutral-500">No matches.</div>
          )}
        </div>
      )}
    </div>
  );
}

function CompetitorGraphPanel({
  selectedFirm,
  onSelectedFirmChange,
}: {
  selectedFirm: GraphFirm | null;
  onSelectedFirmChange: (firm: GraphFirm) => void;
}) {
  const [depth, setDepth] = useState<1 | 2>(1);
  const [trail, setTrail] = useState<GraphFirm[]>([]);

  useEffect(() => {
    if (!selectedFirm) {
      setTrail([]);
      return;
    }
    setTrail((prev) => {
      const last = prev[prev.length - 1];
      if (last?.pif_id === selectedFirm.pif_id) return prev;
      return [selectedFirm];
    });
  }, [selectedFirm]);

  const graph = useQuery({
    queryKey: ["front-competitor-graph", selectedFirm?.pif_id, depth],
    queryFn: () => getFrontCompetitorGraph({ pif_id: selectedFirm?.pif_id || "", depth }),
    enabled: Boolean(selectedFirm?.pif_id),
  });

  if (!selectedFirm) {
    return <div className="mt-2 rounded-md border border-dashed border-neutral-200 px-3 py-4 text-sm text-neutral-500">No firm selected.</div>;
  }

  const data = graph.data;
  const noEdges = data && data.links.length === 0;
  return (
    <div className="mt-3 rounded-md border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-neutral-200 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-neutral-900">{selectedFirm.firm_name}</div>
          <div className="truncate text-xs text-neutral-500">{selectedFirm.domain || selectedFirm.metro || selectedFirm.pif_id}</div>
        </div>
        <div className="ml-auto flex rounded-md border border-neutral-200 p-0.5">
          <DepthButton active={depth === 1} onClick={() => setDepth(1)}>1 hop</DepthButton>
          <DepthButton active={depth === 2} onClick={() => setDepth(2)}>2 hops</DepthButton>
        </div>
      </div>
      {trail.length > 1 && (
        <div className="flex flex-wrap gap-1 border-b border-neutral-100 px-3 py-2">
          {trail.map((firm, index) => (
            <button
              key={`${firm.pif_id}-${index}`}
              type="button"
              onClick={() => {
                const nextTrail = trail.slice(0, index + 1);
                setTrail(nextTrail);
                onSelectedFirmChange(firm);
              }}
              className="max-w-[150px] truncate rounded border border-neutral-200 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-50"
            >
              {firm.firm_name}
            </button>
          ))}
        </div>
      )}
      <div className="p-3">
        {graph.isLoading ? (
          <div className="flex h-80 items-center justify-center text-sm text-neutral-500">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Loading graph...
          </div>
        ) : graph.isError ? (
          <div className="flex h-80 items-center justify-center text-sm text-red-700">Could not load graph.</div>
        ) : noEdges ? (
          <div className="flex h-80 items-center justify-center text-sm text-neutral-500">no competitor data for this firm</div>
        ) : data ? (
          <CompetitorGraphSvg
            data={data}
            onNodeClick={(node) => {
              if (node.is_center) return;
              const firm = {
                pif_id: node.pif_id,
                firm_name: node.firm_name,
                domain: node.domain,
                metro: node.metro,
              };
              setTrail((prev) => {
                const existingIndex = prev.findIndex((item) => item.pif_id === node.pif_id);
                if (existingIndex >= 0) return prev.slice(0, existingIndex + 1);
                return [...prev, firm];
              });
              onSelectedFirmChange(firm);
            }}
          />
        ) : null}
      </div>
    </div>
  );
}

function DepthButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-7 rounded px-2 text-xs font-medium",
        active ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-50",
      )}
    >
      {children}
    </button>
  );
}

type SimNode = FrontCompetitorGraphNode & SimulationNodeDatum;
type SimLink = Omit<FrontCompetitorGraphLink, "source" | "target"> &
  SimulationLinkDatum<SimNode> & {
    source: string | SimNode;
    target: string | SimNode;
  };

function CompetitorGraphSvg({
  data,
  onNodeClick,
}: {
  data: FrontCompetitorGraphResponse;
  onNodeClick: (node: FrontCompetitorGraphNode) => void;
}) {
  const width = 660;
  const height = 380;
  const [layout, setLayout] = useState<{ nodes: SimNode[]; links: SimLink[] }>({ nodes: [], links: [] });
  const [tooltip, setTooltip] = useState<{ x: number; y: number; link: FrontCompetitorGraphLink } | null>(null);

  useEffect(() => {
    const nodes: SimNode[] = data.nodes.map((node, index) => ({
      ...node,
      x: width / 2 + Math.cos(index) * 90,
      y: height / 2 + Math.sin(index) * 70,
    }));
    const links: SimLink[] = data.links.map((link) => ({ ...link }));
    const simulation = forceSimulation<SimNode>(nodes)
      .force(
        "link",
        forceLink<SimNode, SimLink>(links)
          .id((node) => node.pif_id)
          .distance((link) => 120 - Number(link.score || 0) * 45)
          .strength((link) => 0.28 + Number(link.score || 0) * 0.45),
      )
      .force("charge", forceManyBody<SimNode>().strength(-260))
      .force("collide", forceCollide<SimNode>().radius((node) => nodeRadius(node) + 10))
      .force("center", forceCenter(width / 2, height / 2))
      .on("tick", () => setLayout({ nodes: [...nodes], links: [...links] }));

    simulation.alpha(1).restart();
    return () => {
      simulation.stop();
    };
  }, [data]);

  const nodesById = useMemo(
    () => new Map(layout.nodes.map((node) => [node.pif_id, node])),
    [layout.nodes],
  );
  const metros = useMemo(
    () => Array.from(new Set(data.nodes.map((node) => node.metro || "unknown"))).slice(0, 8),
    [data.nodes],
  );

  const linkEndpoint = (value: string | SimNode) => (typeof value === "string" ? nodesById.get(value) : value);

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Competitive neighborhood graph"
        className="h-80 w-full rounded-md border border-neutral-100 bg-neutral-50"
      >
        <g>
          {layout.links.map((link, index) => {
            const source = linkEndpoint(link.source);
            const target = linkEndpoint(link.target);
            if (!source || !target) return null;
            return (
              <line
                key={`${String(source.pif_id)}-${String(target.pif_id)}-${index}`}
                x1={source.x || 0}
                y1={source.y || 0}
                x2={target.x || 0}
                y2={target.y || 0}
                stroke="#525252"
                strokeWidth={1 + Number(link.score || 0) * 4}
                strokeOpacity={0.18 + Number(link.score || 0) * 0.55}
                onMouseMove={(event) =>
                  setTooltip({
                    x: event.clientX,
                    y: event.clientY,
                    link: {
                      source: source.pif_id,
                      target: target.pif_id,
                      score: Number(link.score || 0),
                      components: link.components || {},
                      evidence_summary: link.evidence_summary || "",
                    },
                  })
                }
                onMouseLeave={() => setTooltip(null)}
              />
            );
          })}
        </g>
        <g>
          {layout.nodes.map((node) => {
            const radius = nodeRadius(node);
            return (
              <g
                key={node.pif_id}
                transform={`translate(${node.x || width / 2}, ${node.y || height / 2})`}
                className={node.is_center ? "" : "cursor-pointer"}
                onClick={() => onNodeClick(node)}
              >
                {node.is_center && <circle r={radius + 5} fill="none" stroke="#111827" strokeWidth={2.5} />}
                <circle r={radius} fill={metroColor(node.metro)} stroke="#fff" strokeWidth={1.5} />
                <text
                  x={radius + 6}
                  y={4}
                  className="pointer-events-none fill-neutral-800 text-[11px] font-medium"
                >
                  {truncateLabel(node.firm_name)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="mt-2 flex flex-wrap gap-2">
        {metros.map((metro) => (
          <span key={metro} className="inline-flex items-center gap-1 text-xs text-neutral-500">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: metroColor(metro) }} />
            {metro}
          </span>
        ))}
      </div>
      {tooltip && (
        <div
          className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-700 shadow-lg"
          style={{ left: tooltip.x + 12, top: tooltip.y + 12 }}
        >
          <div className="font-semibold text-neutral-900">score {tooltip.link.score.toFixed(2)}</div>
          <div className="mt-1">{tooltip.link.evidence_summary}</div>
          <div className="mt-1 text-neutral-500">{formatComponents(tooltip.link.components)}</div>
        </div>
      )}
    </div>
  );
}

function nodeRadius(node: Pick<FrontCompetitorGraphNode, "volume_proxy" | "is_center">) {
  const volume = Math.max(0, Number(node.volume_proxy || 0));
  const radius = 6 + Math.sqrt(volume) * 3.2;
  return Math.max(node.is_center ? 10 : 6, Math.min(22, radius));
}

const METRO_PALETTE = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#be123c", "#4f46e5"];

function metroColor(metro?: string | null) {
  const key = metro || "unknown";
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return METRO_PALETTE[hash % METRO_PALETTE.length];
}

function truncateLabel(value: string) {
  return value.length > 22 ? `${value.slice(0, 21)}...` : value;
}

function formatComponents(components: Record<string, number>) {
  const parts = Object.entries(components || {}).map(([key, value]) => `${key} ${Number(value || 0).toFixed(2)}`);
  return parts.slice(0, 5).join(" · ");
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
