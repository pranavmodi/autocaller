"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { listCalls } from "@/lib/api";
import { OutcomePill } from "@/components/OutcomePill";
import { cn } from "@/lib/utils";
import type { CallOutcome } from "@/types";

const OUTCOME_FILTERS: Array<{ value: CallOutcome | "all"; label: string }> = [
  { value: "all", label: "All" },
  { value: "demo_scheduled", label: "Demos" },
  { value: "callback_requested", label: "Callbacks" },
  { value: "not_interested", label: "Not interested" },
  { value: "gatekeeper_only", label: "Gatekeepers" },
  { value: "voicemail", label: "Voicemail" },
  { value: "no_answer", label: "No answer" },
  { value: "failed", label: "Failed" },
];

type ModeFilter = "all" | "real" | "mock";

export default function CallsPage() {
  const [filter, setFilter] = useState<CallOutcome | "all">("all");
  const [modeFilter, setModeFilter] = useState<ModeFilter>("all");

  const { data, isLoading } = useQuery({
    queryKey: ["calls", 200],
    queryFn: () => listCalls(200, 0),
    refetchInterval: 15_000,
  });

  const calls = (data?.calls ?? []).filter((c) => {
    if (filter !== "all" && c.outcome !== filter) return false;
    if (modeFilter === "real" && c.mock_mode) return false;
    if (modeFilter === "mock" && !c.mock_mode) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Call history</h1>
        <p className="text-sm text-neutral-500">
          All call attempts. Click a row to see the transcript and recording.
        </p>
      </div>

      {/* Filter pills */}
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {OUTCOME_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                filter === f.value
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] uppercase text-neutral-400">Mode:</span>
          {(["all", "real", "mock"] as ModeFilter[]).map((m) => (
            <button
              key={m}
              onClick={() => setModeFilter(m)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors",
                modeFilter === m
                  ? m === "mock"
                    ? "border-amber-500 bg-amber-50 text-amber-700"
                    : m === "real"
                      ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                      : "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
              )}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">When</th>
              <th className="px-4 py-2.5 text-left font-medium">Mode</th>
              <th className="px-4 py-2.5 text-left font-medium">Lead</th>
              <th className="px-4 py-2.5 text-left font-medium">Firm</th>
              <th className="px-4 py-2.5 text-left font-medium">State</th>
              <th className="px-4 py-2.5 text-left font-medium">Outcome</th>
              <th className="px-4 py-2.5 text-left font-medium">Disposition</th>
              <th className="px-4 py-2.5 text-center font-medium">Score</th>
              <th className="px-4 py-2.5 text-right font-medium">Duration</th>
              <th className="px-4 py-2.5 text-center font-medium">Audio</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-xs text-neutral-400">
                  loading…
                </td>
              </tr>
            )}
            {!isLoading && calls.length === 0 && (
              <tr>
                <td colSpan={10} className="px-4 py-6 text-center text-xs text-neutral-400">
                  No calls match the filter.
                </td>
              </tr>
            )}
            {calls.map((c) => (
              <tr
                key={c.call_id}
                className="cursor-pointer border-t border-neutral-100 hover:bg-neutral-50"
              >
                <td className="px-4 py-2.5 align-top">
                  <Link
                    href={`/calls/${c.call_id}`}
                    className="block text-xs text-neutral-600"
                    aria-label={`open call ${c.call_id}`}
                  >
                    {c.started_at
                      ? formatDistanceToNow(new Date(c.started_at), { addSuffix: true })
                      : "—"}
                  </Link>
                </td>
                <td className="px-4 py-2.5 align-top">
                  <Link href={`/calls/${c.call_id}`}>
                    {c.mock_mode ? (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-inset ring-amber-200">
                        MOCK
                      </span>
                    ) : (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
                        REAL
                      </span>
                    )}
                  </Link>
                </td>
                <td className="px-4 py-2.5 align-top">
                  <Link href={`/calls/${c.call_id}`} className="font-medium text-neutral-900">
                    {c.patient_name || "(unknown)"}
                  </Link>
                </td>
                <td className="px-4 py-2.5 align-top text-neutral-700">
                  <Link href={`/calls/${c.call_id}`}>{c.firm_name || "—"}</Link>
                </td>
                <td className="px-4 py-2.5 align-top text-neutral-500">
                  <Link href={`/calls/${c.call_id}`}>{c.lead_state ?? "—"}</Link>
                </td>
                <td className="px-4 py-2.5 align-top">
                  <Link href={`/calls/${c.call_id}`}>
                    <OutcomePill outcome={c.outcome} />
                  </Link>
                </td>
                <td className="px-4 py-2.5 align-top">
                  <Link href={`/calls/${c.call_id}`} className="text-xs text-neutral-600">
                    {c.gtm_disposition ? (
                      <span className="font-mono">{c.gtm_disposition}</span>
                    ) : (
                      <span className="text-neutral-300">—</span>
                    )}
                  </Link>
                </td>
                <td className="px-4 py-2.5 align-top text-center">
                  <Link href={`/calls/${c.call_id}`}>
                    {c.judge_score != null ? (
                      <span className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
                        c.judge_score >= 8 ? "bg-emerald-50 text-emerald-700" :
                        c.judge_score >= 5 ? "bg-amber-50 text-amber-700" :
                        "bg-rose-50 text-rose-700"
                      )}>
                        {c.judge_score}
                      </span>
                    ) : (
                      <span className="text-[10px] text-neutral-300">pending</span>
                    )}
                  </Link>
                </td>
                <td className="px-4 py-2.5 align-top text-right text-neutral-600">
                  <Link href={`/calls/${c.call_id}`}>{c.duration_seconds}s</Link>
                </td>
                <td className="px-4 py-2.5 align-top text-center text-neutral-500">
                  <Link href={`/calls/${c.call_id}`}>{c.has_recording ? "🎙" : "—"}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-neutral-400">
        {calls.length} of {data?.total ?? 0} total calls • auto-refreshes every 15s
      </p>
    </div>
  );
}
