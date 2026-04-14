"use client";

import { useDashboardEvents } from "@/hooks/useDashboardEvents";
import { cn } from "@/lib/utils";

export function ConnectionBadge() {
  const { connected } = useDashboardEvents();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium",
        connected
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-neutral-200 bg-neutral-50 text-neutral-500",
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          connected ? "bg-emerald-500" : "bg-neutral-400",
        )}
      />
      {connected ? "live" : "offline"}
    </span>
  );
}
