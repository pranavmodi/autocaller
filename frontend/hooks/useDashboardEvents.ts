"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { wsUrl, getActiveCall } from "@/lib/api";
import type { CallLog, DashboardEvent, DispatcherDecision, TranscriptEntry } from "@/types";

interface State {
  connected: boolean;
  activeCall: CallLog | null;
  transcript: TranscriptEntry[];
  lastDecision: DispatcherDecision | null;
  lastStatus: string | null;
}

const INITIAL: State = {
  connected: false,
  activeCall: null,
  transcript: [],
  lastDecision: null,
  lastStatus: null,
};

// Shared singleton — multiple components that mount this hook share a single
// WS connection to avoid duplicating traffic.
let socket: WebSocket | null = null;
let listeners = new Set<(s: State) => void>();
let state: State = INITIAL;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let retryDelay = 1000;

function setState(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l(state));
}

function connect() {
  if (typeof window === "undefined") return;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

  const url = wsUrl("/ws/dashboard");
  try {
    socket = new WebSocket(url);
  } catch {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    retryDelay = 1000;
    setState({ connected: true });
  };

  socket.onclose = () => {
    setState({ connected: false });
    scheduleReconnect();
  };

  socket.onerror = () => {
    // onclose will fire right after
  };

  socket.onmessage = (ev) => {
    let msg: DashboardEvent;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    handleEvent(msg);
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(retryDelay, 15_000);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    retryDelay = Math.min(retryDelay * 2, 15_000);
    connect();
  }, delay);
}

/**
 * Reconcile active-call state from a server-side source (WS initial_state,
 * WS call_started, or REST poll). Only replace our state when the incoming
 * call's call_id differs from what we already have — otherwise we'd clobber
 * locally-accumulated transcript events with a stale snapshot from the poll.
 */
function applyActiveCallFromServer(incoming: CallLog | null) {
  if (!incoming) {
    // Server says no active call — clear.
    if (state.activeCall !== null) {
      setState({ activeCall: null, transcript: [] });
    }
    return;
  }
  const currentId = state.activeCall?.call_id ?? null;
  if (currentId === incoming.call_id) {
    // Same call; do NOT overwrite transcript (we may have newer deltas).
    // Just refresh non-transcript metadata if needed.
    if (state.activeCall !== incoming) {
      setState({ activeCall: incoming });
    }
    return;
  }
  // New call (or we were idle). Seed from server snapshot.
  setState({
    activeCall: incoming,
    transcript: incoming.transcript ?? [],
  });
}

/**
 * REST-poll fallback. Every 3 seconds, hit /api/calls/active and reconcile.
 * This is belt-and-suspenders for cases where a WS call_started event is
 * lost (reconnect, tab-backgrounding, proxy buffering). When WS is healthy,
 * the poll just confirms what we already know.
 */
let pollTimer: ReturnType<typeof setInterval> | null = null;

function startActiveCallPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (typeof document !== "undefined" && document.hidden) {
      // Tab is in background — skip this tick; we'll catch up on focus.
      return;
    }
    try {
      const res = await getActiveCall();
      applyActiveCallFromServer(res.active ? res.call : null);
    } catch {
      // Network blip — ignore, try again next tick.
    }
  }, 3000);
}

function stopActiveCallPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function handleEvent(msg: DashboardEvent) {
  switch (msg.type) {
    case "initial_state":
      applyActiveCallFromServer(msg.active_call);
      break;
    case "call_started":
      applyActiveCallFromServer(msg.call);
      break;
    case "call_ended":
      setState({ activeCall: null, transcript: [] });
      break;
    case "queue_update":
      if (msg.decision) setState({ lastDecision: msg.decision });
      break;
    case "status_update":
      setState({ lastStatus: msg.status });
      break;
    case "transcript_update": {
      const speaker =
        msg.kind === "patient" ? "patient" : msg.kind === "ai_delta" || msg.kind === "ai" ? "ai" : "system";
      const entry: TranscriptEntry = {
        speaker: speaker as TranscriptEntry["speaker"],
        text: msg.text,
        timestamp: new Date().toISOString(),
      };
      setState({ transcript: [...state.transcript, entry] });
      break;
    }
    case "ping":
      socket?.send(JSON.stringify({ type: "pong" }));
      break;
    default:
      break;
  }
}

export function useDashboardEvents(): State {
  const [snap, setSnap] = useState<State>(state);

  useEffect(() => {
    listeners.add(setSnap);
    connect();
    startActiveCallPolling();

    // Catch-up on tab focus: if the tab was backgrounded and we missed
    // events, fire one immediate reconcile.
    const onVisibilityChange = async () => {
      if (typeof document !== "undefined" && !document.hidden) {
        try {
          const res = await getActiveCall();
          applyActiveCallFromServer(res.active ? res.call : null);
        } catch {
          /* ignore */
        }
        // Also nudge the WS to reconnect if it's dead.
        if (!socket || socket.readyState === WebSocket.CLOSED) {
          connect();
        }
      }
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }

    return () => {
      listeners.delete(setSnap);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
      // Stop polling only when the last listener unmounts.
      if (listeners.size === 0) {
        stopActiveCallPolling();
      }
    };
  }, []);

  return snap;
}

export function sendDashboardPing() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "ping" }));
  }
}
