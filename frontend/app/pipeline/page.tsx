"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Play, RefreshCw, Phone } from "lucide-react";
import { listLeads, startCall } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { Lead } from "@/types";

type Column = "up_next" | "cooling" | "exhausted";

const MAX_ATTEMPTS = 3;
const MIN_HOURS_BETWEEN = 6;

function classify(lead: Lead): Column {
  if (lead.attempt_count >= MAX_ATTEMPTS) return "exhausted";
  if (!lead.last_attempt_at) return "up_next";
  const hoursAgo =
    (Date.now() - new Date(lead.last_attempt_at).getTime()) / 3_600_000;
  return hoursAgo >= MIN_HOURS_BETWEEN ? "up_next" : "cooling";
}

function nextEligible(lead: Lead): string | null {
  if (!lead.last_attempt_at) return null;
  const next = new Date(lead.last_attempt_at);
  next.setHours(next.getHours() + MIN_HOURS_BETWEEN);
  if (next.getTime() <= Date.now()) return null;
  return formatDistanceToNow(next, { addSuffix: true });
}

export default function PipelinePage() {
  const qc = useQueryClient();
  const [filterState, setFilterState] = useState<string>("");
  const [dmOnly, setDmOnly] = useState(false);
  const [search, setSearch] = useState<string>("");

  const { data, isLoading } = useQuery({
    queryKey: ["leads"],
    queryFn: listLeads,
    refetchInterval: 20_000,
  });

  const call = useMutation({
    mutationFn: (id: string) => startCall(id, "twilio"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });

  const { columns, states } = useMemo(() => {
    const leads = data?.patients ?? [];
    const states = Array.from(
      new Set(leads.map((l) => l.state).filter((s): s is string => Boolean(s))),
    ).sort();
    const needle = search.trim().toLowerCase();
    const filtered = leads.filter((l) => {
      if (filterState && l.state !== filterState) return false;
      if (dmOnly && !l.tags?.includes("decision-maker")) return false;
      if (needle) {
        const hay = [
          l.name,
          l.firm_name,
          l.phone,
          l.email,
          l.title,
          l.state,
          l.patient_id,
        ]
          .filter(Boolean)
          .map((x) => String(x).toLowerCase())
          .join(" ");
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
    const columns: Record<Column, Lead[]> = {
      up_next: [],
      cooling: [],
      exhausted: [],
    };
    for (const l of filtered) columns[classify(l)].push(l);
    // Sort up_next by priority_bucket (lower = higher priority)
    columns.up_next.sort(
      (a, b) => a.priority_bucket - b.priority_bucket || a.name.localeCompare(b.name),
    );
    return { columns, states };
  }, [data, filterState, dmOnly, search]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Pipeline</h1>
          <p className="text-sm text-neutral-500">
            {data?.patients?.length ?? 0} leads total. Sorted by priority bucket.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, firm, phone, email…"
            className="w-56 rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm placeholder:text-neutral-400"
          />
          <select
            value={filterState}
            onChange={(e) => setFilterState(e.target.value)}
            className="rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm"
          >
            <option value="">All states</option>
            {states.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5 text-xs text-neutral-600">
            <input
              type="checkbox"
              checked={dmOnly}
              onChange={(e) => setDmOnly(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            DM only
          </label>
          <Button
            size="sm"
            variant="outline"
            onClick={() => qc.invalidateQueries({ queryKey: ["leads"] })}
            className="gap-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <KanbanColumn
          title="Up next"
          count={columns.up_next.length}
          accent="emerald"
          isLoading={isLoading}
        >
          {columns.up_next.slice(0, 50).map((l) => (
            <LeadCard
              key={l.patient_id}
              lead={l}
              showCall
              onCall={() => call.mutate(l.patient_id)}
              calling={call.isPending && call.variables === l.patient_id}
            />
          ))}
          {columns.up_next.length > 50 && (
            <p className="text-xs text-neutral-400">
              … and {columns.up_next.length - 50} more
            </p>
          )}
        </KanbanColumn>

        <KanbanColumn
          title="Cooling down"
          count={columns.cooling.length}
          accent="amber"
          isLoading={isLoading}
        >
          {columns.cooling.slice(0, 25).map((l) => (
            <LeadCard key={l.patient_id} lead={l} />
          ))}
        </KanbanColumn>

        <KanbanColumn
          title="Exhausted"
          count={columns.exhausted.length}
          accent="neutral"
          isLoading={isLoading}
        >
          {columns.exhausted.slice(0, 25).map((l) => (
            <LeadCard key={l.patient_id} lead={l} />
          ))}
        </KanbanColumn>
      </div>
    </div>
  );
}

function KanbanColumn({
  title,
  count,
  accent,
  isLoading,
  children,
}: {
  title: string;
  count: number;
  accent: "emerald" | "amber" | "neutral";
  isLoading: boolean;
  children: React.ReactNode;
}) {
  const dot = {
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    neutral: "bg-neutral-400",
  }[accent];
  return (
    <section className="rounded-lg border border-neutral-200 bg-white">
      <header className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", dot)} />
          <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>
        </div>
        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-600">
          {count}
        </span>
      </header>
      <div className="max-h-[70vh] space-y-2 overflow-y-auto p-3">
        {isLoading && <p className="text-xs text-neutral-400">loading…</p>}
        {!isLoading && count === 0 && (
          <p className="py-8 text-center text-xs text-neutral-400">empty</p>
        )}
        {children}
      </div>
    </section>
  );
}

function LeadCard({
  lead,
  showCall,
  onCall,
  calling,
}: {
  lead: Lead;
  showCall?: boolean;
  onCall?: () => void;
  calling?: boolean;
}) {
  const isDM = lead.tags?.includes("decision-maker");
  const eligible = nextEligible(lead);
  return (
    <div className="rounded-md border border-neutral-100 bg-white p-3 transition-shadow hover:shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-neutral-900">
              {lead.name}
            </span>
            {isDM && (
              <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">
                DM
              </span>
            )}
          </div>
          <div className="truncate text-[11px] text-neutral-500">
            {lead.firm_name || "—"}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-neutral-500">
            {lead.title && <span>{lead.title}</span>}
            {lead.state && <span>· {lead.state}</span>}
            <span className="font-mono">· {lead.phone}</span>
          </div>
          {(lead.attempt_count > 0 || lead.last_outcome) && (
            <div className="mt-1 text-[10px] text-neutral-400">
              attempts: {lead.attempt_count}
              {lead.last_outcome && ` · last: ${lead.last_outcome}`}
              {eligible && ` · next ${eligible}`}
            </div>
          )}
        </div>
        {showCall && (
          <Button
            size="sm"
            variant="outline"
            onClick={onCall}
            disabled={calling}
            className="h-7 shrink-0 gap-1 px-2 text-[11px]"
          >
            {calling ? (
              <>
                <Phone className="h-3 w-3 animate-pulse" />
                dialing…
              </>
            ) : (
              <>
                <Play className="h-3 w-3" />
                call
              </>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
