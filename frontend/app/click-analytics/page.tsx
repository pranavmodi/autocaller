"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import {
  getClickAnalytics,
  type ClickAnalyticsGroupBy,
  type ClickAnalyticsRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const WINDOWS = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 0 },
];

const DEFAULT_GROUPS: Array<{ key: ClickAnalyticsGroupBy; label: string }> = [
  { key: "firm_name", label: "Firm" },
  { key: "app_name", label: "App" },
  { key: "source", label: "Source" },
  { key: "contact", label: "Contact" },
  { key: "persona", label: "Persona" },
  { key: "day", label: "Day" },
  { key: "pif_id", label: "PIF ID" },
  { key: "batch_item", label: "Batch item" },
];

function formatDateTime(value: string | null) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function shortId(value: string | null) {
  return value ? value.slice(0, 10) : "-";
}

function formatRatio(value: number | undefined) {
  return typeof value === "number" ? value.toFixed(3) : "0.000";
}

function formatMs(value: number | null | undefined) {
  if (typeof value !== "number") return "-";
  return `${Math.round(value).toLocaleString()} ms`;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-md border border-neutral-100 bg-neutral-50 px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold text-neutral-950">{value}</div>
    </div>
  );
}

function UserAgent({ value }: { value: string | null }) {
  if (!value) return <span className="text-neutral-400">-</span>;
  const compact = value.length > 80 ? `${value.slice(0, 80)}...` : value;
  return <span title={value}>{compact}</span>;
}

function RecentClickRow({ click }: { click: ClickAnalyticsRow }) {
  return (
    <tr className="border-t border-neutral-100">
      <td className="whitespace-nowrap px-3 py-2 text-xs text-neutral-600">
        {formatDateTime(click.clicked_at)}
      </td>
      <td className="px-3 py-2">
        <div className="text-sm font-medium text-neutral-900">{click.firm_name}</div>
        <div className="mt-0.5 text-xs text-neutral-500">
          {click.contact_name || "Unknown contact"}
          {click.contact_email ? ` · ${click.contact_email}` : ""}
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-xs text-neutral-600">
        {click.app_name}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-xs text-neutral-600">
        {click.source_label}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-xs text-neutral-600">
        {click.persona || "-"}
      </td>
      <td className="max-w-xs px-3 py-2 text-xs text-neutral-500">
        <UserAgent value={click.user_agent} />
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right text-xs text-neutral-500">
        {click.batch_item_id ? (
          <a
            href={`/lead-gen?item=${encodeURIComponent(click.batch_item_id)}`}
            className="inline-flex items-center gap-1 font-medium text-neutral-700 hover:text-neutral-950"
          >
            {shortId(click.batch_item_id)}
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : (
          "-"
        )}
      </td>
    </tr>
  );
}

export default function ClickAnalyticsPage() {
  const [sinceDays, setSinceDays] = useState(30);
  const [groupBy, setGroupBy] = useState<ClickAnalyticsGroupBy>("firm_name");
  const analytics = useQuery({
    queryKey: ["click-analytics", sinceDays, groupBy],
    queryFn: () => getClickAnalytics({ sinceDays, groupBy, limit: 100 }),
    refetchInterval: 30_000,
  });

  const groups = analytics.data?.groups ?? [];
  const recentClicks = analytics.data?.recent_clicks ?? [];
  const summary = analytics.data?.summary;
  const humanSessionsByPage = analytics.data?.human_sessions_by_page ?? [];
  const maxGroupClicks = useMemo(
    () => Math.max(...groups.map((group) => group.click_count), 1),
    [groups],
  );
  const availableGroups = analytics.data?.available_groups ?? DEFAULT_GROUPS;

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="rounded-lg bg-neutral-900 p-2 text-white">
          <BarChart3 className="h-4 w-4" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Click Analytics</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            tracked link engagement by app, firm, contact, source, and segment
          </p>
        </div>
        <button
          type="button"
          onClick={() => analytics.refetch()}
          disabled={analytics.isFetching}
          className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          {analytics.isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh
        </button>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex gap-1">
            {WINDOWS.map((window) => (
              <button
                key={window.label}
                type="button"
                onClick={() => setSinceDays(window.days)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  sinceDays === window.days
                    ? "bg-neutral-900 text-white"
                    : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200",
                )}
              >
                {window.label}
              </button>
            ))}
          </div>
          <label className="ml-auto flex items-center gap-2 text-xs font-medium text-neutral-500">
            Group by
            <select
              value={groupBy}
              onChange={(event) => setGroupBy(event.target.value as ClickAnalyticsGroupBy)}
              className="rounded-md border border-neutral-200 bg-white px-2 py-1.5 text-sm font-medium text-neutral-800"
            >
              {availableGroups.map((group) => (
                <option key={group.key} value={group.key}>
                  {group.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
          <Metric label="Clicks" value={summary?.click_count ?? 0} />
          <Metric label="Human sessions" value={summary?.distinct_human_sessions ?? 0} />
          <Metric label="Human/click" value={formatRatio(summary?.human_to_click_ratio)} />
          <Metric label="Contacts" value={summary?.contact_count ?? 0} />
          <Metric label="Firms" value={summary?.firm_count ?? 0} />
          <Metric label="First click" value={formatDateTime(summary?.first_clicked_at ?? null)} />
          <Metric label="Last click" value={formatDateTime(summary?.last_clicked_at ?? null)} />
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">
            Human sessions by page
          </h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            browser beacon sessions grouped by landing page
          </p>
        </div>
        {analytics.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading human sessions...
          </div>
        ) : humanSessionsByPage.length === 0 ? (
          <div className="px-4 py-8 text-sm text-neutral-500">
            No human sessions in this window.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">Page</th>
                  <th className="px-3 py-2 text-right font-semibold">Sessions</th>
                  <th className="px-3 py-2 text-right font-semibold">Median time</th>
                </tr>
              </thead>
              <tbody>
                {humanSessionsByPage.map((page) => (
                  <tr key={page.page} className="border-t border-neutral-100">
                    <td className="px-3 py-2">
                      <div className="max-w-3xl truncate text-sm font-medium text-neutral-900">
                        {page.page || "unknown"}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-sm font-semibold text-neutral-900">
                      {page.distinct_sessions}
                      {page.sessions !== page.distinct_sessions ? (
                        <span className="ml-1 text-xs font-normal text-neutral-400">
                          ({page.sessions})
                        </span>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-sm text-neutral-600">
                      {formatMs(page.median_time_on_page_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-neutral-100 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-neutral-950">
              Rollup by {analytics.data?.group_label ?? "group"}
            </h2>
            <p className="mt-0.5 text-xs text-neutral-500">
              sorted by click volume, then most recent click
            </p>
          </div>
        </div>
        {analytics.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading click analytics...
          </div>
        ) : analytics.isError ? (
          <div className="px-4 py-8 text-sm text-red-600">
            Could not load click analytics.
          </div>
        ) : groups.length === 0 ? (
          <div className="px-4 py-8 text-sm text-neutral-500">
            No tracked clicks in this window.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">Group</th>
                  <th className="px-3 py-2 text-right font-semibold">Clicks</th>
                  <th className="px-3 py-2 text-right font-semibold">Contacts</th>
                  <th className="px-3 py-2 text-right font-semibold">Firms</th>
                  <th className="px-3 py-2 font-semibold">Last click</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <tr key={group.key} className="border-t border-neutral-100">
                    <td className="px-3 py-2">
                      <div className="max-w-xl truncate text-sm font-medium text-neutral-900">
                        {group.label}
                      </div>
                      <div className="mt-1 h-1.5 w-full max-w-sm rounded-full bg-neutral-100">
                        <div
                          className="h-1.5 rounded-full bg-neutral-900"
                          style={{ width: `${Math.max(8, (group.click_count / maxGroupClicks) * 100)}%` }}
                        />
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-sm font-semibold text-neutral-900">
                      {group.click_count}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-sm text-neutral-600">
                      {group.contact_count}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-sm text-neutral-600">
                      {group.firm_count}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-sm text-neutral-600">
                      {formatDateTime(group.last_clicked_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Recent clicks</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            latest individual click events with contact and batch-item context
          </p>
        </div>
        {recentClicks.length === 0 ? (
          <div className="px-4 py-8 text-sm text-neutral-500">
            No click events yet.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">Clicked</th>
                  <th className="px-3 py-2 font-semibold">Firm / contact</th>
                  <th className="px-3 py-2 font-semibold">App</th>
                  <th className="px-3 py-2 font-semibold">Source</th>
                  <th className="px-3 py-2 font-semibold">Persona</th>
                  <th className="px-3 py-2 font-semibold">User agent</th>
                  <th className="px-3 py-2 text-right font-semibold">Item</th>
                </tr>
              </thead>
              <tbody>
                {recentClicks.map((click) => (
                  <RecentClickRow key={click.id} click={click} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
