"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ListChecks, Voicemail, CheckCircle2, Circle } from "lucide-react";

import {
  getVoicemailRecipients,
  type VoicemailRecipient,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Call lists — named cohorts the operator may want to re-dial.
 *
 * Part 1 of the VM-blast feature. This page surfaces the leads whose
 * last call went to voicemail. A future follow-up wires a dispatcher
 * "VM-only" batch mode that runs through the list, dials each lead,
 * delivers the v1.55 VM script when AMD classifies the pickup as a
 * machine, and hangs up quickly on humans.
 */
export default function CallListsPage() {
  const vm = useQuery({
    queryKey: ["call-lists", "voicemail"],
    queryFn: getVoicemailRecipients,
    refetchInterval: 60_000,
  });

  const { unblasted, blasted } = useMemo(() => {
    const rows = vm.data?.rows ?? [];
    return {
      unblasted: rows.filter((r) => !r.voicemail_left),
      blasted: rows.filter((r) => r.voicemail_left),
    };
  }, [vm.data]);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <h1 className="text-xl font-semibold">Call lists</h1>
        {vm.data && (
          <span className="text-xs text-neutral-500">
            {vm.data.count} voicemail recipients ·{" "}
            {unblasted.length} awaiting VM · {blasted.length} already messaged
          </span>
        )}
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex items-start gap-3">
          <ListChecks className="mt-0.5 h-5 w-5 text-neutral-400" />
          <div>
            <p className="text-sm text-neutral-700">
              <span className="font-medium">About this view.</span> Leads
              whose last call went to voicemail — candidates for a
              VM-only redial. &ldquo;Awaiting VM&rdquo; means we never
              delivered our Precise-anchored script on the last attempt;
              these are the priority to redial. &ldquo;Already messaged&rdquo;
              is for reference — don&apos;t call them again without cause.
            </p>
          </div>
        </div>
      </div>

      {vm.isLoading && (
        <p className="text-sm text-neutral-500">Loading…</p>
      )}
      {vm.isError && (
        <p className="text-sm text-rose-700">
          Couldn&apos;t load voicemail recipients: {(vm.error as Error).message}
        </p>
      )}

      <VMListSection
        title="Awaiting VM"
        subtitle="Next up for a VM-only redial."
        icon={<Circle className="h-4 w-4 text-amber-500" />}
        rows={unblasted}
        variant="unblasted"
      />
      <VMListSection
        title="Already messaged"
        subtitle="We delivered a voicemail to these. Don't double-dial without cause."
        icon={<CheckCircle2 className="h-4 w-4 text-emerald-500" />}
        rows={blasted}
        variant="blasted"
      />
    </div>
  );
}

function VMListSection({
  title,
  subtitle,
  icon,
  rows,
  variant,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  rows: VoicemailRecipient[];
  variant: "unblasted" | "blasted";
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-neutral-500">
            {icon}
            {title}
            <span className="text-neutral-400">({rows.length})</span>
          </h2>
          <p className="mt-0.5 text-xs text-neutral-500">{subtitle}</p>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-neutral-300 bg-white p-8 text-center">
          <Voicemail className="mx-auto h-6 w-6 text-neutral-400" />
          <p className="mt-2 text-sm text-neutral-600">None.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-xs uppercase text-neutral-500">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Lead</th>
                <th className="px-4 py-2 text-left font-medium">Firm</th>
                <th className="px-4 py-2 text-left font-medium">Phone</th>
                <th className="px-4 py-2 text-left font-medium">Last call</th>
                <th className="px-4 py-2 text-left font-medium">Prompt</th>
                <th className="px-4 py-2 text-right font-medium">—</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.call_id}
                  className={cn(
                    "border-t border-neutral-100",
                    variant === "unblasted" ? "bg-white" : "bg-neutral-50/50",
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-neutral-900">
                      {r.patient_name}
                    </div>
                    {r.lead_state && (
                      <div className="mt-0.5 text-xs text-neutral-500">
                        {r.lead_state}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-neutral-700">
                    {r.firm_name || "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-neutral-700">
                    {r.phone}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-neutral-600">
                    {r.started_at
                      ? formatDistanceToNow(new Date(r.started_at), {
                          addSuffix: true,
                        })
                      : "—"}
                    {r.duration_seconds ? (
                      <span className="ml-1 text-neutral-400">
                        · {r.duration_seconds}s
                      </span>
                    ) : null}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-neutral-500">
                    {r.prompt_version || "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    <Link
                      href={`/calls/${r.call_id}`}
                      className="text-xs text-neutral-600 hover:underline"
                    >
                      view →
                    </Link>
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
