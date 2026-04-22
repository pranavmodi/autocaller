"""Voice preview endpoint.

GET /api/voice/preview/{provider}/{voice} → audio bytes for that voice
saying a short canonical phrase. Lets the operator hear what each voice
sounds like before picking one in the /system panel.

OpenAI: `audio.speech.create` with `gpt-4o-mini-tts` — supports the full
Realtime voice set (tts-1 rejects `ballad` / `verse`). Returns MP3.

Gemini: opens a short-lived Live WS session with the target voice,
sends a text prompt, captures `audioDelta` events for ~5 seconds, wraps
the PCM16@24kHz in a WAV header. Returns WAV.

Per-voice results are cached in memory (process lifetime) so repeated
clicks don't re-bill the provider. Cache is keyed on (provider, voice,
phrase) so if we change the canonical phrase, it re-generates.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import struct
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.voice.gemini_live import (
    DEFAULT_MODEL as GEMINI_DEFAULT_MODEL,
    GEMINI_LIVE_HOST,
    GEMINI_LIVE_PATH,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


OPENAI_VOICES = {
    "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse",
}
GEMINI_VOICES = {
    "Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Zephyr",
}

# Same phrase both providers say — short, representative of cold-call
# opener material so the operator hears the voice in the context it
# will actually be used.
PREVIEW_PHRASE = (
    "Hi, this is Alex at Possible Minds. I'll keep this short — "
    "quick context on what we're doing."
)

# In-memory cache: (provider, voice, phrase) → (mime_type, bytes).
_cache: dict[tuple[str, str, str], tuple[str, bytes]] = {}


async def _openai_preview(voice: str) -> tuple[str, bytes]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY not set")
    # OpenAI's TTS is HTTP — /v1/audio/speech. One round-trip, MP3 out.
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                # gpt-4o-mini-tts accepts the full Realtime voice set
                # (alloy, ash, ballad, coral, echo, sage, shimmer, verse);
                # the older tts-1 rejects ballad/verse.
                "model": "gpt-4o-mini-tts",
                "voice": voice,
                "input": PREVIEW_PHRASE,
                "response_format": "mp3",
            },
        )
    if resp.status_code >= 300:
        raise HTTPException(
            502,
            f"OpenAI TTS HTTP {resp.status_code}: {resp.text[:300]}",
        )
    return "audio/mpeg", resp.content


def _pcm16_24k_to_wav(pcm: bytes) -> bytes:
    """Wrap raw PCM16 LE @ 24kHz mono in a WAV container for <audio>."""
    n_channels = 1
    sampwidth = 2  # int16
    framerate = 24_000
    n_frames = len(pcm) // sampwidth
    byte_rate = framerate * n_channels * sampwidth
    block_align = n_channels * sampwidth
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ", 16, 1, n_channels, framerate, byte_rate, block_align, 16,
    )
    data_chunk = struct.pack("<4sI", b"data", len(pcm)) + pcm
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


async def _gemini_preview(voice: str) -> tuple[str, bytes]:
    """Standalone Gemini Live preview session — mirrors the setup in
    GeminiLiveBackend._send_setup but pins `voice` (bypasses the
    settings-voice override that would otherwise make every preview
    sound like the default).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY not set")

    model = GEMINI_DEFAULT_MODEL
    url = f"wss://{GEMINI_LIVE_HOST}{GEMINI_LIVE_PATH}?key={api_key}"

    audio_chunks: list[bytes] = []
    turn_done = asyncio.Event()

    try:
        async with websockets.connect(url) as ws:
            # 1. Setup — same shape as production connect, stripped to
            #    the minimum needed to generate audio output.
            await ws.send(json.dumps({
                "setup": {
                    "model": f"models/{model}",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {"voiceName": voice},
                            }
                        },
                    },
                    "systemInstruction": {
                        "parts": [{
                            "text": (
                                "Say exactly the text the user sends. "
                                "No introduction, no follow-up, no questions."
                            ),
                        }],
                    },
                    "inputAudioTranscription": {},
                    "outputAudioTranscription": {},
                }
            }))

            # 2. Wait for setupComplete.
            try:
                first = await asyncio.wait_for(ws.recv(), timeout=10.0)
                if isinstance(first, bytes):
                    first = first.decode("utf-8", errors="replace")
                try:
                    first_data = json.loads(first)
                except Exception:
                    first_data = {}
                if not (first_data.get("setupComplete") or "setupComplete" in first):
                    logger.warning(
                        "[voice-preview] unexpected first Gemini message: %s",
                        str(first)[:200],
                    )
            except asyncio.TimeoutError:
                raise HTTPException(502, "Gemini Live setup timed out")

            # 3. Send the text prompt.
            # Gemini Live rejects clientContent.turns[] with 'invalid
            # argument'; realtimeInput.text is the working path.
            await ws.send(json.dumps({
                "realtimeInput": {
                    "text": (
                        f"[System: say EXACTLY this sentence, nothing else, "
                        f"no intro, no follow-up]: {PREVIEW_PHRASE}"
                    ),
                }
            }))

            # 4. Read until turnComplete or 15s pass. Collect audio as
            #    it arrives.
            async def _drain() -> None:
                try:
                    while True:
                        msg = await ws.recv()
                        if isinstance(msg, bytes):
                            try:
                                msg = msg.decode("utf-8")
                            except UnicodeDecodeError:
                                continue
                        try:
                            payload = json.loads(msg)
                        except Exception:
                            continue
                        sc = payload.get("serverContent") or {}
                        model_turn = sc.get("modelTurn") or {}
                        for part in (model_turn.get("parts") or []):
                            inline = part.get("inlineData") or {}
                            mime = inline.get("mimeType") or ""
                            if mime.startswith("audio/"):
                                b64 = inline.get("data") or ""
                                if b64:
                                    try:
                                        audio_chunks.append(base64.b64decode(b64))
                                    except Exception:
                                        pass
                        if sc.get("turnComplete") or sc.get("generationComplete"):
                            turn_done.set()
                            return
                except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
                    return

            drainer = asyncio.create_task(_drain())
            try:
                await asyncio.wait_for(turn_done.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                pass
            drainer.cancel()
            try:
                await drainer
            except (asyncio.CancelledError, Exception):
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            502, f"Gemini Live preview failed: {type(e).__name__}: {e}"
        )

    if not audio_chunks:
        raise HTTPException(502, "Gemini Live returned no audio for voice preview")

    pcm = b"".join(audio_chunks)
    wav = _pcm16_24k_to_wav(pcm)
    return "audio/wav", wav


@router.get("/preview/{provider}/{voice}")
async def voice_preview(provider: str, voice: str):
    """Return a short audio clip of `voice` saying the canonical phrase."""
    provider = provider.strip().lower()
    if provider == "openai":
        if voice not in OPENAI_VOICES:
            raise HTTPException(400, f"Unknown OpenAI voice: {voice}")
    elif provider == "gemini":
        if voice not in GEMINI_VOICES:
            raise HTTPException(400, f"Unknown Gemini voice: {voice}")
    else:
        raise HTTPException(400, f"Unknown provider: {provider}")

    cache_key = (provider, voice, PREVIEW_PHRASE)
    if cache_key in _cache:
        mime, data = _cache[cache_key]
    else:
        if provider == "openai":
            mime, data = await _openai_preview(voice)
        else:
            mime, data = await _gemini_preview(voice)
        _cache[cache_key] = (mime, data)

    headers = {
        # Cache in the browser for a day — it's a static TTS clip.
        "Cache-Control": "public, max-age=86400",
    }
    return Response(content=data, media_type=mime, headers=headers)
