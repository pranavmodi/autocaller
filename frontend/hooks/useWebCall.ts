"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { wsUrl } from "@/lib/api";

export type WebCallState = "idle" | "connecting" | "active" | "ended";

export function useWebCall() {
  const [state, setState] = useState<WebCallState>("idle");
  const [callId, setCallId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const nextPlayTimeRef = useRef(0);

  const cleanup = useCallback(() => {
    if (workletRef.current) {
      workletRef.current.disconnect();
      workletRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    nextPlayTimeRef.current = 0;
  }, []);

  const playAudio = useCallback((pcm16: ArrayBuffer) => {
    const ctx = audioCtxRef.current;
    if (!ctx || ctx.state === "closed") return;

    const int16 = new Int16Array(pcm16);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768;
    }

    // AI output is 24kHz PCM16 from Gemini, but the /ws/voice endpoint
    // may resample. Use 24000 as default; the AudioContext resamples to
    // device output rate automatically.
    const sampleRate = 24000;
    const buf = ctx.createBuffer(1, float32.length, sampleRate);
    buf.getChannelData(0).set(float32);

    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);

    const now = ctx.currentTime;
    const start = Math.max(now, nextPlayTimeRef.current);
    src.start(start);
    nextPlayTimeRef.current = start + buf.duration;
  }, []);

  const start = useCallback(
    async (leadId: string, mode: "twilio" | "web" = "web") => {
      setError(null);
      setState("connecting");

      try {
        // Ensure AudioContext
        if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
          audioCtxRef.current = new AudioContext({ sampleRate: 16000 });
        }
        const ctx = audioCtxRef.current;
        if (ctx.state === "suspended") await ctx.resume();

        // Get mic
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            sampleRate: 16000,
          },
        });
        streamRef.current = stream;

        // Connect WebSocket
        const url = wsUrl("/ws/voice");
        const ws = new WebSocket(url);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          // Send start command
          ws.send(
            JSON.stringify({
              type: "start_call",
              patient_id: leadId,
              mode,
            })
          );
        };

        ws.onmessage = (ev) => {
          if (typeof ev.data === "string") {
            try {
              const msg = JSON.parse(ev.data);
              if (msg.type === "call_started") {
                setCallId(msg.call_id);
                setState("active");
                startMicCapture(ctx, stream, ws);
              } else if (msg.type === "audio") {
                // Base64-encoded PCM16 from the AI
                const binary = atob(msg.data);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) {
                  bytes[i] = binary.charCodeAt(i);
                }
                playAudio(bytes.buffer);
              } else if (msg.type === "call_ended") {
                setState("ended");
                cleanup();
              } else if (msg.type === "error") {
                setError(msg.message || "Call failed");
                setState("ended");
                cleanup();
              }
            } catch {
              // ignore parse errors
            }
          }
        };

        ws.onclose = () => {
          if (state !== "ended") {
            setState("ended");
            cleanup();
          }
        };

        ws.onerror = () => {
          setError("WebSocket connection failed");
          setState("ended");
          cleanup();
        };
      } catch (err: any) {
        setError(err.message || "Failed to start web call");
        setState("idle");
        cleanup();
      }
    },
    [cleanup, playAudio, state]
  );

  const stop = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end_call" }));
    }
    setState("ended");
    cleanup();
  }, [cleanup]);

  // Cleanup on unmount
  useEffect(() => {
    return () => cleanup();
  }, [cleanup]);

  return { state, callId, error, start, stop };
}

function startMicCapture(
  ctx: AudioContext,
  stream: MediaStream,
  ws: WebSocket
) {
  const source = ctx.createMediaStreamSource(stream);

  // Use ScriptProcessor (widely supported) to capture raw PCM
  // AudioWorklet would be cleaner but requires serving a separate JS file
  const processor = ctx.createScriptProcessor(4096, 1, 1);

  processor.onaudioprocess = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;

    const float32 = e.inputBuffer.getChannelData(0);
    // Convert float32 → int16 PCM
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    ws.send(int16.buffer);
  };

  source.connect(processor);
  processor.connect(ctx.destination); // needed for ScriptProcessor to work
}
