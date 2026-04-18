"use client";

import { useState } from "react";
import { useWebCall } from "@/hooks/useWebCall";
import { cn } from "@/lib/utils";
import { Phone, PhoneOff, Mic, MicOff, X } from "lucide-react";
import type { Lead } from "@/types";

export function WebCallModal({
  lead,
  onClose,
}: {
  lead: Lead;
  onClose: () => void;
}) {
  const { state, callId, error, start, stop } = useWebCall();
  const [muted, setMuted] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-neutral-100 px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-neutral-900">Web test call</h3>
            <p className="text-[11px] text-neutral-500">
              Speak to Alex through your browser — AI thinks it's a real call
            </p>
          </div>
          <button
            onClick={() => {
              stop();
              onClose();
            }}
            className="rounded-full p-1.5 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Lead info */}
        <div className="border-b border-neutral-100 px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-neutral-100 text-sm font-bold text-neutral-500">
              {lead.name.charAt(0)}
            </div>
            <div>
              <div className="text-sm font-medium text-neutral-900">{lead.name}</div>
              <div className="text-xs text-neutral-500">
                {lead.firm_name ?? "—"}
                {lead.state ? ` · ${lead.state}` : ""}
              </div>
            </div>
          </div>
        </div>

        {/* Call area */}
        <div className="px-6 py-8">
          {state === "idle" && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-emerald-50">
                <Phone className="h-8 w-8 text-emerald-600" />
              </div>
              <p className="text-sm text-neutral-600">
                Start a web call to test the AI conversation
              </p>
              <button
                onClick={() => start(lead.patient_id)}
                className="flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 transition-colors"
              >
                <Phone className="h-4 w-4" />
                Start call
              </button>
            </div>
          )}

          {state === "connecting" && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-amber-50">
                <div className="h-8 w-8 animate-spin rounded-full border-4 border-amber-200 border-t-amber-600" />
              </div>
              <p className="text-sm text-neutral-600">Connecting to AI...</p>
              <p className="text-[11px] text-neutral-400">
                Setting up voice backend + microphone
              </p>
            </div>
          )}

          {state === "active" && (
            <div className="flex flex-col items-center gap-6">
              {/* Pulse animation */}
              <div className="relative flex h-20 w-20 items-center justify-center">
                <div className="absolute inset-0 animate-ping rounded-full bg-emerald-100 opacity-30" />
                <div className="relative flex h-20 w-20 items-center justify-center rounded-full bg-emerald-50">
                  <Mic className="h-8 w-8 text-emerald-600" />
                </div>
              </div>

              <div className="text-center">
                <p className="text-sm font-medium text-emerald-700">Call active</p>
                <p className="text-[11px] text-neutral-500">
                  Speaking as {lead.name} at {lead.firm_name || "their firm"}
                </p>
              </div>

              {/* Controls */}
              <div className="flex items-center gap-4">
                <button
                  onClick={() => stop()}
                  className="flex items-center gap-2 rounded-xl bg-rose-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-rose-700 transition-colors"
                >
                  <PhoneOff className="h-4 w-4" />
                  End call
                </button>
              </div>

              {callId && (
                <p className="text-[10px] font-mono text-neutral-400">
                  call: {callId.slice(0, 8)}…
                </p>
              )}
            </div>
          )}

          {state === "ended" && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-20 w-20 items-center justify-center rounded-full bg-neutral-100">
                <PhoneOff className="h-8 w-8 text-neutral-400" />
              </div>
              <p className="text-sm text-neutral-600">Call ended</p>
              {callId && (
                <a
                  href={`/calls/${callId}`}
                  className="text-xs text-blue-600 hover:underline"
                >
                  View transcript →
                </a>
              )}
              <button
                onClick={() => start(lead.patient_id)}
                className="flex items-center gap-2 rounded-xl bg-neutral-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-neutral-800 transition-colors"
              >
                <Phone className="h-4 w-4" />
                Call again
              </button>
            </div>
          )}

          {error && (
            <div className="mt-4 rounded-lg bg-rose-50 px-4 py-2 text-xs text-rose-700">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
