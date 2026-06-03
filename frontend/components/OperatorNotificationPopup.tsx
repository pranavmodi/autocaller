"use client";

/**
 * Global persisted operator notifications.
 *
 * Polls durable notification rows and exposes a non-blocking pointer into the
 * action index. Execution stays in the workflow-specific pages.
 */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  BellRing,
  Inbox,
  PanelRightOpen,
  X,
} from "lucide-react";
import {
  getPendingOperatorNotifications,
} from "@/lib/api";

const POPUP_PENDING_LIMIT = 10;
const notificationQueryKey = ["operator-notifications-pending", POPUP_PENDING_LIMIT] as const;

export function OperatorNotificationPopup() {
  const pending = useQuery({
    queryKey: notificationQueryKey,
    queryFn: () => getPendingOperatorNotifications(POPUP_PENDING_LIMIT),
    refetchInterval: 5_000,
    refetchIntervalInBackground: true,
  });

  const queue = pending.data?.pending ?? [];
  const [dismissedToastId, setDismissedToastId] = useState<number | null>(null);

  const latest = queue[0];
  const showToast = Boolean(latest && dismissedToastId !== latest.id);

  const lastChimedId = useRef<number | null>(null);
  useEffect(() => {
    if (!latest) return;
    if (lastChimedId.current === latest.id) return;
    lastChimedId.current = latest.id;
    setDismissedToastId(null);
    try {
      const Ctx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new Ctx();
      const beep = (freq: number, startOffset: number, dur: number) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = "triangle";
        o.frequency.value = freq;
        o.connect(g);
        g.connect(ctx.destination);
        const t0 = ctx.currentTime + startOffset;
        g.gain.setValueAtTime(0, t0);
        g.gain.linearRampToValueAtTime(0.22, t0 + 0.02);
        g.gain.linearRampToValueAtTime(0, t0 + dur);
        o.start(t0);
        o.stop(t0 + dur + 0.02);
      };
      beep(740, 0, 0.13);
      beep(988, 0.16, 0.18);
    } catch {
      // AudioContext may be blocked before user gesture.
    }
  }, [latest]);

  if (queue.length === 0 || !latest) return null;

  return (
    <>
      {showToast && (
        <div className="fixed bottom-24 right-6 z-[980] hidden w-[calc(100vw_-_2rem)] max-w-sm rounded-lg border border-neutral-200 bg-white shadow-xl md:block">
          <div className="flex items-start gap-3 p-4">
            <span className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700">
              <BellRing className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="line-clamp-2 text-sm font-semibold text-neutral-900">
                {latest.title}
              </div>
              <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-neutral-600">
                {latest.body}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Link
                  href={`/actions?notification=${latest.id}`}
                  onClick={() => setDismissedToastId(latest.id)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-neutral-800"
                >
                  <PanelRightOpen className="h-3.5 w-3.5" />
                  Review
                </Link>
                <button
                  type="button"
                  onClick={() => setDismissedToastId(latest.id)}
                  className="rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 transition hover:bg-neutral-50"
                >
                  Later
                </button>
              </div>
            </div>
            <button
              type="button"
              aria-label="Dismiss notification toast"
              onClick={() => setDismissedToastId(latest.id)}
              className="rounded-md p-1 text-neutral-500 transition hover:bg-neutral-100 hover:text-neutral-900"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      <Link
        href="/actions"
        onClick={() => setDismissedToastId(latest.id)}
        className="fixed bottom-[calc(5.5rem_+_env(safe-area-inset-bottom))] right-3 z-[970] inline-flex h-12 items-center gap-2 rounded-full border border-neutral-200 bg-white px-4 text-sm font-semibold text-neutral-900 shadow-xl transition hover:bg-neutral-50 md:bottom-6 md:right-6"
        aria-label="Open operator action center"
      >
        <span className="relative rounded-full bg-neutral-900 p-2 text-white">
          <Inbox className="h-4 w-4" />
          <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-amber-500 px-1 text-center text-[10px] font-bold leading-5 text-white">
            {queue.length}
          </span>
        </span>
        Actions
      </Link>
    </>
  );
}
