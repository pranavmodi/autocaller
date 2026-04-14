"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { wsUrl } from "@/lib/api";
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

function handleEvent(msg: DashboardEvent) {
  switch (msg.type) {
    case "initial_state":
      setState({
        activeCall: msg.active_call,
        transcript: msg.active_call?.transcript ?? [],
      });
      break;
    case "call_started":
      setState({ activeCall: msg.call, transcript: msg.call.transcript ?? [] });
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
    return () => {
      listeners.delete(setSnap);
    };
  }, []);

  return snap;
}

export function sendDashboardPing() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "ping" }));
  }
}
