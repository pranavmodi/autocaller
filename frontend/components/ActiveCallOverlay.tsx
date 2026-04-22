"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Grid3x3,
  Headphones,
  HeadphoneOff,
  Mic,
  MicOff,
  PhoneOff,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDashboardEvents } from "@/hooks/useDashboardEvents";
import { useLiveListener } from "@/hooks/useLiveListener";
import { clearActiveCall, sendDtmf, setManualIvr } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { TranscriptStream } from "@/components/TranscriptStream";

// Note: expanded/collapsed is per-call state (keyed by call_id in the
// effect below), not persisted to localStorage. Each new call re-opens
// the modal so you can never miss one due to stale UI prefs.

/**
 * Floating overlay that shows the live call on every page.
 *
 * - Hidden while there's no active call.
 * - When a call is active, appears bottom-right. Two modes:
 *   minimized (a pill with lead name + status + expand button) and
 *   expanded (full transcript + listen + end-call controls).
 * - Expanded/minimized preference persists in localStorage.
 * - The underlying WS (useDashboardEvents) is a shared singleton so
 *   mounting this in root layout doesn't double-connect.
 */
export function ActiveCallOverlay() {
  const qc = useQueryClient();
  const { activeCall, lastStatus, transcript } = useDashboardEvents();
  const listener = useLiveListener(activeCall?.call_id ?? null);

  // Remember whether the user wants the overlay expanded or collapsed.
  // Expanded/collapsed is per-call, not session-global. Each new call_id
  // resets the modal to expanded; the user's minimize only sticks within
  // that same call. This prevents the failure mode where you minimized
  // call 1 and then call 2 silently opens as a collapsed pill (or worse,
  // doesn't render at all if the pill itself stalls).
  const [expanded, setExpanded] = useState<boolean>(true);
  const [autoExpandedFor, setAutoExpandedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!activeCall) {
      // Call ended — reset so the next call auto-expands cleanly.
      setAutoExpandedFor(null);
      return;
    }
    if (autoExpandedFor !== activeCall.call_id) {
      // New call (or first call after a gap). Force expanded view and
      // remember which call_id we auto-expanded for.
      setExpanded(true);
      setAutoExpandedFor(activeCall.call_id);
    }
  }, [activeCall, autoExpandedFor]);

  const toggleExpanded = () => {
    setExpanded((v) => !v);
  };

  const hangup = useMutation({
    mutationFn: clearActiveCall,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["active-call"] }),
  });

  // Manual IVR: operator drives the phone tree, AI stays muted.
  const [manualIvrOn, setManualIvrOn] = useState(false);
  const [ivrError, setIvrError] = useState<string | null>(null);
  // Reset when the call changes so the next call starts in auto mode.
  useEffect(() => {
    setManualIvrOn(false);
    setIvrError(null);
  }, [activeCall?.call_id]);

  const toggleIvr = useMutation({
    mutationFn: (enabled: boolean) =>
      setManualIvr(activeCall!.call_id, enabled),
    onSuccess: (res, enabled) => {
      setManualIvrOn(enabled);
      setIvrError(null);
    },
    onError: (err: unknown) => {
      setIvrError(err instanceof Error ? err.message : String(err));
    },
  });

  const dtmf = useMutation({
    mutationFn: (digit: string) => sendDtmf(activeCall!.call_id, digit),
    onError: (err: unknown) => {
      setIvrError(err instanceof Error ? err.message : String(err));
    },
  });

  if (!activeCall) {
    // No live call — also show the "auto-listen waiting" pill if the user
    // opted in. Otherwise render nothing.
    if (!listener.autoReconnect) return null;
    return (
      <div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm shadow-lg">
        <Headphones className="h-4 w-4 text-amber-800" />
        <span className="text-amber-900">
          Auto-listen is on — waiting for next call…
          {listener.error && (
            <span className="ml-2 text-xs text-rose-700">({listener.error})</span>
          )}
        </span>
        <button
          onClick={listener.stop}
          className="text-xs font-medium text-neutral-600 underline-offset-2 hover:underline"
        >
          turn off
        </button>
      </div>
    );
  }

  const leadLabel = activeCall.patient_name || activeCall.phone || "Active call";
  const firmLabel = activeCall.firm_name ? ` · ${activeCall.firm_name}` : "";
  const stateLabel = activeCall.lead_state ? ` · ${activeCall.lead_state}` : "";

  // -- Minimized pill --
  if (!expanded) {
    return (
      <button
        onClick={toggleExpanded}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-full border border-emerald-200 bg-white px-4 py-2 text-sm shadow-lg transition hover:bg-emerald-50"
      >
        <span className="flex h-2.5 w-2.5 items-center justify-center">
          <span className="absolute h-2.5 w-2.5 animate-ping rounded-full bg-emerald-500 opacity-75" />
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
        </span>
        <span className="font-medium text-emerald-900">{leadLabel}</span>
        <span className="hidden text-xs text-neutral-500 sm:inline">
          {firmLabel.replace(/^ · /, "")}
        </span>
        <ChevronUp className="h-4 w-4 text-neutral-500" />
      </button>
    );
  }

  // -- Expanded panel --
  return (
    <div className="fixed bottom-4 right-4 z-50 w-[min(420px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-emerald-200 bg-white shadow-2xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 border-b border-emerald-100 bg-emerald-50 p-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-emerald-700">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
            Active call
          </div>
          <div className="mt-0.5 truncate text-sm font-semibold text-neutral-900">
            <Link
              href={`/calls/${activeCall.call_id}`}
              className="hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {leadLabel}
            </Link>
            <span className="text-neutral-500">
              {firmLabel}
              {stateLabel}
            </span>
          </div>
          <div className="mt-0.5 truncate text-[11px] text-neutral-500">
            {activeCall.phone}
            {lastStatus ? ` · ${lastStatus}` : ""}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={toggleExpanded}
            title="Minimize"
            className="rounded p-1 text-neutral-500 hover:bg-neutral-100"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 p-3">
        {listener.autoReconnect ? (
          <Button
            size="sm"
            variant="outline"
            onClick={listener.stop}
            className="gap-1.5"
          >
            <HeadphoneOff className="h-3.5 w-3.5" />
            {listener.listening
              ? "Stop listening"
              : listener.connecting
                ? "Connecting…"
                : "Stop auto-listen"}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={listener.start}
            disabled={listener.connecting}
            className="gap-1.5"
          >
            <Headphones className="h-3.5 w-3.5" />
            {listener.connecting ? "Connecting…" : "Listen"}
          </Button>
        )}
        {listener.takeover ? (
          <Button
            size="sm"
            variant="outline"
            onClick={listener.stopTakeover}
            disabled={listener.takeoverPending}
            className="gap-1.5 border-rose-300 bg-rose-50 text-rose-800 hover:bg-rose-100"
            title="Release: unmute AI, close mic"
          >
            <MicOff className="h-3.5 w-3.5" />
            Hand back
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={listener.startTakeover}
            disabled={!listener.listening || listener.takeoverPending}
            className="gap-1.5"
            title={
              listener.listening
                ? "Mute AI and speak into this call from your browser mic"
                : "Start listening first"
            }
          >
            <Mic className="h-3.5 w-3.5" />
            {listener.takeoverPending ? "…" : "Take over"}
          </Button>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={() => toggleIvr.mutate(!manualIvrOn)}
          disabled={toggleIvr.isPending}
          className={cn(
            "gap-1.5",
            manualIvrOn && "border-amber-400 bg-amber-50 text-amber-900 hover:bg-amber-100",
          )}
          title={
            manualIvrOn
              ? "Turn off manual IVR — AI resumes on next caller turn"
              : "Mute AI and drive the phone tree yourself — digits will send DTMF"
          }
        >
          <Grid3x3 className="h-3.5 w-3.5" />
          {manualIvrOn ? "Exit IVR" : "IVR"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => hangup.mutate()}
          disabled={hangup.isPending}
          className="gap-1.5 text-rose-700"
          title="Hang up the live Twilio call"
        >
          <PhoneOff className="h-3.5 w-3.5" />
          End
        </Button>
        <Link
          href={`/calls/${activeCall.call_id}`}
          className="ml-auto text-xs text-neutral-500 hover:underline"
        >
          open detail →
        </Link>
      </div>
      {listener.error && (
        <div className="border-b border-rose-100 bg-rose-50 px-3 py-1.5 text-xs text-rose-700">
          ⚠ {listener.error}
        </div>
      )}

      {manualIvrOn && (
        <div className="border-b border-amber-200 bg-amber-50/60 p-3">
          <div className="mb-2 flex items-start justify-between gap-2 text-[11px] text-amber-900">
            <span>
              <strong className="font-semibold">Manual IVR active.</strong>{" "}
              AI is muted. Press a key to send DTMF. Click &ldquo;Exit IVR&rdquo;
              when a human is on the line.
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {["1","2","3","4","5","6","7","8","9","*","0","#"].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => dtmf.mutate(d)}
                disabled={dtmf.isPending}
                className={cn(
                  "rounded-md border border-amber-300 bg-white py-2 text-sm font-semibold text-amber-900 transition",
                  "hover:bg-amber-100 active:bg-amber-200",
                  dtmf.isPending && "cursor-wait opacity-50",
                )}
                title={`Send DTMF ${d}`}
              >
                {d}
              </button>
            ))}
          </div>
          {ivrError && (
            <p className="mt-2 text-[11px] text-rose-700">⚠ {ivrError}</p>
          )}
        </div>
      )}
      {!manualIvrOn && ivrError && (
        <div className="border-b border-rose-100 bg-rose-50 px-3 py-1.5 text-xs text-rose-700">
          ⚠ {ivrError}
        </div>
      )}

      {/* Transcript */}
      <div className="p-3">
        <TranscriptStream entries={transcript} maxHeight={260} />
      </div>
    </div>
  );
}
