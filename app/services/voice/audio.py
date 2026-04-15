"""Audio transcoding helpers between Twilio (mulaw 8kHz) and Gemini (PCM16).

Twilio media streams use 8kHz mulaw. Gemini Live wants 16kHz PCM16 in and
emits 24kHz PCM16 out. OpenAI Realtime takes mulaw natively on its
`g711_ulaw` format so we only need transcoding when Gemini is in play.

Uses `audioop` (stdlib through 3.12; `audioop-lts` package covers 3.13+).
State tuples for `audioop.ratecv` MUST be preserved across chunks per
stream direction, otherwise we get clicks at chunk boundaries.
"""
from __future__ import annotations

import audioop
from typing import Optional, Tuple

# audioop rate-conversion state is None on the first chunk, then carries
# the resampler's filter tail for subsequent chunks.
RatecvState = Optional[Tuple[int, Tuple[Tuple[int, int], ...]]]


class AudioTranscoder:
    """Stateful transcoder for one call. Holds ratecv state in each direction."""

    def __init__(self) -> None:
        # Inbound: Twilio mulaw 8kHz → Gemini PCM16 16kHz
        self._in_state: RatecvState = None
        # Outbound: Gemini PCM16 24kHz → Twilio mulaw 8kHz
        self._out_state: RatecvState = None

    def mulaw8k_to_pcm16k(self, mulaw: bytes) -> bytes:
        """Twilio inbound → Gemini. Decodes mulaw to linear PCM, then
        upsamples 8kHz→16kHz."""
        if not mulaw:
            return b""
        # mulaw → 16-bit linear PCM at 8kHz
        pcm8k = audioop.ulaw2lin(mulaw, 2)
        # 8kHz → 16kHz
        pcm16k, self._in_state = audioop.ratecv(
            pcm8k, 2, 1, 8000, 16000, self._in_state
        )
        return pcm16k

    def pcm24k_to_mulaw8k(self, pcm24k: bytes) -> bytes:
        """Gemini outbound → Twilio. Downsamples 24kHz PCM16 to 8kHz, then
        encodes mulaw."""
        if not pcm24k:
            return b""
        pcm8k, self._out_state = audioop.ratecv(
            pcm24k, 2, 1, 24000, 8000, self._out_state
        )
        return audioop.lin2ulaw(pcm8k, 2)

    def pcm16k_passthrough(self, pcm16k: bytes) -> bytes:
        """Browser → Gemini. Browser WS already sends 16kHz PCM16 in
        practice — this is here as a named no-op."""
        return pcm16k

    def pcm24k_to_pcm16k(self, pcm24k: bytes) -> bytes:
        """Gemini → browser (when browser expects 16kHz). Most browsers are
        happy with 24kHz; this exists for completeness."""
        if not pcm24k:
            return b""
        pcm16k, _state = audioop.ratecv(
            pcm24k, 2, 1, 24000, 16000, None
        )
        return pcm16k
