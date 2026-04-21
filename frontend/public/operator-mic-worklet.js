// AudioWorkletProcessor: browser-mic → µ-law 8kHz 20ms frames.
//
// Runs in the AudioWorklet global scope (no DOM, no WebSockets). Posts
// each 20ms frame (160 samples @ 8kHz = 160 µ-law bytes) back to the main
// thread via port.postMessage({frame: Uint8Array}).
//
// The main thread base64-encodes and ships it over the existing
// /ws/listen/{call_id} WebSocket as {type:"inbound_audio", payload:"..."}.
//
// Input sample rate is whatever the AudioContext runs at (browser default,
// typically 48000 or 44100). We downsample with simple averaging — µ-law
// voice telephony is 8 kHz anyway, so aliasing from skipping a few samples
// isn't audible on a phone call.

const OUT_RATE = 8000;
const FRAME_MS = 20;
const FRAME_SAMPLES = (OUT_RATE * FRAME_MS) / 1000; // 160

// PCM16 → µ-law (ITU-T G.711).
function pcm16ToMulaw(sample) {
  const BIAS = 0x84;
  const CLIP = 32635;
  let sign = (sample >> 8) & 0x80;
  if (sign !== 0) sample = -sample;
  if (sample > CLIP) sample = CLIP;
  sample = sample + BIAS;
  let exponent = 7;
  for (let mask = 0x4000; (sample & mask) === 0 && exponent > 0; mask >>= 1) {
    exponent--;
  }
  const mantissa = (sample >> (exponent + 3)) & 0x0f;
  const ulawByte = ~(sign | (exponent << 4) | mantissa) & 0xff;
  return ulawByte;
}

class OperatorMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Accumulates downsampled PCM16 samples until we have a full 20ms frame.
    this._buf = new Int16Array(FRAME_SAMPLES);
    this._bufPos = 0;
    // Fractional resampler state: how many input samples per output sample.
    this._step = sampleRate / OUT_RATE; // e.g. 48000/8000 = 6
    this._accum = 0;
    this._sum = 0;
    this._count = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0];
    if (!ch) return true;

    // Downsample: average each `_step` input samples into one output sample.
    for (let i = 0; i < ch.length; i++) {
      this._sum += ch[i];
      this._count++;
      this._accum++;
      if (this._accum >= this._step) {
        const avg = this._sum / this._count;
        // Float [-1,1] → int16
        let s16 = Math.max(-1, Math.min(1, avg)) * 32767;
        s16 = s16 | 0;
        this._buf[this._bufPos++] = s16;
        this._sum = 0;
        this._count = 0;
        this._accum -= this._step;

        if (this._bufPos >= FRAME_SAMPLES) {
          const frame = new Uint8Array(FRAME_SAMPLES);
          for (let k = 0; k < FRAME_SAMPLES; k++) {
            frame[k] = pcm16ToMulaw(this._buf[k]);
          }
          this.port.postMessage({ frame }, [frame.buffer]);
          this._bufPos = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("operator-mic-processor", OperatorMicProcessor);
