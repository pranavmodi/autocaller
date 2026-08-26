"""Realtime voice provider abstraction.

Exports:
    RealtimeVoiceBackend   — Protocol every provider conforms to
    get_voice_backend      — factory returning a concrete backend
    BACKEND_OPENAI / BACKEND_GEMINI / BACKEND_OPERATOR — backend constants
"""
from .base import RealtimeVoiceBackend, BACKEND_OPENAI, BACKEND_GEMINI, BACKEND_OPERATOR
from .factory import get_voice_backend

__all__ = [
    "RealtimeVoiceBackend",
    "BACKEND_OPENAI",
    "BACKEND_GEMINI",
    "BACKEND_OPERATOR",
    "get_voice_backend",
]
