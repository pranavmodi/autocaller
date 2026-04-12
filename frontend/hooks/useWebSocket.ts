"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import type { WSMessage, QueueState, CallLog, Statistics } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

declare global {
  interface Window {
    __DASHBOARD_WS__?: WebSocket;
  }
}

interface DispatchedPatient {
  patient_id: string;
  patient_name: string;
}

export interface DispatcherDecision {
  timestamp: string;
  decision: string;
  detail: string;
  state: string;
  repeatCount?: number;
}

interface UseDashboardWSReturn {
  connected: boolean;
  queueState: QueueState | null;
  activeCall: CallLog | null;
  statistics: Statistics | null;
  lastStatus: string | null;
  dispatchedPatient: DispatchedPatient | null;
  clearDispatch: () => void;
  dispatcherEvents: DispatcherDecision[];
  pushEvent: (decision: string, detail: string) => void;
  onCallEnded: React.MutableRefObject<(() => void) | null>;
  onSettingsUpdated: React.MutableRefObject<((settings: any) => void) | null>;
}

export function useDashboardWS(): UseDashboardWSReturn {
  const isDev = process.env.NODE_ENV !== "production";
  const [connected, setConnected] = useState(false);
  const [queueState, setQueueState] = useState<QueueState | null>(null);
  const [activeCall, setActiveCall] = useState<CallLog | null>(null);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [lastStatus, setLastStatus] = useState<string | null>(null);
  const [dispatchedPatient, setDispatchedPatient] = useState<DispatchedPatient | null>(null);
  const onCallEndedRef = useRef<(() => void) | null>(null);
  const onSettingsUpdatedRef = useRef<((settings: any) => void) | null>(null);
  const [dispatcherEvents, setDispatcherEvents] = useState<DispatcherDecision[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isMountedRef = useRef(false);
  const allowReconnectRef = useRef(true);

  const appendEvent = useCallback((event: DispatcherDecision) => {
    setDispatcherEvents((prev) => {
      const latest = prev[0];
      if (latest && latest.decision === event.decision && latest.detail === event.detail) {
        // Same event repeated — bump count and update timestamp
        const updated = { ...latest, timestamp: event.timestamp, repeatCount: (latest.repeatCount || 1) + 1 };
        return [updated, ...prev.slice(1)];
      }
      return [{ ...event, repeatCount: 1 }, ...prev].slice(0, 50);
    });
  }, []);

  const clearDispatch = useCallback(() => {
    setDispatchedPatient(null);
  }, []);

  const pushEvent = useCallback((decision: string, detail: string) => {
    const event: DispatcherDecision = {
      timestamp: new Date().toISOString(),
      decision,
      detail,
      state: "frontend",
    };
    appendEvent(event);
  }, [appendEvent]);

  const attachHandlers = useCallback((ws: WebSocket) => {
    ws.onopen = () => {
      setConnected(true);
      console.log("Dashboard WS connected");
    };

    ws.onclose = () => {
      setConnected(false);
      if (!allowReconnectRef.current || !isMountedRef.current) return;
      console.log("Dashboard WS disconnected, reconnecting...");
      reconnectTimeoutRef.current = setTimeout(connect, 3000);
    };

    ws.onerror = (error) => {
      console.error("Dashboard WS error:", error);
    };

    ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);

        switch (message.type) {
          case "initial_state":
            setQueueState(message.queue_state as QueueState);
            setActiveCall(message.active_call as CallLog | null);
            setStatistics(message.statistics as Statistics);
            break;

          case "call_started":
            setActiveCall(message.call as CallLog);
            break;

          case "call_ended":
            setActiveCall(null);
            onCallEndedRef.current?.();
            break;

          case "status_update":
            {
              const status = message.status as string;
              setLastStatus(status);
              const normalized = status.toLowerCase();
              if (normalized.includes("sms sent")) {
                appendEvent({
                  timestamp: new Date().toISOString(),
                  decision: "sms_sent",
                  detail: status,
                  state: "backend",
                });
              } else if (normalized.includes("sms failed")) {
                appendEvent({
                  timestamp: new Date().toISOString(),
                  decision: "sms_failed",
                  detail: status,
                  state: "backend",
                });
              }
            }
            break;

          case "transcript":
            // Update active call transcript (deduplicate consecutive identical entries)
            setActiveCall((prev) => {
              if (!prev) return prev;
              const speaker = message.speaker as string;
              const text = message.text as string;
              const last = prev.transcript[prev.transcript.length - 1];
              if (last && last.speaker === speaker && last.text === text) {
                return prev; // skip duplicate
              }
              return {
                ...prev,
                transcript: [
                  ...prev.transcript,
                  { speaker, text, timestamp: new Date().toISOString() },
                ],
              };
            });
            break;

          case "queue_update":
            setQueueState(message.queue_state as QueueState);
            if (message.decision) {
              const decision = message.decision as DispatcherDecision;
              if (!decision.timestamp) {
                decision.timestamp = new Date().toISOString();
              }
              appendEvent(decision);
            }
            break;

          case "dispatcher_event":
            if (message.decision) {
              const decision = message.decision as DispatcherDecision;
              if (!decision.timestamp) {
                decision.timestamp = new Date().toISOString();
              }
              appendEvent(decision);
            }
            break;

          case "settings_updated":
            if (message.settings && onSettingsUpdatedRef.current) {
              onSettingsUpdatedRef.current(message.settings);
            }
            break;

          case "dispatch_call":
            console.log("Received dispatch_call:", message.patient_id, message.patient_name);
            setDispatchedPatient({
              patient_id: message.patient_id as string,
              patient_name: message.patient_name as string,
            });
            // Send ack back
            ws.send(JSON.stringify({ type: "dispatch_ack", patient_id: message.patient_id }));
            break;

          case "ping":
            ws.send(JSON.stringify({ type: "pong" }));
            break;
        }
      } catch (e) {
        console.error("Failed to parse WS message:", e);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appendEvent]);

  const connect = useCallback(() => {
    // Reuse a singleton socket across dev hot-reloads / strict-mode double-mounts
    if (isDev && typeof window !== "undefined" && window.__DASHBOARD_WS__ && window.__DASHBOARD_WS__.readyState <= WebSocket.OPEN) {
      wsRef.current = window.__DASHBOARD_WS__;
      if (window.__DASHBOARD_WS__.readyState === WebSocket.OPEN) setConnected(true);
      // Re-attach handlers so this mount receives events
      attachHandlers(window.__DASHBOARD_WS__);
      return;
    }
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return;

    const ws = new WebSocket(`${WS_BASE}/ws/dashboard`);
    attachHandlers(ws);

    wsRef.current = ws;
    if (isDev && typeof window !== "undefined") {
      window.__DASHBOARD_WS__ = ws;
    }
  }, [attachHandlers, isDev]);

  useEffect(() => {
    isMountedRef.current = true;
    allowReconnectRef.current = true;
    connect();

    return () => {
      isMountedRef.current = false;
      allowReconnectRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      // In production always close; in dev close only non-singleton sockets.
      if (!isDev) {
        wsRef.current?.close();
      } else if (typeof window !== "undefined" && wsRef.current && wsRef.current !== window.__DASHBOARD_WS__) {
        wsRef.current.close();
      }
    };
  }, [connect, isDev]);

  return { connected, queueState, activeCall, statistics, lastStatus, dispatchedPatient, clearDispatch, dispatcherEvents, pushEvent, onCallEnded: onCallEndedRef, onSettingsUpdated: onSettingsUpdatedRef };
}

interface UseVoiceWSReturn {
  connected: boolean;
  connect: () => void;
  disconnect: () => void;
  startCall: (patientId: string) => void;
  endCall: (outcome?: string) => void;
  sendAudio: (audioData: ArrayBuffer) => void;
  callStatus: string | null;
  transcript: Array<{ speaker: string; text: string }>;
  error: string | null;
  isCallActive: boolean;
  onAudioReceived: (callback: (audioData: ArrayBuffer) => void) => void;
}

export function useVoiceWS(): UseVoiceWSReturn {
  const [connected, setConnected] = useState(false);
  const [callStatus, setCallStatus] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Array<{ speaker: string; text: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [isCallActive, setIsCallActive] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const audioCallbackRef = useRef<((audioData: ArrayBuffer) => void) | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`${WS_BASE}/ws/voice`);

    ws.onopen = () => {
      setConnected(true);
      setError(null);
      console.log("Voice WS connected");
    };

    ws.onclose = () => {
      setConnected(false);
      setIsCallActive(false);
      console.log("Voice WS disconnected");
    };

    ws.onerror = (error) => {
      console.error("Voice WS error:", error);
      setError("Connection error");
    };

    ws.onmessage = (event) => {
      try {
        const message: WSMessage = JSON.parse(event.data);

        switch (message.type) {
          case "call_started":
            setIsCallActive(true);
            setTranscript([]);
            setCallStatus("Connected");
            break;

          case "call_ended":
            setIsCallActive(false);
            setCallStatus("Call ended");
            break;

          case "transcript":
            const speaker = message.speaker as string;
            const text = message.text as string;
            // Only add complete transcripts, not deltas
            if (speaker === "ai" || speaker === "patient") {
              setTranscript((prev) => [...prev, { speaker, text }]);
            }
            break;

          case "audio":
            // Decode base64 audio and pass to callback
            const audioB64 = message.data as string;
            const binaryString = atob(audioB64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
              bytes[i] = binaryString.charCodeAt(i);
            }
            if (audioCallbackRef.current) {
              audioCallbackRef.current(bytes.buffer);
            }
            break;

          case "status":
            setCallStatus(message.status as string);
            break;

          case "error":
            setError(message.message as string);
            break;

          case "pong":
            break;
        }
      } catch (e) {
        console.error("Failed to parse WS message:", e);
      }
    };

    wsRef.current = ws;
  }, []);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  const startCall = useCallback((patientId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "start_call", patient_id: patientId }));
    }
  }, []);

  const endCall = useCallback((outcome: string = "completed") => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end_call", outcome }));
    }
  }, []);

  const audioSentCountRef = useRef(0);
  const sendAudio = useCallback((audioData: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(audioData);
      audioSentCountRef.current++;
      if (audioSentCountRef.current === 1) {
        console.log("[VoiceWS] Sending first audio chunk to backend:", audioData.byteLength, "bytes");
      }
    } else {
      if (audioSentCountRef.current === 0) {
        console.warn("[VoiceWS] Cannot send audio - WebSocket not open, state:", wsRef.current?.readyState);
      }
    }
  }, []);

  const onAudioReceived = useCallback((callback: (audioData: ArrayBuffer) => void) => {
    audioCallbackRef.current = callback;
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  return {
    connected,
    connect,
    disconnect,
    startCall,
    endCall,
    sendAudio,
    callStatus,
    transcript,
    error,
    isCallActive,
    onAudioReceived,
  };
}
