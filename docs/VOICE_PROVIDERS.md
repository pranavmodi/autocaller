# Voice Provider Abstraction (OpenAI Realtime ↔ Gemini Live)

**Status (2026-04-15): Phases 1-5 shipped.** Abstraction is live, both backends implemented, DB columns record per-call attribution, CLI/API/UI toggles all work. Phase 6 (real A/B measurement against booked demos) is pending — fire a mixed batch once you have a handful of each on both providers.

See `app/services/voice/` for the implementation. Migration `u2v3w4x5y6z7` added `call_logs.voice_provider` + `call_logs.voice_model` + `system_settings.voice_provider` + `system_settings.voice_model`.

---

## Why bother

Two legitimate reasons to be able to flip providers:
1. **Cost.** OpenAI Realtime is premium-priced (audio minutes are the expensive part). Gemini Live is typically cheaper. If we're doing 500 cold calls/day, the per-minute rate compounds fast.
2. **Quality + reliability.** OpenAI Realtime has better barge-in/VAD today. Gemini Live is improving rapidly and has better multilingual audio. For certain lead segments, one may just sound better. Also: having a second provider means we can keep dialing when one has an outage.

What we're **not** doing: mixing providers mid-call. Pick one at call start, use it for the whole call.

---

## API comparison (what actually matters)

| concern | OpenAI Realtime | Gemini Live (2.0 Flash / 2.5 native audio) |
|---|---|---|
| Endpoint | `wss://api.openai.com/v1/realtime` | `wss://generativelanguage.googleapis.com/ws/.../BidiGenerateContent` |
| Auth | `Authorization: Bearer sk-…` header | `?key=…` query or `x-goog-api-key` header |
| Model | `gpt-realtime-2025-08-28` | `gemini-2.0-flash-live-001`, `gemini-2.5-flash-preview-native-audio-dialog` |
| Input audio | `pcm16` (24 kHz) **or `g711_ulaw` (8 kHz mulaw)** ← Twilio-native | `pcm16` (16 kHz mono) only |
| Output audio | `pcm16` or `g711_ulaw` | `pcm16` (24 kHz mono) only |
| Server VAD | yes, tunable threshold/prefix/silence | yes, less granular |
| Barge-in | robust (automatic response cancel on voice) | good; cancellation events differ |
| Tools | OpenAI-style function calling, `tools: [{type: "function", name, description, parameters}]` | Gemini-style `function_declarations`, JSON Schema subset |
| Transcription (caller side) | built-in `input_audio_transcription` (gpt-4o-transcribe) | native multimodal transcription |
| Session config | one `session.update` message | `setup` message; different shape |
| Wire protocol | one long-lived WS, many small JSON events | same, different event names |
| Voices | alloy, echo, shimmer, etc. | Aoede, Charon, Fenrir, Kore, Puck + native-audio voices |
| Languages | ~12 strong, many more usable | 30+ languages, particularly strong on Hindi/Spanish/Chinese |

**The Twilio-format gap is the single biggest hidden cost.** OpenAI takes mulaw natively; Gemini only takes 16kHz PCM16. For Gemini-on-Twilio we need a transcoder in both directions:

- Inbound (Twilio → Gemini): 8kHz mulaw → 16kHz PCM16
- Outbound (Gemini → Twilio): 24kHz PCM16 → 8kHz mulaw

Python `audioop` (stdlib through 3.12, `audioop-lts` for 3.13+) can do both in a few ms per chunk. We buffer, resample, and forward.

---

## Proposed architecture

### Abstract base (`app/services/voice/base.py`)

```python
class RealtimeVoiceBackend(Protocol):
    # Identity
    provider: str                        # "openai" | "gemini"
    audio_format: str                    # "pcm16" | "g711_ulaw"

    # Lifecycle
    async def connect(self, *, call_id, lead_name, language,
                      system_prompt, tools) -> bool: ...
    async def disconnect(self) -> None: ...

    # Audio + control
    async def send_audio(self, pcm_or_mulaw: bytes) -> None: ...
    async def commit_audio(self) -> None: ...
    async def start_response(self) -> None: ...
    async def cancel_response(self) -> None: ...
    async def send_function_result(self, call_id: str, result: dict) -> None: ...

    # Callbacks (assigned by caller)
    on_transcript: Callable[[speaker, text], Awaitable[None]]
    on_audio: Callable[[bytes], Awaitable[None]]
    on_function_call: Callable[[name, args, call_id], Awaitable[None]]
    on_session_ended: Callable[[], Awaitable[None]]
    on_error: Callable[[str], Awaitable[None]]
```

Both implementations conform. Caller code (orchestrator, Twilio bridge) only touches this interface.

### Implementations

```
app/services/voice/
├── base.py              # Protocol + tool schema converters
├── openai_realtime.py   # current code, moved
├── gemini_live.py       # new
├── audio.py             # mulaw<->pcm16 + resampling helpers
└── factory.py           # get_voice_backend(provider: str) -> instance
```

### Factory / selection

Precedence (highest wins):
1. Per-call override — `orchestrator.start_call(..., voice_provider="gemini")`
2. DB setting — `system_settings.voice_provider`
3. Env var — `VOICE_PROVIDER=openai|gemini` (default `openai`)

Exposed via:
- CLI: `bin/autocaller call LEAD-XXX --voice=gemini`
- API: `POST /api/call/start` accepts `voice_provider` in body
- Frontend Now screen: toggle dropdown (stretch)

### Tool-schema normalization

Both providers support tools; the JSON differs. Write a single **canonical tool spec** (already in `app/prompts/attorney_cold_call.py::TOOLS` — OpenAI-ish format) and convert at the adapter boundary:

```python
# base.py
def normalize_tools(canonical: list[dict], provider: str) -> list[dict]:
    if provider == "openai":
        return canonical                 # already in OpenAI format
    if provider == "gemini":
        return [_to_gemini(t) for t in canonical]
```

This keeps the orchestrator's tool-dispatch logic (`_handle_function_call`) provider-agnostic — tool names and arg schemas are identical across both.

### Audio layer (`audio.py`)

```python
def mulaw8k_to_pcm16k(mulaw: bytes) -> bytes: ...    # Twilio → Gemini
def pcm24k_to_mulaw8k(pcm: bytes) -> bytes: ...      # Gemini → Twilio
def pcm16k_to_pcm24k(pcm: bytes) -> bytes: ...       # if needed (unusual)
```

Uses `audioop.ulaw2lin` + `audioop.ratecv` for sample-rate conversion. Each chunk is 20ms (~160 samples at 8kHz) — overhead is negligible.

For OpenAI-on-Twilio, these are no-ops; the adapter just passes mulaw through.

### Error handling + fallback

In `start_call`:
```python
backend = get_voice_backend(preferred)
if not await backend.connect(...):
    if fallback_enabled:
        backend = get_voice_backend(other_provider)
        if not await backend.connect(...):
            # both dead → end call with FAILED
```
Gate this with a flag so we don't silently switch providers without logging it. Every call log records `voice_provider_used` for post-mortem.

---

## Per-call quality signals to capture

For A/B comparison once both work:
- `voice_provider` — which backend ran this call
- `tts_latency_p50` — time from `start_response` to first audio byte out
- `barge_in_success` — did the AI cleanly yield when user spoke
- `transcription_errors` — count of weird/empty transcript entries
- `function_call_latency` — tool-call round-trip time

Pipe these into the Health page funnel + a provider-breakdown panel.

---

## Effort estimate

| phase | work | effort |
|---|---|---|
| 1 | Refactor current code into `voice/openai_realtime.py`, write `base.py` Protocol, wire orchestrator + Twilio bridge to it. Backend tests pass unchanged. | 0.5 day |
| 2 | Implement `gemini_live.py` against Gemini Live API. Session setup, message loop, tool dispatch. Works for web (pcm16 in/out). | 1 day |
| 3 | Build `audio.py` transcoder. Unit tests with real mulaw samples. | 0.5 day |
| 4 | Wire Gemini-on-Twilio path through transcoder. Fix chunk-boundary + buffering issues. | 0.5 day |
| 5 | Add `voice_provider` to settings, API, CLI flag, frontend toggle. Record provider on call log. | 0.5 day |
| 6 | Live test: 10 calls each provider, compare latency + quality logs. Document observed differences. | 0.5 day |
| **Total** | | **3.5 days** |

---

## Open questions

1. **Do we actually need fallback across providers, or just selection?** Fallback adds complexity; a simpler "pick one and if it fails, the call fails" may be enough.
2. **Gemini 2.0 Flash Live vs 2.5 native-audio-dialog?** The 2.5 native-audio model is higher quality but in preview with stricter rate limits. Start with 2.0 Flash Live.
3. **Voice matching.** If we switch providers mid-day, voices won't match. That's fine for a cold-call tool (different leads, different calls) but worth noting.
4. **Latency budget.** OpenAI Realtime is ~300-500ms round-trip. Gemini Live is similar on 2.0, sometimes higher on 2.5 native-audio. Anything over 900ms feels conversationally broken — we must measure, not guess.
5. **Rate limits.** OpenAI has concurrent-session limits by tier. Gemini has stricter QPM caps. Both need to be measured against our concurrency plans.
6. **Regulatory.** Both providers train on or log audio depending on tier; check ToS against TCPA / attorney confidentiality guarantees (the AI is talking to lawyers — sensitive).

---

## Recommendation

Worth doing in Phase 2 of the product, **not Phase 1**. The pipeline works on OpenAI today; Phase 1 goal is "get one booked demo end-to-end". Provider abstraction unlocks real cost savings and resilience but doesn't move the first-demo needle.

Sequence:
1. Ship the current stack, get first 5-10 demos booked end-to-end on OpenAI.
2. Measure per-demo cost in real dollars.
3. If OpenAI cost is bearable, defer this. If not, build this next.

When we do build it, do Phase 1 (refactor into provider-agnostic interface with OpenAI only) as a safe in-place change — that alone is a big code-quality win and unlocks everything else whenever we decide to pull the trigger.
