"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSettings,
  setPromptStyle,
  type PromptStyle,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Settings = {
  prompt_style?: PromptStyle | string;
  prompt_version?: string;
};

const OPTIONS: { value: PromptStyle; label: string; hint: string }[] = [
  {
    value: "current",
    label: "Current",
    hint: "Long Sobczak-style prompt — full opener, gatekeeper, discovery, closing scripts.",
  },
  {
    value: "minimal",
    label: "Minimal",
    hint: "Trimmed prompt — same intent, less verbiage. Use to A/B against current.",
  },
];

/**
 * Panel for switching the active voice-AI prompt style.
 *
 * DB-backed (`system_settings.prompt_style`); the change takes effect
 * on the next call (~5s cache invalidation). No daemon restart needed.
 * Per CLAUDE.md, prompt edits to the underlying file still require
 * version bump + commit + push + restart — this panel only flips the
 * selector between two committed styles.
 */
export function PromptStylePanel() {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => getSettings() as Promise<Settings>,
    refetchInterval: 30_000,
  });

  const active = (settings.data?.prompt_style as PromptStyle) || "current";
  const version = settings.data?.prompt_version || "";

  const switchStyle = useMutation({
    mutationFn: (s: PromptStyle) => setPromptStyle(s),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Prompt style
        </h2>
        {settings.data && (
          <span className="text-xs text-neutral-500">
            active: <span className="font-mono">{active}</span>
            {version && (
              <>
                <span className="mx-2 text-neutral-300">·</span>
                <span className="font-mono text-neutral-400">{version}</span>
              </>
            )}
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {OPTIONS.map((opt) => {
          const selected = active === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => switchStyle.mutate(opt.value)}
              disabled={switchStyle.isPending || selected}
              className={cn(
                "flex flex-col items-start gap-1 rounded-md border p-4 text-left transition",
                selected
                  ? "border-emerald-400 bg-emerald-50"
                  : "border-neutral-200 bg-white hover:border-neutral-300 hover:bg-neutral-50",
                switchStyle.isPending && "opacity-60",
              )}
            >
              <div className="flex w-full items-center justify-between">
                <span
                  className={cn(
                    "text-sm font-semibold",
                    selected ? "text-emerald-900" : "text-neutral-900",
                  )}
                >
                  {opt.label}
                </span>
                {selected && (
                  <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                    active
                  </span>
                )}
              </div>
              <span className="text-[11px] text-neutral-500">{opt.hint}</span>
            </button>
          );
        })}
      </div>

      {switchStyle.isError && (
        <p className="mt-3 text-xs text-rose-700">
          Switch failed: {(switchStyle.error as Error).message}
        </p>
      )}
      <p className="mt-3 text-[11px] text-neutral-500">
        Takes effect on the next call (~5s cache). Editing prompt text
        itself still requires the standard version-bump + commit + push +
        restart flow.
      </p>
    </section>
  );
}
