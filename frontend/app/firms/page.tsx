"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchPifFirms, listPifFirms, type PifFirm } from "@/lib/pifstats";
import { cn } from "@/lib/utils";
import { Building2, Search, ChevronRight } from "lucide-react";

function tierColor(tier: string | null) {
  if (tier === "A") return "bg-emerald-100 text-emerald-800";
  if (tier === "B") return "bg-sky-100 text-sky-800";
  if (tier === "C") return "bg-amber-100 text-amber-800";
  return "bg-neutral-100 text-neutral-600";
}

export default function FirmsPage() {
  const [search, setSearch] = useState("");

  const { data: firms, isLoading } = useQuery({
    queryKey: ["pif-firms", search],
    queryFn: () =>
      search.trim()
        ? searchPifFirms(search.trim(), 50)
        : listPifFirms("icp_score", "desc", 50),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Firms</h1>
        <p className="text-sm text-neutral-500">
          PI firms from the PIF Stats pipeline — ranked by ICP score. Click to view contacts, behavior, and intel.
        </p>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
        <input
          type="text"
          placeholder="Search firms by name, email, or website..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-xl border border-neutral-200 bg-white py-2.5 pl-10 pr-4 text-sm placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
        />
      </div>

      {/* Firms list */}
      <div className="rounded-xl border border-neutral-200 bg-white">
        {isLoading && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">Loading firms...</div>
        )}
        {!isLoading && (!firms || firms.length === 0) && (
          <div className="px-5 py-8 text-center text-xs text-neutral-400">No firms found.</div>
        )}
        <div className="divide-y divide-neutral-100">
          {firms?.map((f) => (
            <Link
              key={f.id}
              href={`/firms/${f.id}`}
              className="flex items-center gap-4 px-5 py-3.5 hover:bg-neutral-50 transition-colors"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-neutral-100 text-sm font-bold text-neutral-500">
                {f.firm_name.charAt(0)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-neutral-900 truncate">
                    {f.firm_name}
                  </span>
                  {f.icp_tier && (
                    <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-bold", tierColor(f.icp_tier))}>
                      {f.icp_tier}
                    </span>
                  )}
                  {f.icp_score != null && (
                    <span className="text-[11px] font-mono text-neutral-400">{f.icp_score}</span>
                  )}
                </div>
                <div className="text-[11px] text-neutral-500 truncate">
                  {f.website ?? "—"}
                  {f.leadership?.length > 0 && ` · ${f.leadership.length} leaders`}
                  {f.behavioral_data?.primary_pain_point &&
                    ` · ${f.behavioral_data.primary_pain_point.replace(/_/g, " ")}`}
                  {f.behavioral_data?.after_hours_ratio != null &&
                    f.behavioral_data.after_hours_ratio > 0.5 &&
                    ` · ${Math.round(f.behavioral_data.after_hours_ratio * 100)}% after-hours`}
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs text-neutral-400">
                {f.phones?.length > 0 && (
                  <span className="hidden font-mono sm:inline">{f.phones[0]}</span>
                )}
                <ChevronRight className="h-4 w-4" />
              </div>
            </Link>
          ))}
        </div>
      </div>

      <p className="text-xs text-neutral-400">
        {firms?.length ?? 0} firms · sorted by ICP score · data from PIF Stats
      </p>
    </div>
  );
}
