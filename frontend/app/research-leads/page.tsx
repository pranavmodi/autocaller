"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Building2,
  CalendarDays,
  ExternalLink,
  Lightbulb,
  Link2,
  Loader2,
  MessageSquareQuote,
  RefreshCw,
  Search,
  Sparkles,
  UserRound,
  Users,
  X,
} from "lucide-react";
import {
  listLeadFinderResults,
  type LeadFinderPublishedResult,
} from "@/lib/api";

function resultKey(result: LeadFinderPublishedResult) {
  return `${result.run.id}:${result.step.id}:${result.lead.id}`;
}

function formatDate(value: string | null | undefined, compact = false) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, compact
    ? { month: "short", day: "numeric", year: "numeric" }
    : { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function searchableText(result: LeadFinderPublishedResult) {
  const { lead, run } = result;
  return [
    lead.name,
    lead.role,
    lead.organization,
    lead.profile_summary,
    lead.notes,
    run.user_direction,
    ...lead.outreach_angles.flatMap((angle) => [angle.title, angle.why_relevant, angle.question]),
    ...lead.recent_signals.flatMap((signal) => [signal.title, signal.summary, signal.relevance]),
  ].filter(Boolean).join(" ").toLowerCase();
}

export default function ResearchLeadsPage() {
  const [results, setResults] = useState<LeadFinderPublishedResult[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [query, setQuery] = useState("");
  const [organization, setOrganization] = useState("all");
  const [runId, setRunId] = useState("all");
  const [sort, setSort] = useState<"newest" | "oldest" | "name">("newest");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const detailRef = useRef<HTMLDivElement>(null);

  const loadResults = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError("");
    try {
      const response = await listLeadFinderResults(1000);
      setResults(response.results);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load researched leads.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadResults();
  }, [loadResults]);

  const organizations = useMemo(() => Array.from(new Set(
    results.map((result) => result.lead.organization).filter((value): value is string => Boolean(value)),
  )).sort((a, b) => a.localeCompare(b)), [results]);

  const runs = useMemo(() => {
    const seen = new Map<string, LeadFinderPublishedResult["run"]>();
    results.forEach((result) => seen.set(result.run.id, result.run));
    return Array.from(seen.values());
  }, [results]);

  const visibleResults = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = results.filter((result) => (
      (organization === "all" || result.lead.organization === organization)
      && (runId === "all" || result.run.id === runId)
      && (!normalizedQuery || searchableText(result).includes(normalizedQuery))
    ));
    return [...filtered].sort((left, right) => {
      if (sort === "name") return left.lead.name.localeCompare(right.lead.name);
      const leftTime = new Date(left.published_at || 0).getTime();
      const rightTime = new Date(right.published_at || 0).getTime();
      return sort === "oldest" ? leftTime - rightTime : rightTime - leftTime;
    });
  }, [organization, query, results, runId, sort]);

  const selectedResult = useMemo(() => (
    visibleResults.find((result) => resultKey(result) === selectedKey)
    || visibleResults[0]
    || null
  ), [selectedKey, visibleResults]);

  const uniqueOrganizations = new Set(results.map((result) => result.lead.organization).filter(Boolean)).size;
  const newestPublication = results.reduce<string | null>((latest, result) => {
    if (!result.published_at) return latest;
    if (!latest || new Date(result.published_at) > new Date(latest)) return result.published_at;
    return latest;
  }, null);
  const filtersActive = Boolean(query || organization !== "all" || runId !== "all" || sort !== "newest");

  function selectResult(result: LeadFinderPublishedResult) {
    setSelectedKey(resultKey(result));
    if (window.matchMedia("(max-width: 1279px)").matches) {
      window.setTimeout(() => detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    }
  }

  function clearFilters() {
    setQuery("");
    setOrganization("all");
    setRunId("all");
    setSort("newest");
  }

  return (
    <div className="space-y-6">
      <header className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
        <div className="relative px-5 py-6 sm:px-7 sm:py-8">
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-violet-600 via-fuchsia-500 to-amber-400" />
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-violet-700">
                <Sparkles className="h-4 w-4" /> Lead intelligence
              </div>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-neutral-950">All researched leads</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-600">
                One place to review every lead the Lead Finder has verified and published across runs. Scan the evidence, choose an angle, and trace every recommendation back to its research run.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => void loadResults(true)} disabled={refreshing}
                className="inline-flex items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3.5 py-2.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50">
                {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Refresh
              </button>
              <Link href="/lead-finder" className="inline-flex items-center gap-2 rounded-lg bg-neutral-950 px-4 py-2.5 text-sm font-medium text-white hover:bg-neutral-800">
                Open Lead Finder <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>

        <div className="grid border-t border-neutral-200 bg-neutral-50/70 sm:grid-cols-2 xl:grid-cols-4">
          <div className="border-b border-neutral-200 px-5 py-4 sm:border-r xl:border-b-0">
            <div className="text-xs text-neutral-500">Published leads</div>
            <div className="mt-1 text-2xl font-semibold text-neutral-950">{results.length}</div>
          </div>
          <div className="border-b border-neutral-200 px-5 py-4 xl:border-b-0 xl:border-r">
            <div className="text-xs text-neutral-500">Organizations</div>
            <div className="mt-1 text-2xl font-semibold text-neutral-950">{uniqueOrganizations}</div>
          </div>
          <div className="border-b border-neutral-200 px-5 py-4 sm:border-b-0 sm:border-r">
            <div className="text-xs text-neutral-500">Research runs</div>
            <div className="mt-1 text-2xl font-semibold text-neutral-950">{runs.length}</div>
          </div>
          <div className="px-5 py-4">
            <div className="text-xs text-neutral-500">Newest publication</div>
            <div className="mt-1 text-sm font-semibold text-neutral-950">{formatDate(newestPublication, true)}</div>
          </div>
        </div>
      </header>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <section className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="grid gap-3 lg:grid-cols-[minmax(16rem,1fr)_15rem_15rem_10rem_auto]">
          <label className="relative block">
            <span className="sr-only">Search researched leads</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search people, firms, evidence, or angles…"
              className="h-10 w-full rounded-lg border border-neutral-200 bg-white pl-9 pr-3 text-sm outline-none placeholder:text-neutral-400 focus:border-violet-400 focus:ring-2 focus:ring-violet-100" />
          </label>
          <select value={organization} onChange={(event) => setOrganization(event.target.value)} aria-label="Filter by organization"
            className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-700 outline-none focus:border-violet-400">
            <option value="all">All organizations</option>
            {organizations.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={runId} onChange={(event) => setRunId(event.target.value)} aria-label="Filter by run"
            className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-700 outline-none focus:border-violet-400">
            <option value="all">All research runs</option>
            {runs.map((item) => <option key={item.id} value={item.id}>{item.id.slice(0, 18)} · {item.status}</option>)}
          </select>
          <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} aria-label="Sort leads"
            className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-700 outline-none focus:border-violet-400">
            <option value="newest">Newest</option>
            <option value="oldest">Oldest</option>
            <option value="name">Name A–Z</option>
          </select>
          <button type="button" onClick={clearFilters} disabled={!filtersActive}
            className="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg border border-neutral-200 px-3 text-sm font-medium text-neutral-600 hover:bg-neutral-50 disabled:opacity-35">
            <X className="h-4 w-4" /> Clear
          </button>
        </div>
      </section>

      {loading ? (
        <div className="flex min-h-80 items-center justify-center gap-2 rounded-2xl border border-neutral-200 bg-white text-sm text-neutral-500 shadow-sm">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading researched leads…
        </div>
      ) : results.length === 0 ? (
        <div className="flex min-h-80 flex-col items-center justify-center rounded-2xl border border-neutral-200 bg-white px-6 text-center shadow-sm">
          <Users className="h-9 w-9 text-neutral-300" />
          <h2 className="mt-4 text-base font-semibold text-neutral-900">No leads have been published yet</h2>
          <p className="mt-1 max-w-md text-sm leading-6 text-neutral-500">Run the Lead Finder until it verifies a candidate and explicitly publishes the research.</p>
          <Link href="/lead-finder" className="mt-4 inline-flex items-center gap-2 rounded-lg bg-neutral-950 px-4 py-2.5 text-sm font-medium text-white">Open Lead Finder <ArrowRight className="h-4 w-4" /></Link>
        </div>
      ) : visibleResults.length === 0 ? (
        <div className="flex min-h-72 flex-col items-center justify-center rounded-2xl border border-neutral-200 bg-white px-6 text-center shadow-sm">
          <Search className="h-8 w-8 text-neutral-300" />
          <h2 className="mt-3 text-base font-semibold text-neutral-900">No leads match these filters</h2>
          <button type="button" onClick={clearFilters} className="mt-3 text-sm font-medium text-violet-700 hover:underline">Clear filters</button>
        </div>
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
          <aside className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm xl:sticky xl:top-6">
            <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
              <div className="text-sm font-semibold text-neutral-900">Lead list</div>
              <div className="text-xs text-neutral-400">{visibleResults.length} shown</div>
            </div>
            <div className="max-h-[calc(100vh-10rem)] divide-y divide-neutral-200 overflow-y-auto">
              {visibleResults.map((result) => {
                const selected = selectedResult ? resultKey(result) === resultKey(selectedResult) : false;
                const primaryAngle = result.lead.outreach_angles[0];
                return (
                  <button key={resultKey(result)} type="button" onClick={() => selectResult(result)}
                    className={`w-full px-4 py-4 text-left transition-colors ${selected ? "bg-violet-50 ring-1 ring-inset ring-violet-200" : "bg-white hover:bg-neutral-50"}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-neutral-950">{result.lead.name}</div>
                        <div className="mt-0.5 truncate text-xs text-neutral-600">{result.lead.organization || "Organization unverified"}</div>
                      </div>
                      <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-1 text-[9px] font-semibold uppercase tracking-wide text-emerald-700">researched</span>
                    </div>
                    <div className="mt-2 line-clamp-2 text-xs leading-5 text-neutral-500">{result.lead.role || result.lead.profile_summary}</div>
                    {primaryAngle && (
                      <div className="mt-3 rounded-md bg-white/80 px-2.5 py-2 text-xs text-violet-800 ring-1 ring-violet-100">
                        <Lightbulb className="mr-1.5 inline h-3.5 w-3.5" />{primaryAngle.title}
                      </div>
                    )}
                    <div className="mt-3 flex items-center justify-between text-[10px] text-neutral-400">
                      <span>{formatDate(result.published_at, true)}</span>
                      <span>{result.lead.sources.length} sources</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          {selectedResult && (
            <div ref={detailRef} className="scroll-mt-4 space-y-5">
              <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-2xl font-semibold tracking-tight text-neutral-950">{selectedResult.lead.name}</h2>
                      {selectedResult.lead.identity_confidence !== null && (
                        <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                          {Math.round(selectedResult.lead.identity_confidence * 100)}% identity confidence
                        </span>
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-sm text-neutral-600">
                      {selectedResult.lead.role && <span className="inline-flex items-center gap-1.5"><UserRound className="h-4 w-4" />{selectedResult.lead.role}</span>}
                      {selectedResult.lead.organization && <span className="inline-flex items-center gap-1.5"><Building2 className="h-4 w-4" />{selectedResult.lead.organization}</span>}
                    </div>
                  </div>
                  {selectedResult.lead.official_profile_url && (
                    <a href={selectedResult.lead.official_profile_url} target="_blank" rel="noreferrer"
                      className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-neutral-200 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50">
                      Public profile <ExternalLink className="h-4 w-4" />
                    </a>
                  )}
                </div>
                <p className="mt-5 text-sm leading-7 text-neutral-700">{selectedResult.lead.profile_summary}</p>
                {selectedResult.lead.notes && (
                  <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950">
                    <span className="font-semibold">Research note:</span> {selectedResult.lead.notes}
                  </div>
                )}
                <div className="mt-5 grid gap-3 border-t border-neutral-100 pt-5 text-xs sm:grid-cols-2 xl:grid-cols-4">
                  <div><div className="text-neutral-400">Published</div><div className="mt-1 font-medium text-neutral-800">{formatDate(selectedResult.published_at)}</div></div>
                  <div><div className="text-neutral-400">Origin</div><div className="mt-1 font-medium text-neutral-800">Step {selectedResult.step.step_number}</div></div>
                  <div className="sm:col-span-2"><div className="text-neutral-400">Research direction</div><div className="mt-1 font-medium leading-5 text-neutral-800">{selectedResult.run.user_direction || "No run-specific direction"}</div></div>
                </div>
                <Link href={`/lead-finder?run=${encodeURIComponent(selectedResult.run.id)}`}
                  className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-violet-700 hover:underline">
                  Inspect originating run <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </section>

              <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
                <div className="flex items-center gap-2"><Lightbulb className="h-5 w-5 text-violet-600" /><h3 className="text-base font-semibold text-neutral-950">Possible outreach angles</h3></div>
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  {selectedResult.lead.outreach_angles.map((angle, index) => (
                    <article key={`${selectedResult.lead.id}-angle-${index}`} className="rounded-xl border border-violet-100 bg-violet-50/60 p-4">
                      <div className="text-sm font-semibold text-violet-950">{angle.title}</div>
                      <p className="mt-2 text-xs leading-5 text-violet-900">{angle.why_relevant}</p>
                      <div className="mt-3 rounded-lg bg-white/70 p-3 text-xs font-medium leading-5 text-violet-950">{angle.question}</div>
                      {angle.source_urls.length > 0 && <div className="mt-3 text-[10px] text-violet-600">Grounded in {angle.source_urls.length} cited source{angle.source_urls.length === 1 ? "" : "s"}</div>}
                    </article>
                  ))}
                </div>
              </section>

              <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
                <div className="flex items-center gap-2"><CalendarDays className="h-5 w-5 text-sky-600" /><h3 className="text-base font-semibold text-neutral-950">Recent signals</h3></div>
                <div className="mt-4 space-y-3">
                  {selectedResult.lead.recent_signals.map((signal, index) => (
                    <article key={`${selectedResult.lead.id}-signal-${index}`} className="rounded-xl border border-neutral-200 p-4">
                      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                        <a href={signal.source_url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-neutral-950 hover:text-violet-700 hover:underline">{signal.title}</a>
                        <span className="shrink-0 text-xs text-neutral-400">{signal.date || "Date not published"}</span>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-neutral-600">{signal.summary}</p>
                      {signal.relevance && <p className="mt-2 text-xs leading-5 text-sky-800"><span className="font-semibold">Why it matters:</span> {signal.relevance}</p>}
                    </article>
                  ))}
                </div>
              </section>

              {selectedResult.lead.mission_control_evidence.length > 0 && (
                <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
                  <div className="flex items-center gap-2"><MessageSquareQuote className="h-5 w-5 text-amber-600" /><h3 className="text-base font-semibold text-neutral-950">Transcript evidence</h3></div>
                  <div className="mt-4 space-y-3">
                    {selectedResult.lead.mission_control_evidence.map((evidence, index) => (
                      <blockquote key={`${selectedResult.lead.id}-evidence-${index}`} className="rounded-xl border-l-4 border-amber-300 bg-amber-50/60 px-4 py-3">
                        <div className="text-xs font-semibold text-amber-950">{String(evidence.episode_title || "Mission Control transcript")}</div>
                        <p className="mt-2 text-xs leading-5 text-amber-900">{String(evidence.excerpt || "Passage retained in the research record.")}</p>
                        {evidence.chunk_id !== undefined && <div className="mt-2 font-mono text-[10px] text-amber-700">chunk {String(evidence.chunk_id)}</div>}
                      </blockquote>
                    ))}
                  </div>
                </section>
              )}

              <section className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm sm:p-6">
                <div className="flex items-center gap-2"><Link2 className="h-5 w-5 text-neutral-600" /><h3 className="text-base font-semibold text-neutral-950">Sources and caveats</h3></div>
                <div className="mt-4 grid gap-5 lg:grid-cols-2">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.12em] text-neutral-500">Sources</div>
                    <div className="mt-2 space-y-2">
                      {selectedResult.lead.sources.map((source, index) => (
                        <a key={`${selectedResult.lead.id}-source-${index}`} href={source.url} target="_blank" rel="noreferrer"
                          className="block rounded-lg border border-neutral-200 px-3 py-2.5 hover:border-violet-200 hover:bg-violet-50/40">
                          <div className="flex items-start justify-between gap-2 text-xs font-medium text-neutral-900"><span>{source.title || source.url}</span><ExternalLink className="h-3.5 w-3.5 shrink-0 text-neutral-400" /></div>
                          <div className="mt-1 text-[10px] text-neutral-400">{source.source_type}{source.published_date ? ` · ${source.published_date}` : ""}</div>
                          {source.supports && <p className="mt-1 text-[11px] leading-4 text-neutral-500">{source.supports}</p>}
                        </a>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.12em] text-neutral-500">Contrary or missing evidence</div>
                    {selectedResult.lead.contrary_evidence.length > 0 ? (
                      <ul className="mt-2 space-y-2">
                        {selectedResult.lead.contrary_evidence.map((item, index) => (
                          <li key={`${selectedResult.lead.id}-caveat-${index}`} className="rounded-lg bg-neutral-50 px-3 py-2.5 text-xs leading-5 text-neutral-600">{item}</li>
                        ))}
                      </ul>
                    ) : <p className="mt-2 text-xs text-neutral-500">No contrary evidence was recorded.</p>}
                  </div>
                </div>
              </section>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
