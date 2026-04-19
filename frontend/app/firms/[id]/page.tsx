"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getPifFirm, type PifFirm, type PifLeader } from "@/lib/pifstats";
import { cn } from "@/lib/utils";
import {
  ArrowLeft,
  Building2,
  Globe,
  Mail,
  Phone,
  MapPin,
  Users,
  BarChart3,
  Trophy,
  Clock,
  AlertTriangle,
  Linkedin,
  ExternalLink,
  Briefcase,
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
    </div>
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
