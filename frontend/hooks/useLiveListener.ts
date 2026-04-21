"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl, wsUrl } from "@/lib/api";

interface State {
  listening: boolean;      // actively streaming audio right now
  connecting: boolean;     // WS opening
  autoReconnect: boolean;  // user opted into follow-the-batch mode
  takeover: boolean;       // operator has taken over — AI muted, mic live
  takeoverPending: boolean;// server round-trip in flight
  error: string | null;
}

const AUTO_LS_KEY = "autocaller_listen_auto";

function u8ToBase64(bytes: Uint8Array): string {
  // btoa wants a binary string. Loop is fine — frames are 160 bytes.
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s);
}

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
    takeover: false,
    takeoverPending: false,
    error: null,
  }));

  const socketRef = useRef<WebSocket | null>(null);
  const socketCallIdRef = useRef<string | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  // Per-direction playback schedulers. Caller and AI audio have totally
  // different timing profiles: caller arrives at steady 8kHz real-time;
  // AI bursts at 2-4× real-time from Gemini/OpenAI. A shared scheduler
  // forced us to either drop AI audio (garbled) or let lag accumulate
  // forever. Two timelines, both feeding AudioContext.destination, lets
  // Web Audio mix them naturally with no timing coupling.
  const nextStartCallerRef = useRef<number>(0);
  const nextStartAiRef = useRef<number>(0);
  const autoReconnectRef = useRef<boolean>(state.autoReconnect);
  // Mic pipeline refs — created on takeover, torn down on release.
  const micStreamRef = useRef<MediaStream | null>(null);
  const micSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const micWorkletRef = useRef<AudioWorkletNode | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);

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
      nextStartCallerRef.current = 0;
      nextStartAiRef.current = 0;
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
        nextStartCallerRef.current = 0;
        nextStartAiRef.current = 0;
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
        // 2-byte header: [tag, 0xAC magic]. Tag 0x01=caller, 0x02=ai.
        // Magic byte is a versioning guard — if it's missing, the server
        // is speaking a different framing protocol and we'd rather drop
        // than play garbage.
        if (buf.byteLength < 4) return;
        const headerBytes = new Uint8Array(buf, 0, 2);
        if (headerBytes[1] !== 0xac) {
          console.warn("[listener] stale/unknown frame header, dropping");
          return;
        }
        const isAi = headerBytes[0] === 0x02;
        const samples = (buf.byteLength - 2) / 2;
        if (samples <= 0) return;
        const i16 = new Int16Array(buf, 2, samples);
        const f32 = new Float32Array(samples);
        for (let i = 0; i < samples; i++) f32[i] = i16[i] / 32768;

        const audioBuf = ctxNow.createBuffer(1, samples, 8000);
        audioBuf.copyToChannel(f32, 0);

        const src = ctxNow.createBufferSource();
        src.buffer = audioBuf;
        src.connect(ctxNow.destination);

        // Per-direction scheduling with different drift policies.
        // Caller: steady real-time, 300ms drop cap handles network
        // jitter. AI: bursty at 2-4× real-time (confirmed via
        // AUDIO_RATE: 29335 bps during Gemini utterances). Use a much
        // larger cap (3s) so normal bursts buffer freely; Web Audio
        // plays them out at 8kHz and naturally catches up when the
        // model stops generating. The cap only triggers on pathological
        // lag (e.g. tab-sleep) where we want to resync.
        const now = ctxNow.currentTime;
        const nextRef = isAi ? nextStartAiRef : nextStartCallerRef;
        const MAX_LEAD = isAi ? 3.0 : 0.30;
        const TARGET_LEAD = isAi ? 0.20 : 0.08;
        let startT = Math.max(now + 0.02, nextRef.current);
        if (startT - now > MAX_LEAD) {
          startT = now + TARGET_LEAD;
        }
        src.start(startT);
        nextRef.current = startT + samples / 8000;
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
    nextStartCallerRef.current = 0;
    nextStartAiRef.current = 0;
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

  // ----------------------------------------------------------------------
  // Human takeover: mute AI + pipe browser mic into the call
  // ----------------------------------------------------------------------

  const tearDownMic = useCallback(() => {
    const w = micWorkletRef.current;
    if (w) {
      try {
        w.port.onmessage = null;
        w.disconnect();
      } catch {}
    }
    micWorkletRef.current = null;

    const src = micSourceRef.current;
    if (src) {
      try {
        src.disconnect();
      } catch {}
    }
    micSourceRef.current = null;

    const stream = micStreamRef.current;
    if (stream) {
      for (const track of stream.getTracks()) {
        try {
          track.stop();
        } catch {}
      }
    }
    micStreamRef.current = null;

    const ctx = micCtxRef.current;
    if (ctx) {
      try {
        ctx.close();
      } catch {}
    }
    micCtxRef.current = null;
  }, []);

  const startTakeover = useCallback(async () => {
    if (!callId) return;
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      setState((s) => ({ ...s, error: "must be listening before taking over" }));
      return;
    }
    setState((s) => ({ ...s, takeoverPending: true, error: null }));

    // 1. Flip the server flag first. If this fails, don't open the mic.
    try {
      const res = await fetch(apiUrl(`/api/calls/${callId}/takeover`), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: true }),
        credentials: "include",
      });
      if (!res.ok) {
        setState((s) => ({
          ...s,
          takeoverPending: false,
          error: `takeover failed (${res.status})`,
        }));
        return;
      }
    } catch (e) {
      setState((s) => ({ ...s, takeoverPending: false, error: "takeover request failed" }));
      return;
    }

    // 2. Open the mic and wire it into a worklet. One AudioContext per
    //    takeover session — we close it on release so mic doesn't linger.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      micStreamRef.current = stream;

      const ctx = new (window.AudioContext ||
        (window as any).webkitAudioContext)();
      micCtxRef.current = ctx;
      await ctx.audioWorklet.addModule("/operator-mic-worklet.js");

      const source = ctx.createMediaStreamSource(stream);
      micSourceRef.current = source;

      const node = new AudioWorkletNode(ctx, "operator-mic-processor");
      micWorkletRef.current = node;
      node.port.onmessage = (ev: MessageEvent) => {
        const frame = ev.data?.frame as Uint8Array | undefined;
        if (!frame) return;
        const ws = socketRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(
          JSON.stringify({
            type: "inbound_audio",
            payload: u8ToBase64(frame),
          }),
        );
      };
      source.connect(node);
      // Worklet needs to be in the audio graph for `process()` to run.
      // Connect to destination with zero-gain so we don't loopback our own
      // voice to the speakers (echo).
      const mute = ctx.createGain();
      mute.gain.value = 0;
      node.connect(mute).connect(ctx.destination);

      setState((s) => ({ ...s, takeover: true, takeoverPending: false }));
    } catch (e) {
      // Roll back the server flag if we couldn't open the mic.
      tearDownMic();
      try {
        await fetch(apiUrl(`/api/calls/${callId}/takeover`), {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ enabled: false }),
          credentials: "include",
        });
      } catch {}
      setState((s) => ({
        ...s,
        takeover: false,
        takeoverPending: false,
        error: e instanceof Error ? `mic: ${e.message}` : "mic open failed",
      }));
    }
  }, [callId, tearDownMic]);

  const stopTakeover = useCallback(async () => {
    tearDownMic();
    setState((s) => ({ ...s, takeover: false, takeoverPending: true }));
    if (callId) {
      try {
        await fetch(apiUrl(`/api/calls/${callId}/takeover`), {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ enabled: false }),
          credentials: "include",
        });
      } catch {}
    }
    setState((s) => ({ ...s, takeoverPending: false }));
  }, [callId, tearDownMic]);

  /** Tear down on unmount. */
  useEffect(() => {
    return () => {
      try {
        socketRef.current?.close(1000, "unmount");
      } catch {}
      try {
        ctxRef.current?.close();
      } catch {}
      tearDownMic();
    };
  }, [tearDownMic]);

  // If the live call changes while takeover is on, release mic immediately
  // so we don't suddenly be speaking into a different call.
  useEffect(() => {
    if (!callId && state.takeover) {
      tearDownMic();
      setState((s) => ({ ...s, takeover: false }));
    }
  }, [callId, state.takeover, tearDownMic]);

  return { ...state, start, stop, startTakeover, stopTakeover };
}
