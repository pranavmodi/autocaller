"""OpenAI Realtime backend.

Conforms to `RealtimeVoiceBackend`. Wraps the OpenAI Realtime WebSocket
and the `session.update` / `input_audio_buffer.append` / function-call
event protocol.

This file is a straight port of `app/services/realtime_voice.py` with the
`provider` / `model` attrs added and the legacy Precise Imaging path
removed — the autocaller always supplies system_prompt + tools explicitly.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Any

import websockets
from dotenv import load_dotenv

# Ensure .env is loaded (idempotent; safe if already loaded by app.config)
_project_root = Path(__file__).resolve().parent.parent.parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=str(_env_path))


OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
DEFAULT_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2025-08-28")


@dataclass
class VoiceSession:
    session_id: str
    call_id: str
    patient_name: str
    is_active: bool = True
    conversation_id: Optional[str] = None


class OpenAIRealtimeBackend:
    """OpenAI Realtime-API implementation of RealtimeVoiceBackend."""

    provider: str = "openai"

    def __init__(
        self,
        audio_format: str = "pcm16",
        verbose: bool = False,
        model: Optional[str] = None,
        voice_name: Optional[str] = None,
    ):
        self._ws = None
        self._session: Optional[VoiceSession] = None
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._audio_format = audio_format
        self._verbose = verbose
        self.model = model or DEFAULT_MODEL
        self._voice_name = voice_name
        self._custom_prompt: Optional[str] = None
        self._custom_tools: Optional[list[dict]] = None

        # Callbacks assigned by CallOrchestrator
        self.on_transcript: Optional[Callable[[str, str], Any]] = None
        self.on_audio: Optional[Callable[[bytes], Any]] = None
        self.on_session_created: Optional[Callable[[str], Any]] = None
        self.on_session_ended: Optional[Callable[[], Any]] = None
        self.on_error: Optional[Callable[[str], Any]] = None
        self.on_function_call: Optional[Callable[[str, dict, str], Any]] = None

    @property
    def audio_format(self) -> str:
        return self._audio_format

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
        self._custom_prompt = system_prompt
        self._custom_tools = tools

        if not self._api_key:
            if self.on_error:
                await self.on_error("OPENAI_API_KEY not set in environment")
            return False
        if not self._api_key.startswith("sk-"):
            if self.on_error:
                await self.on_error("Invalid OPENAI_API_KEY (must start with 'sk-')")
            return False
        if not system_prompt or not tools:
            if self.on_error:
                await self.on_error(
                    "OpenAIRealtimeBackend requires explicit system_prompt + tools"
                )
            return False

        try:
            url = f"{OPENAI_REALTIME_URL}?model={self.model}"
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            }
            print(f"[OpenAIRealtime] Connecting model={self.model} format={self._audio_format}")
            self._ws = await websockets.connect(url, additional_headers=headers)
            self._session = VoiceSession(
                session_id="",
                call_id=call_id,
                patient_name=patient_name,
            )
            await self._configure_session()
            asyncio.create_task(self._listen())
            return True
        except websockets.exceptions.InvalidStatusCode as e:
            msg = f"OpenAI rejected connection (HTTP {e.status_code})"
            if e.status_code == 401:
                msg = "Invalid OpenAI API key (401)"
            elif e.status_code == 403:
                msg = "API key lacks Realtime access (403)"
            if self.on_error:
                await self.on_error(msg)
            return False
        except Exception as e:
            if self.on_error:
                await self.on_error(f"Connection failed: {type(e).__name__}: {e}")
            return False

    async def _configure_session(self):
        assert self._custom_prompt is not None and self._custom_tools is not None
        # Pull per-provider voice config from system_settings. Fall back
        # to env vars / defaults when keys are missing. Imported lazily
        # to keep the voice backend free of circular-import risk at
        # module load (settings provider pulls in the ORM).
        voice_name = self._voice_name or os.getenv("OPENAI_VOICE", "alloy")
        temperature: Optional[float] = None
        try:
            from app.providers import get_settings_provider
            s = await get_settings_provider().get_settings()
            cfg = (s.voice_config or {}).get("openai") or {}
            if cfg.get("voice"):
                voice_name = str(cfg["voice"])
            if cfg.get("temperature") is not None:
                temperature = float(cfg["temperature"])
        except Exception as e:
            # Settings unavailable (e.g. DB not ready during startup test
            # harness) — env defaults still apply, just log.
            print(f"[OpenAIRealtime] voice_config lookup failed: {e}")

        session: dict = {
            "modalities": ["text", "audio"],
            "instructions": self._custom_prompt,
            "voice": voice_name,
            "input_audio_format": self._audio_format,
            "output_audio_format": self._audio_format,
            "input_audio_transcription": {
                "model": "gpt-4o-transcribe",
            },
            "turn_detection": {
                "type": "server_vad",
                "threshold": float(os.getenv("OPENAI_VAD_THRESHOLD", "0.85")),
                "prefix_padding_ms": int(os.getenv("OPENAI_VAD_PREFIX_MS", "300")),
                "silence_duration_ms": int(os.getenv("OPENAI_VAD_SILENCE_MS", "700")),
            },
            "tools": self._custom_tools,
        }
        if temperature is not None:
            session["temperature"] = temperature
        config = {"type": "session.update", "session": session}
        await self._send(config)

    # ------------------------------------------------------------------ listen
    async def _listen(self):
        if not self._ws:
            return
        try:
            async for message in self._ws:
                await self._handle_message(message)
            print("[OpenAIRealtime] WebSocket closed normally")
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[OpenAIRealtime] WebSocket closed: code={e.code}, reason={e.reason}")
            if self.on_session_ended:
                await self.on_session_ended()
        except Exception as e:
            if self.on_error:
                await self.on_error(f"Listen error: {type(e).__name__}: {e}")

    async def _handle_message(self, message: str):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")
            if self._verbose and msg_type not in (
                "response.audio.delta", "response.audio_transcript.delta"
            ):
                print(f"[OpenAIRealtime] Received: {msg_type}")

            if msg_type == "session.created":
                self._session.session_id = data.get("session", {}).get("id", "")
                if self.on_session_created:
                    await self.on_session_created(self._session.session_id)
            elif msg_type == "session.updated":
                pass
            elif msg_type == "response.audio.delta":
                audio_b64 = data.get("delta", "")
                if audio_b64 and self.on_audio:
                    await self.on_audio(base64.b64decode(audio_b64))
            elif msg_type == "response.audio_transcript.delta":
                text = data.get("delta", "")
                if text and self.on_transcript:
                    await self.on_transcript("ai", text)
            elif msg_type == "response.audio_transcript.done":
                text = data.get("transcript", "")
                if text and self.on_transcript:
                    await self.on_transcript("ai_complete", text)
            elif msg_type == "conversation.item.input_audio_transcription.completed":
                text = data.get("transcript", "")
                if text and text.strip() and self.on_transcript:
                    await self.on_transcript("patient", text.strip())
            elif msg_type == "conversation.item.input_audio_transcription.failed":
                if self.on_transcript:
                    await self.on_transcript("patient", "[inaudible]")
            elif msg_type == "response.function_call_arguments.done":
                name = data.get("name", "")
                fn_call_id = data.get("call_id", "")
                try:
                    args = json.loads(data.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                if self.on_function_call:
                    await self.on_function_call(name, args, fn_call_id)
            elif msg_type == "error":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                if self.on_error:
                    await self.on_error(error_msg)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            if self.on_error:
                await self.on_error(f"Message handling error: {e}")

    # ------------------------------------------------------------------ I/O
    async def _send(self, data: dict):
        if self._ws:
            await self._ws.send(json.dumps(data))

    async def send_audio(self, audio_data: bytes):
        if not self._ws or not self._session or not self._session.is_active:
            return
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        await self._send({
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        })

    async def commit_audio(self):
        if self._ws:
            await self._send({"type": "input_audio_buffer.commit"})

    async def start_response(self):
        if self._ws:
            await self._send({"type": "response.create"})

    async def cancel_response(self):
        if self._ws:
            await self._send({"type": "response.cancel"})

    async def send_function_result(self, call_id: str, result: dict):
        if self._ws:
            await self._send({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                },
            })
            await self._send({"type": "response.create"})

    async def start_conversation(self, language: str = "en"):
        """Seed the single-word opener and wait for VAD."""
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
        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": seed_text}],
            },
        })
        await self._send({"type": "response.create"})

    async def disconnect(self):
        if self._session:
            self._session.is_active = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self.on_session_ended:
            await self.on_session_ended()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._session is not None and self._session.is_active
