"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  listPifFirms,
  searchPifPeople,
  type PifFirm,
  type PifPersonResult,
} from "@/lib/pifstats";
import {
  syncFirms,
  getReviewsSummary,
  getFirmsStats,
  getFirmsAutorespondSummary,
  getFirmsWithReviews,
  type FirmsStats,
  type AutorespondFirmRow,
  type FirmWithReviewsRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Building2,
  Search,
  ChevronRight,
  ChevronLeft,
  Filter,
  Users,
  User,
  RefreshCw,
  Star,
} from "lucide-react";

function tierColor(tier: string | null) {
  if (tier === "A") return "bg-emerald-100 text-emerald-800";
  if (tier === "B") return "bg-sky-100 text-sky-800";
  if (tier === "C") return "bg-amber-100 text-amber-800";
  if (tier === "D") return "bg-rose-100 text-rose-800";
  return "bg-neutral-100 text-neutral-500";
}

type ResearchFilter = "all" | "completed" | "pending";
type TierFilter = "all" | "A" | "B" | "C" | "D";
type SearchMode = "firms" | "people";
type ReviewFilter = "all" | "any" | "google" | "yelp";
type ActivityFilter = "all" | "autorespond_7d";

const PAGE_SIZE = 25;
// When the review filter is on, the matching set is small (operator-
// pasted reviews — usually <100). We intersect client-side after the
// PIF-Stats fetch, so bigger pages mean more matches per page and
// less pagination friction.
const PAGE_SIZE_REVIEW_FILTER = 100;

export default function FirmsPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [researchFilter, setResearchFilter] = useState<ResearchFilter>("all");
  const [tierFilter, setTierFilter] = useState<TierFilter>("all");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("all");
  const [searchMode, setSearchMode] = useState<SearchMode>("firms");

  // Reviews summary — small payload (~100 pif_ids), refreshed when the
  // review filter is active. Used to client-side intersect with the
  // server-paginated PIF Stats firm list.
  const reviews = useQuery({
    queryKey: ["reviews-summary"],
    queryFn: getReviewsSummary,
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  // Header stats — total firms, researched count, with-reviews count,
  // autorespond-7d unique-firm count. Cached 60s server-side; refetch
  // every 2 min on the client.
  const stats = useQuery({
    queryKey: ["firms-stats"],
    queryFn: getFirmsStats,
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  // Autorespond-7d list (only fetched when the activity filter is on).
  // Server returns rows pre-sorted by latest_event_at desc.
  const autorespond7d = useQuery({
    queryKey: ["firms-autorespond-7d"],
    queryFn: () => getFirmsAutorespondSummary(7),
    enabled: activityFilter === "autorespond_7d" && searchMode === "firms",
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  // Firms-with-reviews list (only fetched when the review filter is
  // not "all"). Avoids the "matches scattered across PIF-Stats
  // pagination" problem — backend fetches all matched pif_ids
  // directly so the operator sees every match in one view.
  const withReviews = useQuery({
    queryKey: ["firms-with-reviews", reviewFilter],
    queryFn: () => getFirmsWithReviews(reviewFilter as "any" | "google" | "yelp"),
    enabled:
      reviewFilter !== "all"
      && activityFilter === "all"
      && searchMode === "firms",
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const reviewIdSet = (() => {
    if (reviewFilter === "all" || !reviews.data) return null;
    const ids =
      reviewFilter === "google"
        ? reviews.data.google
        : reviewFilter === "yelp"
          ? reviews.data.yelp
          : reviews.data.any;
    return new Set(ids);
  })();

  // Firm search/list
  const firmsQuery = useQuery({
    queryKey: ["pif-firms", search, page, researchFilter, tierFilter, reviewFilter],
    queryFn: () =>
      listPifFirms({
        search: search.trim() || undefined,
        page,
        page_size:
          reviewFilter !== "all" ? PAGE_SIZE_REVIEW_FILTER : PAGE_SIZE,
        sort: "updated_at",
        order: "desc",
        research_status: researchFilter !== "all" ? researchFilter : undefined,
        icp_tier: tierFilter !== "all" ? tierFilter : undefined,
      }),
    enabled: searchMode === "firms",
    refetchInterval: 60_000,
  });

  // People search
  const peopleQuery = useQuery({
    queryKey: ["pif-people", search],
    queryFn: () => searchPifPeople(search.trim()),
    enabled: searchMode === "people" && search.trim().length > 1,
  });

  const data = firmsQuery.data;
  const allFirms = data?.items ?? [];
  // Apply the client-side review intersection. Server-side total /
  // total_pages are still authoritative for pagination since the
  // filter operates on the current page only.
  const firms =
    reviewIdSet === null
      ? allFirms
      : allFirms.filter((f) => reviewIdSet.has(f.id));
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 1;
  const hiddenByReviewFilter =
    reviewIdSet === null ? 0 : allFirms.length - firms.length;

  // Sync now — pulls researched firms into the local patients table so
  // they become callable leads. The background loop already does this
  // every 15 min by default; the button is for "I just researched a
  // batch on Mediflow and don't want to wait."
  const sync = useMutation({
    mutationFn: () => syncFirms(),
  });

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Firms</h1>
          <p className="text-sm text-neutral-500">
            {total.toLocaleString()} PI firms from PIF Stats. Search by firm name,
            person name, email, or website.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <button
            type="button"
            onClick={() => sync.mutate()}
            disabled={sync.isPending}
            title="Pull newly-researched firms from PIF Stats into the local leads table"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition",
              sync.isPending
                ? "border-neutral-200 bg-neutral-100 text-neutral-400"
                : "border-neutral-200 bg-white text-neutral-700 hover:border-neutral-300 hover:bg-neutral-50",
            )}
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", sync.isPending && "animate-spin")}
            />
            {sync.isPending ? "Syncing…" : "Sync from PIF Stats"}
          </button>
          {sync.data && (
            <span className="text-[10px] text-emerald-700">
              fetched {sync.data.fetched} · inserted {sync.data.inserted} ·
              updated {sync.data.updated}
              {sync.data.skipped > 0 ? ` · skipped ${sync.data.skipped}` : ""}
            </span>
          )}
          {sync.isError && (
            <span className="text-[10px] text-rose-600">
              {(sync.error as Error).message}
            </span>
          )}
        </div>
      </div>

      {/* Stats strip */}
      {searchMode === "firms" && (
        <FirmsStatsStrip data={stats.data} loading={stats.isLoading} />
      )}

      {/* Search + mode toggle */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
          <input
            type="text"
            placeholder={
              searchMode === "firms"
                ? "Search firms by name, email, website..."
                : "Search people by name, title..."
            }
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full rounded-xl border border-neutral-200 bg-white py-2.5 pl-10 pr-4 text-sm placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </div>
        <div className="flex overflow-hidden rounded-xl border border-neutral-200 text-[11px] font-medium">
          <button
            onClick={() => setSearchMode("firms")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 transition-colors",
              searchMode === "firms"
                ? "bg-neutral-900 text-white"
                : "bg-white text-neutral-600 hover:bg-neutral-50",
            )}
          >
            <Building2 className="h-3.5 w-3.5" />
            Firms
          </button>
          <button
            onClick={() => setSearchMode("people")}
            className={cn(
              "flex items-center gap-1.5 border-l border-neutral-200 px-3 py-2 transition-colors",
              searchMode === "people"
                ? "bg-neutral-900 text-white"
                : "bg-white text-neutral-600 hover:bg-neutral-50",
            )}
          >
            <User className="h-3.5 w-3.5" />
            People
          </button>
        </div>
      </div>

      {/* Filters (firms mode only) */}
      {searchMode === "firms" && (
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="h-3.5 w-3.5 text-neutral-400" />
          {(["all", "completed", "pending"] as ResearchFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => { setResearchFilter(f); setPage(1); }}
              className={cn(
                "rounded-full border px-3 py-1 text-[11px] font-medium transition-colors",
                researchFilter === f
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
              )}
            >
              {f === "all" ? "All" : f === "completed" ? "Researched" : "Not researched"}
            </button>
          ))}
          <span className="mx-1 text-neutral-300">|</span>
          {(["all", "A", "B", "C", "D"] as TierFilter[]).map((t) => (
            <button
              key={t}
              onClick={() => { setTierFilter(t); setPage(1); }}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                tierFilter === t
                  ? t === "all"
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : cn("border-transparent", tierColor(t))
                  : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
              )}
            >
              {t === "all" ? "All tiers" : `Tier ${t}`}
            </button>
          ))}
          <span className="mx-1 text-neutral-300">|</span>
          <Star className="h-3.5 w-3.5 text-neutral-400" />
          {(["all", "any", "google", "yelp"] as ReviewFilter[]).map((r) => {
            const summary = reviews.data;
            const count =
              r === "all"
                ? null
                : r === "any"
                  ? summary?.total_count
                  : r === "google"
                    ? summary?.google_count
                    : summary?.yelp_count;
            const label =
              r === "all"
                ? "Any reviews"
                : r === "any"
                  ? `Has reviews${count != null ? ` (${count})` : ""}`
                  : r === "google"
                    ? `Google${count != null ? ` (${count})` : ""}`
                    : `Yelp${count != null ? ` (${count})` : ""}`;
            return (
              <button
                key={r}
                onClick={() => { setReviewFilter(r); setPage(1); }}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                  reviewFilter === r
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
                )}
                title={
                  r === "all"
                    ? "Show all firms regardless of review presence"
                    : r === "any"
                      ? "Only firms with Google or Yelp reviews stored"
                      : `Only firms with ${r === "google" ? "Google" : "Yelp"} reviews stored`
                }
              >
                {label}
              </button>
            );
          })}
        </div>
      )}

      {/* Activity filter — autorespond events in last N days, sorted newest first */}
      {searchMode === "firms" && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-neutral-400">
            Activity
          </span>
          {(["all", "autorespond_7d"] as ActivityFilter[]).map((a) => {
            const count =
              a === "autorespond_7d"
                ? stats.data?.autorespond_7d_count
                : null;
            const label =
              a === "all"
                ? "All firms"
                : `Autorespond (7d)${count != null ? ` (${count})` : ""}`;
            return (
              <button
                key={a}
                onClick={() => { setActivityFilter(a); setPage(1); }}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                  activityFilter === a
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
                )}
                title={
                  a === "all"
                    ? "Show the standard firm list"
                    : "Only firms that received an autorespond email reply in the last 7 days, sorted by most-recent first"
                }
              >
                {label}
              </button>
            );
          })}
        </div>
      )}

      {/* Firms list — autorespond-7d, review-filter, or standard view */}
      {searchMode === "firms" && activityFilter === "autorespond_7d" && (
        <AutorespondFirmsList
          rows={autorespond7d.data?.items ?? []}
          loading={autorespond7d.isLoading}
        />
      )}
      {searchMode === "firms"
        && activityFilter === "all"
        && reviewFilter !== "all" && (
        <WithReviewsFirmsList
          rows={withReviews.data?.items ?? []}
          source={reviewFilter as "any" | "google" | "yelp"}
          loading={withReviews.isLoading}
        />
      )}
      {searchMode === "firms"
        && activityFilter === "all"
        && reviewFilter === "all" && (
        <>
          <div className="rounded-xl border border-neutral-200 bg-white">
            {firmsQuery.isLoading && (
              <div className="px-5 py-8 text-center text-xs text-neutral-400">
                Loading firms...
              </div>
            )}
            {!firmsQuery.isLoading && firms.length === 0 && (
              <div className="px-5 py-8 text-center text-xs text-neutral-400">
                No firms match the filter.
              </div>
            )}
            <div className="divide-y divide-neutral-100">
              {firms.map((f) => (
                <FirmRow key={f.id} firm={f} />
              ))}
            </div>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between text-xs text-neutral-500">
            <span>
              Page {page} of {totalPages} ({total.toLocaleString()} firms)
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="flex items-center gap-1 rounded-lg border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30"
              >
                <ChevronLeft className="h-3 w-3" />
                Prev
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="flex items-center gap-1 rounded-lg border border-neutral-300 px-2.5 py-1 text-xs font-medium disabled:opacity-30"
              >
                Next
                <ChevronRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </>
      )}

      {/* People search results */}
      {searchMode === "people" && (
        <div className="rounded-xl border border-neutral-200 bg-white">
          {!search.trim() && (
            <div className="px-5 py-8 text-center text-xs text-neutral-400">
              Type a name or title to search across all firms.
            </div>
          )}
          {peopleQuery.isLoading && (
            <div className="px-5 py-8 text-center text-xs text-neutral-400">
              Searching...
            </div>
          )}
          {peopleQuery.data && peopleQuery.data.length === 0 && (
            <div className="px-5 py-8 text-center text-xs text-neutral-400">
              No people found.
            </div>
          )}
          <div className="divide-y divide-neutral-100">
            {peopleQuery.data?.map((p, i) => (
              <div
                key={i}
                className="flex items-start gap-3 px-5 py-3.5 hover:bg-neutral-50 transition-colors"
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-neutral-100 text-xs font-bold text-neutral-500">
                  {p.name.charAt(0)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-neutral-900">
                      {p.name}
                    </span>
                    {p.title && (
                      <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-600 truncate max-w-[200px]">
                        {p.title}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5 text-[11px] text-neutral-500">
                    {p.firm_name && (
                      <span className="flex items-center gap-1">
                        <Building2 className="h-3 w-3" />
                        {p.firm_id ? (
                          <Link
                            href={`/firms/${p.firm_id}`}
                            className="text-blue-600 hover:underline"
                          >
                            {p.firm_name}
                          </Link>
                        ) : (
                          p.firm_name
                        )}
                      </span>
                    )}
                    {p.email && <span>{p.email}</span>}
                    {p.phone && <span className="font-mono">{p.phone}</span>}
                    {p.source && (
                      <span className="text-neutral-400">{p.source}</span>
                    )}
                  </div>
                </div>
                {p.linkedin && (
                  <a
                    href={p.linkedin}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] text-blue-600 hover:underline"
                  >
                    LinkedIn
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FirmRow({ firm }: { firm: PifFirm }) {
  const beh = firm.behavioral_data;
  const researched = firm.research_status === "completed" || !!firm.last_researched_at;

  return (
    <Link
      href={`/firms/${firm.id}`}
      className="flex items-center gap-4 px-5 py-3.5 hover:bg-neutral-50 transition-colors"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-neutral-100 text-sm font-bold text-neutral-500">
        {firm.firm_name.charAt(0)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-neutral-900 truncate">
            {firm.firm_name}
          </span>
          {firm.icp_tier && (
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-bold",
                tierColor(firm.icp_tier),
              )}
            >
              {firm.icp_tier}
            </span>
          )}
          {firm.icp_score != null && (
            <span className="text-[11px] font-mono text-neutral-400">
              {firm.icp_score}
            </span>
          )}
          {researched && (
            <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-600">
              RESEARCHED
            </span>
          )}
        </div>
        <div className="text-[11px] text-neutral-500 truncate">
          {firm.website ?? ""}
          {firm.leadership?.length > 0 &&
            ` · ${firm.leadership.length} leaders`}
          {firm.contacts?.length > 0 &&
            ` · ${firm.contacts.length} contacts`}
          {beh?.primary_pain_point &&
            ` · ${beh.primary_pain_point.replace(/_/g, " ")}`}
          {beh?.after_hours_ratio != null &&
            beh.after_hours_ratio > 0.5 &&
            ` · ${Math.round(beh.after_hours_ratio * 100)}% after-hrs`}
        </div>
      </div>
      <div className="flex items-center gap-3 text-xs text-neutral-400">
        {firm.phones?.length > 0 && (
          <span className="hidden font-mono text-[11px] sm:inline">
            {firm.phones[0]}
          </span>
        )}
        <ChevronRight className="h-4 w-4" />
      </div>
    </Link>
  );
}

function FirmsStatsStrip({
  data,
  loading,
}: {
  data?: FirmsStats;
  loading?: boolean;
}) {
  const cards: Array<{
    label: string;
    value: number | null | undefined;
    hint: string;
  }> = [
    {
      label: "Total firms",
      value: data?.total_firms,
      hint: "All PI firms in PIF Stats",
    },
    {
      label: "Researched",
      value: data?.researched_count,
      hint: "research_status = completed",
    },
    {
      label: "With reviews",
      value: data?.with_reviews_count,
      hint: "Google or Yelp content stored locally",
    },
    {
      label: "Autorespond (7d)",
      value: data?.autorespond_7d_count,
      hint: "Unique firms with at least 1 autorespond event in last 7 days",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-lg border border-neutral-200 bg-white px-4 py-3 shadow-sm"
        >
          <div className="text-[10px] font-medium uppercase tracking-wide text-neutral-500">
            {c.label}
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-neutral-900">
            {loading
              ? "…"
              : c.value == null
                ? "—"
                : c.value.toLocaleString()}
          </div>
          <div className="mt-0.5 text-[11px] text-neutral-500">{c.hint}</div>
        </div>
      ))}
    </div>
  );
}

function AutorespondFirmsList({
  rows,
  loading,
}: {
  rows: AutorespondFirmRow[];
  loading?: boolean;
}) {
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-neutral-500">
        Firms with autorespond activity in the last 7 days, sorted by
        most-recent event first. Click a firm name for the full detail
        page (research, contacts, calls, reviews).
      </p>
      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
        {loading && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">
            Loading autorespond activity…
          </div>
        )}
        {!loading && rows.length === 0 && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">
            No autorespond activity in the last 7 days.
          </div>
        )}
        {!loading && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-[10px] uppercase tracking-wide text-neutral-500">
              <tr className="text-left">
                <th className="w-10 px-3 py-2 text-right font-medium">#</th>
                <th className="px-3 py-2 font-medium">Firm</th>
                <th className="w-32 px-3 py-2 font-medium">Latest event</th>
                <th className="w-24 px-3 py-2 font-medium">24h / 7d</th>
                <th className="px-3 py-2 font-medium">Top agent_types</th>
                <th className="w-20 px-3 py-2 text-right font-medium">Contacts</th>
                <th className="px-3 py-2 font-medium">Latest subject</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {rows.map((r, idx) => (
                <tr key={r.pif_id} className="hover:bg-neutral-50">
                  <td className="px-3 py-2 text-right text-xs text-neutral-400">
                    {idx + 1}
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/firms/${r.pif_id}`}
                      className="font-medium text-neutral-900 hover:text-blue-600 hover:underline"
                      title="Open firm detail"
                    >
                      {r.firm_name || "(unnamed firm)"}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-600">
                    {r.latest_event_at
                      ? humanAgo(r.latest_event_at)
                      : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span className="font-mono text-xs">
                      <span className="font-semibold text-emerald-700">
                        {r.events_24h}
                      </span>
                      <span className="text-neutral-400"> / </span>
                      <span className="text-neutral-700">{r.events_7d}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {r.top_agent_types.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {r.top_agent_types.map((t) => (
                          <span
                            key={t}
                            className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[10px] text-neutral-700"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-neutral-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-xs tabular-nums">
                    {r.distinct_contact_count}
                  </td>
                  <td
                    className="max-w-[24rem] truncate px-3 py-2 text-[11px] text-neutral-500"
                    title={r.latest_subject}
                  >
                    {r.latest_subject ? `“${r.latest_subject}”` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function humanAgo(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function WithReviewsFirmsList({
  rows,
  source,
  loading,
}: {
  rows: FirmWithReviewsRow[];
  source: "any" | "google" | "yelp";
  loading?: boolean;
}) {
  const sourceLabel =
    source === "any" ? "Google or Yelp" : source === "google" ? "Google" : "Yelp";
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-neutral-500">
        All firms with {sourceLabel} reviews stored locally — every
        match shown in one view, sorted by most-recent review-paste
        first. Click a firm name for the full detail page.
      </p>
      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
        {loading && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">
            Loading firms with reviews…
          </div>
        )}
        {!loading && rows.length === 0 && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">
            No firms with {sourceLabel} reviews yet. Paste reviews via
            the firm detail page.
          </div>
        )}
        {!loading && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-[10px] uppercase tracking-wide text-neutral-500">
              <tr className="text-left">
                <th className="w-10 px-3 py-2 text-right font-medium">#</th>
                <th className="px-3 py-2 font-medium">Firm</th>
                <th className="w-14 px-3 py-2 text-center font-medium">Tier</th>
                <th className="px-3 py-2 font-medium">Phone</th>
                <th className="w-28 px-3 py-2 text-right font-medium">Google</th>
                <th className="w-28 px-3 py-2 text-right font-medium">Yelp</th>
                <th className="w-32 px-3 py-2 font-medium">Reviews updated</th>
                <th className="w-20 px-3 py-2 text-right font-medium">Contacts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {rows.map((r, idx) => (
                <tr key={r.pif_id} className="hover:bg-neutral-50">
                  <td className="px-3 py-2 text-right text-xs text-neutral-400">
                    {idx + 1}
                  </td>
                  <td className="px-3 py-2">
                    {r.missing ? (
                      <span className="text-neutral-400">
                        (PIF Stats record unavailable)
                      </span>
                    ) : (
                      <Link
                        href={`/firms/${r.pif_id}`}
                        className="font-medium text-neutral-900 hover:text-blue-600 hover:underline"
                        title="Open firm detail"
                      >
                        {r.firm_name || "(unnamed firm)"}
                      </Link>
                    )}
                    {r.research_status === "completed" && (
                      <span className="ml-1.5 rounded bg-emerald-50 px-1 py-0.5 text-[9px] font-semibold text-emerald-700">
                        RESEARCHED
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span
                      className={cn(
                        "inline-block w-6 rounded text-center text-xs font-semibold",
                        tierColor(r.icp_tier),
                      )}
                    >
                      {r.icp_tier || "–"}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-neutral-600">
                    {(r.phones && r.phones[0]) || "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r.google_chars > 0 ? (
                      <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-emerald-800">
                        {r.google_chars.toLocaleString()} chars
                      </span>
                    ) : (
                      <span className="text-xs text-neutral-300">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r.yelp_chars > 0 ? (
                      <span className="rounded bg-rose-50 px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-rose-800">
                        {r.yelp_chars.toLocaleString()} chars
                      </span>
                    ) : (
                      <span className="text-xs text-neutral-300">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-600">
                    {r.reviews_updated_at
                      ? humanAgo(r.reviews_updated_at)
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-right text-xs tabular-nums">
                    {r.contacts_count + r.leadership_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
