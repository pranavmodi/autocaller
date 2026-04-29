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
import { syncFirms, getReviewsSummary } from "@/lib/api";
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
      {searchMode === "firms" && reviewFilter !== "all" && hiddenByReviewFilter > 0 && (
        <p className="text-[11px] text-neutral-500">
          Hiding {hiddenByReviewFilter} firms on this page that don&apos;t have
          {reviewFilter === "google" ? " Google" : reviewFilter === "yelp" ? " Yelp" : ""} reviews stored.
          {totalPages > 1 ? " Use the pagination below to find more." : ""}
        </p>
      )}

      {/* Firms list */}
      {searchMode === "firms" && (
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
