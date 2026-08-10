"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  Clock3,
  Eye,
  Loader2,
  MailOpen,
  MousePointerClick,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  UserRound,
  Users,
} from "lucide-react";
import {
  getClickAnalytics,
  getWorkshopClickAnalytics,
  type ClickAnalyticsRow,
  type WorkshopTrackingActivity,
  type WorkshopTrackingContact,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const WINDOWS = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "All", days: 0 },
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

function formatDuration(value: number | null | undefined) {
  if (!value) return "-";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

const SCANNER_MARKERS = [
  "proofpoint",
  "mimecast",
  "barracuda",
  "safelinks",
  "urlprotect",
  "defender",
  "microsoft office",
  "microsoft preview",
  "googleimageproxy",
  "google web preview",
  "headlesschrome",
  "curl/",
  "python-requests",
];

function isKnownScanner(userAgent: string | null) {
  const value = (userAgent ?? "").toLowerCase();
  return SCANNER_MARKERS.some((marker) => value.includes(marker));
}

function clientLabel(userAgent: string | null) {
  const value = userAgent ?? "";
  if (!value) return "Unknown client";
  if (isKnownScanner(value)) return "Known scanner";
  if (/edg\//i.test(value)) return "Edge";
  if (/chrome\//i.test(value)) return "Chrome";
  if (/safari\//i.test(value) && !/chrome\//i.test(value)) return "Safari";
  if (/firefox\//i.test(value)) return "Firefox";
  if (/outlook|microsoft office/i.test(value)) return "Outlook";
  return "Other client";
}

function Metric({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string | number;
  icon: typeof Users;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-3">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold text-neutral-950">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: WorkshopTrackingContact["status"] }) {
  return (
    <span
      className={cn(
        "inline-flex whitespace-nowrap rounded-full px-2 py-1 text-[11px] font-semibold",
        status === "Prompt revealed" && "bg-emerald-100 text-emerald-800",
        status === "Engaged" && "bg-blue-100 text-blue-800",
        status === "Visited" && "bg-violet-100 text-violet-800",
        status === "Scanner / suspect only" && "bg-amber-100 text-amber-800",
        status === "No activity" && "bg-neutral-100 text-neutral-500",
      )}
    >
      {status}
    </span>
  );
}

function QualityBadge({ quality }: { quality: WorkshopTrackingActivity["quality"] }) {
  const label = quality === "human" ? "Human" : quality === "scanner" ? "Scanner" : "Unconfirmed";
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        quality === "human" && "bg-emerald-100 text-emerald-800",
        quality === "scanner" && "bg-amber-100 text-amber-800",
        quality === "suspect" && "bg-neutral-100 text-neutral-600",
      )}
    >
      {label}
    </span>
  );
}

function ContactRow({ contact }: { contact: WorkshopTrackingContact }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="px-3 py-3">
        <div className="text-sm font-semibold text-neutral-950">{contact.contact_name}</div>
        <div className="mt-0.5 text-xs text-neutral-500">{contact.title || contact.firm_name}</div>
        {contact.title ? <div className="mt-0.5 text-xs text-neutral-400">{contact.firm_name}</div> : null}
      </td>
      <td className="px-3 py-3"><StatusBadge status={contact.status} /></td>
      <td className="px-3 py-3 text-right text-sm font-semibold text-neutral-900">
        {contact.raw_link_clicks}
        {contact.scanner_link_clicks ? (
          <div className="mt-0.5 text-[10px] font-normal text-amber-700">
            {contact.scanner_link_clicks} known scanner
          </div>
        ) : null}
      </td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">
        {contact.confirmed_sessions}
        {contact.scanner_or_suspect_sessions ? (
          <div className="mt-0.5 text-[10px] text-neutral-400">
            {contact.scanner_or_suspect_sessions} unconfirmed
          </div>
        ) : null}
      </td>
      <td className="px-3 py-3 text-right text-sm font-semibold text-emerald-700">
        {contact.prompt_reveals}
      </td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{contact.on_page_clicks}</td>
      <td className="px-3 py-3 text-right text-sm text-neutral-700">{contact.scroll_50}</td>
      <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-500">
        {formatDateTime(contact.last_activity_at)}
        {contact.max_time_on_page_ms ? (
          <div className="mt-0.5 text-[10px] text-neutral-400">
            max {formatDuration(contact.max_time_on_page_ms)}
          </div>
        ) : null}
      </td>
    </tr>
  );
}

function ActivityRow({ activity }: { activity: WorkshopTrackingActivity }) {
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-500">
        {formatDateTime(activity.occurred_at)}
      </td>
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-950">{activity.contact_name}</div>
        <div className="mt-0.5 text-xs text-neutral-400">{activity.firm_name}</div>
      </td>
      <td className="px-3 py-3">
        <div className="text-sm font-medium text-neutral-900">{activity.label}</div>
        <div className="mt-0.5 max-w-2xl break-words text-xs text-neutral-500">{activity.detail}</div>
      </td>
      <td className="px-3 py-3"><QualityBadge quality={activity.quality} /></td>
      <td className="px-3 py-3 text-xs text-neutral-500">
        <div>{activity.page}</div>
        {activity.time_on_page_ms ? (
          <div className="mt-0.5 text-neutral-400">{formatDuration(activity.time_on_page_ms)}</div>
        ) : null}
      </td>
    </tr>
  );
}

function EmailClickRow({ click }: { click: ClickAnalyticsRow }) {
  const scanner = isKnownScanner(click.user_agent);
  return (
    <tr className="border-t border-neutral-100 align-top">
      <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-500">
        {formatDateTime(click.clicked_at)}
      </td>
      <td className="px-3 py-3">
        <div className="text-sm font-semibold text-neutral-950">
          {click.contact_name || "Unknown contact"}
        </div>
        <div className="mt-0.5 text-xs text-neutral-500">{click.contact_email || "-"}</div>
      </td>
      <td className="px-3 py-3">
        <div className="text-sm text-neutral-900">{click.firm_name}</div>
        {click.persona ? <div className="mt-0.5 text-xs text-neutral-400">{click.persona}</div> : null}
      </td>
      <td className="px-3 py-3">
        <span
          className={cn(
            "inline-flex whitespace-nowrap rounded-full px-2 py-1 text-[11px] font-semibold",
            scanner ? "bg-amber-100 text-amber-800" : "bg-blue-100 text-blue-800",
          )}
        >
          {scanner ? "Known scanner" : "Unconfirmed click"}
        </span>
      </td>
      <td className="px-3 py-3 text-xs text-neutral-500">
        <div>{clientLabel(click.user_agent)}</div>
        <div className="mt-0.5 font-mono text-[10px] text-neutral-400">{click.ip || "No IP"}</div>
      </td>
    </tr>
  );
}

export default function ClickAnalyticsPage() {
  const [sinceDays, setSinceDays] = useState(1);
  const workshopAnalytics = useQuery({
    queryKey: ["workshop-click-analytics", sinceDays],
    queryFn: () => getWorkshopClickAnalytics({ sinceDays, limit: 250 }),
    refetchInterval: 30_000,
  });
  const emailAnalytics = useQuery({
    queryKey: ["email-automation-click-analytics", sinceDays],
    queryFn: () => getClickAnalytics({
      sinceDays,
      groupBy: "firm_name",
      limit: 250,
      source: "solution_email_automation",
    }),
    refetchInterval: 30_000,
  });
  const summary = workshopAnalytics.data?.summary;
  const contacts = workshopAnalytics.data?.contacts ?? [];
  const activities = workshopAnalytics.data?.activities ?? [];
  const emailSummary = emailAnalytics.data?.summary;
  const emailClicks = emailAnalytics.data?.recent_clicks ?? [];
  const refreshing = workshopAnalytics.isFetching || emailAnalytics.isFetching;

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="rounded-lg bg-neutral-900 p-2 text-white">
          <MousePointerClick className="h-4 w-4" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Workflow Clicks</h1>
          <p className="mt-0.5 text-sm text-neutral-500">
            recipient-level email and workshop engagement
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            workshopAnalytics.refetch();
            emailAnalytics.refetch();
          }}
          disabled={refreshing}
          className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-1">
        {WINDOWS.map((window) => (
          <button
            key={window.label}
            type="button"
            onClick={() => setSinceDays(window.days)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              sinceDays === window.days
                ? "bg-neutral-900 text-white"
                : "border border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-100",
            )}
          >
            {window.label}
          </button>
        ))}
      </div>

      <div className="pt-2">
        <h2 className="text-sm font-semibold text-neutral-950">Workshop clicks</h2>
        <p className="mt-0.5 text-xs text-neutral-500">
          page visits, prompt reveals, and workshop actions
        </p>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Metric label="People with activity" value={summary?.tracked_contacts ?? 0} icon={Users} />
          <Metric label="Raw link opens" value={summary?.raw_link_clicks ?? 0} icon={MousePointerClick} />
          <Metric label="Known scanners" value={summary?.scanner_link_clicks ?? 0} icon={ShieldAlert} />
          <Metric label="Confirmed visits" value={summary?.confirmed_visitors ?? 0} icon={Eye} />
          <Metric label="Prompt reveals" value={summary?.prompt_reveals ?? 0} icon={Sparkles} />
          <Metric label="Page clicks" value={summary?.on_page_clicks ?? 0} icon={MousePointerClick} />
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">People</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            recipients with workshop activity in the selected window
          </p>
        </div>
        {workshopAnalytics.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading workshop tracking...
          </div>
        ) : workshopAnalytics.isError ? (
          <div className="px-4 py-8 text-sm text-red-600">Could not load workshop tracking.</div>
        ) : contacts.length === 0 ? (
          <div className="px-4 py-8 text-sm text-neutral-500">No workshop recipient activity in this window.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">Contact</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 text-right font-semibold">Raw opens</th>
                  <th className="px-3 py-2 text-right font-semibold">Confirmed visits</th>
                  <th className="px-3 py-2 text-right font-semibold">Prompts revealed</th>
                  <th className="px-3 py-2 text-right font-semibold">Page clicks</th>
                  <th className="px-3 py-2 text-right font-semibold">50% scroll</th>
                  <th className="px-3 py-2 font-semibold">Last activity</th>
                </tr>
              </thead>
              <tbody>{contacts.map((contact) => <ContactRow key={contact.contact_id} contact={contact} />)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Workshop activity</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            individual tracked actions, including the exact prompt-reveal and button-click events
          </p>
        </div>
        {activities.length === 0 ? (
          <div className="px-4 py-8 text-sm text-neutral-500">No workshop activity in this window.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">When</th>
                  <th className="px-3 py-2 font-semibold">Contact</th>
                  <th className="px-3 py-2 font-semibold">Action</th>
                  <th className="px-3 py-2 font-semibold">Signal</th>
                  <th className="px-3 py-2 font-semibold">Workshop</th>
                </tr>
              </thead>
              <tbody>{activities.map((activity) => <ActivityRow key={activity.id} activity={activity} />)}</tbody>
            </table>
          </div>
        )}
      </section>

      <div className="pt-4">
        <h2 className="text-sm font-semibold text-neutral-950">Email automation clicks</h2>
        <p className="mt-0.5 text-xs text-neutral-500">
          attributed opens of the tracked email-automation links
        </p>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Total clicks" value={emailSummary?.click_count ?? 0} icon={MailOpen} />
          <Metric label="Unique recipients" value={emailSummary?.contact_count ?? 0} icon={UserRound} />
          <Metric label="Firms clicked" value={emailSummary?.firm_count ?? 0} icon={Building2} />
          <Metric
            label="Last click"
            value={emailSummary?.last_clicked_at ? formatDateTime(emailSummary.last_clicked_at) : "-"}
            icon={Clock3}
          />
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Email click activity</h2>
          <p className="mt-0.5 text-xs text-neutral-500">
            automatic security previews are labeled separately from browser-like clicks
          </p>
        </div>
        {emailAnalytics.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-8 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading email clicks...
          </div>
        ) : emailAnalytics.isError ? (
          <div className="px-4 py-8 text-sm text-red-600">Could not load email click analytics.</div>
        ) : emailClicks.length === 0 ? (
          <div className="px-4 py-8 text-sm text-neutral-500">
            No email-automation link clicks in this window.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <thead className="bg-neutral-50 text-[11px] uppercase tracking-wider text-neutral-400">
                <tr>
                  <th className="px-3 py-2 font-semibold">When</th>
                  <th className="px-3 py-2 font-semibold">Recipient</th>
                  <th className="px-3 py-2 font-semibold">Firm</th>
                  <th className="px-3 py-2 font-semibold">Signal</th>
                  <th className="px-3 py-2 font-semibold">Client</th>
                </tr>
              </thead>
              <tbody>{emailClicks.map((click) => <EmailClickRow key={click.id} click={click} />)}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
