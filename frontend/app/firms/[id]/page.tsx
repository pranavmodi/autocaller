"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getPifFirm,
  triggerResearch,
  triggerStaffResearch,
  triggerBehaviorAnalysis,
  triggerIcpScore,
  pollResearchStatus,
  type PifFirm,
  type PifLeader,
} from "@/lib/pifstats";
import { getFirmReviews, putFirmReviews, getFirmCalls } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  ArrowLeft,
  Building2,
  Globe,
  Mail,
  Phone,
  PhoneCall,
  MapPin,
  Users,
  BarChart3,
  Trophy,
  Clock,
  AlertTriangle,
  Linkedin,
  ExternalLink,
  Briefcase,
  Star,
  Search,
} from "lucide-react";

function tierColor(tier: string | null) {
  if (tier === "A") return "bg-emerald-100 text-emerald-800";
  if (tier === "B") return "bg-sky-100 text-sky-800";
  if (tier === "C") return "bg-amber-100 text-amber-800";
  return "bg-neutral-100 text-neutral-600";
}

function painLabel(pain: string) {
  return pain
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function FirmDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: firm, isLoading, error } = useQuery({
    queryKey: ["pif-firm", id],
    queryFn: () => getPifFirm(id),
  });

  if (isLoading) {
    return <div className="py-12 text-center text-sm text-neutral-400">Loading firm...</div>;
  }
  if (error || !firm) {
    return <div className="py-12 text-center text-sm text-rose-500">Failed to load firm.</div>;
  }

  const beh = firm.behavioral_data;
  const research = firm.research_data;
  const score = firm.score_breakdown;

  return (
    <div className="space-y-6">
      <Link
        href="/firms"
        className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-800"
      >
        <ArrowLeft className="h-3 w-3" />
        back to firms
      </Link>

      {/* Header */}
      <section className="rounded-xl border border-neutral-200 bg-white p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <Building2 className="h-6 w-6 text-neutral-400" />
              <h1 className="text-2xl font-bold text-neutral-900">{firm.firm_name}</h1>
              {firm.icp_tier && (
                <span className={cn("rounded-full px-3 py-1 text-xs font-bold", tierColor(firm.icp_tier))}>
                  Tier {firm.icp_tier}
                </span>
              )}
              {firm.icp_score != null && (
                <span className="text-sm font-mono text-neutral-500">
                  ICP {firm.icp_score}/100
                </span>
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-neutral-500">
              {firm.website && (
                <a href={`https://${firm.website}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-neutral-800">
                  <Globe className="h-3.5 w-3.5" />
                  {firm.website}
                </a>
              )}
              {firm.addresses?.[0] && (
                <span className="flex items-center gap-1">
                  <MapPin className="h-3.5 w-3.5" />
                  {firm.addresses[0]}
                </span>
              )}
              {research?.firm_size && (
                <span className="flex items-center gap-1">
                  <Users className="h-3.5 w-3.5" />
                  {research.firm_size}
                </span>
              )}
              {research?.founded_year && (
                <span className="text-neutral-400">Est. {research.founded_year}</span>
              )}
            </div>
          </div>
        </div>

        {/* Phones + emails */}
        <div className="mt-4 flex flex-wrap gap-3">
          {firm.phones?.map((p, i) => (
            <span key={i} className="flex items-center gap-1 rounded-lg bg-neutral-50 px-2.5 py-1 text-xs font-mono text-neutral-700">
              <Phone className="h-3 w-3 text-neutral-400" />
              {p}
            </span>
          ))}
          {firm.fax && (
            <span className="flex items-center gap-1 rounded-lg bg-neutral-50 px-2.5 py-1 text-xs font-mono text-neutral-500">
              Fax: {firm.fax}
            </span>
          )}
        </div>
      </section>

      {/* Research actions */}
      <ResearchActions firmId={firm.id} firm={firm} />

      {/* Operator-pasted reviews — separate blobs per source */}
      <FirmReviewsPanel
        pifId={firm.id}
        firmName={firm.firm_name}
        address={firm.addresses?.[0] ?? null}
      />

      {/* Score breakdown + Behavior — two columns */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* ICP Score */}
        {score && (
          <section className="rounded-xl border border-neutral-200 bg-white p-5">
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
              <BarChart3 className="h-4 w-4" />
              ICP Score Breakdown
            </h2>
            <div className="mt-4 space-y-3">
              {[
                { label: "Email Volume", score: score.email_volume_score, max: 30, reason: score.email_volume_reason },
                { label: "Recency", score: score.recency_score, max: 20, reason: score.recency_reason },
                { label: "Pain Signals", score: score.pain_signals_score, max: 25, reason: score.pain_signals_reason },
                { label: "Firm Size", score: score.firm_size_score, max: 15, reason: score.firm_size_reason },
                { label: "Completeness", score: score.completeness_score, max: 10, reason: score.completeness_reason },
              ].map((item) => (
                <div key={item.label}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="font-medium text-neutral-700">{item.label}</span>
                    <span className="font-mono text-neutral-500">{item.score}/{item.max}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-neutral-100">
                    <div
                      className="h-full rounded-full bg-neutral-800"
                      style={{ width: `${(item.score / item.max) * 100}%` }}
                    />
                  </div>
                  <p className="mt-0.5 text-[10px] text-neutral-400">{item.reason}</p>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Behavior */}
        {beh && (
          <section className="rounded-xl border border-neutral-200 bg-white p-5">
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
              <Clock className="h-4 w-4" />
              Behavioral Signals
            </h2>
            <div className="mt-4 grid grid-cols-2 gap-4">
              <Stat label="Emails (total)" value={String(beh.total_email_count)} />
              <Stat label="Monthly avg" value={`${(beh.monthly_email_volume.reduce((a, b) => a + b, 0) / Math.max(beh.monthly_email_volume.length, 1)).toFixed(1)}/mo`} />
              <Stat label="Last contact" value={beh.days_since_last_contact === 0 ? "Today" : `${beh.days_since_last_contact}d ago`} />
              <Stat
                label="After hours"
                value={`${Math.round(beh.after_hours_ratio * 100)}%`}
                accent={beh.after_hours_ratio > 0.5 ? "amber" : undefined}
              />
              <Stat label="Peak days" value={beh.peak_contact_days.join(", ")} />
              <Stat
                label="Primary pain"
                value={painLabel(beh.primary_pain_point)}
                accent="rose"
              />
            </div>

            {/* Topic distribution */}
            <div className="mt-5">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-neutral-400">
                Email Topics
              </div>
              <div className="space-y-1.5">
                {Object.entries(beh.topic_distribution)
                  .sort(([, a], [, b]) => b - a)
                  .map(([topic, count]) => {
                    const total = Object.values(beh.topic_distribution).reduce((a, b) => a + b, 0);
                    const pct = total > 0 ? (count / total) * 100 : 0;
                    return (
                      <div key={topic} className="flex items-center gap-2 text-xs">
                        <span className="w-36 truncate text-neutral-600">
                          {painLabel(topic)}
                        </span>
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-100">
                          <div
                            className="h-full rounded-full bg-neutral-700"
                            style={{ width: `${Math.max(pct, 3)}%` }}
                          />
                        </div>
                        <span className="w-8 text-right tabular-nums text-neutral-500">{count}</span>
                      </div>
                    );
                  })}
              </div>
            </div>
          </section>
        )}
      </div>

      {/* Leadership */}
      {firm.leadership?.length > 0 && (
        <section className="rounded-xl border border-neutral-200 bg-white">
          <div className="border-b border-neutral-100 px-5 py-3">
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
              <Briefcase className="h-4 w-4" />
              Leadership ({firm.leadership.length})
            </h2>
          </div>
          <div className="divide-y divide-neutral-100">
            {firm.leadership.map((person, i) => (
              <PersonRow key={i} person={person} />
            ))}
          </div>
        </section>
      )}

      {/* Staff / Contacts */}
      {firm.contacts?.length > 0 && (
        <section className="rounded-xl border border-neutral-200 bg-white">
          <div className="border-b border-neutral-100 px-5 py-3">
            <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
              <Users className="h-4 w-4" />
              Contacts ({firm.contacts.length})
            </h2>
          </div>
          <div className="divide-y divide-neutral-100">
            {firm.contacts.map((c, i) => (
              <div key={i} className="flex items-center gap-3 px-5 py-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-full bg-neutral-100 text-xs font-bold text-neutral-500">
                  {c.name.charAt(0)}
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-neutral-900">{c.name}</div>
                  <div className="text-[11px] text-neutral-500">{c.title}</div>
                </div>
                {c.email && (
                  <a href={`mailto:${c.email}`} className="text-neutral-400 hover:text-neutral-600">
                    <Mail className="h-3.5 w-3.5" />
                  </a>
                )}
                {c.phone && (
                  <span className="text-xs font-mono text-neutral-500">{c.phone}</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Research — practice areas, awards, notable cases */}
      {research && (
        <div className="grid gap-5 lg:grid-cols-2">
          {research.practice_areas?.length > 0 && (
            <section className="rounded-xl border border-neutral-200 bg-white p-5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
                Practice Areas
              </h2>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {research.practice_areas.map((pa) => (
                  <span key={pa} className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-[11px] font-medium text-neutral-700">
                    {pa}
                  </span>
                ))}
              </div>
            </section>
          )}

          {research.awards_recognition?.length > 0 && (
            <section className="rounded-xl border border-neutral-200 bg-white p-5">
              <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
                <Trophy className="h-4 w-4" />
                Awards & Recognition
              </h2>
              <ul className="mt-3 space-y-2">
                {research.awards_recognition.map((a, i) => (
                  <li key={i} className="text-xs leading-relaxed text-neutral-600">{a}</li>
                ))}
              </ul>
            </section>
          )}

          {research.notable_cases?.length > 0 && (
            <section className="rounded-xl border border-neutral-200 bg-white p-5 lg:col-span-2">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-neutral-400">
                Notable Cases
              </h2>
              <ul className="mt-3 space-y-2">
                {research.notable_cases.map((c, i) => (
                  <li key={i} className="text-xs leading-relaxed text-neutral-600">{c}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {/* Emails */}
      {firm.emails?.length > 0 && (
        <section className="rounded-xl border border-neutral-200 bg-white p-5">
          <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
            <Mail className="h-4 w-4" />
            Email addresses ({firm.emails.length})
          </h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {firm.emails.map((e) => (
              <a
                key={e}
                href={`mailto:${e}`}
                className="rounded-lg bg-neutral-50 px-2.5 py-1 text-xs font-mono text-neutral-600 hover:bg-neutral-100"
              >
                {e}
              </a>
            ))}
          </div>
        </section>
      )}

      <FirmCallsPanel pifId={id} />
    </div>
  );
}

function FirmCallsPanel({ pifId }: { pifId: string }) {
  const calls = useQuery({
    queryKey: ["firm-calls", pifId],
    queryFn: () => getFirmCalls(pifId, 100),
    refetchInterval: 30_000,
  });

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
        <PhoneCall className="h-4 w-4" />
        Calls ({calls.data?.total ?? 0})
      </h2>
      {calls.isLoading && (
        <div className="mt-3 text-xs text-neutral-400">loading…</div>
      )}
      {!calls.isLoading && (calls.data?.items?.length ?? 0) === 0 && (
        <div className="mt-3 text-xs text-neutral-400">
          No calls yet to this firm.
        </div>
      )}
      {(calls.data?.items?.length ?? 0) > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-neutral-400">
              <tr className="text-left">
                <th className="px-2 py-1.5 font-medium">When</th>
                <th className="px-2 py-1.5 font-medium">Contact</th>
                <th className="px-2 py-1.5 font-medium">Phone</th>
                <th className="px-2 py-1.5 font-medium">Outcome</th>
                <th className="px-2 py-1.5 font-medium">Disposition</th>
                <th className="px-2 py-1.5 text-right font-medium">Dur</th>
                <th className="px-2 py-1.5 font-medium">Judge</th>
                <th className="px-2 py-1.5 font-medium">VM</th>
                <th className="px-2 py-1.5 font-medium">IVR</th>
                <th className="px-2 py-1.5 font-medium">Voice</th>
                <th className="px-2 py-1.5 font-medium">Prompt</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {calls.data?.items?.map((c) => (
                <tr
                  key={c.call_id}
                  className="text-neutral-700 hover:bg-neutral-50"
                >
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <Link
                      href={`/calls/${c.call_id}`}
                      className="text-blue-600 hover:underline"
                      title={c.started_at ?? ""}
                    >
                      {c.started_at
                        ? new Date(c.started_at).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })
                        : "—"}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5 max-w-[14rem] truncate">
                    {c.patient_name || "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[11px] text-neutral-500">
                    {c.phone || "—"}
                  </td>
                  <td className="px-2 py-1.5">
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-medium",
                        outcomeColor(c.outcome),
                      )}
                    >
                      {c.outcome}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-[11px] text-neutral-600">
                    {c.call_disposition}
                    {c.ended_by ? (
                      <span className="ml-1 text-[10px] text-neutral-400">
                        ({c.ended_by})
                      </span>
                    ) : null}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {c.duration_seconds}s
                  </td>
                  <td className="px-2 py-1.5">
                    {c.judge_score != null ? c.judge_score : "—"}
                  </td>
                  <td className="px-2 py-1.5">{c.voicemail_left ? "✓" : ""}</td>
                  <td className="px-2 py-1.5 text-[10px] text-neutral-500">
                    {c.ivr_detected ? c.ivr_outcome ?? "yes" : ""}
                  </td>
                  <td className="px-2 py-1.5 text-[10px] text-neutral-500">
                    {c.voice_provider ?? "—"}
                  </td>
                  <td className="px-2 py-1.5 text-[10px] text-neutral-500">
                    {c.prompt_version ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function outcomeColor(outcome: string): string {
  switch (outcome) {
    case "demo_scheduled":
      return "bg-emerald-100 text-emerald-800";
    case "callback_requested":
      return "bg-sky-100 text-sky-800";
    case "voicemail":
      return "bg-violet-100 text-violet-800";
    case "gatekeeper_only":
      return "bg-amber-100 text-amber-800";
    case "not_interested":
      return "bg-rose-100 text-rose-800";
    case "wrong_number":
      return "bg-neutral-200 text-neutral-700";
    case "completed":
      return "bg-neutral-100 text-neutral-700";
    case "failed":
    case "disconnected":
      return "bg-neutral-100 text-neutral-500";
    default:
      return "bg-neutral-100 text-neutral-600";
  }
}

function ResearchActions({ firmId, firm }: { firmId: string; firm: PifFirm }) {
  const qc = useQueryClient();
  const [taskId, setTaskId] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  const setBtn = (key: string, val: boolean) =>
    setLoading((prev) => ({ ...prev, [key]: val }));

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["pif-firm", firmId] });
  }, [qc, firmId]);

  // Poll research status
  useEffect(() => {
    if (!taskId || !polling) return;
    const interval = setInterval(async () => {
      try {
        const res = await pollResearchStatus(taskId);
        setStatus(res.status);
        if (res.status === "completed" || res.status === "failed") {
          setPolling(false);
          setTaskId(null);
          refresh();
        }
      } catch {
        setPolling(false);
      }
    }, 4000);
    return () => clearInterval(interval);
  }, [taskId, polling, refresh]);

  const handleResearch = async () => {
    setBtn("research", true);
    try {
      const res = await triggerResearch(firmId);
      setTaskId(res.task_id);
      setStatus("queued");
      setPolling(true);
    } catch (e: any) {
      setStatus(`error: ${e.message}`);
    }
    setBtn("research", false);
  };

  const handleStaff = async () => {
    setBtn("staff", true);
    try {
      const res = await triggerStaffResearch(firmId);
      setTaskId(res.task_id);
      setStatus("queued");
      setPolling(true);
    } catch (e: any) {
      setStatus(`error: ${e.message}`);
    }
    setBtn("staff", false);
  };

  const handleBehavior = async () => {
    setBtn("behavior", true);
    try {
      await triggerBehaviorAnalysis(firmId);
      setStatus("behavior analysis queued");
      // Poll by re-fetching firm data after a delay
      setTimeout(refresh, 5000);
      setTimeout(refresh, 15000);
    } catch (e: any) {
      setStatus(`error: ${e.message}`);
    }
    setBtn("behavior", false);
  };

  const handleScore = async () => {
    setBtn("score", true);
    try {
      await triggerIcpScore(firmId);
      refresh();
      setStatus("scored");
    } catch (e: any) {
      setStatus(`error: ${e.message}`);
    }
    setBtn("score", false);
  };

  const hasLeadership = (firm.leadership?.length ?? 0) > 0;
  const hasBehavior = !!firm.behavioral_data;
  const hasScore = firm.icp_score != null;

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
          <BarChart3 className="h-4 w-4" />
          Research & Enrichment
        </h2>
        {polling && (
          <span className="flex items-center gap-1.5 text-xs text-amber-700">
            <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
            {status === "queued" ? "Queued..." : status === "started" ? "Researching..." : status}
          </span>
        )}
        {status && !polling && (
          <span className="text-[11px] text-neutral-500">{status}</span>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <ResearchButton
          label="Leadership"
          description={hasLeadership ? `${firm.leadership!.length} found` : "Not researched"}
          done={hasLeadership}
          loading={loading.research || (polling && !loading.staff)}
          onClick={handleResearch}
        />
        <ResearchButton
          label="Staff"
          description={firm.staff ? `${firm.staff.length} found` : "Not researched"}
          done={!!firm.staff}
          loading={loading.staff}
          onClick={handleStaff}
        />
        <ResearchButton
          label="Behavior"
          description={hasBehavior ? `${firm.behavioral_data!.total_email_count} emails analyzed` : "Not analyzed"}
          done={hasBehavior}
          loading={loading.behavior}
          onClick={handleBehavior}
        />
        <ResearchButton
          label="ICP Score"
          description={hasScore ? `${firm.icp_score}/100 (Tier ${firm.icp_tier})` : "Not scored"}
          done={hasScore}
          loading={loading.score}
          onClick={handleScore}
          disabled={!hasBehavior}
          disabledReason="Run behavior analysis first"
        />
      </div>
    </section>
  );
}

function ResearchButton({
  label,
  description,
  done,
  loading,
  onClick,
  disabled,
  disabledReason,
}: {
  label: string;
  description: string;
  done: boolean;
  loading: boolean;
  onClick: () => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={loading || disabled}
      title={disabled ? disabledReason : `Run ${label.toLowerCase()} research`}
      className={cn(
        "flex flex-col items-start rounded-xl border px-4 py-3 text-left transition-colors min-w-[140px]",
        done
          ? "border-emerald-200 bg-emerald-50 hover:bg-emerald-100"
          : disabled
            ? "border-neutral-200 bg-neutral-50 opacity-50 cursor-not-allowed"
            : "border-neutral-200 bg-white hover:border-neutral-300 hover:bg-neutral-50",
      )}
    >
      <div className="flex items-center gap-2">
        {loading ? (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-neutral-300 border-t-neutral-700" />
        ) : done ? (
          <span className="h-3 w-3 rounded-full bg-emerald-500" />
        ) : (
          <span className="h-3 w-3 rounded-full border-2 border-neutral-300" />
        )}
        <span className="text-xs font-semibold text-neutral-800">{label}</span>
      </div>
      <span className="mt-1 text-[10px] text-neutral-500">{description}</span>
    </button>
  );
}

function PersonRow({ person }: { person: PifLeader }) {
  return (
    <div className="flex items-start gap-3 px-5 py-4 hover:bg-neutral-50 transition-colors">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-neutral-200 to-neutral-100 text-sm font-bold text-neutral-600">
        {person.name.charAt(0)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-neutral-900">{person.name}</span>
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-600">
            {person.title}
          </span>
        </div>
        {person.bio && (
          <p className="mt-1 text-xs leading-relaxed text-neutral-500 line-clamp-2">
            {person.bio}
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-3">
          {person.email && (
            <a href={`mailto:${person.email}`} className="flex items-center gap-1 text-[11px] text-neutral-500 hover:text-neutral-800">
              <Mail className="h-3 w-3" />
              {person.email}
            </a>
          )}
          {person.phone && (
            <span className="flex items-center gap-1 text-[11px] font-mono text-neutral-500">
              <Phone className="h-3 w-3" />
              {person.phone}
            </span>
          )}
          {person.linkedin && (
            <a href={person.linkedin} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800">
              <Linkedin className="h-3 w-3" />
              LinkedIn
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "amber" | "rose";
}) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wider text-neutral-400">
        {label}
      </div>
      <div
        className={cn(
          "mt-0.5 text-lg font-semibold",
          accent === "amber"
            ? "text-amber-700"
            : accent === "rose"
              ? "text-rose-700"
              : "text-neutral-900",
        )}
      >
        {value}
      </div>
    </div>
  );
}


// 2-letter US state code → full state name. Google search matches on
// either, but the full word is a stronger signal than the abbrev
// (which often collides with other words — "CA" vs "California").
const STATE_NAMES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas",
  CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho",
  IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas",
  KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi",
  MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada",
  NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York",
  NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma",
  OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina",
  SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
  VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia",
  WI: "Wisconsin", WY: "Wyoming", DC: "District of Columbia",
};

/** Pull the US state name out of an address string like
 * "123 Main St, Los Angeles, CA 90210". Falls back to empty if no
 * 2-letter state abbrev is present. */
function extractState(address: string | null | undefined): string {
  if (!address) return "";
  const m = address.match(/\b([A-Z]{2})\b\s*\d{5}(?:-\d{4})?\b/);
  const ab = (m?.[1] ?? "").toUpperCase();
  return STATE_NAMES[ab] ?? "";
}

function FirmReviewsPanel({
  pifId,
  firmName,
  address,
}: {
  pifId: string;
  firmName: string;
  address: string | null;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["firm-reviews", pifId],
    queryFn: () => getFirmReviews(pifId),
  });

  // Loose bag-of-words — quoted phrases were too strict (Yelp pages
  // often don't have the firm's full legal name verbatim) and
  // Mediflow's practice-area copy was marketing fluff. Keep the query
  // short: name + canonical firm type + full state name. Let Google
  // fuzzy-match.
  const state = extractState(address);
  const firmType = "personal injury law firm";

  const googleQuery = [firmName, firmType, state, "reviews"]
    .filter(Boolean)
    .join(" ");
  const yelpQuery = ["site:yelp.com", firmName, firmType, state]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-neutral-400">
          <Star className="h-4 w-4" />
          Reviews
        </h2>
        <span className="text-[11px] text-neutral-400">
          {isLoading
            ? "loading…"
            : data?.updated_at
              ? `last saved ${new Date(data.updated_at).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "2-digit",
                })}`
              : "not saved"}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-neutral-500">
        Paste reviews per source. The search buttons open Google in a new
        tab scoped to that source — copy the blurbs back here.
      </p>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <ReviewSourcePane
          pifId={pifId}
          firmName={firmName}
          source="google"
          label="Google Reviews"
          searchQuery={googleQuery}
          serverValue={data?.google ?? ""}
          isLoading={isLoading}
          placeholder={"Google — 4.8 ★ (312 reviews)\n\n★★★★★ Jane D. — Aug 2024\n\"They were great on my auto-accident case…\""}
        />
        <ReviewSourcePane
          pifId={pifId}
          firmName={firmName}
          source="yelp"
          label="Yelp Reviews"
          searchQuery={yelpQuery}
          serverValue={data?.yelp ?? ""}
          isLoading={isLoading}
          placeholder={"Yelp — 4.5 ★ (87 reviews)\n\n★★★★★ Mark T. — 2/2025\n\"Responsive and honest. Explained every step…\""}
        />
      </div>
    </section>
  );
}


function ReviewSourcePane({
  pifId,
  source,
  label,
  searchQuery,
  serverValue,
  isLoading,
  placeholder,
}: {
  pifId: string;
  firmName: string;
  source: "google" | "yelp";
  label: string;
  searchQuery: string;
  serverValue: string;
  isLoading: boolean;
  placeholder: string;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const [synced, setSynced] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // First non-loading sync: seed the textarea with whatever the server
  // has. Afterwards, remote pushes that don't match the last-sync we
  // saw are treated as a reconciliation (e.g. another tab saved).
  useEffect(() => {
    if (isLoading) return;
    if (synced === null) {
      setDraft(serverValue);
      setSynced(serverValue);
      return;
    }
    if (serverValue !== synced && draft === synced) {
      setDraft(serverValue);
      setSynced(serverValue);
    }
  }, [serverValue, isLoading, synced, draft]);

  const dirty = synced !== null && draft !== synced;

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const patch = source === "google" ? { google: draft } : { yelp: draft };
      const res = await putFirmReviews(pifId, patch);
      const next = source === "google" ? res.google : res.yelp;
      setDraft(next);
      setSynced(next);
      qc.setQueryData(["firm-reviews", pifId], res);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  };

  const openSearch = () => {
    const url = `https://www.google.com/search?q=${encodeURIComponent(searchQuery)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50/40 p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-600">
            {label}
          </div>
          <div
            className="mt-0.5 truncate font-mono text-[10px] text-neutral-400"
            title={searchQuery}
          >
            q: {searchQuery}
          </div>
        </div>
        <button
          type="button"
          onClick={openSearch}
          title={`Open Google search: ${searchQuery}`}
          className="shrink-0 inline-flex items-center gap-1 rounded border border-neutral-300 bg-white px-2 py-1 text-[10px] font-medium text-neutral-700 hover:bg-neutral-100"
        >
          <Search className="h-3 w-3" />
          Search {source === "google" ? "Google" : "Yelp"}
        </button>
      </div>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={placeholder}
        rows={9}
        disabled={isLoading}
        className="mt-2 w-full resize-y rounded-md border border-neutral-300 bg-white px-3 py-2 font-mono text-xs text-neutral-800 focus:border-neutral-400 focus:outline-none"
      />
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px] text-neutral-400">
          {draft.length.toLocaleString()} chars
          {dirty && <span className="ml-2 text-amber-600">unsaved</span>}
        </span>
        <div className="flex items-center gap-2">
          {saveError && (
            <span className="text-[10px] text-rose-600">{saveError}</span>
          )}
          <button
            type="button"
            onClick={save}
            disabled={saving || !dirty}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition",
              dirty && !saving
                ? "bg-neutral-900 text-white hover:bg-neutral-700"
                : "bg-neutral-100 text-neutral-400",
            )}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
