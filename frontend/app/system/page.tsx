"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { getHealthChecks, getFunnel, getJudgeAggregate } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function HealthPage() {
  const checks = useQuery({
    queryKey: ["health-checks"],
    queryFn: getHealthChecks,
    refetchInterval: 15_000,
  });

  const funnel = useQuery({
    queryKey: ["health-funnel", 7],
    queryFn: () => getFunnel(7),
    refetchInterval: 30_000,
  });

  const judge = useQuery({
    queryKey: ["health-judge"],
    queryFn: getJudgeAggregate,
    refetchInterval: 30_000,
  });

  const allOk = checks.data?.checks.every((c) => c.ok) ?? false;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Health</h1>
          <p className="text-sm text-neutral-500">
            Configuration + connectivity checks. Auto-refreshes every 15s.
          </p>
        </div>
        {checks.data && (
          <span
            className={cn(
              "rounded-full px-3 py-1 text-xs font-semibold",
              allOk ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
            )}
          >
            {allOk ? "all good" : `${checks.data.checks.filter((c) => !c.ok).length} issues`}
          </span>
        )}
      </div>

      <section className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-xs uppercase text-neutral-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Check</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-left font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {checks.isLoading && (
              <tr>
                <td colSpan={3} className="px-4 py-4 text-xs text-neutral-400">
                  loading…
                </td>
              </tr>
            )}
            {checks.data?.checks.map((c) => (
              <tr key={c.name} className="border-t border-neutral-100">
                <td className="px-4 py-2.5 font-mono text-xs text-neutral-700">{c.name}</td>
                <td className="px-4 py-2.5">
                  {c.ok ? (
                    <Check className="h-4 w-4 text-emerald-600" />
                  ) : (
                    <X className="h-4 w-4 text-rose-600" />
                  )}
                </td>
                <td className="px-4 py-2.5 text-xs text-neutral-600">{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Judge aggregate */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
              Judge (7-day)
            </h2>
            <p className="text-[11px] text-neutral-400">
              LLM reviews every completed call. See{" "}
              <span className="font-mono">docs/SELF_IMPROVEMENT.md</span>.
            </p>
          </div>
          {judge.data && (
            <div className="text-right">
              <div className="text-[11px] uppercase text-neutral-500">Median score</div>
              <div
                className={cn(
                  "mt-0.5 text-lg font-semibold",
                  (judge.data.score_p50 ?? 0) >= 7 ? "text-emerald-700"
                    : (judge.data.score_p50 ?? 0) >= 4 ? "text-amber-700"
                    : "text-rose-700",
                )}
              >
                {judge.data.score_p50 ?? "—"}
                <span className="text-sm text-neutral-400">/10</span>
              </div>
            </div>
          )}
        </div>

        {judge.data && (
          <div className="mt-4 grid gap-4 md:grid-cols-3 text-sm">
            <div>
              <span className="text-[11px] uppercase text-neutral-500">Judged last 7d</span>
              <div className="mt-0.5 text-lg font-semibold">{judge.data.judged_7d}</div>
              {judge.data.pending > 0 && (
                <div className="text-[11px] text-neutral-500">+ {judge.data.pending} pending</div>
              )}
            </div>
            <div>
              <span className="text-[11px] uppercase text-neutral-500">Score p25 / p50 / p75</span>
              <div className="mt-0.5 font-mono text-sm">
                {judge.data.score_p25 ?? "—"} / {judge.data.score_p50 ?? "—"} / {judge.data.score_p75 ?? "—"}
              </div>
            </div>
            <div>
              <span className="text-[11px] uppercase text-neutral-500">Mean</span>
              <div className="mt-0.5 font-mono text-sm">
                {judge.data.score_mean != null ? judge.data.score_mean.toFixed(1) : "—"}
              </div>
            </div>
          </div>
        )}

        {judge.data && judge.data.by_disposition.length > 0 && (
          <div className="mt-5">
            <div className="mb-2 text-[11px] uppercase text-neutral-500">
              By GTM disposition
            </div>
            <div className="space-y-1.5">
              {judge.data.by_disposition.map((d) => {
                const total = judge.data!.by_disposition.reduce((a, b) => a + b.count, 0);
                const pct = total > 0 ? (d.count / total) * 100 : 0;
                return (
                  <div key={d.disposition} className="flex items-center gap-2 text-xs">
                    <span className="w-52 truncate font-mono text-neutral-700">
                      {d.disposition}
                    </span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-100">
                      <div
                        className="h-full rounded-full bg-neutral-900"
                        style={{ width: `${Math.max(pct, 3)}%` }}
                      />
                    </div>
                    <span className="w-10 text-right tabular-nums text-neutral-500">
                      {d.count}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      {/* Funnel */}
      <section className="rounded-lg border border-neutral-200 bg-white p-5">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          7-day funnel
        </h2>
        {funnel.data && (
          <div className="mt-4 space-y-3">
            {(() => {
              const top = Math.max(...funnel.data!.stages.map((s) => s.count), 1);
              return funnel.data!.stages.map((s, i) => {
                const prev = i > 0 ? funnel.data!.stages[i - 1].count : null;
                const rate =
                  prev != null && prev > 0 ? Math.round((s.count / prev) * 100) : null;
                const width = `${Math.max((s.count / top) * 100, 4)}%`;
                return (
                  <div key={s.name}>
                    <div className="mb-1 flex items-baseline justify-between text-xs">
                      <span className="font-medium text-neutral-700">{s.name}</span>
                      <span className="text-neutral-500">
                        {s.count}
                        {rate != null && (
                          <span className="ml-2 text-neutral-400">{rate}%</span>
                        )}
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-neutral-100">
                      <div
                        className="h-full rounded-full bg-neutral-900"
                        style={{ width }}
                      />
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        )}
      </section>
    </div>
  );
}
