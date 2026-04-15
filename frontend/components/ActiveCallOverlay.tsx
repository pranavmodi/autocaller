"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Headphones,
  HeadphoneOff,
  PhoneOff,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useDashboardEvents } from "@/hooks/useDashboardEvents";
import { useLiveListener } from "@/hooks/useLiveListener";
import { clearActiveCall } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { TranscriptStream } from "@/components/TranscriptStream";

const LS_OPEN_KEY = "autocaller_active_call_overlay_expanded";

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
  const [expanded, setExpanded] = useState<boolean>(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(LS_OPEN_KEY);
    if (saved === "true") setExpanded(true);
    if (saved === "false") setExpanded(false);
  }, []);

  // Auto-expand the first time a call appears after being idle.
  const [hasAutoExpanded, setHasAutoExpanded] = useState<boolean>(false);
  useEffect(() => {
    if (!activeCall) {
      setHasAutoExpanded(false);
      return;
    }
    if (activeCall && !hasAutoExpanded) {
      setHasAutoExpanded(true);
      if (typeof window !== "undefined") {
        const saved = window.localStorage.getItem(LS_OPEN_KEY);
        // If the user hasn't explicitly chosen, expand by default.
        if (saved !== "false") setExpanded(true);
      } else {
        setExpanded(true);
      }
    }
  }, [activeCall, hasAutoExpanded]);

  const toggleExpanded = () => {
    const next = !expanded;
    setExpanded(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LS_OPEN_KEY, next ? "true" : "false");
    }
  };

  const hangup = useMutation({
    mutationFn: clearActiveCall,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["active-call"] }),
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

      {/* Transcript */}
      <div className="p-3">
        <TranscriptStream entries={transcript} maxHeight={260} />
      </div>
    </div>
  );
}
