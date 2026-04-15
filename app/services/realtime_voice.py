"""Backward-compat shim.

The OpenAI Realtime implementation moved to `app.services.voice.openai_realtime`
as part of the voice-provider abstraction. Existing imports of
`RealtimeVoiceService` from this module continue to work — they now get the
new `OpenAIRealtimeBackend` (which is API-compatible).

Prefer `from app.services.voice import get_voice_backend` in new code.
"""
from app.services.voice.openai_realtime import OpenAIRealtimeBackend

# Legacy name — kept so orchestrator / simulator / twilio_voice_service
# imports don't break during the abstraction rollout.
RealtimeVoiceService = OpenAIRealtimeBackend

__all__ = ["RealtimeVoiceService", "OpenAIRealtimeBackend"]
