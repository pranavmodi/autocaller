"""Gemini Live backend (Google BidiGenerateContent WebSocket).

Implements `RealtimeVoiceBackend` against the Gemini Live API. As of
March 2026 the latest model is Gemini 3.1 Flash Live.

Key protocol differences from OpenAI Realtime:
  - Audio in MUST be 16 kHz 16-bit PCM mono (not mulaw). For Twilio calls
    (audio_format='g711_ulaw') we transcode via AudioTranscoder.
  - Audio out is 24 kHz 16-bit PCM mono. For Twilio we downsample + encode
    mulaw before calling `on_audio`.
  - Tools use `function_declarations`, not the OpenAI `tools` shape.
  - Function-call events are `tool_call` / `tool_response`.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Optional, Callable, Any

import websockets
from dotenv import load_dotenv

from .audio import AudioTranscoder
from .base import openai_tools_to_gemini as _canonical_tools_to_gemini_camel


_project_root = Path(__file__).resolve().parent.parent.parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=str(_env_path))


GEMINI_LIVE_HOST = "generativelanguage.googleapis.com"
GEMINI_LIVE_PATH = (
    "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
DEFAULT_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
DEFAULT_VOICE = os.getenv("GEMINI_VOICE", "Aoede")
# Per-call voice override — set by the orchestrator before connect().
_voice_override: str | None = None


class GeminiLiveBackend:
    """Gemini Live implementation of RealtimeVoiceBackend."""

    provider: str = "gemini"

    def __init__(
        self,
        audio_format: str = "pcm16",
        verbose: bool = False,
        model: Optional[str] = None,
        voice_name: Optional[str] = None,
    ):
        self._ws = None
        self._call_id: str = ""
        self._patient_name: str = ""
        self._is_active: bool = False
        self._api_key = os.getenv("GEMINI_API_KEY", "")
        self._audio_format = audio_format  # what the ORCHESTRATOR feeds us
        self._verbose = verbose
        self.model = model or DEFAULT_MODEL
        self._voice_name = voice_name

        # Twilio bridging requires mulaw<->pcm transcoding. Browser path
        # already sends pcm16; we just pass through + resample output.
        self._transcoder = AudioTranscoder()

        # Callbacks
        self.on_transcript: Optional[Callable[[str, str], Any]] = None
        self.on_audio: Optional[Callable[[bytes], Any]] = None
        self.on_session_created: Optional[Callable[[str], Any]] = None
        self.on_session_ended: Optional[Callable[[], Any]] = None
        self.on_error: Optional[Callable[[str], Any]] = None
        self.on_function_call: Optional[Callable[[str, dict, str], Any]] = None

    @property
    def audio_format(self) -> str:
        return self._audio_format

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._is_active

    # ------------------------------------------------------------------ connect
    async def connect(
        self,
        call_id: str,
        patient_name: str,
        patient_language: str = "en",
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
    ) -> bool:
        if not self._api_key:
            if self.on_error:
                await self.on_error("GEMINI_API_KEY not set in environment")
            return False
        if not system_prompt or not tools:
            if self.on_error:
                await self.on_error(
                    "GeminiLiveBackend requires explicit system_prompt + tools"
                )
            return False

        self._call_id = call_id
        self._patient_name = patient_name

        # Gemini Live auth is an API key on the query string.
        url = (
            f"wss://{GEMINI_LIVE_HOST}{GEMINI_LIVE_PATH}"
            f"?key={self._api_key}"
        )
        try:
            print(f"[GeminiLive] Connecting model={self.model} format={self._audio_format}")
            self._ws = await websockets.connect(url)
            self._is_active = True
            await self._send_setup(system_prompt, tools)
            asyncio.create_task(self._listen())
            if self.on_session_created:
                await self.on_session_created(call_id)
            return True
        except Exception as e:
            if self.on_error:
                await self.on_error(f"Gemini Live connect failed: {type(e).__name__}: {e}")
            return False

    async def _send_setup(self, system_prompt: str, tools: list[dict]):
        # JSON uses camelCase over the wire for Gemini Live.
        # https://ai.google.dev/api/live
        gemini_tools = _canonical_tools_to_gemini_camel(tools)

        # Pull per-provider voice config from system_settings. Missing
        # keys fall back to env-var / hardcoded defaults. Lazy import
        # to avoid ORM pulling in at module load.
        voice_name = self._voice_name or DEFAULT_VOICE
        temperature: Optional[float] = None
        top_p: Optional[float] = None
        affective = False
        proactive = False
        try:
            from app.providers import get_settings_provider
            s = await get_settings_provider().get_settings()
            cfg = (s.voice_config or {}).get("gemini") or {}
            if cfg.get("voice"):
                voice_name = str(cfg["voice"])
            if cfg.get("temperature") is not None:
                temperature = float(cfg["temperature"])
            if cfg.get("top_p") is not None:
                top_p = float(cfg["top_p"])
            affective = bool(cfg.get("affective_dialog", False))
            proactive = bool(cfg.get("proactive_audio", False))
        except Exception as e:
            print(f"[GeminiLive] voice_config lookup failed: {e}")

        generation_config: dict = {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice_name}
                }
            },
        }
        if temperature is not None:
            generation_config["temperature"] = temperature
        if top_p is not None:
            generation_config["topP"] = top_p

        setup_body: dict = {
            "model": f"models/{self.model}",
            "generationConfig": generation_config,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            # Transcription for both sides so we can populate the
            # transcript stream / CallLog.transcript just like OpenAI.
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
        # enableAffectiveDialog / proactivity.proactiveAudio were
        # Gemini-only flags for prosody matching + short non-verbal
        # cues. `gemini-3.1-flash-live-preview` rejects both with
        # WS close code 1007 ("Unknown name 'enableAffectiveDialog'
        # at 'setup': Cannot find field"), which dropped every call
        # at ~1s. Drop the fields until the model spec supports them
        # again; the operator toggles in /system are effectively
        # no-ops by design.
        if affective or proactive:
            print(
                "[GeminiLive] ignoring affective/proactive — not supported "
                f"by model {self.model}; toggle in /system is a no-op"
            )
        setup = {"setup": setup_body}
        if gemini_tools:
            setup_body["tools"] = gemini_tools

        if self._verbose:
            print(
                f"[GeminiLive] setup: voice={voice_name} "
                f"temp={temperature} affective={affective} proactive={proactive}"
            )
        await self._send(setup)

    # ------------------------------------------------------------------ listen
    async def _listen(self):
        if not self._ws:
            return
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    # Gemini sends bytes for some events; decode as JSON.
                    try:
                        message = message.decode("utf-8")
                    except UnicodeDecodeError:
                        continue
                await self._handle_message(message)
            print("[GeminiLive] WebSocket closed normally")
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[GeminiLive] WebSocket closed: code={e.code}, reason={e.reason}")
        except Exception as e:
            if self.on_error:
                await self.on_error(f"Gemini Live listen error: {type(e).__name__}: {e}")
        finally:
            self._is_active = False
            if self.on_session_ended:
                await self.on_session_ended()

    async def _handle_message(self, message: str):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        # Gemini setup ack
        if "setup_complete" in data or "setupComplete" in data:
            if self._verbose:
                print("[GeminiLive] setup complete")
            return

        server_content = data.get("server_content") or data.get("serverContent")
        if server_content:
            await self._handle_server_content(server_content)
            return

        tool_call = data.get("tool_call") or data.get("toolCall")
        if tool_call:
            await self._handle_tool_call(tool_call)
            return

        if "go_away" in data or "goAway" in data:
            if self.on_error:
                await self.on_error("Gemini Live: server requested disconnect (goAway)")
            return

        if self._verbose:
            print(f"[GeminiLive] unhandled event: {list(data.keys())}")

    async def _handle_server_content(self, sc: dict):
        # model_turn -> parts -> inlineData (audio) or text
        model_turn = sc.get("model_turn") or sc.get("modelTurn") or {}
        for part in model_turn.get("parts", []) or []:
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                pcm24k = base64.b64decode(inline["data"])
                await self._emit_audio_out(pcm24k)
                continue
            text = part.get("text")
            if text and self.on_transcript:
                await self.on_transcript("ai", text)

        # Input/output transcription for transcript capture
        input_t = sc.get("input_transcription") or sc.get("inputTranscription")
        if input_t and input_t.get("text") and self.on_transcript:
            await self.on_transcript("patient", input_t["text"])
        output_t = sc.get("output_transcription") or sc.get("outputTranscription")
        if output_t and output_t.get("text") and self.on_transcript:
            await self.on_transcript("ai_complete", output_t["text"])

        # Turn / generation complete — nothing to forward; orchestrator
        # uses VAD / timing on its end. Logged in verbose mode only.
        if self._verbose and (sc.get("turn_complete") or sc.get("turnComplete")):
            print("[GeminiLive] turn complete")

    async def _emit_audio_out(self, pcm24k: bytes):
        """Pipe Gemini's 24 kHz PCM16 back out to the caller in whatever
        format the caller expects. Twilio needs 8 kHz mulaw; browser gets
        the raw 24 kHz stream."""
        if not self.on_audio:
            return
        if self._audio_format == "g711_ulaw":
            chunk = self._transcoder.pcm24k_to_mulaw8k(pcm24k)
        else:
            chunk = pcm24k
        if chunk:
            await self.on_audio(chunk)

    async def _handle_tool_call(self, tool_call: dict):
        calls = tool_call.get("function_calls") or tool_call.get("functionCalls") or []
        for fc in calls:
            name = fc.get("name", "")
            args = fc.get("args") or {}
            fn_call_id = fc.get("id", "")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if self.on_function_call:
                await self.on_function_call(name, args, fn_call_id)

    # ------------------------------------------------------------------ I/O
    async def _send(self, data: dict):
        if self._ws:
            await self._ws.send(json.dumps(data))

    async def send_audio(self, audio_data: bytes):
        """Accept whatever format the orchestrator declared. Transcode if
        needed before forwarding to Gemini (which only accepts 16 kHz PCM16).
        """
        if not self._ws or not self._is_active or not audio_data:
            return
        if self._audio_format == "g711_ulaw":
            pcm16k = self._transcoder.mulaw8k_to_pcm16k(audio_data)
        else:
            # Browser path already supplies 16 kHz PCM16.
            pcm16k = audio_data
        if not pcm16k:
            return
        # Gemini Live: realtimeInput.audio (singular, camelCase).
        # mimeType must be "audio/pcm;rate=16000".
        payload = {
            "realtimeInput": {
                "audio": {
                    "mimeType": "audio/pcm;rate=16000",
                    "data": base64.b64encode(pcm16k).decode("utf-8"),
                },
            }
        }
        await self._send(payload)

    async def commit_audio(self):
        """Gemini Live uses continuous streaming + server VAD; no explicit
        commit is required. Kept as a no-op for interface parity."""
        return

    async def start_response(self):
        """Gemini auto-generates on VAD end-of-speech; no-op for parity."""
        return

    async def cancel_response(self):
        """Gemini cancels via client_content with `turn_complete=true` and
        a barge-in signal on the input stream. The audio bridge already
        stops forwarding when the orchestrator asks; an explicit cancel
        is rarely needed."""
        return

    async def start_conversation(self, language: str = "en"):
        """Seed the single-word opener and wait for VAD.

        Gemini Live accepts a text-only kick-off via `realtimeInput.text`.
        `clientContent.turns[]` is rejected by the 3.1-flash-live-preview
        gateway with 'invalid argument'.
        """
        if not self._ws:
            return
        lang = (language or "en").strip().lower()[:2]
        if lang == "es":
            seed_text = (
                "[System: La llamada se acaba de conectar. Di SOLO la única "
                "palabra '¿Bueno?' en tono cálido y casual — nada más. NO te "
                "presentes todavía. NO pitchees. Espera a que la otra persona "
                "hable antes de continuar. Cuando respondan, sigue las "
                "instrucciones completas del sistema."
            )
        else:
            seed_text = (
                "[System: The call just connected. Say ONLY the single word "
                "'Hello?' in a warm, casual tone — nothing else. Do NOT "
                "introduce yourself yet. Do NOT pitch. Wait for the other "
                "party to speak before continuing. When they respond, follow "
                "your full system instructions."
            )
        await self._send({"realtimeInput": {"text": seed_text}})

    async def send_function_result(self, call_id: str, result: dict):
        if not self._ws:
            return
        # Gemini expects toolResponse.functionResponses[].response.output.
        await self._send({
            "toolResponse": {
                "functionResponses": [{
                    "id": call_id,
                    "response": {"output": json.dumps(result)},
                }],
            }
        })

    async def send_system_nudge(self, text: str):
        """Inject a [System: ...] instruction mid-call so the model redirects."""
        if not self._ws or not text:
            return
        await self._send({"realtimeInput": {"text": f"[System: {text}]"}})

    async def disconnect(self):
        self._is_active = False
        ws = self._ws
        self._ws = None
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
        if self.on_session_ended:
            await self.on_session_ended()
