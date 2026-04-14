"""OpenAI Realtime API voice service."""
import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Optional, Callable, Any
from dataclasses import dataclass
import websockets
from dotenv import load_dotenv

# Ensure .env is loaded
_project_root = Path(__file__).resolve().parent.parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=str(_env_path))


OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
OPENAI_MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2025-08-28")


@dataclass
class VoiceSession:
    """Active voice session state."""
    session_id: str
    call_id: str
    patient_name: str
    is_active: bool = True
    conversation_id: Optional[str] = None


SYSTEM_INSTRUCTIONS = """Fallback prompt placeholder. The autocaller always
passes an explicit system_prompt + tools to RealtimeVoiceService.connect(),
so this default is never used in normal flow. If you see this text reach a
caller, the call path has regressed to the legacy branch — investigate.
"""

# --- DISABLED FEATURES (may be re-enabled later) ---
#
# 1. KNOWLEDGE BASE / FAQ ANSWERING
#    The AI previously could answer general questions (office hours, locations,
#    MRI prep, what to bring, insurance, scheduling process, etc.) from a built-in
#    knowledge base. Currently replaced with "let me transfer you to someone who
#    can help." To re-enable, add a "Knowledge Scope" section to SYSTEM_INSTRUCTIONS
#    with allowed topics and the company info block (locations, hours, contact info,
#    MRI prep, scheduling process, insurance, etc.).
#
# 2. PREFERRED CALLBACK TIME COLLECTION
#    When patient said NO, the AI would ask: "No problem at all. Before I let you go,
#    is there anything quick I can help with?" and then collect a preferred callback
#    time (e.g. "tomorrow 3 PM"). The time was passed to end_call.preferred_callback_time
#    and stored on the call log for the scheduling team.
#
# 3. EXTRA TRANSFER CONFIRMATION STEP
#    Before transferring, the AI would first ask: "Would you like me to transfer you
#    to our scheduling team right now?" and wait for explicit yes before proceeding.
#    Current flow goes straight to "hold while I transfer you" after patient says yes.
#
# 4. "BEFORE I LET YOU GO" FOLLOW-UP
#    When patient said NO, the AI would offer: "Before I let you go, is there anything
#    quick I can help with — like what to bring to your appointment or our office hours?"
#    and answer from the knowledge base before ending the call.


class RealtimeVoiceService:
    """Manages OpenAI Realtime API connections for voice calls."""

    def __init__(self, audio_format: str = "pcm16", verbose: bool = False):
        """Initialize voice service.

        Args:
            audio_format: Audio format for OpenAI Realtime API.
                          "pcm16" for browser WebSocket (24kHz 16-bit PCM).
                          "g711_ulaw" for Twilio media streams (8kHz mulaw).
            verbose: Whether to log detailed message-level info.
        """
        self._ws = None  # WebSocket connection
        self._session: Optional[VoiceSession] = None
        self._api_key = os.getenv("OPENAI_API_KEY", "")
        self._audio_format = audio_format
        self._verbose = verbose
        # Optional override — caller supplies rendered prompt + tool list
        self._custom_prompt: Optional[str] = None
        self._custom_tools: Optional[list[dict]] = None

        # Callbacks
        self.on_transcript: Optional[Callable[[str, str], Any]] = None  # (speaker, text)
        self.on_audio: Optional[Callable[[bytes], Any]] = None  # audio data
        self.on_session_created: Optional[Callable[[str], Any]] = None
        self.on_session_ended: Optional[Callable[[], Any]] = None
        self.on_error: Optional[Callable[[str], Any]] = None
        self.on_function_call: Optional[Callable[[str, dict, str], Any]] = None  # (name, args, call_id)

    @staticmethod
    def _normalize_language_code(language: Optional[str]) -> str:
        value = (language or "en").strip().lower()
        return value if value else "en"

    @classmethod
    def _language_instruction(cls, language: Optional[str]) -> str:
        code = cls._normalize_language_code(language)

        # Common adaptive rule appended to every language variant.
        adaptive = (
            "However, if the patient responds in a DIFFERENT language than expected, "
            "switch to their language immediately and continue the call in that language. "
            "The patient's comfort is more important than the on-file preference. "
            "Supported languages: English, Spanish, Mandarin Chinese."
        )

        if code == "es":
            return (
                "IMPORTANT LANGUAGE RULE: The patient preference is Spanish ('es'). "
                "Start in natural Spanish for the greeting, questions, and transfer/callback phrasing. "
                f"{adaptive}"
            )
        if code == "zh":
            return (
                "IMPORTANT LANGUAGE RULE: The patient preference is Chinese ('zh'). "
                "Start in simple, clear Mandarin Chinese for the greeting and conversation. "
                "If Mandarin is not possible for a specific phrase, use very simple English and offer transfer. "
                f"{adaptive}"
            )
        return (
            "IMPORTANT LANGUAGE RULE: The patient preference is English ('en'). "
            "Start the call in English. "
            f"{adaptive}"
        )

    async def connect(
        self,
        call_id: str,
        patient_name: str,
        patient_language: str = "en",
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
    ) -> bool:
        """Connect to OpenAI Realtime API and start a session.

        When `system_prompt` and `tools` are provided (autocaller path), they
        override the legacy hard-coded Precise Imaging prompt + tool set.
        """
        self._custom_prompt = system_prompt
        self._custom_tools = tools
        # Validate API key first
        if not self._api_key:
            error_msg = "OPENAI_API_KEY not set in environment"
            print(f"[RealtimeVoice] Error: {error_msg}")
            if self.on_error:
                await self.on_error(error_msg)
            return False

        if not self._api_key.startswith("sk-"):
            error_msg = f"Invalid API key format (should start with 'sk-')"
            print(f"[RealtimeVoice] Error: {error_msg}")
            if self.on_error:
                await self.on_error(error_msg)
            return False

        try:
            url = f"{OPENAI_REALTIME_URL}?model={OPENAI_MODEL}"
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "OpenAI-Beta": "realtime=v1",
            }

            print(f"[RealtimeVoice] Connecting to {url}...")
            self._ws = await websockets.connect(url, additional_headers=headers)
            print(f"[RealtimeVoice] WebSocket connected successfully")

            self._session = VoiceSession(
                session_id="",
                call_id=call_id,
                patient_name=patient_name,
            )

            # Configure the session
            await self._configure_session(patient_name, patient_language)

            # Start listening for messages
            asyncio.create_task(self._listen())

            return True

        except websockets.exceptions.InvalidStatusCode as e:
            error_msg = f"OpenAI rejected connection (HTTP {e.status_code})"
            if e.status_code == 401:
                error_msg = "Invalid OpenAI API key (401 Unauthorized)"
            elif e.status_code == 403:
                error_msg = "API key doesn't have access to Realtime API (403 Forbidden)"
            print(f"[RealtimeVoice] Error: {error_msg}")
            if self.on_error:
                await self.on_error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Connection failed: {type(e).__name__}: {str(e)}"
            print(f"[RealtimeVoice] Error: {error_msg}")
            if self.on_error:
                await self.on_error(error_msg)
            return False

    async def _configure_session(self, patient_name: str, patient_language: str = "en"):
        """Configure the realtime session."""
        # Autocaller path: custom prompt + tools supplied by caller.
        if self._custom_prompt is not None and self._custom_tools is not None:
            config = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": self._custom_prompt,
                    "voice": os.getenv("OPENAI_VOICE", "alloy"),
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
                },
            }
            await self._send(config)
            return

        # Legacy Precise Imaging path — retained for backward compat.
        language_instruction = self._language_instruction(patient_language)
        config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": (
                    f"{SYSTEM_INSTRUCTIONS.replace('{patient_name}', patient_name)}\n\n"
                    f"{language_instruction}"
                ),
                "voice": "alloy",
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
                "tools": [
                    {
                        "type": "function",
                        "name": "check_transfer_availability",
                        "description": "Check whether a scheduler is available to take a transfer right now. Call this BEFORE offering or promising a transfer to the patient. Returns {\"available\": true/false}.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "type": "function",
                        "name": "transfer_to_scheduler",
                        "description": "Transfer the patient to a human scheduler only after explicit consent to transfer. Never use this tool when patient indicates wrong number or identity mismatch.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "confirmed": {
                                    "type": "boolean",
                                    "description": "Whether the patient confirmed they want to transfer",
                                }
                            },
                            "required": ["confirmed"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "end_call",
                        "description": "End the call. Use reason='wrong_number' immediately when patient says this is the wrong number/person.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reason": {
                                    "type": "string",
                                    "enum": ["patient_busy", "wrong_number", "voicemail", "completed", "patient_request"],
                                    "description": "The reason for ending the call",
                                },
                                "callback_requested": {
                                    "type": "boolean",
                                    "description": "Whether the patient requested a callback",
                                },
                                "preferred_callback_time": {
                                    "type": "string",
                                    "description": "Optional preferred callback preference, e.g. 'tomorrow 3 PM' or 'after 1 hour'.",
                                },
                            },
                            "required": ["reason"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "send_sms",
                        "description": "Send an SMS to the patient with callback information.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "message_type": {
                                    "type": "string",
                                    "enum": ["callback_info", "appointment_reminder"],
                                    "description": "Type of message to send",
                                }
                            },
                            "required": ["message_type"],
                        },
                    },
                ],
            },
        }
        await self._send(config)

    async def _listen(self):
        """Listen for messages from OpenAI."""
        if not self._ws:
            return

        try:
            async for message in self._ws:
                await self._handle_message(message)
            # Normal exit — WebSocket closed cleanly after iteration
            print(f"[RealtimeVoice] OpenAI WebSocket closed normally")
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[RealtimeVoice] OpenAI WebSocket closed: code={e.code}, reason={e.reason}")
            if self.on_session_ended:
                await self.on_session_ended()
        except Exception as e:
            print(f"[RealtimeVoice] OpenAI listen error: {type(e).__name__}: {e}")
            if self.on_error:
                await self.on_error(f"Listen error: {str(e)}")

    async def _handle_message(self, message: str):
        """Handle incoming message from OpenAI."""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            # Log message types only in verbose mode (skip high-frequency audio deltas always)
            if self._verbose and msg_type not in ("response.audio.delta", "response.audio_transcript.delta"):
                print(f"[RealtimeVoice] Received: {msg_type}")

            if msg_type == "session.created":
                self._session.session_id = data.get("session", {}).get("id", "")
                if self.on_session_created:
                    await self.on_session_created(self._session.session_id)

            elif msg_type == "session.updated":
                pass  # Session config acknowledged

            elif msg_type == "response.audio.delta":
                # Audio chunk from AI
                audio_b64 = data.get("delta", "")
                if audio_b64 and self.on_audio:
                    audio_bytes = base64.b64decode(audio_b64)
                    await self.on_audio(audio_bytes)

            elif msg_type == "response.audio_transcript.delta":
                # AI speech transcript delta
                text = data.get("delta", "")
                if text and self.on_transcript:
                    await self.on_transcript("ai", text)

            elif msg_type == "response.audio_transcript.done":
                # AI finished speaking - full transcript
                text = data.get("transcript", "")
                if text and self.on_transcript:
                    await self.on_transcript("ai_complete", text)

            elif msg_type == "conversation.item.input_audio_transcription.completed":
                # Patient speech transcript
                text = data.get("transcript", "")
                if text and text.strip() and self.on_transcript:
                    await self.on_transcript("patient", text.strip())
                elif not text or not text.strip():
                    print("[RealtimeVoice] Patient transcription completed but text was empty")

            elif msg_type == "conversation.item.input_audio_transcription.failed":
                # Whisper failed to transcribe patient speech
                error = data.get("error", {})
                error_msg = error.get("message", "unknown")
                print(f"[RealtimeVoice] Patient transcription FAILED: {error_msg}")
                if self.on_transcript:
                    await self.on_transcript("patient", "[inaudible]")

            elif msg_type == "response.function_call_arguments.done":
                # Function call completed
                name = data.get("name", "")
                fn_call_id = data.get("call_id", "")
                args_str = data.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                if self.on_function_call:
                    await self.on_function_call(name, args, fn_call_id)

            elif msg_type == "error":
                error = data.get("error", {})
                error_msg = error.get("message", "Unknown error")
                if self.on_error:
                    await self.on_error(error_msg)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            if self.on_error:
                await self.on_error(f"Message handling error: {str(e)}")

    async def _send(self, data: dict):
        """Send a message to OpenAI."""
        if self._ws:
            await self._ws.send(json.dumps(data))

    async def send_audio(self, audio_data: bytes):
        """Send audio data to OpenAI."""
        if not self._ws or not self._session or not self._session.is_active:
            return

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        # Debug: log audio chunks being sent (first time only to avoid spam)
        if not hasattr(self, '_audio_logged'):
            self._audio_logged = True
            print(f"[RealtimeVoice] Sending audio chunk: {len(audio_data)} bytes")
        await self._send({
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        })

    async def commit_audio(self):
        """Commit the audio buffer (signal end of speech)."""
        if self._ws:
            await self._send({"type": "input_audio_buffer.commit"})

    async def start_response(self):
        """Trigger AI to generate a response."""
        if self._ws:
            await self._send({"type": "response.create"})

    async def cancel_response(self):
        """Cancel the current AI response."""
        if self._ws:
            await self._send({"type": "response.cancel"})

    async def send_function_result(self, call_id: str, result: dict):
        """Send function call result back to OpenAI."""
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

    async def start_conversation(self):
        """Open the call with a single 'Hello?' and then wait for the caller.

        Cold-call flow: answering party usually speaks first ('Hello?' /
        'Chen.' / an IVR greeting). If we barrel in with our full opener
        the instant Twilio's media stream connects, we often talk over them
        or blurt a pitch at a phone tree. Instead: say only 'Hello?',
        then server-side VAD on OpenAI waits for their reply and triggers
        the AI's next turn (the real introduction). If an IVR/voicemail
        picks up, its scripted prompt hits our transcript-based IVR
        detector in call_orchestrator._handle_transcript and force-ends
        the call silently.
        """
        if not self._ws:
            return

        await self._send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "[System: The call just connected. Say ONLY the single "
                            "word 'Hello?' in a warm, casual tone — nothing else. "
                            "Do NOT introduce yourself yet. Do NOT pitch. Wait for "
                            "the other party to speak before continuing. When they "
                            "respond, follow your full system instructions "
                            "(identify who's on the line, then the opener)."
                        ),
                    }
                ],
            },
        })
        await self._send({"type": "response.create"})

    async def disconnect(self):
        """Disconnect from OpenAI."""
        if self._session:
            self._session.is_active = False

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self.on_session_ended:
            await self.on_session_ended()

    @property
    def is_connected(self) -> bool:
        """Check if connected to OpenAI."""
        return self._ws is not None and self._session is not None and self._session.is_active
