"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  listCadence,
  getCadenceStats,
  updateCadence,
  refreshCadence,
  cadenceCall,
  getCadenceCallHistory,
  type CadenceEntry,
  type CadenceCallRecord,
} from "@/lib/cadence";
import { OutcomePill } from "@/components/OutcomePill";
import { cn } from "@/lib/utils";
import {
  RefreshCw,
  Search,
  Building2,
  Clock,
  AlertTriangle,
  Trophy,
  XCircle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Phone,
  PhoneCall,
} from "lucide-react";

const STAGES = [
  "all",
  "signal_detected",
  "call_1",
  "call_1_alt",
  "callback_pending",
  "email_intro",
  "linkedin",
  "call_retry",
] as const;

const STAGE_LABELS: Record<string, string> = {
  signal_detected: "Signal",
  call_1: "Call 1",
  call_1_alt: "Call alt",
  callback_pending: "Callback",
  email_intro: "Email",
  linkedin: "LinkedIn",
  call_retry: "Retry",
  completed: "Done",
  exhausted: "Exhausted",
  dnc: "DNC",
};

const STAGE_COLORS: Record<string, string> = {
  signal_detected: "bg-blue-100 text-blue-800",
  call_1: "bg-emerald-100 text-emerald-800",
  call_1_alt: "bg-teal-100 text-teal-800",
  callback_pending: "bg-amber-100 text-amber-800",
  email_intro: "bg-violet-100 text-violet-800",
  linkedin: "bg-sky-100 text-sky-800",
  call_retry: "bg-orange-100 text-orange-800",
  completed: "bg-emerald-100 text-emerald-800",
  exhausted: "bg-neutral-100 text-neutral-600",
  dnc: "bg-rose-100 text-rose-800",
};

const PAGE_SIZE = 25;

export default function CadencePage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("all");
  const [owner, setOwner] = useState("all");
  const [dueToday, setDueToday] = useState(false);
  const [page, setPage] = useState(0);

  const stats = useQuery({
    queryKey: ["cadence-stats"],
    queryFn: getCadenceStats,
    refetchInterval: 30_000,
  });

  const entries = useQuery({
    queryKey: ["cadence", stage, owner, dueToday, search, page],
    queryFn: () =>
      listCadence({
        stage: stage !== "all" ? stage : undefined,
        owner: owner !== "all" ? owner : undefined,
        due_today: dueToday || undefined,
        search: search || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    refetchInterval: 30_000,
  });

  const refresh = useMutation({
    mutationFn: refreshCadence,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cadence"] });
      qc.invalidateQueries({ queryKey: ["cadence-stats"] });
    },
  });

  const update = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      updateCadence(id, action),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cadence"] });
      qc.invalidateQueries({ queryKey: ["cadence-stats"] });
    },
  });

  const placeCall = useMutation({
    mutationFn: ({ entryId, contact }: {
      entryId: string;
      contact: { name: string; phone: string; title?: string; email?: string | null };
    }) => cadenceCall(entryId, contact),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cadence"] });
    },
  });

  const items = entries.data?.items ?? [];
  const total = entries.data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);
  const s = stats.data;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Cadence</h1>
          <p className="text-sm text-neutral-500">
            Multi-day outreach tracking. Signal → Call → Email → LinkedIn → Retry.
          </p>
        </div>
        <button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="flex items-center gap-1.5 rounded-lg bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("h-3 w-3", refresh.isPending && "animate-spin")} />
          {refresh.isPending ? "Scanning..." : "Refresh"}
        </button>
      </div>

      {/* Stats bar */}
      {s && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCard
            label="Active"
            value={s.total_active}
            icon={<Building2 className="h-4 w-4" />}
          />
          <StatCard
            label="Due today"
            value={s.actions_due_today}
            icon={<Clock className="h-4 w-4" />}
            accent={s.actions_due_today > 0 ? "amber" : undefined}
          />
          <StatCard
            label="Overdue"
            value={s.overdue}
            icon={<AlertTriangle className="h-4 w-4" />}
            accent={s.overdue > 0 ? "rose" : undefined}
          />
          <StatCard
            label="Demos booked"
            value={s.by_outcome?.demo_booked ?? 0}
            icon={<Trophy className="h-4 w-4" />}
            accent="emerald"
          />
          <StatCard
            label="Exhausted"
            value={s.by_outcome?.exhausted ?? 0}
            icon={<XCircle className="h-4 w-4" />}
          />
        </div>
      )}

      {/* Filters */}
      <div className="space-y-2">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
          <input
            type="text"
            placeholder="Search firm name..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full rounded-xl border border-neutral-200 bg-white py-2 pl-10 pr-4 text-sm placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none focus:ring-1 focus:ring-neutral-400"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {STAGES.map((s) => (
            <button
              key={s}
              onClick={() => { setStage(s); setPage(0); }}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                stage === s
                  ? "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
              )}
            >
              {s === "all" ? "All stages" : STAGE_LABELS[s] || s}
            </button>
          ))}
          <span className="mx-1 text-neutral-300">|</span>
          {["all", "autocaller", "pranav"].map((o) => (
            <button
              key={o}
              onClick={() => { setOwner(o); setPage(0); }}
              className={cn(
                "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                owner === o
                  ? o === "pranav"
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : o === "autocaller"
                      ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                      : "border-neutral-900 bg-neutral-900 text-white"
                  : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
              )}
            >
              {o === "all" ? "All owners" : o}
            </button>
          ))}
          <button
            onClick={() => { setDueToday(!dueToday); setPage(0); }}
            className={cn(
              "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
              dueToday
                ? "border-amber-500 bg-amber-50 text-amber-700"
                : "border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300",
            )}
          >
            Due today
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-[11px] uppercase text-neutral-500">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Firm</th>
              <th className="px-4 py-2.5 text-left font-medium">Stage</th>
              <th className="px-4 py-2.5 text-left font-medium">Next Action</th>
              <th className="px-4 py-2.5 text-left font-medium">Due</th>
              <th className="px-4 py-2.5 text-left font-medium">Owner</th>
              <th className="px-4 py-2.5 text-center font-medium">Calls</th>
              <th className="px-4 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {entries.isLoading && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-xs text-neutral-400">
                  Loading...
                </td>
              </tr>
            )}
            {!entries.isLoading && items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-xs text-neutral-400">
                  No entries match the filters. Click Refresh to scan PIF Stats.
                </td>
              </tr>
            )}
            {items.map((e) => (
              <CadenceRow
                key={e.id}
                entry={e}
                onAction={(action) => update.mutate({ id: e.id, action })}
                onCall={(contact) => placeCall.mutate({ entryId: e.id, contact })}
                updating={update.isPending}
                calling={placeCall.isPending}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-neutral-500">
          <span>
            {total} entries · page {page + 1} of {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="flex items-center gap-1 rounded-lg border border-neutral-300 px-2.5 py-1 font-medium disabled:opacity-30"
            >
              <ChevronLeft className="h-3 w-3" /> Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="flex items-center gap-1 rounded-lg border border-neutral-300 px-2.5 py-1 font-medium disabled:opacity-30"
            >
              Next <ChevronRight className="h-3 w-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CadenceRow({
  entry,
  onAction,
  onCall,
  updating,
  calling,
}: {
  entry: CadenceEntry;
  onAction: (action: string) => void;
  onCall: (contact: { name: string; phone: string; title?: string; email?: string | null; persona?: string }) => void;
  updating: boolean;
  calling: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [callHistory, setCallHistory] = useState<CadenceCallRecord[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const now = new Date();
  const due = entry.next_action_due ? new Date(entry.next_action_due) : null;
  const overdue = due && due < now;
  const contacts = entry.available_contacts || [];
  const triedPhones = new Set((entry.contacts_tried || []).map((c) => c.phone));

  const loadHistory = async () => {
    if (historyLoaded) return;
    try {
      const data = await getCadenceCallHistory(entry.id);
      setCallHistory(data.calls);
    } catch { /* ignore */ }
    setHistoryLoaded(true);
  };

  return (
    <>
      <tr className="border-t border-neutral-100 hover:bg-neutral-50">
        <td className="px-4 py-2.5">
          <div className="flex items-center gap-1.5">
            {contacts.length > 0 && (
              <button
                onClick={() => {
                  setExpanded(!expanded);
                  if (!expanded) loadHistory();
                }}
                className="text-neutral-400 hover:text-neutral-600"
              >
                <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} />
              </button>
            )}
            <div>
              <Link
                href={`/firms/${entry.pif_id}`}
                className="text-sm font-medium text-neutral-900 hover:underline"
              >
                {entry.firm_name}
              </Link>
              {entry.icp_tier && (
                <span className={cn(
                  "ml-1.5 rounded-full px-1.5 py-0.5 text-[9px] font-bold",
                  entry.icp_tier === "A" ? "bg-emerald-100 text-emerald-800" :
                  entry.icp_tier === "B" ? "bg-sky-100 text-sky-800" :
                  "bg-neutral-100 text-neutral-600",
                )}>
                  {entry.icp_tier}
                </span>
              )}
              <div className="text-[10px] text-neutral-400">
                {contacts.length} contacts
                {entry.contacts_tried?.length > 0 &&
                  ` · ${entry.contacts_tried.length} tried`}
              </div>
            </div>
          </div>
        </td>
        <td className="px-4 py-2.5">
          <span className={cn(
            "rounded-full px-2 py-0.5 text-[10px] font-semibold",
            STAGE_COLORS[entry.cadence_stage] || "bg-neutral-100 text-neutral-600",
          )}>
            {STAGE_LABELS[entry.cadence_stage] || entry.cadence_stage}
          </span>
        </td>
        <td className="px-4 py-2.5 text-xs text-neutral-600 max-w-[200px] truncate">
          {entry.next_action || "—"}
        </td>
        <td className="px-4 py-2.5">
          {due ? (
            <span className={cn("text-xs", overdue ? "font-semibold text-rose-600" : "text-neutral-500")}>
              {overdue ? "overdue · " : ""}
              {formatDistanceToNow(due, { addSuffix: true })}
            </span>
          ) : (
            <span className="text-xs text-neutral-300">—</span>
          )}
        </td>
        <td className="px-4 py-2.5">
          {entry.owner ? (
            <span className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold",
              entry.owner === "pranav" ? "bg-blue-50 text-blue-700" :
              entry.owner === "autocaller" ? "bg-emerald-50 text-emerald-700" :
              "bg-neutral-100 text-neutral-600",
            )}>
              {entry.owner}
            </span>
          ) : (
            <span className="text-xs text-neutral-300">—</span>
          )}
        </td>
        <td className="px-4 py-2.5 text-center">
          {entry.call_ids.length > 0 ? (
            <Link
              href={`/calls/${entry.call_ids[entry.call_ids.length - 1]}`}
              className="text-xs text-blue-600 hover:underline"
            >
              {entry.call_ids.length}
            </Link>
          ) : (
            <span className="text-xs text-neutral-300">0</span>
          )}
        </td>
        <td className="px-4 py-2.5 text-right">
          <div className="flex items-center justify-end gap-1">
            {entry.cadence_stage === "email_intro" && (
              <ActionBtn label="Email sent" onClick={() => onAction("mark_email_sent")} disabled={updating} />
            )}
            {entry.cadence_stage === "linkedin" && (
              <ActionBtn label="LI sent" onClick={() => onAction("mark_linkedin_sent")} disabled={updating} />
            )}
            {entry.cadence_stage === "callback_pending" && (
              <ActionBtn label="Demo booked" onClick={() => onAction("mark_demo_booked")} disabled={updating} color="emerald" />
            )}
            <ActionBtn label="Skip" onClick={() => onAction("skip")} disabled={updating} />
            <ActionBtn label="DNC" onClick={() => onAction("mark_dnc")} disabled={updating} color="rose" />
          </div>
        </td>
      </tr>
      {/* Expanded contacts */}
      {expanded && contacts.length > 0 && (
        <tr className="bg-neutral-50/50">
          <td colSpan={7} className="px-4 py-2">
            <div className="ml-6 space-y-1">
              {contacts.map((c, i) => {
                const tried = triedPhones.has(c.phone);
                const cDigits = c.phone.replace(/\D/g, "").slice(-10);
                const contactCalls = callHistory.filter(
                  (call) => call.phone.replace(/\D/g, "").slice(-10) === cDigits
                );
                return (
                  <div key={i} className="space-y-1">
                  <div
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-1.5 text-xs",
                      tried ? "bg-neutral-100" : "bg-white border border-neutral-100",
                    )}
                  >
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-neutral-200 text-[9px] font-bold text-neutral-600">
                      {c.name.charAt(0)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <span className="font-medium text-neutral-800">{c.name}</span>
                      {c.title && (
                        <span className="ml-1.5 text-neutral-500">{c.title}</span>
                      )}
                      {tried && (
                        <span className="ml-1.5 rounded bg-neutral-200 px-1 py-0.5 text-[9px] text-neutral-500">
                          called
                        </span>
                      )}
                    </div>
                    <span className="font-mono text-[11px] text-neutral-500">{c.phone}</span>
                    {c.email && (
                      <span className="text-[11px] text-neutral-400 truncate max-w-[140px]">{c.email}</span>
                    )}
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => onCall({
                          name: c.name,
                          phone: c.phone,
                          title: c.title,
                          email: c.email,
                          persona: "alex",
                        })}
                        disabled={calling}
                        className={cn(
                          "flex items-center gap-1 rounded-l-lg px-2 py-1 text-[10px] font-semibold transition-colors",
                          tried
                            ? "bg-neutral-200 text-neutral-500 hover:bg-neutral-300"
                            : "bg-emerald-600 text-white hover:bg-emerald-700",
                        )}
                        title="Call as Alex (male)"
                      >
                        <PhoneCall className="h-3 w-3" />
                        Alex
                      </button>
                      <button
                        onClick={() => onCall({
                          name: c.name,
                          phone: c.phone,
                          title: c.title,
                          email: c.email,
                          persona: "natalia",
                        })}
                        disabled={calling}
                        className={cn(
                          "flex items-center gap-1 rounded-r-lg px-2 py-1 text-[10px] font-semibold transition-colors",
                          tried
                            ? "bg-neutral-200 text-neutral-500 hover:bg-neutral-300"
                            : "bg-violet-600 text-white hover:bg-violet-700",
                        )}
                        title="Call as Natalia (female)"
                      >
                        Natalia
                      </button>
                    </div>
                  </div>
                  {/* Call history for this contact */}
                  {contactCalls.length > 0 && (
                    <div className="ml-9 space-y-0.5">
                      {contactCalls.map((call) => (
                        <Link
                          key={call.call_id}
                          href={`/calls/${call.call_id}`}
                          className="flex items-center gap-2 rounded-md px-2 py-1 text-[10px] text-neutral-500 hover:bg-neutral-100"
                        >
                          <span className="text-neutral-400">
                            {call.started_at
                              ? formatDistanceToNow(new Date(call.started_at), { addSuffix: true })
                              : "—"}
                          </span>
                          <span className="text-neutral-600">{call.duration_seconds}s</span>
                          <OutcomePill outcome={call.outcome as any} />
                          {call.prompt_version && (
                            <span className="text-neutral-400">{call.prompt_version}</span>
                          )}
                          {call.mock_mode && (
                            <span className="rounded bg-amber-100 px-1 py-0.5 text-[9px] text-amber-700">mock</span>
                          )}
                        </Link>
                      ))}
                    </div>
                  )}
                  </div>
                );
              })}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function ActionBtn({
  label,
  onClick,
  disabled,
  color,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  color?: "emerald" | "rose";
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md border px-2 py-0.5 text-[10px] font-medium transition-colors disabled:opacity-40",
        color === "emerald"
          ? "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
          : color === "rose"
            ? "border-rose-300 text-rose-700 hover:bg-rose-50"
            : "border-neutral-200 text-neutral-600 hover:bg-neutral-50",
      )}
    >
      {label}
    </button>
  );
}

function StatCard({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  accent?: "amber" | "rose" | "emerald";
}) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2 text-neutral-400">
        {icon}
        <span className="text-[10px] font-medium uppercase tracking-wider">{label}</span>
      </div>
      <div
        className={cn(
          "mt-1 text-2xl font-bold",
          accent === "amber" ? "text-amber-700" :
          accent === "rose" ? "text-rose-700" :
          accent === "emerald" ? "text-emerald-700" :
          "text-neutral-900",
        )}
      >
        {value}
      </div>
    </div>
  );
}
