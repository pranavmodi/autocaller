"""Tests for provider/carrier resolution helpers."""
import sys
import types
import pytest

from app.services.carrier import _twilio_hangup_noop, get_carrier, resolve_carrier_name
from app.services.voice import factory as voice_factory


def test_resolve_carrier_name_precedence_and_validation():
    assert resolve_carrier_name("telnyx", "twilio", "twilio") == "telnyx"
    assert resolve_carrier_name("bad", "telnyx", "twilio") == "telnyx"
    assert resolve_carrier_name(None, "bad", "telnyx") == "telnyx"
    assert resolve_carrier_name(None, None, None) == "twilio"


def test_get_carrier_defaults_unknown_to_twilio():
    assert get_carrier(None).name == "twilio"
    assert get_carrier("unknown").name == "twilio"
    assert get_carrier(" telnyx ").name == "telnyx"


def test_resolve_default_voice_provider(monkeypatch):
    monkeypatch.delenv("VOICE_PROVIDER", raising=False)
    assert voice_factory.resolve_default_provider() == "openai"

    monkeypatch.setenv("VOICE_PROVIDER", " GEMINI ")
    assert voice_factory.resolve_default_provider() == "gemini"

    monkeypatch.setenv("VOICE_PROVIDER", "bad")
    assert voice_factory.resolve_default_provider() == "openai"


def test_get_voice_backend_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown voice provider"):
        voice_factory.get_voice_backend("bad", audio_format="g711_ulaw")


def test_get_voice_backend_instantiates_openai_and_gemini(monkeypatch):
    class FakeOpenAIBackend:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeGeminiBackend:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    openai_module = types.ModuleType("app.services.voice.openai_realtime")
    openai_module.OpenAIRealtimeBackend = FakeOpenAIBackend
    gemini_module = types.ModuleType("app.services.voice.gemini_live")
    gemini_module.GeminiLiveBackend = FakeGeminiBackend
    monkeypatch.setitem(sys.modules, "app.services.voice.openai_realtime", openai_module)
    monkeypatch.setitem(sys.modules, "app.services.voice.gemini_live", gemini_module)

    openai = voice_factory.get_voice_backend(
        "openai",
        audio_format="g711_ulaw",
        verbose=True,
        model="m1",
        voice_name="v1",
    )
    gemini = voice_factory.get_voice_backend("gemini", audio_format="pcm16")

    assert isinstance(openai, FakeOpenAIBackend)
    assert openai.kwargs == {
        "audio_format": "g711_ulaw",
        "verbose": True,
        "model": "m1",
        "voice_name": "v1",
    }
    assert isinstance(gemini, FakeGeminiBackend)


def test_twilio_hangup_noops_without_credentials(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)

    assert _twilio_hangup_noop("CA123") is None
