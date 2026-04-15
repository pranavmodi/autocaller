"""Voice-backend factory.

Selection precedence (highest wins):
    1. explicit `provider` arg (per-call override from CLI / API body)
    2. DB setting `system_settings.voice_provider`
    3. env var `VOICE_PROVIDER`
    4. default "openai"

The caller passes the decided provider string; resolving DB / env defaults
is the orchestrator's job (it already loads SystemSettings for every call).
"""
from __future__ import annotations

import os
from typing import Optional

from .base import BACKEND_OPENAI, BACKEND_GEMINI, RealtimeVoiceBackend


def get_voice_backend(
    provider: str,
    *,
    audio_format: str,
    verbose: bool = False,
    model: Optional[str] = None,
) -> RealtimeVoiceBackend:
    """Instantiate a backend by provider name."""
    p = (provider or "").strip().lower() or BACKEND_OPENAI
    if p == BACKEND_OPENAI:
        from .openai_realtime import OpenAIRealtimeBackend
        return OpenAIRealtimeBackend(audio_format=audio_format, verbose=verbose, model=model)
    if p == BACKEND_GEMINI:
        from .gemini_live import GeminiLiveBackend
        return GeminiLiveBackend(audio_format=audio_format, verbose=verbose, model=model)
    raise ValueError(f"Unknown voice provider: {provider!r} (expected 'openai' or 'gemini')")


def resolve_default_provider() -> str:
    """Resolve the env-level default provider (DB/per-call overrides are
    applied by the orchestrator, not here)."""
    env_val = (os.getenv("VOICE_PROVIDER") or "").strip().lower()
    if env_val in (BACKEND_OPENAI, BACKEND_GEMINI):
        return env_val
    return BACKEND_OPENAI
