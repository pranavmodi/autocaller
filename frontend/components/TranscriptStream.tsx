"use client";

import { useEffect, useMemo, useRef } from "react";
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

  const coalesced = useMemo(() => {
    const result: { speaker: string; text: string }[] = [];
    for (const e of entries) {
      const prev = result[result.length - 1];
      if (prev && prev.speaker === e.speaker && e.speaker !== "system") {
        prev.text += e.text;
      } else {
        result.push({ speaker: e.speaker, text: e.text });
      }
    }
    return result;
  }, [entries]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [coalesced.length]);

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
      className="space-y-2.5 overflow-y-auto rounded-md bg-neutral-50 p-3 text-sm"
      style={{ maxHeight }}
    >
      {coalesced.map((e, i) => {
        const isAi = e.speaker === "ai";
        const isPatient = e.speaker === "patient";
        const isSystem = e.speaker === "system";
        return (
          <div
            key={i}
            className={cn(
              "flex flex-col gap-0.5",
              isAi ? "items-start" : isPatient ? "items-end" : "items-center",
            )}
          >
            <span className="text-[9px] font-medium uppercase tracking-wider text-neutral-400">
              {isAi ? "Alex (AI)" : isPatient ? "Caller" : ""}
            </span>
            <div
              className={cn(
                "max-w-[80%] rounded-lg px-3 py-1.5 text-sm leading-relaxed",
                isAi && "bg-white text-neutral-800 ring-1 ring-neutral-200",
                isPatient && "bg-emerald-600 text-white",
                isSystem &&
                  "border border-dashed border-amber-300 bg-amber-50 px-2 py-1 text-[11px] text-amber-900",
              )}
            >
              {isSystem ? (
                <>
                  <span className="mr-1 font-semibold uppercase text-[10px] tracking-wide">system</span>
                  <span className="font-normal">{e.text}</span>
                </>
              ) : (
                e.text.trim()
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
