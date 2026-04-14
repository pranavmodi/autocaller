"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/api";

interface State {
  listening: boolean;
  connecting: boolean;
  error: string | null;
}

/**
 * Connects to /ws/listen/{callId}, plays the received PCM16 @ 8kHz mono
 * stream through the browser speakers. No push-to-talk.
 *
 * Strategy: each binary frame is raw Int16 little-endian PCM. We convert to
 * Float32 [-1,1], allocate an AudioBuffer, and schedule an
 * AudioBufferSourceNode at `nextStartTime`. A few-hundred-ms jitter buffer
 * is implied by the scheduler — good enough for monitoring.
 */
export function useLiveListener(callId: string | null) {
  const [state, setState] = useState<State>({
    listening: false,
    connecting: false,
    error: null,
  });

  const socketRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const nextStartRef = useRef<number>(0);

  const start = useCallback(() => {
    if (!callId) return;
    if (socketRef.current) return;

    setState({ listening: false, connecting: true, error: null });

    let ctx: AudioContext;
    try {
      // Use 8 kHz sample rate so scheduling is 1:1 with the PCM we get.
      ctx = new (window.AudioContext || (window as any).webkitAudioContext)({
        sampleRate: 8000,
      });
    } catch (e) {
      setState({ listening: false, connecting: false, error: "AudioContext init failed" });
      return;
    }
    ctxRef.current = ctx;
    nextStartRef.current = 0;

    const ws = new WebSocket(wsUrl(`/ws/listen/${callId}`));
    ws.binaryType = "arraybuffer";
    socketRef.current = ws;

    ws.onopen = () => {
      // Most browsers block autoplay until a user gesture starts the AudioContext.
      ctx.resume().catch(() => {});
      setState({ listening: true, connecting: false, error: null });
    };

    ws.onerror = () => {
      setState((s) => ({ ...s, error: "websocket error" }));
    };

    ws.onclose = (ev) => {
      setState({
        listening: false,
        connecting: false,
        error:
          ev.code === 4004
            ? "No active call to listen to."
            : ev.code === 1000 || ev.code === 1005
              ? null
              : `closed (${ev.code})`,
      });
      socketRef.current = null;
      try {
        ctx.close();
      } catch {}
      ctxRef.current = null;
    };

    ws.onmessage = (ev) => {
      // Text messages = metadata ("ready", "ping", etc). Ignore for playback.
      if (typeof ev.data === "string") {
        if (ev.data === "ping") ws.send("pong");
        return;
      }
      if (!ctxRef.current) return;

      // Binary: Int16 little-endian PCM @ 8kHz mono
      const buf = ev.data as ArrayBuffer;
      const samples = buf.byteLength / 2;
      if (samples <= 0) return;
      const i16 = new Int16Array(buf);
      const f32 = new Float32Array(samples);
      for (let i = 0; i < samples; i++) f32[i] = i16[i] / 32768;

      const audioBuf = ctxRef.current.createBuffer(1, samples, 8000);
      audioBuf.copyToChannel(f32, 0);

      const src = ctxRef.current.createBufferSource();
      src.buffer = audioBuf;
      src.connect(ctxRef.current.destination);

      const now = ctxRef.current.currentTime;
      const start = Math.max(now + 0.02, nextStartRef.current);
      src.start(start);
      nextStartRef.current = start + samples / 8000;
    };
  }, [callId]);

  const stop = useCallback(() => {
    const ws = socketRef.current;
    if (ws) {
      try {
        ws.close(1000, "stop");
      } catch {}
    }
    socketRef.current = null;
    const ctx = ctxRef.current;
    if (ctx) {
      try {
        ctx.close();
      } catch {}
    }
    ctxRef.current = null;
    nextStartRef.current = 0;
    setState({ listening: false, connecting: false, error: null });
  }, []);

  useEffect(() => {
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ...state, start, stop };
}
