"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Filter } from "lucide-react";
import {
  listCommunications,
  type CommsItem,
  type CommsListParams,
} from "@/lib/api";
import { CommsTable } from "@/components/CommsTable";
import { cn } from "@/lib/utils";

const CHANNELS: Array<{ key: CommsItem["channel"] | "all"; label: string }> = [
  { key: "all", label: "All channels" },
  { key: "call", label: "Calls" },
  { key: "voicemail", label: "Voicemail" },
  { key: "sms", label: "SMS" },
  { key: "email", label: "Email" },
];

const RANGES: Array<{ key: string; label: string }> = [
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "", label: "All" },
];

export default function CommsPage() {
  const [channel, setChannel] = useState<CommsItem["channel"] | "all">("all");
  const [since, setSince] = useState<string>("7d");
  const [q, setQ] = useState<string>("");
  const [limit, setLimit] = useState<number>(100);

  const params: CommsListParams = {
    limit,
    ...(channel !== "all" ? { channel } : {}),
    ...(since ? { since } : {}),
    ...(q ? { q } : {}),
  };

  const comms = useQuery({
    queryKey: ["comms-feed", params],
    queryFn: () => listCommunications(params),
    refetchInterval: 30_000,
  });

  const items = comms.data?.items ?? [];

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-8">
      <div className="mb-6 flex items-center gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-800"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <span className="text-neutral-300">/</span>
        <h1 className="text-lg font-semibold text-neutral-900">
          Communications
        </h1>
        <span className="text-xs text-neutral-400">
          outbound · calls · voicemail · sms · email
        </span>
      </div>

      <section className="mb-4 rounded-xl border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5 text-neutral-400" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
              Filter
            </span>
          </div>

          <div className="flex gap-1">
            {CHANNELS.map((c) => (
              <button
                key={c.key}
                onClick={() => setChannel(c.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  channel === c.key
                    ? "bg-neutral-900 text-white"
                    : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200",
                )}
              >
                {c.label}
              </button>
            ))}
          </div>

          <div className="ml-2 flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setSince(r.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  since === r.key
                    ? "bg-neutral-900 text-white"
                    : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>

          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search firm, contact, recipient, summary…"
            className="ml-2 w-72 rounded-md border border-neutral-200 px-2.5 py-1 text-xs text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-400 focus:outline-none"
          />

          <span className="ml-auto text-[11px] text-neutral-400">
            {comms.isLoading
              ? "loading…"
              : `${items.length} of last ${limit}`}
          </span>
        </div>
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        {items.length === 0 && !comms.isLoading && (
          <div className="px-5 py-10 text-center text-sm text-neutral-400">
            No communications match the current filters.
          </div>
        )}
        {items.length > 0 && (
          <div className="px-3 py-2">
            <CommsTable items={items} />
          </div>
        )}
        {items.length === limit && (
          <div className="border-t border-neutral-100 px-5 py-2 text-right">
            <button
              onClick={() => setLimit(limit + 100)}
              className="text-[11px] font-medium text-neutral-500 hover:text-neutral-800"
            >
              Load 100 more →
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
