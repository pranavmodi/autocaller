"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { TranscriptEntry } from "@/types";

export function TranscriptStream({
  entries,
  maxHeight = 280,
}: {
  entries: TranscriptEntry[];
  maxHeight?: number;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [entries.length]);

  if (!entries.length) {
    return (
      <div className="rounded-md bg-neutral-50 px-3 py-4 text-center text-xs text-neutral-400">
        Waiting for conversation…
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="space-y-1.5 overflow-y-auto rounded-md bg-neutral-50 p-3 text-sm"
      style={{ maxHeight }}
    >
      {entries.map((e, i) => (
        <div
          key={i}
          className={cn(
            "flex",
            e.speaker === "ai" ? "justify-start" : e.speaker === "patient" ? "justify-end" : "justify-center",
          )}
        >
          <div
            className={cn(
              "max-w-[80%] rounded-lg px-3 py-1.5 text-sm",
              e.speaker === "ai" && "bg-white text-neutral-800 ring-1 ring-neutral-200",
              e.speaker === "patient" && "bg-emerald-600 text-white",
              e.speaker === "system" && "bg-neutral-200 text-neutral-600 text-[11px]",
            )}
          >
            {e.text}
          </div>
        </div>
      ))}
    </div>
  );
}
