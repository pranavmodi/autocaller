import { cn } from "@/lib/utils";
import type { CallOutcome } from "@/types";

const STYLES: Record<CallOutcome, { label: string; className: string }> = {
  in_progress: { label: "in progress", className: "bg-blue-50 text-blue-700 ring-blue-200" },
  demo_scheduled: { label: "demo scheduled", className: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  callback_requested: { label: "callback", className: "bg-amber-50 text-amber-700 ring-amber-200" },
  not_interested: { label: "not interested", className: "bg-neutral-100 text-neutral-600 ring-neutral-200" },
  gatekeeper_only: { label: "gatekeeper", className: "bg-violet-50 text-violet-700 ring-violet-200" },
  voicemail: { label: "voicemail", className: "bg-slate-50 text-slate-600 ring-slate-200" },
  no_answer: { label: "no answer", className: "bg-slate-50 text-slate-600 ring-slate-200" },
  wrong_number: { label: "wrong number", className: "bg-rose-50 text-rose-700 ring-rose-200" },
  disconnected: { label: "disconnected", className: "bg-rose-50 text-rose-700 ring-rose-200" },
  failed: { label: "failed", className: "bg-red-50 text-red-700 ring-red-200" },
  completed: { label: "completed", className: "bg-neutral-100 text-neutral-700 ring-neutral-200" },
  transferred: { label: "transferred", className: "bg-neutral-100 text-neutral-700 ring-neutral-200" },
};

export function OutcomePill({ outcome }: { outcome: CallOutcome }) {
  const s = STYLES[outcome] ?? STYLES.completed;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        s.className,
      )}
    >
      {s.label}
    </span>
  );
}
