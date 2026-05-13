"use client";

import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import type { CommsItem } from "@/lib/api";

export function CommsTable({
  items,
  hideFirm = false,
}: {
  items: CommsItem[];
  hideFirm?: boolean;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b border-neutral-200 text-[11px] uppercase tracking-wider text-neutral-500">
          <tr>
            <th className="py-2 pr-3 text-left font-medium">When</th>
            <th className="py-2 pr-3 text-left font-medium">Channel</th>
            {!hideFirm && (
              <th className="py-2 pr-3 text-left font-medium">Firm</th>
            )}
            <th className="py-2 pr-3 text-left font-medium">Contact</th>
            <th className="py-2 pr-3 text-left font-medium">Recipient</th>
            <th className="py-2 pr-3 text-left font-medium">Summary</th>
            <th className="py-2 pr-0 text-left font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const open = openId === it.id;
            return (
              <Fragment key={it.id}>
                <tr
                  className={cn(
                    "cursor-pointer border-b border-neutral-100 hover:bg-neutral-50",
                    open && "bg-neutral-50",
                  )}
                  onClick={() => setOpenId(open ? null : it.id)}
                >
                  <td className="py-2 pr-3 font-mono text-[11px] text-neutral-500 whitespace-nowrap">
                    {formatCommsDate(it.occurred_at)}
                  </td>
                  <td className="py-2 pr-3">
                    <ChannelPill channel={it.channel} />
                  </td>
                  {!hideFirm && (
                    <td className="py-2 pr-3 max-w-[12rem] truncate text-neutral-700">
                      {it.firm_name ?? "—"}
                    </td>
                  )}
                  <td className="py-2 pr-3 max-w-[10rem] truncate text-neutral-700">
                    {it.contact_name ?? "—"}
                  </td>
                  <td className="py-2 pr-3 font-mono text-[11px] text-neutral-600">
                    {it.recipient ?? "—"}
                  </td>
                  <td className="py-2 pr-3 max-w-[24rem] truncate text-neutral-700">
                    {it.summary || "—"}
                  </td>
                  <td className="py-2 pr-0">
                    <StatusPill status={it.status} channel={it.channel} />
                  </td>
                </tr>
                {open && (
                  <tr className="border-b border-neutral-100 bg-neutral-50">
                    <td
                      colSpan={hideFirm ? 6 : 7}
                      className="px-3 py-3 text-xs text-neutral-700"
                    >
                      <div className="grid gap-2 sm:grid-cols-2">
                        <div>
                          <span className="text-neutral-400">id</span>{" "}
                          <span className="font-mono">{it.id}</span>
                        </div>
                        {it.message_type && (
                          <div>
                            <span className="text-neutral-400">type</span>{" "}
                            {it.message_type}
                          </div>
                        )}
                        {it.duration_seconds != null && (
                          <div>
                            <span className="text-neutral-400">duration</span>{" "}
                            {it.duration_seconds}s
                          </div>
                        )}
                        {it.call_id && (
                          <div>
                            <span className="text-neutral-400">call_id</span>{" "}
                            <span className="font-mono">{it.call_id}</span>
                          </div>
                        )}
                      </div>
                      {it.body_excerpt && (
                        <pre className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-neutral-200 bg-white p-3 text-[12px] text-neutral-700">
                          {it.body_excerpt}
                        </pre>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}


function ChannelPill({ channel }: { channel: CommsItem["channel"] }) {
  const map: Record<CommsItem["channel"], { label: string; bg: string; fg: string }> = {
    call: { label: "📞 call", bg: "bg-blue-100", fg: "text-blue-800" },
    voicemail: { label: "📼 voicemail", bg: "bg-amber-100", fg: "text-amber-800" },
    sms: { label: "💬 sms", bg: "bg-violet-100", fg: "text-violet-800" },
    email: { label: "📧 email", bg: "bg-emerald-100", fg: "text-emerald-800" },
  };
  const v = map[channel];
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[11px] font-medium",
        v.bg, v.fg,
      )}
    >
      {v.label}
    </span>
  );
}


function StatusPill({
  status,
  channel,
}: {
  status: string;
  channel: CommsItem["channel"];
}) {
  const s = (status ?? "").toLowerCase();
  let bg = "bg-neutral-100", fg = "text-neutral-700";
  if (s === "sent" || s === "completed" || s === "demo_scheduled") {
    bg = "bg-emerald-50"; fg = "text-emerald-700";
  } else if (s === "failed" || s === "no_answer" || s === "disconnected") {
    bg = "bg-red-50"; fg = "text-red-700";
  } else if (s === "in_progress" || s === "live") {
    bg = "bg-blue-50"; fg = "text-blue-700";
  }
  const label = status || (channel === "voicemail" ? "vm left" : "—");
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[11px] font-medium",
        bg, fg,
      )}
    >
      {label}
    </span>
  );
}


function formatCommsDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
