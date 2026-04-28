"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  getCadenceNextUp,
  getAutorespondSummary,
  type CadencePriorityRow,
} from "@/lib/api";

/**
 * Priority-ordered call queue.
 *
 * Joins cadence_entries with autorespond-events signals from PIF Stats
 * to compute a per-firm score. Top-to-bottom = call top-to-bottom. The
 * score formula lives in app/services/autorespond_signals.py.
 */
export default function CadencePage() {
  const [limit, setLimit] = useState(50);

  const queue = useQuery({
    queryKey: ["cadence-next-up", limit],
    queryFn: () => getCadenceNextUp(limit),
    refetchInterval: 30_000,
  });

  const summary = useQuery({
    queryKey: ["autorespond-summary"],
    queryFn: () => getAutorespondSummary(),
    refetchInterval: 60_000,
  });

  const items = queue.data?.items ?? [];
  const total = queue.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-5">
        <h1 className="text-2xl font-semibold">Call queue</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Firms ordered by call priority. Top of the list = call first.
          Score combines recent autorespond activity, ICP tier,
          DM-callability, and cadence stage. Recent activity weighs
          most — firms whose people interacted with our Precise system
          today float to the top.
        </p>
      </header>

      <SummaryStrip data={summary.data} />

      <div className="mt-6 overflow-x-auto rounded-lg border border-neutral-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="w-12 px-3 py-2 text-right">#</th>
              <th className="w-20 px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-left">Firm</th>
              <th className="w-14 px-3 py-2 text-center">Tier</th>
              <th className="w-32 px-3 py-2 text-left">Recent activity</th>
              <th className="px-3 py-2 text-left">Signal</th>
              <th className="px-3 py-2 text-left">Last contact in office</th>
              <th className="w-32 px-3 py-2 text-left">Stage</th>
              <th className="w-32 px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100">
            {queue.isLoading && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-neutral-400">
                  Loading queue…
                </td>
              </tr>
            )}
            {!queue.isLoading && items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-neutral-400">
                  No active cadence entries. Nothing to call.
                </td>
              </tr>
            )}
            {items.map((row, idx) => (
              <QueueRow key={row.id} index={idx + 1} row={row} />
            ))}
          </tbody>
        </table>
      </div>

      <footer className="mt-3 flex items-center justify-between text-xs text-neutral-500">
        <span>
          Showing {items.length} of {total} active cadence entries.
          Refresh every 30s; autorespond signals cache 60s server-side.
        </span>
        <span className="flex items-center gap-2">
          Show
          {[25, 50, 100, 200].map((n) => (
            <button
              key={n}
              onClick={() => setLimit(n)}
              className={`rounded px-2 py-1 text-xs ${
                limit === n
                  ? "bg-neutral-900 text-white"
                  : "border border-neutral-200 hover:bg-neutral-100"
              }`}
            >
              {n}
            </button>
          ))}
        </span>
      </footer>
    </div>
  );
}

function SummaryStrip({ data }: { data?: ReturnType<typeof getAutorespondSummary> extends Promise<infer R> ? R : never }) {
  if (!data || data.error) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        Autorespond summary unavailable
        {data?.error ? ` (${data.error})` : ""} — queue still works,
        but the priority bar above is from cached data.
      </div>
    );
  }
  const cards = [
    {
      label: "Events today",
      value: data.events_today ?? 0,
      hint: "Autorespond replies sent today",
    },
    {
      label: "This week",
      value: data.events_this_week ?? 0,
      hint: "Autorespond replies sent since Monday",
    },
    {
      label: "All-time",
      value: data.total_events ?? 0,
      hint: "Total autorespond events on record",
    },
  ];
  return (
    <div className="grid grid-cols-3 gap-3">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-lg border border-neutral-200 bg-white px-4 py-3 shadow-sm"
        >
          <div className="text-xs uppercase tracking-wide text-neutral-500">
            {c.label}
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">
            {c.value.toLocaleString()}
          </div>
          <div className="mt-1 text-[11px] text-neutral-500">{c.hint}</div>
        </div>
      ))}
    </div>
  );
}

function QueueRow({ index, row }: { index: number; row: CadencePriorityRow }) {
  const ar = row.autorespond;
  const tierColor =
    row.icp_tier === "A"
      ? "bg-emerald-100 text-emerald-800"
      : row.icp_tier === "B"
        ? "bg-sky-100 text-sky-800"
        : row.icp_tier === "C"
          ? "bg-neutral-100 text-neutral-700"
          : "bg-neutral-100 text-neutral-400";

  const dmContact = (row.available_contacts || []).find(
    (c) => (c.phone || "").trim().length > 0,
  );

  const lastEvent = ar.latest_event_at
    ? new Date(ar.latest_event_at)
    : null;
  const lastEventStr = lastEvent ? humanAge(lastEvent) : "—";

  const lastCallAge =
    row.last_call_age_hours != null ? humanHours(row.last_call_age_hours) : "—";

  const stageColor =
    row.cadence_stage === "callback_pending"
      ? "bg-amber-100 text-amber-800"
      : row.cadence_stage === "signal_detected"
        ? "bg-emerald-100 text-emerald-800"
        : row.cadence_stage === "call_retry"
          ? "bg-rose-100 text-rose-800"
          : "bg-neutral-100 text-neutral-700";

  return (
    <tr className="hover:bg-neutral-50">
      <td className="px-3 py-2 text-right text-xs text-neutral-400">{index}</td>
      <td className="px-3 py-2 text-right">
        <span
          className={`inline-block rounded px-2 py-0.5 text-xs font-mono tabular-nums ${
            row.priority_score >= 30
              ? "bg-emerald-100 text-emerald-900"
              : row.priority_score >= 10
                ? "bg-sky-100 text-sky-900"
                : "bg-neutral-100 text-neutral-600"
          }`}
        >
          {row.priority_score}
        </span>
      </td>
      <td className="px-3 py-2">
        <Link
          href={`/firms/${row.pif_id}`}
          className="font-medium text-neutral-900 hover:text-blue-600 hover:underline"
          title="Open firm detail page"
        >
          {row.firm_name || "(unnamed firm)"}
        </Link>
        {dmContact && (
          <div className="text-xs text-neutral-500">
            {dmContact.name}
            {dmContact.title ? ` · ${dmContact.title}` : ""}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-center">
        <span
          className={`inline-block w-6 rounded text-center text-xs font-semibold ${tierColor}`}
        >
          {row.icp_tier || "–"}
        </span>
      </td>
      <td className="px-3 py-2">
        {ar.events_24h > 0 || ar.events_7d > 0 ? (
          <div>
            <span className="font-mono text-xs">
              <span className="font-semibold text-emerald-700">
                {ar.events_24h}
              </span>
              <span className="text-neutral-400"> / </span>
              <span className="text-neutral-700">{ar.events_7d}</span>
            </span>
            <div className="text-[11px] text-neutral-500">
              {lastEventStr} · {ar.distinct_contact_count} ppl
            </div>
          </div>
        ) : (
          <span className="text-xs text-neutral-400">no events</span>
        )}
      </td>
      <td className="px-3 py-2">
        {ar.top_agent_types.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {ar.top_agent_types.map((t) => (
              <span
                key={t}
                className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-mono text-neutral-700"
              >
                {t}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-neutral-400">—</span>
        )}
        {ar.latest_subject && (
          <div
            className="mt-0.5 truncate text-[11px] text-neutral-500"
            title={ar.latest_subject}
          >
            “{ar.latest_subject}”
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-xs text-neutral-600">{lastCallAge}</td>
      <td className="px-3 py-2">
        <span
          className={`inline-block rounded px-2 py-0.5 text-[10px] font-mono ${stageColor}`}
        >
          {row.cadence_stage}
        </span>
      </td>
      <td className="px-3 py-2 text-right text-xs">
        <Link
          href={`/firms/${row.pif_id}`}
          className="text-blue-600 hover:underline"
        >
          firm →
        </Link>
      </td>
    </tr>
  );
}

function humanAge(d: Date): string {
  const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function humanHours(h: number): string {
  if (h < 1) return `${Math.floor(h * 60)}m ago`;
  if (h < 24) return `${h.toFixed(1)}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
