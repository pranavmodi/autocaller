"use client";

/**
 * Global one-shot popup for new consult bookings.
 *
 * Polls /api/consults/pending every 5s. If any booking has not yet been
 * acknowledged, shows it as a modal the operator must click through.
 * On click, POSTs /api/consults/{id}/acknowledge which sets
 * `acknowledged_at` server-side — so the popup never fires again for
 * that booking, even after a daemon restart or a different browser.
 *
 * One popup per booking, ever.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getPendingBookings,
  acknowledgeBooking,
  type PendingBooking,
} from "@/lib/api";

export function ConsultBookingPopup() {
  const qc = useQueryClient();
  const pending = useQuery({
    queryKey: ["consult-pending"],
    queryFn: getPendingBookings,
    refetchInterval: 5_000,
    // Cheap enough to keep running in background tabs too.
    refetchIntervalInBackground: true,
  });

  const ack = useMutation({
    mutationFn: (id: number) => acknowledgeBooking(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["consult-pending"] }),
  });

  const queue = pending.data?.pending ?? [];
  const current: PendingBooking | undefined = queue[0];

  // Chime on the leading edge of a new booking surfacing. Tracks the
  // ID we've already chimed for so re-renders don't re-chime.
  const lastChimedId = useRef<number | null>(null);
  useEffect(() => {
    if (!current) return;
    if (lastChimedId.current === current.id) return;
    lastChimedId.current = current.id;
    try {
      // Three-beat tone via Web Audio — no external asset needed.
      const Ctx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new Ctx();
      const beep = (freq: number, startOffset: number, dur: number) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.type = "sine";
        o.frequency.value = freq;
        o.connect(g);
        g.connect(ctx.destination);
        const t0 = ctx.currentTime + startOffset;
        g.gain.setValueAtTime(0, t0);
        g.gain.linearRampToValueAtTime(0.3, t0 + 0.02);
        g.gain.linearRampToValueAtTime(0, t0 + dur);
        o.start(t0);
        o.stop(t0 + dur + 0.02);
      };
      beep(880, 0, 0.15);
      beep(1175, 0.18, 0.15);
      beep(1480, 0.36, 0.22);
    } catch {
      // AudioContext unavailable / user gesture missing — silent is fine.
    }
  }, [current]);

  if (!current) return null;

  const slotLocal = new Date(current.slot_start).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  const remaining = queue.length - 1;

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="consult-popup-title"
    >
      <div className="w-full max-w-md rounded-xl border border-emerald-300 bg-white shadow-2xl">
        <div className="rounded-t-xl bg-emerald-600 px-5 py-3 text-white">
          <div className="flex items-center justify-between">
            <h2 id="consult-popup-title" className="text-sm font-semibold uppercase tracking-wide">
              New consult booking
            </h2>
            {remaining > 0 && (
              <span className="rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-medium">
                +{remaining} more
              </span>
            )}
          </div>
        </div>
        <div className="space-y-3 px-5 py-4 text-sm">
          <div>
            <div className="text-lg font-semibold text-neutral-900">
              {current.name}
            </div>
            {current.firm_name && (
              <div className="text-sm text-neutral-600">{current.firm_name}</div>
            )}
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
            <dt className="text-neutral-500">Slot</dt>
            <dd className="font-medium text-neutral-900">{slotLocal}</dd>
            <dt className="text-neutral-500">Email</dt>
            <dd className="break-all font-mono text-neutral-800">{current.email}</dd>
            {current.phone && (
              <>
                <dt className="text-neutral-500">Phone</dt>
                <dd className="font-mono text-neutral-800">{current.phone}</dd>
              </>
            )}
            {current.notes && (
              <>
                <dt className="text-neutral-500">Notes</dt>
                <dd className="whitespace-pre-wrap text-neutral-800">{current.notes}</dd>
              </>
            )}
          </dl>
        </div>
        <div className="flex justify-end gap-2 rounded-b-xl border-t border-neutral-200 bg-neutral-50 px-5 py-3">
          <button
            type="button"
            onClick={() => ack.mutate(current.id)}
            disabled={ack.isPending}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow transition hover:bg-emerald-700 disabled:opacity-60"
          >
            {ack.isPending ? "Acknowledging…" : "Acknowledge"}
          </button>
        </div>
      </div>
    </div>
  );
}
