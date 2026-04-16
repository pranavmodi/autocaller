"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/api";

interface State {
  listening: boolean;      // actively streaming audio right now
  connecting: boolean;     // WS opening
  autoReconnect: boolean;  // user opted into follow-the-batch mode
  error: string | null;
}

const AUTO_LS_KEY = "autocaller_listen_auto";

/**
 * Stream live call audio to the browser speakers.
 *
 * Two modes:
 *   1. One-shot: user clicks start() for one specific call_id. When that
 *      call ends, we stop.
 *   2. Auto-follow (autoReconnect=true): user clicks start() once; we keep
 *      listening to whatever call_id the caller hook receives. When one
 *      call ends, we automatically reconnect to the next active call.
 *      Persisted in localStorage so it survives page refreshes.
 *
 * The hook doesn't know about the dispatcher — it just responds to the
 * callId prop. The NowPage feeds it the active-call id from the dashboard
 * WS stream.
 */
export function useLiveListener(callId: string | null) {
  const [state, setState] = useState<State>(() => ({
    listening: false,
    connecting: false,
    autoReconnect:
      typeof window !== "undefined" &&
      window.localStorage.getItem(AUTO_LS_KEY) === "true",
    error: null,
  }));

  const socketRef = useRef<WebSocket | null>(null);
  const socketCallIdRef = useRef<string | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const nextStartRef = useRef<number>(0);
  const autoReconnectRef = useRef<boolean>(state.autoReconnect);

  // Keep a ref in sync with state so the WS onclose handler sees the latest value.
  useEffect(() => {
    autoReconnectRef.current = state.autoReconnect;
  }, [state.autoReconnect]);

  const ensureAudioContext = useCallback((): AudioContext | null => {
    if (ctxRef.current && ctxRef.current.state !== "closed") return ctxRef.current;
    try {
      const ctx = new (window.AudioContext ||
        (window as any).webkitAudioContext)({ sampleRate: 8000 });
      ctxRef.current = ctx;
      nextStartRef.current = 0;
      return ctx;
    } catch {
      setState((s) => ({ ...s, error: "AudioContext init failed" }));
      return null;
    }
  }, []);

  const openSocket = useCallback(
    (targetCallId: string) => {
      if (!targetCallId) return;
      if (socketRef.current && socketCallIdRef.current === targetCallId) return;

      // Close any stale socket first
      if (socketRef.current) {
        try {
          socketRef.current.close(1000, "switching call");
        } catch {}
        socketRef.current = null;
      }

      const ctx = ensureAudioContext();
      if (!ctx) return;

      setState((s) => ({ ...s, connecting: true, error: null }));

      const ws = new WebSocket(wsUrl(`/ws/listen/${targetCallId}`));
      ws.binaryType = "arraybuffer";
      socketRef.current = ws;
      socketCallIdRef.current = targetCallId;

      ws.onopen = () => {
        ctx.resume().catch(() => {});
        nextStartRef.current = 0;
        setState((s) => ({ ...s, listening: true, connecting: false, error: null }));
      };

      ws.onerror = () => {
        setState((s) => ({ ...s, error: "websocket error" }));
      };

      ws.onclose = (ev) => {
        socketRef.current = null;
        socketCallIdRef.current = null;
        // Close codes we treat as "normal" (no error to surface):
        //   1000 — normal closure
        //   1005 — no status received (client-initiated unload)
        //   1006 — abnormal closure (network); noisy, don't show
        //   1012 — server restart (daemon deploy) — we'll reconnect
        //   4004 — our backend's "no active call" signal during auto mode
        const silentCodes = new Set([1000, 1005, 1006, 1012, 4004]);
        setState((s) => ({
          ...s,
          listening: false,
          connecting: false,
          error: silentCodes.has(ev.code) ? null : `closed (${ev.code})`,
        }));
        // Don't close the AudioContext — we may reconnect on next call.
      };

      ws.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          if (ev.data === "ping") ws.send("pong");
          return;
        }
        const ctxNow = ctxRef.current;
        if (!ctxNow || ctxNow.state === "closed") return;

        const buf = ev.data as ArrayBuffer;
        const samples = buf.byteLength / 2;
        if (samples <= 0) return;
        const i16 = new Int16Array(buf);
        const f32 = new Float32Array(samples);
        for (let i = 0; i < samples; i++) f32[i] = i16[i] / 32768;

        const audioBuf = ctxNow.createBuffer(1, samples, 8000);
        audioBuf.copyToChannel(f32, 0);

        const src = ctxNow.createBufferSource();
        src.buffer = audioBuf;
        src.connect(ctxNow.destination);

        const now = ctxNow.currentTime;
        const startT = Math.max(now + 0.02, nextStartRef.current);
        src.start(startT);
        nextStartRef.current = startT + samples / 8000;
      };
    },
    [ensureAudioContext],
  );

  /** Start listening to the current callId and set auto-reconnect on. */
  const start = useCallback(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(AUTO_LS_KEY, "true");
    }
    setState((s) => ({ ...s, autoReconnect: true }));
    autoReconnectRef.current = true;
    if (callId) openSocket(callId);
  }, [callId, openSocket]);

  /** Stop — closes socket AND disables auto-reconnect. */
  const stop = useCallback(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(AUTO_LS_KEY, "false");
    }
    setState((s) => ({ ...s, autoReconnect: false }));
    autoReconnectRef.current = false;

    const ws = socketRef.current;
    if (ws) {
      try {
        ws.close(1000, "stop");
      } catch {}
    }
    socketRef.current = null;
    socketCallIdRef.current = null;

    const ctx = ctxRef.current;
    if (ctx) {
      try {
        ctx.close();
      } catch {}
    }
    ctxRef.current = null;
    nextStartRef.current = 0;
    setState((s) => ({
      ...s,
      listening: false,
      connecting: false,
      error: null,
    }));
  }, []);

  /** When the active call changes, auto-connect if the user opted in. */
  useEffect(() => {
    if (!callId) {
      // Between calls — clear any stale error text from the previous
      // session (e.g. "closed (1012)" from a daemon restart) so the
      // "waiting for next call" pill doesn't surface zombie errors.
      setState((s) => (s.error ? { ...s, error: null } : s));
      return;
    }
    if (!autoReconnectRef.current) return;
    openSocket(callId);
  }, [callId, openSocket]);

  /** Tear down on unmount. */
  useEffect(() => {
    return () => {
      try {
        socketRef.current?.close(1000, "unmount");
      } catch {}
      try {
        ctxRef.current?.close();
      } catch {}
    };
  }, []);

  return { ...state, start, stop };
}
