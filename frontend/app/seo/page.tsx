"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Loader2,
  RefreshCw,
  SearchCheck,
  Sparkles,
} from "lucide-react";
import {
  generateSeoActions,
  getSeoAudit,
  type SeoAuditAction,
  type SeoAuditPage,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const AUDIT_LIMIT = 25;
const ACTION_LIMIT = 20;

function scoreTone(score: number) {
  if (score >= 80) return "text-emerald-700 bg-emerald-50 border-emerald-200";
  if (score >= 55) return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-red-700 bg-red-50 border-red-200";
}

function priorityTone(priority: string) {
  if (priority === "high") return "bg-red-50 text-red-700 border-red-200";
  if (priority === "low") return "bg-neutral-50 text-neutral-600 border-neutral-200";
  return "bg-amber-50 text-amber-700 border-amber-200";
}

function shortPath(url: string) {
  try {
    const parsed = new URL(url);
    return parsed.pathname === "/" ? "/" : parsed.pathname;
  } catch {
    return url;
  }
}

export default function SeoPage() {
  const qc = useQueryClient();
  const audit = useQuery({
    queryKey: ["seo-audit", AUDIT_LIMIT],
    queryFn: () => getSeoAudit({ limit: AUDIT_LIMIT }),
    staleTime: 60_000,
  });
  const generateActions = useMutation({
    mutationFn: () => generateSeoActions({ limit: AUDIT_LIMIT, action_limit: ACTION_LIMIT }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["operator-notifications-pending"] });
      qc.invalidateQueries({ queryKey: ["seo-audit"] });
    },
  });

  const summary = audit.data?.summary;
  const pages = audit.data?.pages ?? [];
  const topActions = audit.data?.summary.top_actions ?? [];

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-900">
          SEO & Agent Optimization
        </h1>
        <span className="text-xs text-neutral-400">
          evaluate discoverability, AI legibility, and conversion paths
        </span>
        <button
          type="button"
          onClick={() => audit.refetch()}
          disabled={audit.isFetching}
          className="ml-auto inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60"
        >
          {audit.isFetching ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Refresh audit
        </button>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex min-w-[260px] flex-1 items-start gap-3">
            <span className="rounded-lg bg-neutral-900 p-2 text-white">
              <SearchCheck className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-neutral-950">
                Current loop
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-neutral-600">
                This v1 crawls getpossibleminds.com, checks each page for search
                basics, agent-readable answer structure, proof, schema, internal
                links, and consult paths, then turns the highest leverage fixes
                into durable Actions.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => generateActions.mutate()}
            disabled={generateActions.isPending || audit.isLoading}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
          >
            {generateActions.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Generate improvement actions
          </button>
        </div>
        {generateActions.isSuccess && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            <CheckCircle2 className="h-4 w-4" />
            Created or refreshed {generateActions.data.created_count} action candidates.
            <Link href="/actions" className="inline-flex items-center gap-1 font-semibold">
              Open Actions <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}
        {generateActions.isError && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Could not generate SEO actions. Check backend logs.
          </div>
        )}
      </section>

      {audit.isLoading ? (
        <div className="flex items-center gap-2 rounded-xl border border-neutral-200 bg-white px-4 py-10 text-sm text-neutral-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Running audit...
        </div>
      ) : audit.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-6 text-sm text-red-700">
          Could not load SEO audit.
        </div>
      ) : (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <Metric label="Pages crawled" value={summary?.page_count ?? 0} />
            <Metric label="SEO score" value={summary?.avg_seo_score ?? 0} score />
            <Metric label="Agent score" value={summary?.avg_aeo_score ?? 0} score />
            <Metric label="High priority actions" value={summary?.high_priority_action_count ?? 0} />
          </section>

          <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div className="rounded-xl border border-neutral-200 bg-white">
              <div className="border-b border-neutral-100 px-4 py-3">
                <h2 className="text-sm font-semibold text-neutral-950">
                  Page audit
                </h2>
              </div>
              <div className="divide-y divide-neutral-100">
                {pages.map((page) => (
                  <PageRow key={page.url} page={page} />
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-neutral-200 bg-white">
              <div className="border-b border-neutral-100 px-4 py-3">
                <h2 className="text-sm font-semibold text-neutral-950">
                  Top action candidates
                </h2>
              </div>
              <div className="divide-y divide-neutral-100">
                {topActions.length === 0 ? (
                  <div className="px-4 py-8 text-sm text-neutral-500">
                    No obvious action candidates found.
                  </div>
                ) : (
                  topActions.map((action) => (
                    <ActionCandidate key={action.id} action={action} />
                  ))
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Metric({ label, value, score = false }: { label: string; value: number; score?: boolean }) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {label}
      </div>
      <div
        className={cn(
          "mt-2 inline-flex min-w-16 items-center justify-center rounded-md border px-3 py-1.5 text-2xl font-semibold",
          score ? scoreTone(value) : "border-neutral-200 bg-neutral-50 text-neutral-900",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function PageRow({ page }: { page: SeoAuditPage }) {
  const findings = [...page.issues, ...page.opportunities].slice(0, 4);
  return (
    <div className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_230px]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={page.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-w-0 items-center gap-1 text-sm font-semibold text-neutral-950 hover:underline"
          >
            <span className="truncate">{shortPath(page.url)}</span>
            <ExternalLink className="h-3.5 w-3.5 shrink-0" />
          </a>
          {page.status_code && (
            <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[11px] font-medium text-neutral-600">
              {page.status_code}
            </span>
          )}
        </div>
        <div className="mt-1 truncate text-sm text-neutral-600">
          {page.title || "No title found"}
        </div>
        {findings.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs leading-5 text-neutral-600">
            {findings.map((finding) => (
              <li key={finding} className="flex gap-2">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-neutral-400" />
                <span>{finding}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <Score label="SEO" value={page.seo_score} />
        <Score label="Agent" value={page.aeo_score} />
        <Score label="Overall" value={page.score} />
      </div>
    </div>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  return (
    <div className={cn("rounded-md border px-2 py-2", scoreTone(value))}>
      <div className="font-semibold">{value}</div>
      <div className="mt-0.5 text-[11px] opacity-80">{label}</div>
    </div>
  );
}

function ActionCandidate({ action }: { action: SeoAuditAction }) {
  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-0.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
            priorityTone(action.priority),
          )}
        >
          {action.priority}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-neutral-950">
            {action.title}
          </div>
          <div className="mt-1 break-all text-xs text-neutral-500">
            {shortPath(action.page_url)}
          </div>
          <p className="mt-2 text-xs leading-5 text-neutral-700">
            {action.suggested_change}
          </p>
        </div>
      </div>
    </div>
  );
}
