"""Synthesize voicemail audio with Gemini TTS and serve it back to the carrier.

Why this exists
---------------
Carrier `<Say>` (Twilio) / `/actions/speak` (Telnyx) produces a robotic
Polly voice. Gemini Live voices sound natural but the Live WS is
unreliable for voicemails (loops, clips, missing end_call). This module
splits those concerns:

  1. Synthesize the canonical VM script with Gemini's non-realtime TTS
     API — returns complete audio, no streaming, no turn-taking.
  2. Save it under /audio/vm/{call_id}.wav.
  3. Hand the carrier a URL — let the carrier do what it's good at:
     deterministically stream the audio and hang up.

Gemini's TTS endpoint returns 24 kHz signed 16-bit PCM. Twilio and
Telnyx both accept standard WAV, so we wrap the PCM in a WAV header and
serve it as .wav — no MP3 encoding required.

Fallback chain: if TTS synthesis fails for any reason, `synthesize_vm_audio`
returns None and the caller falls back to the existing carrier-TTS path
(robotic Polly/Alice) — reliability of the hangup itself is unchanged.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import struct
from pathlib import Path
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


# Gemini TTS — non-realtime, returns complete audio. Distinct model from
# the gemini-3.1-flash-live-preview we use for live calls.
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GEMINI_TTS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_TTS_MODEL}:generateContent"
)

# PCM format Gemini TTS returns.
_PCM_RATE_HZ = 24000
_PCM_CHANNELS = 1
_PCM_BITS = 16

# Where synthesized audio lives on disk. Served at /audio/vm/{call_id}.wav
# via the StaticFiles mount in app/main.py.
_AUDIO_ROOT = Path(__file__).resolve().parent.parent / "audio"
_VM_DIR = _AUDIO_ROOT / "vm"
_VM_DIR.mkdir(parents=True, exist_ok=True)


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = _PCM_RATE_HZ) -> bytes:
    """Wrap raw PCM16LE in a RIFF/WAVE header. No external deps."""
    num_samples = len(pcm_bytes) // 2
    byte_rate = sample_rate * _PCM_CHANNELS * (_PCM_BITS // 8)
    block_align = _PCM_CHANNELS * (_PCM_BITS // 8)
    data_size = len(pcm_bytes)
    fmt_chunk_size = 16
    riff_size = 4 + (8 + fmt_chunk_size) + (8 + data_size)
    header = (
        b"RIFF"
        + struct.pack("<I", riff_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", fmt_chunk_size)
        + struct.pack("<H", 1)             # PCM
        + struct.pack("<H", _PCM_CHANNELS)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", _PCM_BITS)
        + b"data"
        + struct.pack("<I", data_size)
    )
    return header + pcm_bytes


async def _fetch_tts_pcm(script: str, voice_name: str) -> Optional[bytes]:
    """Call Gemini TTS. Returns raw PCM16LE @ 24 kHz, or None on failure."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("[vm_audio] GEMINI_API_KEY not set; can't synthesize")
        return None

    body = {
        "contents": [{"parts": [{"text": script}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice_name},
                },
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GEMINI_TTS_URL,
                params={"key": api_key},
                json=body,
                headers={"Content-Type": "application/json"},
            )
    except Exception as e:
        logger.warning("[vm_audio] TTS request raised: %s", e)
        return None

    if resp.status_code >= 300:
        logger.warning(
            "[vm_audio] TTS HTTP %s: %s",
            resp.status_code, resp.text[:300],
        )
        return None

    try:
        data = resp.json()
    except Exception as e:
        logger.warning("[vm_audio] TTS response parse failed: %s", e)
        return None

    try:
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") or []
        inline = parts[0].get("inlineData") or parts[0].get("inline_data") or {}
        b64 = inline.get("data")
        if not b64:
            logger.warning("[vm_audio] TTS response had no inlineData: %s", str(data)[:300])
            return None
        return base64.b64decode(b64)
    except Exception as e:
        logger.warning("[vm_audio] TTS response extract failed: %s", e)
        return None


async def synthesize_vm_audio(
    script: str,
    call_id: str,
    voice_name: Optional[str] = None,
) -> Optional[str]:
    """Synthesize a voicemail audio file. Returns the public HTTPS URL
    the carrier should fetch, or None if synthesis failed (caller should
    fall back to the built-in carrier TTS).

    `voice_name` defaults to the active Gemini Live voice so the VM
    sounds like the same "Alex" the rest of the call used. Pass
    explicit "Aoede" / "Puck" / etc. to override.
    """
    if not script:
        return None

    voice = (voice_name or await _resolve_live_voice()).strip() or "Aoede"

    pcm = await _fetch_tts_pcm(script, voice)
    if pcm is None or len(pcm) < 1000:  # < 1 KB is almost certainly a TTS failure
        return None

    wav_bytes = _pcm16_to_wav(pcm)
    out_path = _VM_DIR / f"{call_id}.wav"
    try:
        await asyncio.to_thread(out_path.write_bytes, wav_bytes)
    except Exception as e:
        logger.warning("[vm_audio] write failed: %s", e)
        return None

    public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not public_base:
        logger.warning(
            "[vm_audio] PUBLIC_BASE_URL not set; carrier won't be able "
            "to fetch the audio file"
        )
        return None

    url = f"{public_base}/audio/vm/{call_id}.wav"
    logger.info(
        "[vm_audio] synthesized %s for call=%s (voice=%s, %d bytes wav)",
        url, call_id, voice, len(wav_bytes),
    )
    return url


async def _resolve_live_voice() -> str:
    """Pull the configured Gemini Live voice from system_settings, so the
    VM voice matches the call voice. Safe fallback to Aoede on any error."""
    try:
        from app.providers import get_settings_provider
        settings = await get_settings_provider().get_settings()
        cfg = (getattr(settings, "voice_config", None) or {}).get("gemini") or {}
        voice = str(cfg.get("voice") or "").strip()
        if voice:
            return voice
    except Exception as e:
        logger.debug("[vm_audio] voice_config lookup failed: %s", e)
    return os.getenv("GEMINI_VOICE", "Aoede")


def cleanup_vm_audio(call_id: str) -> None:
    """Remove the synthesized file once the call has ended. Called from
    the orchestrator's end-of-call path. Best-effort — file may already
    be gone if the retention sweep ran first."""
    try:
        (_VM_DIR / f"{call_id}.wav").unlink(missing_ok=True)
    except Exception as e:
        logger.debug("[vm_audio] cleanup failed for %s: %s", call_id, e)


def sweep_stale(max_age_seconds: int = 3600) -> int:
    """Delete synthesized VM audio older than `max_age_seconds`.

    Runs occasionally from the reconciler. Keeps the disk bounded
    without relying on cleanup_vm_audio() always running — some
    failure paths skip the explicit cleanup call.
    """
    import time
    now = time.time()
    removed = 0
    try:
        for p in _VM_DIR.glob("*.wav"):
            try:
                age = now - p.stat().st_mtime
                if age > max_age_seconds:
                    p.unlink()
                    removed += 1
            except Exception:
                continue
    except Exception as e:
        logger.debug("[vm_audio] sweep failed: %s", e)
    return removed
