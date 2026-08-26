"""No-AI voice backend for browser-operated carrier calls."""
from __future__ import annotations

from typing import Optional


class OperatorVoiceBackend:
    """Keeps the carrier media bridge alive without starting an AI session."""

    provider = "operator"
    model = "browser-operator"

    def __init__(self, *, audio_format: str = "g711_ulaw", **_: object):
        self.audio_format = audio_format
        self.on_transcript = None
        self.on_audio = None
        self.on_session_created = None
        self.on_session_ended = None
        self.on_error = None
        self.on_function_call = None
        self._connected = False

    async def connect(
        self,
        call_id: str,
        patient_name: str,
        patient_language: str = "en",
        *,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict]] = None,
    ) -> bool:
        del call_id, patient_name, patient_language, system_prompt, tools
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_audio(self, audio_data: bytes) -> None:
        del audio_data

    async def commit_audio(self) -> None:
        return None

    async def start_response(self) -> None:
        return None

    async def cancel_response(self) -> None:
        return None

    async def start_conversation(self, language: str = "en") -> None:
        del language

    async def send_function_result(self, call_id: str, result: dict) -> None:
        del call_id, result

    async def send_system_nudge(self, text: str) -> None:
        del text

    @property
    def is_connected(self) -> bool:
        return self._connected
