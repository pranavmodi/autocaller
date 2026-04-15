"""Realtime voice backend interface.

Every provider (OpenAI Realtime, Gemini Live, future additions) implements
this surface so the orchestrator and Twilio bridge can treat them
identically. One call → one backend instance; never swap mid-call.

The interface deliberately mirrors what `RealtimeVoiceService` (OpenAI) has
exposed historically, so moving OpenAI into this shape is a structural
refactor, not a behavior change.
"""
from __future__ import annotations

from typing import Protocol, Callable, Any, Awaitable, Optional, runtime_checkable


BACKEND_OPENAI = "openai"
BACKEND_GEMINI = "gemini"

# Callback signatures the orchestrator assigns before connect().
TranscriptCallback = Callable[[str, str], Awaitable[None]]        # (speaker, text)
AudioCallback = Callable[[bytes], Awaitable[None]]                # PCM / mulaw chunk out to Twilio or browser
SessionCreatedCallback = Callable[[str], Awaitable[None]]         # (session_id)
SessionEndedCallback = Callable[[], Awaitable[None]]
ErrorCallback = Callable[[str], Awaitable[None]]
FunctionCallCallback = Callable[[str, dict, str], Awaitable[None]]  # (name, args, tool_call_id)


@runtime_checkable
class RealtimeVoiceBackend(Protocol):
    """Common interface for realtime voice providers."""

    # -- Identity / attribution --------------------------------------------
    # Stamped onto every CallLog so we know which backend ran which call.
    provider: str        # "openai" | "gemini"
    model: str           # exact model ID (e.g. "gemini-3.1-flash-live")

    # Audio format the backend expects on its WIRE SIDE (what the provider's
    # WebSocket wants to receive). The orchestrator itself still decides
    # whether to feed mulaw (Twilio) or pcm16 (browser); the transcoder
    # in audio.py handles any mismatch before calling send_audio().
    audio_format: str    # "pcm16" | "g711_ulaw"

    # -- Callbacks (assigned by caller before connect) ---------------------
    on_transcript: Optional[TranscriptCallback]
    on_audio: Optional[AudioCallback]
    on_session_created: Optional[SessionCreatedCallback]
    on_session_ended: Optional[SessionEndedCallback]
    on_error: Optional[ErrorCallback]
    on_function_call: Optional[FunctionCallCallback]

    # -- Lifecycle ---------------------------------------------------------
    async def connect(
        self,
        call_id: str,
        patient_name: str,
        patient_language: str = "en",
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
    ) -> bool: ...

    async def disconnect(self) -> None: ...

    # -- Audio + control ---------------------------------------------------
    async def send_audio(self, audio_data: bytes) -> None: ...
    async def commit_audio(self) -> None: ...
    async def start_response(self) -> None: ...
    async def cancel_response(self) -> None: ...
    async def start_conversation(self) -> None: ...
    async def send_function_result(self, call_id: str, result: dict) -> None: ...

    @property
    def is_connected(self) -> bool: ...


# ---------------------------------------------------------------------------
# Tool schema conversion
# ---------------------------------------------------------------------------
# We author tools in the OpenAI-style canonical format used by
# app.prompts.attorney_cold_call.TOOLS:
#
#   { "type": "function", "name": ..., "description": ..., "parameters": {...} }
#
# Gemini Live wants `function_declarations` with a slightly different shape.
# Tool names and argument schemas are identical so we can round-trip without
# loss; only the outer wrapping changes.


def openai_tools_to_gemini(tools: list[dict]) -> list[dict]:
    """Convert canonical OpenAI-style tool list to Gemini Live function_declarations.

    Gemini wires tools into `setup.tools = [{"function_declarations": [...]}]`.
    Each declaration is `{"name", "description", "parameters"}` with a JSON
    Schema subset (mostly aligned with OpenAI's format — no `$ref`, limited
    types, no `anyOf`).

    We pass `parameters` through verbatim; the canonical schemas in the
    autocaller use only the supported subset (type, properties, enum,
    required, minimum, maximum, description).
    """
    decls: list[dict] = []
    for t in tools:
        if t.get("type") != "function":
            continue
        name = t.get("name")
        if not name:
            continue
        decls.append({
            "name": name,
            "description": t.get("description", ""),
            "parameters": t.get("parameters") or {"type": "object", "properties": {}},
        })
    return [{"function_declarations": decls}] if decls else []
