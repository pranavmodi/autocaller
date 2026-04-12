"use client";

import { useRef, useState, useCallback, useEffect } from "react";

interface UseAudioReturn {
  isRecording: boolean;
  isPlaying: boolean;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  playAudio: (audioData: ArrayBuffer) => void;
  onAudioData: (callback: (data: ArrayBuffer) => void) => void;
  audioLevel: number;
  error: string | null;
}

export function useAudio(): UseAudioReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCallbackRef = useRef<((data: ArrayBuffer) => void) | null>(null);
  const playbackQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);

  const getAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext({ sampleRate: 24000 });
    }
    return audioContextRef.current;
  }, []);

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      const audioContext = getAudioContext();

      // Resume audio context if suspended
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }

      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 24000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      mediaStreamRef.current = stream;

      console.log("[Audio] AudioContext sample rate:", audioContext.sampleRate);
      console.log("[Audio] Stream tracks:", stream.getAudioTracks().map(t => t.getSettings()));

      // Create audio nodes
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;

      // Use ScriptProcessorNode for raw audio access
      // Note: This is deprecated but AudioWorklet requires more setup
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      let audioChunkCount = 0;
      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);

        // Convert Float32 to Int16 PCM
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }

        // Send to callback
        if (audioCallbackRef.current) {
          audioCallbackRef.current(pcmData.buffer);
          audioChunkCount++;
          if (audioChunkCount === 1) {
            console.log("[Audio] Sending first audio chunk:", pcmData.buffer.byteLength, "bytes");
          }
        }
      };

      // Connect nodes
      source.connect(analyser);
      analyser.connect(processor);
      processor.connect(audioContext.destination);

      // Start level monitoring
      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const updateLevel = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        setAudioLevel(average / 255);
        if (isRecording) {
          requestAnimationFrame(updateLevel);
        }
      };
      requestAnimationFrame(updateLevel);

      setIsRecording(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start recording");
    }
  }, [getAudioContext, isRecording]);

  const stopRecording = useCallback(() => {
    // Stop media tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    // Disconnect processor
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    analyserRef.current = null;
    setIsRecording(false);
    setAudioLevel(0);
  }, []);

  const playAudio = useCallback(
    async (audioData: ArrayBuffer) => {
      // Queue the audio
      playbackQueueRef.current.push(audioData);

      // If already playing, the queue will be processed
      if (isPlayingRef.current) return;

      isPlayingRef.current = true;
      setIsPlaying(true);

      const audioContext = getAudioContext();

      while (playbackQueueRef.current.length > 0) {
        const data = playbackQueueRef.current.shift();
        if (!data) continue;

        try {
          // Convert Int16 PCM to Float32
          const int16Data = new Int16Array(data);
          const float32Data = new Float32Array(int16Data.length);
          for (let i = 0; i < int16Data.length; i++) {
            float32Data[i] = int16Data[i] / 0x8000;
          }

          // Create audio buffer
          const audioBuffer = audioContext.createBuffer(1, float32Data.length, 24000);
          audioBuffer.copyToChannel(float32Data, 0);

          // Play the buffer
          const source = audioContext.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(audioContext.destination);

          await new Promise<void>((resolve) => {
            source.onended = () => resolve();
            source.start();
          });
        } catch (e) {
          console.error("Error playing audio:", e);
        }
      }

      isPlayingRef.current = false;
      setIsPlaying(false);
    },
    [getAudioContext]
  );

  const onAudioData = useCallback((callback: (data: ArrayBuffer) => void) => {
    audioCallbackRef.current = callback;
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopRecording();
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, [stopRecording]);

  return {
    isRecording,
    isPlaying,
    startRecording,
    stopRecording,
    playAudio,
    onAudioData,
    audioLevel,
    error,
  };
}
