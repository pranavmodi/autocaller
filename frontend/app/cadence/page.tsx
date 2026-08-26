"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Building2,
  Check,
  ExternalLink,
  Loader2,
  Mail,
  Phone,
  PhoneCall,
  Search,
  Users,
} from "lucide-react";

import { getActiveCall } from "@/lib/api";
import {
  getCallLabFirms,
  startCallLabCall,
  type CallLabFirm,
  type CallLabLeader,
} from "@/lib/callLab";
import { cn } from "@/lib/utils";

export default function CallLabPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedFirmId, setSelectedFirmId] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const firms = useQuery({
    queryKey: ["call-lab-firms", debouncedSearch],
    queryFn: () => getCallLabFirms({ query: debouncedSearch, limit: 50 }),
    staleTime: 60_000,
  });
  const activeCall = useQuery({
    queryKey: ["active-call"],
    queryFn: getActiveCall,
    refetchInterval: 5_000,
  });
  const items = firms.data?.items ?? [];
  const selected = useMemo(
    () => items.find((firm) => firm.pif_id === selectedFirmId) ?? null,
    [items, selectedFirmId],
  );

  useEffect(() => {
    if (selectedFirmId && !items.some((firm) => firm.pif_id === selectedFirmId)) {
      setSelectedFirmId(null);
    }
  }, [items, selectedFirmId]);

  const startCall = useMutation({
    mutationFn: startCallLabCall,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-call"] });
      queryClient.invalidateQueries({ queryKey: ["calls"] });
    },
  });
  const currentCall = activeCall.data?.call ?? null;
  const callInProgress = Boolean(activeCall.data?.active || currentCall);

  return (
    <div className="mx-auto min-w-0 max-w-[1500px] space-y-4">
      <header className="flex flex-col gap-3 border-b border-neutral-200 pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-neutral-950">Call Lab</h1>
            <span className="rounded bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800">Filevine</span>
          </div>
          <p className="mt-1 text-sm text-neutral-600">50 PI firms · 15–50 people · manual operator calls</p>
        </div>
        {currentCall && (
          <Link href={`/calls/${currentCall.call_id}`} className="inline-flex items-center gap-2 text-sm font-medium text-emerald-700 hover:underline">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
            {currentCall.patient_name || currentCall.phone}
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        )}
      </header>

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_390px]">
        <section className="min-w-0">
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search this list by firm, leader, title, phone, or technology"
              className="h-10 w-full rounded-md border border-neutral-300 bg-white pl-9 pr-3 text-sm outline-none focus:border-neutral-500 focus:ring-2 focus:ring-neutral-200"
            />
          </label>

          <div className="mt-3 flex h-6 items-center justify-between text-xs text-neutral-500">
            <span>{firms.data ? `${firms.data.total} of ${firms.data.curated_total} firms` : "Loading firms"}</span>
            {firms.isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          </div>

          <div className="mt-1 overflow-hidden border border-neutral-200 bg-white">
            <div className="hidden grid-cols-[minmax(180px,1.2fr)_minmax(170px,1fr)_70px_110px_120px_30px] gap-3 border-b border-neutral-200 bg-neutral-50 px-3 py-2 text-xs font-medium text-neutral-500 lg:grid">
              <span>Firm</span><span>Call target</span><span>Size</span><span>Relationship</span><span>Phone</span><span />
            </div>
            <div className="divide-y divide-neutral-100">
              {firms.isLoading && <LoadingRows />}
              {firms.isError && (
                <div className="px-4 py-10 text-center text-sm text-rose-700">
                  {firms.error instanceof Error ? firms.error.message : "Could not load call list"}
                </div>
              )}
              {!firms.isLoading && !firms.isError && items.length === 0 && (
                <div className="px-4 py-12 text-center text-sm text-neutral-500">No firms in this list match the search.</div>
              )}
              {items.map((firm) => (
                <FirmRow
                  key={firm.pif_id}
                  firm={firm}
                  selected={firm.pif_id === selectedFirmId}
                  onSelect={() => setSelectedFirmId(firm.pif_id)}
                />
              ))}
            </div>
          </div>
        </section>

        <aside className="min-w-0 border-t border-neutral-200 pt-5 xl:border-l xl:border-t-0 xl:pl-5 xl:pt-0">
          {selected ? (
            <FirmBrief
              firm={selected}
              disabled={callInProgress || startCall.isPending}
              pending={startCall.isPending}
              onCall={() => startCall.mutate(selected.target_contact)}
              error={startCall.error instanceof Error ? startCall.error.message : null}
            />
          ) : (
            <div className="flex min-h-64 flex-col items-center justify-center text-center text-neutral-500">
              <Building2 className="h-7 w-7 text-neutral-300" />
              <p className="mt-3 text-sm">Select a firm to see the call brief</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function FirmRow({ firm, selected, onSelect }: { firm: CallLabFirm; selected: boolean; onSelect: () => void }) {
  const target = firm.target_contact;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "grid w-full min-w-0 gap-2 px-3 py-3 text-left transition-colors lg:grid-cols-[minmax(180px,1.2fr)_minmax(170px,1fr)_70px_110px_120px_30px] lg:items-center lg:gap-3",
        selected ? "bg-neutral-100" : "hover:bg-neutral-50",
      )}
    >
      <span className="min-w-0">
        <span className="block truncate text-sm font-semibold text-neutral-950">{firm.firm_name}</span>
        <span className="block truncate text-xs text-neutral-500">{firm.metro || firm.website || "PI law firm"}</span>
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm text-neutral-800">{target.name}</span>
        <span className="block truncate text-xs text-neutral-500">{target.title || target.role_category || "Leader"}</span>
      </span>
      <span className="flex items-center gap-1 text-xs text-neutral-700"><Users className="h-3.5 w-3.5 text-neutral-400" />{firm.team_size}</span>
      <span className="text-xs text-neutral-600">{firm.conversation_count.toLocaleString()} conversations</span>
      <span className="font-mono text-xs text-neutral-700">{target.phone}</span>
      <span className="hidden h-7 w-7 items-center justify-center lg:flex">
        {selected ? <Check className="h-4 w-4" /> : <ArrowUpRight className="h-4 w-4 text-neutral-300" />}
      </span>
    </button>
  );
}

function FirmBrief({ firm, disabled, pending, onCall, error }: {
  firm: CallLabFirm; disabled: boolean; pending: boolean; onCall: () => void; error: string | null;
}) {
  const target = firm.target_contact;
  return (
    <div className="space-y-4 xl:sticky xl:top-4">
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-neutral-950">{firm.firm_name}</h2>
            <p className="mt-0.5 text-xs text-neutral-500">{firm.metro || "Location unavailable"}</p>
          </div>
          {firm.icp_tier && <span className="rounded bg-neutral-100 px-2 py-1 text-xs font-medium">Tier {firm.icp_tier}</span>}
        </div>
        <div className="mt-3 grid grid-cols-3 divide-x divide-neutral-200 border-y border-neutral-200 py-3 text-center">
          <Metric label="People" value={String(firm.team_size)} />
          <Metric label="Conversations" value={firm.conversation_count.toLocaleString()} />
          <Metric label="ICP" value={firm.icp_score === null ? "—" : String(firm.icp_score)} />
        </div>
        <p className="mt-2 text-[11px] text-neutral-400" title={firm.team_size_basis}>Size source: {firm.team_size_label}</p>
      </div>

      <section>
        <h3 className="text-xs font-semibold uppercase text-neutral-500">Call target</h3>
        <div className="mt-2 flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-neutral-950">{target.name}</p>
            <p className="text-xs text-neutral-600">{target.title || target.role_category || "Firm leader"}</p>
            <p className="mt-1 font-mono text-sm text-neutral-900">{target.phone}</p>
          </div>
          <ContactLinks person={target} website={firm.website} />
        </div>
        <button
          type="button"
          onClick={onCall}
          disabled={disabled}
          className="mt-3 inline-flex h-11 w-full items-center justify-center gap-2 rounded-md bg-neutral-950 px-4 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300"
        >
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <PhoneCall className="h-4 w-4" />}
          {pending ? "Connecting" : `Call ${target.name.split(" ")[0]}`}
        </button>
        {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
        {disabled && !pending && !error && <p className="mt-2 text-center text-xs text-neutral-500">Another call is active.</p>}
      </section>

      <section className="border-t border-neutral-200 pt-4">
        <h3 className="text-xs font-semibold uppercase text-neutral-500">Technology</h3>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {firm.technology.map((vendor) => (
            <span key={vendor.key} className={cn("rounded px-2 py-1 text-xs", vendor.key === "filevine" ? "bg-emerald-50 font-medium text-emerald-800" : "bg-neutral-100 text-neutral-700")}>{vendor.label}</span>
          ))}
        </div>
      </section>

      {(firm.primary_pain_point || firm.monthly_email_volume || firm.summary) && (
        <section className="border-t border-neutral-200 pt-4">
          <h3 className="text-xs font-semibold uppercase text-neutral-500">Call context</h3>
          {firm.primary_pain_point && <p className="mt-2 text-sm text-neutral-700"><span className="font-medium">Signal:</span> {firm.primary_pain_point}</p>}
          {firm.monthly_email_volume !== null && <p className="mt-1 text-xs text-neutral-500">About {firm.monthly_email_volume.toLocaleString()} emails/month</p>}
          {firm.summary && <p className="mt-2 line-clamp-4 text-xs leading-5 text-neutral-600">{firm.summary}</p>}
        </section>
      )}

      <section className="border-t border-neutral-200 pt-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase text-neutral-500">Leadership</h3>
          <Link href={`/emailtag-firms?firm=${encodeURIComponent(firm.pif_id)}`} className="text-xs text-neutral-500 hover:text-neutral-900">Full firm <ArrowUpRight className="inline h-3 w-3" /></Link>
        </div>
        <div className="mt-2 divide-y divide-neutral-100">
          {firm.leadership.slice(0, 6).map((leader) => (
            <div key={`${leader.name}-${leader.title}`} className="flex items-start gap-2 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-neutral-900">{leader.name}</p>
                <p className="truncate text-xs text-neutral-500">{leader.title || "Leadership"}</p>
              </div>
              <ContactLinks person={leader} />
            </div>
          ))}
        </div>
      </section>

      {firm.practice_areas.length > 0 && (
        <p className="border-t border-neutral-200 pt-3 text-xs text-neutral-500">{firm.practice_areas.join(" · ")}</p>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><div className="text-base font-semibold tabular-nums text-neutral-900">{value}</div><div className="text-[10px] uppercase text-neutral-400">{label}</div></div>;
}

function ContactLinks({ person, website }: { person: Pick<CallLabLeader, "email" | "linkedin" | "phone">; website?: string | null }) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      {person.phone && <a href={`tel:${person.phone}`} className="p-1.5 text-neutral-400 hover:text-neutral-900" title="Dial number"><Phone className="h-3.5 w-3.5" /></a>}
      {person.email && <a href={`mailto:${person.email}`} className="p-1.5 text-neutral-400 hover:text-neutral-900" title="Email"><Mail className="h-3.5 w-3.5" /></a>}
      {person.linkedin && <a href={person.linkedin} target="_blank" rel="noreferrer" className="p-1.5 text-neutral-400 hover:text-neutral-900" title="LinkedIn"><ExternalLink className="h-3.5 w-3.5" /></a>}
      {website && <a href={website} target="_blank" rel="noreferrer" className="p-1.5 text-neutral-400 hover:text-neutral-900" title="Website"><Building2 className="h-3.5 w-3.5" /></a>}
    </div>
  );
}

function LoadingRows() {
  return <>{[0, 1, 2, 3, 4, 5].map((row) => <div key={row} className="grid gap-3 px-3 py-3 lg:grid-cols-6"><span className="h-8 animate-pulse rounded bg-neutral-100" /><span className="h-8 animate-pulse rounded bg-neutral-100" /><span className="h-5 animate-pulse rounded bg-neutral-100" /><span className="h-5 animate-pulse rounded bg-neutral-100" /><span className="h-5 animate-pulse rounded bg-neutral-100" /><span /></div>)}</>;
}
