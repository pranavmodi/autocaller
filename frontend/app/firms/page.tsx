"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  listPifFirms,
  searchPifPeople,
  type PifFirm,
  type PifPersonResult,
} from "@/lib/pifstats";
import { cn } from "@/lib/utils";
import {
  Building2,
  Search,
  ChevronRight,
  ChevronLeft,
  Filter,
  Users,
  User,
} from "lucide-react";

function tierColor(tier: string | null) {
  if (tier === "A") return "bg-emerald-100 text-emerald-800";
  if (tier === "B") return "bg-sky-100 text-sky-800";
  if (tier === "C") return "bg-amber-100 text-amber-800";
  if (tier === "D") return "bg-rose-100 text-rose-800";
  return "bg-neutral-100 text-neutral-500";
}

type ResearchFilter = "all" | "researched" | "unresearched";
type SearchMode = "firms" | "people";

const PAGE_SIZE = 25;

export default function FirmsPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [researchFilter, setResearchFilter] = useState<ResearchFilter>("all");
  const [searchMode, setSearchMode] = useState<SearchMode>("firms");

  // Firm search/list
  const firmsQuery = useQuery({
    queryKey: ["pif-firms", search, page],
    queryFn: () =>
      listPifFirms({
        search: search.trim() || undefined,
        page,
        page_size: PAGE_SIZE,
        sort: "updated_at",
        order: "desc",
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
  const firms = (data?.items ?? []).filter((f) => {
    if (researchFilter === "researched")
      return f.research_status === "completed" || f.last_researched_at;
    if (researchFilter === "unresearched")
      return !f.research_status || f.research_status !== "completed";
    return true;
  });
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 1;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Firms</h1>
        <p className="text-sm text-neutral-500">
          {total.toLocaleString()} PI firms from PIF Stats. Search by firm name,
          person name, email, or website.
        </p>
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
        <div className="flex items-center gap-2">
          <Filter className="h-3.5 w-3.5 text-neutral-400" />
          {(["all", "researched", "unresearched"] as ResearchFilter[]).map(
            (f) => (
              <button
                key={f}
                onClick={() => setResearchFilter(f)}
                className={cn(
                  "rounded-full border px-3 py-1 text-[11px] font-medium transition-colors",
                  researchFilter === f
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
                )}
              >
                {f === "all"
                  ? "All"
                  : f === "researched"
                    ? "Researched"
                    : "Not researched"}
              </button>
            ),
          )}
        </div>
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
