"""Telnyx outbound call + media stream bridge.

Parallel to `twilio_voice_service.py`. Telnyx exposes a TeXML REST API that
mirrors Twilio's Programmable Voice API — same parameters, near-identical
media-stream protocol over a WebSocket. We lean on that to keep this file
a thin mirror of the Twilio path; the orchestrator routes to either carrier
through `app/services/carrier.py`.

Telnyx TeXML REST:
    POST https://api.telnyx.com/v2/texml/calls/{texml_app_id}
    Authorization: Bearer <TELNYX_API_KEY>
    Form body: To, From, Url, StatusCallback, Record, ...

(Yes, Telnyx does also expose the Twilio-compat /v2/texml/Accounts/{sid}/Calls
form, but that path requires the internal account SID which isn't always
visible in the portal. The connection-id form above works everywhere an
operator has a TeXML App configured, which is our case.)

Media stream events (same names as Twilio, with minor field differences):
    {"event": "connected"}
    {"event": "start",  "start":  {"stream_id", "call_control_id", ...}}
    {"event": "media",  "media":  {"payload": "<base64 mulaw>"}}
    {"event": "stop",   "stop":   {"reason": "..."}}
    {"event": "dtmf",   "dtmf":   {"digit": "N"}}     (inbound from Telnyx)

When sending audio back we use the same event shape Twilio uses so the
bridge code is nearly identical; Telnyx accepts both `streamSid`
(Twilio-compat) and `stream_id` keys on outbound media frames.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from typing import Optional

import httpx
from fastapi import WebSocket

from app.services.realtime_voice import RealtimeVoiceService

logger = logging.getLogger(__name__)


TELNYX_API_BASE = "https://api.telnyx.com/v2"


# Registry keyed by stream_id (same pattern as Twilio).
_pending_bridges: dict[str, "TelnyxMediaBridge"] = {}


def register_bridge(stream_id: str, bridge: "TelnyxMediaBridge"):
    _pending_bridges[stream_id] = bridge


def pop_bridge(stream_id: str) -> Optional["TelnyxMediaBridge"]:
    return _pending_bridges.pop(stream_id, None)


def _api_key() -> str:
    key = os.getenv("TELNYX_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Telnyx is not configured. Set TELNYX_API_KEY (V2 bearer key)."
        )
    return key


def _from_number() -> str:
    n = os.getenv("TELNYX_FROM_NUMBER", "")
    if not n:
        raise RuntimeError("TELNYX_FROM_NUMBER not set.")
    return n


def _texml_app_id() -> str:
    """Telnyx TeXML App (connection) ID — required to place outbound calls.

    The TeXML App wraps the number, webhooks, OVP, and codecs. We POST
    outbound calls to /v2/texml/calls/{texml_app_id}. Configured at setup
    time via `TELNYX_TEXML_APP_ID` in `.env`.
    """
    v = os.getenv("TELNYX_TEXML_APP_ID", "").strip()
    if not v:
        raise RuntimeError(
            "TELNYX_TEXML_APP_ID is not set. Find it in the Telnyx portal under "
            "Voice → Programmable Voice → TeXML Applications → autocaller → App ID."
        )
    return v


class TelnyxMediaBridge:
    """Bridges a Telnyx media stream WebSocket with a RealtimeVoiceService.

    Mirrors `TwilioMediaBridge`. Telnyx's WS protocol is near-identical to
    Twilio's Media Streams — same event names, same base64 mulaw payloads,
    slightly different field names inside `start` (`stream_id` /
    `call_control_id` vs. `streamSid` / `callSid`).
    """

    def __init__(self, voice_service: RealtimeVoiceService, verbose: bool = False):
        self.voice_service = voice_service
        self._verbose = verbose
        self._ws: Optional[WebSocket] = None
        self._stream_sid: Optional[str] = None  # Telnyx calls it stream_id
        self._call_sid: Optional[str] = None    # Telnyx calls it call_control_id
        self._connected = asyncio.Event()
        self._ai_audio_muted: bool = False
        self._listeners: set[WebSocket] = set()

        self._original_on_audio = voice_service.on_audio
        voice_service.on_audio = self._forward_audio_to_carrier
        self._media_codec: Optional[str] = None  # set from start event

        # AI audio is paced to listeners at real-time (8000 bps µ-law)
        # even when the voice backend bursts it faster. See the comment
        # on `_broadcast_audio` and `_ai_pacer_loop` for why.
        self._ai_pacer_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._ai_pacer_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Listener fan-out (identical to Twilio bridge)
    # ------------------------------------------------------------------

    def add_listener(self, ws: WebSocket):
        self._listeners.add(ws)

    def remove_listener(self, ws: WebSocket):
        self._listeners.discard(ws)

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def _broadcast_audio(self, mulaw: bytes, source: str = "unknown"):
        """Fan out µ-law → PCM16 to listeners. `source` is "ai" or "caller".

        Caller audio is sent directly. AI audio goes through the pacer
        queue — UNLESS `_ai_audio_muted` is set (IVR nav / human
        takeover), in which case we drop it entirely instead of
        queuing. Reason: during human takeover the operator does NOT
        want to hear the AI reasoning in their browser — it's noise
        that makes it hard to follow the prospect's side. During IVR
        nav, same thing. Dropping at broadcast keeps the listener clean.
        """
        if source == "ai":
            if self._ai_audio_muted:
                return
            await self._ai_pacer_queue.put(mulaw)
            if self._ai_pacer_task is None or self._ai_pacer_task.done():
                self._ai_pacer_task = asyncio.create_task(self._ai_pacer_loop())
            return
        await self._send_to_listeners(mulaw, source)

    async def _send_to_listeners(self, mulaw: bytes, source: str):
        if not self._listeners:
            return
        try:
            import audioop
            pcm16 = audioop.ulaw2lin(mulaw, 2)
        except Exception as e:
            logger.debug("audioop.ulaw2lin failed: %s", e)
            return
        # 2-byte header for PCM16 alignment: [tag, 0xAC magic]. The magic
        # byte lets a stale client drop misframed data instead of playing
        # garbage. Tag: 0x01=caller, 0x02=ai.
        tag = b"\x02" if source == "ai" else b"\x01"
        frame = tag + b"\xac" + pcm16
        dead: list[WebSocket] = []
        for ws in list(self._listeners):
            try:
                await ws.send_bytes(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._listeners.discard(ws)

    async def _ai_pacer_loop(self):
        """Drain the AI audio queue at real-time (8000 bps µ-law).

        Emits one 20ms frame (160 bytes) per tick to listeners. This is
        the same pacing the carrier (Telnyx/Twilio) applies before
        playing AI audio to the prospect, so the listener hears what the
        prospect hears, in sync with the caller-side stream. When the
        queue is empty the loop just sleeps — cheap, keeps the pacer
        ready for the next AI utterance.

        If the queue ever accumulates > MAX_BACKLOG_BYTES of unsent
        audio (pathological case: listener stalled or AI produced
        catastrophic excess), drop the oldest backlog to bound memory
        and resync. Normal bursts (1-3 seconds) are fine.
        """
        import time
        FRAME_BYTES = 160
        FRAME_DT = 0.02
        MAX_BACKLOG_BYTES = 8000 * 10  # 10 seconds of audio
        buf = bytearray()
        t_next = time.monotonic()
        try:
            while True:
                # Non-blocking drain of any chunks that arrived.
                while True:
                    try:
                        chunk = self._ai_pacer_queue.get_nowait()
                        buf.extend(chunk)
                    except asyncio.QueueEmpty:
                        break
                if len(buf) > MAX_BACKLOG_BYTES:
                    drop = len(buf) - MAX_BACKLOG_BYTES
                    del buf[:drop]
                    logger.warning(
                        "[TelnyxMedia] AI pacer backlog dropped %d bytes (listener stall?)",
                        drop,
                    )
                if len(buf) >= FRAME_BYTES:
                    frame = bytes(buf[:FRAME_BYTES])
                    del buf[:FRAME_BYTES]
                    await self._send_to_listeners(frame, source="ai")
                # Keep the loop on a 20ms cadence — using monotonic
                # target-time so sleep drift doesn't accumulate.
                t_next += FRAME_DT
                sleep_dt = t_next - time.monotonic()
                if sleep_dt < -0.2:
                    # Fell way behind (GC pause / heavy load). Resync.
                    t_next = time.monotonic()
                elif sleep_dt > 0:
                    await asyncio.sleep(sleep_dt)
                else:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("AI pacer loop crashed: %s", e)

    # ------------------------------------------------------------------
    # Audio paths
    # ------------------------------------------------------------------

    async def _forward_audio_to_carrier(self, audio_data: bytes):
        # Rate-limited diagnostic: bytes/sec of AI output + mute state,
        # so we can catch cases where the mute flag SHOULD be True but
        # audio is still reaching the carrier.
        import time
        now = time.monotonic()
        if not hasattr(self, "_ai_fwd_bytes"):
            self._ai_fwd_bytes_sent = 0
            self._ai_fwd_bytes_skipped = 0
            self._ai_fwd_last_log = now
        sent_to_carrier = (
            not self._ai_audio_muted and self._ws and self._stream_sid
        )
        if sent_to_carrier:
            payload = base64.b64encode(audio_data).decode("utf-8")
            msg = {
                "event": "media",
                "media": {
                    "payload": payload,
                },
            }
            try:
                await self._ws.send_json(msg)
            except Exception as e:
                print(f"[TelnyxMedia] OUTBOUND SEND ERROR: {e}")
            self._ai_fwd_bytes_sent += len(audio_data)
        else:
            self._ai_fwd_bytes_skipped += len(audio_data)
        if now - self._ai_fwd_last_log >= 2.0:
            if self._ai_fwd_bytes_sent or self._ai_fwd_bytes_skipped:
                print(
                    f"[TelnyxMedia] AI→carrier: sent={self._ai_fwd_bytes_sent}B "
                    f"skipped={self._ai_fwd_bytes_skipped}B "
                    f"(ai_audio_muted={self._ai_audio_muted})"
                )
            self._ai_fwd_bytes_sent = 0
            self._ai_fwd_bytes_skipped = 0
            self._ai_fwd_last_log = now

        await self._broadcast_audio(audio_data, source="ai")

        if self._original_on_audio:
            await self._original_on_audio(audio_data)

    def mute_ai_audio(self) -> None:
        self._ai_audio_muted = True
        if self._verbose:
            logger.info("[TelnyxMedia] AI audio MUTED (IVR nav active)")

    def unmute_ai_audio(self) -> None:
        self._ai_audio_muted = False
        if self._verbose:
            logger.info("[TelnyxMedia] AI audio UNMUTED")

    async def inject_inbound_audio(self, mulaw: bytes) -> None:
        """Inject operator audio (µ-law 8kHz mono) into the Telnyx media
        stream during human-takeover. Mirrors the Twilio bridge.
        """
        if not self._ws or not self._stream_sid or not mulaw:
            return
        payload = base64.b64encode(mulaw).decode("utf-8")
        msg = {
            "event": "media",
            "media": {"payload": payload},
        }
        try:
            await self._ws.send_json(msg)
        except Exception as e:
            logger.error(f"inject_inbound_audio (telnyx) failed: {e}")

    async def send_dtmf(self, digit: str) -> None:
        """Send a single DTMF tone over the PSTN leg.

        Telnyx's TeXML Media Streams WebSocket does not accept outbound
        DTMF — digits sent via {"event":"dtmf"} frames on the WS are
        silently dropped and never reach the called party. We confirmed
        this the hard way on the Champ Law call: neither auto-navigator
        nor manual-operator DTMF was ever acknowledged by the IVR.

        The correct channel is the Telnyx Call Control REST action
        `POST /v2/calls/{call_control_id}/actions/send_dtmf`. That
        endpoint injects tones onto the actual PSTN leg and natively
        accepts multi-digit batches.
        """
        await self.send_dtmf_batch(digit)

    async def send_dtmf_batch(self, digits: str) -> bool:
        """Send one OR MORE DTMF tones via Telnyx Call Control.

        Telnyx's REST action accepts a full digit string and handles
        inter-digit pacing itself (default 250ms/tone). One REST call
        per batch — no need for per-digit WS events.

        Returns True on HTTP 2xx.
        """
        cleaned = "".join(c for c in (digits or "").strip() if c in "0123456789*#")
        if not cleaned:
            logger.warning("[TelnyxMedia] refusing DTMF batch %r (empty/invalid)", digits)
            return False
        if not self._call_sid:
            logger.warning(
                "[TelnyxMedia] DTMF %r dropped — no call_control_id yet",
                cleaned,
            )
            return False
        try:
            api_key = _api_key()
        except Exception as e:
            logger.error("[TelnyxMedia] DTMF %r dropped — API key missing: %s", cleaned, e)
            return False
        url = f"{TELNYX_API_BASE}/calls/{self._call_sid}/actions/send_dtmf"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {"digits": cleaned}
        # One retry — the operator saw a 400 on Champ Law today because the
        # first attempt raised a transient (empty-message) exception; the
        # second click succeeded without any other change. A silent retry
        # handles that without surfacing a failure to the UI.
        last_err: Optional[Exception] = None
        last_status: Optional[int] = None
        last_text: str = ""
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=body, headers=headers)
                if resp.status_code >= 400:
                    last_status = resp.status_code
                    last_text = resp.text[:200]
                    logger.warning(
                        "[TelnyxMedia] send_dtmf(%s) attempt %d HTTP %s: %s",
                        cleaned, attempt, resp.status_code, resp.text[:200],
                    )
                    if 500 <= resp.status_code < 600 and attempt == 1:
                        await asyncio.sleep(0.25)
                        continue
                    return False
                if self._verbose:
                    logger.info(
                        f"[TelnyxMedia] DTMF batch sent via Call Control: "
                        f"{cleaned} (attempt {attempt})"
                    )
                return True
            except Exception as e:
                last_err = e
                # Include type + repr so a bare exception with empty str()
                # still produces diagnosable output — previous logging
                # format ("raised: %s") printed nothing when str(e) was ''.
                logger.warning(
                    "[TelnyxMedia] DTMF batch %s attempt %d raised "
                    "%s: %s (repr=%r)",
                    cleaned, attempt, type(e).__name__, e, e,
                )
                if attempt == 1:
                    await asyncio.sleep(0.25)
                    continue
                break
        logger.error(
            "[TelnyxMedia] DTMF batch %s FAILED after retries. "
            "last_status=%s last_text=%r last_err=%r",
            cleaned, last_status, last_text, last_err,
        )
        return False

    async def handle_carrier_ws(self, websocket: WebSocket):
        """Handle an incoming Telnyx media stream WebSocket."""
        self._ws = websocket
        logger.info("Telnyx media stream WebSocket connected")

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                event = msg.get("event")

                if event == "connected":
                    if self._verbose:
                        logger.info("Telnyx stream connected")

                elif event == "start":
                    start = msg.get("start", {})
                    self._stream_sid = (
                        start.get("stream_id")
                        or start.get("streamSid")
                        or msg.get("stream_id")
                        or msg.get("streamSid")
                    )
                    self._call_sid = (
                        start.get("call_control_id")
                        or start.get("callSid")
                        or msg.get("call_control_id")
                        or msg.get("callSid")
                    )
                    media_fmt = start.get("media_format") or msg.get("media_format") or {}
                    self._media_codec = (media_fmt.get("encoding") or "PCMU").upper()
                    if self._verbose:
                        logger.info(
                            f"Telnyx stream started: stream_id={self._stream_sid} "
                            f"media_format={media_fmt}"
                        )
                    # Persist the call_control_id onto the CallLog row
                    # ASAP. The reconciler + force-hangup CLI need it
                    # to look the call up carrier-side. voice_service
                    # carries the call_id; resolve it lazily so we
                    # don't hard-require the CallLog provider here.
                    try:
                        cid = getattr(self.voice_service, "_call_id", None) or \
                              getattr(self.voice_service, "call_id", None)
                        if cid and self._call_sid:
                            from app.providers.call_log_provider import (
                                get_call_log_provider as _get_clp,
                            )
                            asyncio.create_task(
                                _get_clp().set_carrier_call_sid(cid, self._call_sid)
                            )
                    except Exception as e:
                        logger.debug(
                            "could not stamp carrier_call_sid: %s", e,
                        )
                    self._connected.set()

                elif event == "media":
                    media = msg.get("media", {})
                    track = media.get("track", "inbound")
                    payload = media.get("payload", "")
                    if not payload:
                        payload = msg.get("payload", "")
                    if payload:
                        audio_bytes = base64.b64decode(payload)
                        if track == "inbound":
                            # Caller audio → voice service. Keep feeding
                            # even during takeover/IVR-mute so
                            # transcription continues (transcript stays
                            # populated, silence watchdog sees activity).
                            # The AI's generated responses are blocked
                            # at the carrier-egress side (mute flag) and
                            # at the listener-broadcast side, so even
                            # though Gemini keeps reasoning, the
                            # prospect and operator don't hear it.
                            if self.voice_service.is_connected:
                                await self.voice_service.send_audio(audio_bytes)
                            # Broadcast caller-side to listeners
                            await self._broadcast_audio(audio_bytes, source="caller")
                        # Outbound track = our own AI audio echoed back;
                        # ignore it to avoid feedback loops.

                elif event == "stop":
                    reason = msg.get("stop", {}).get("reason", "unknown")
                    print(
                        f"[TelnyxMedia] stop event: reason={reason}, "
                        f"call={self._call_sid}"
                    )
                    break

                elif event not in ("connected", "start", "media", "mark", "dtmf"):
                    if self._verbose:
                        print(f"[TelnyxMedia] Unexpected event: {event}")

        except Exception as e:
            print(f"[TelnyxMedia] Bridge error: {type(e).__name__}: {e}")
        finally:
            self._ws = None
            self._connected.clear()
            if self._ai_pacer_task is not None and not self._ai_pacer_task.done():
                self._ai_pacer_task.cancel()
            self._ai_pacer_task = None
            for ws in list(self._listeners):
                try:
                    await ws.close(code=1000, reason="call ended")
                except Exception:
                    pass
            self._listeners.clear()

    async def wait_for_connection(self, timeout: float = 30.0) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


def place_telnyx_call(
    to_number: str,
    twiml_url: str,
    status_callback_url: Optional[str] = None,
    recording_status_callback_url: Optional[str] = None,
    enable_amd: bool = False,
) -> str:
    """Place an outbound call via Telnyx TeXML REST API. Returns Call SID.

    Mirrors `place_twilio_call`'s signature so the orchestrator can dispatch
    to either carrier with the same call site.
    """
    if os.getenv("ALLOW_TWILIO_CALLS", "false").lower() != "true":
        # Same safety gate as Twilio — there's no separate ALLOW_TELNYX_CALLS
        # flag because the operational gate is "is the agent allowed to dial
        # a real PSTN number right now," not a per-carrier toggle.
        raise RuntimeError(
            "Live calls are disabled. Set ALLOW_TWILIO_CALLS=true to enable."
        )

    api_key = _api_key()
    texml_app_id = _texml_app_id()
    from_number = _from_number()

    url = f"{TELNYX_API_BASE}/texml/calls/{texml_app_id}"
    data: dict[str, str] = {
        "To": to_number,
        "From": from_number,
        "Url": twiml_url,
    }
    if status_callback_url:
        data["StatusCallback"] = status_callback_url
        data["StatusCallbackMethod"] = "POST"
        data["StatusCallbackEvent"] = "answered completed"
    if recording_status_callback_url:
        data["Record"] = "true"
        data["RecordingChannels"] = "dual"
        data["RecordingStatusCallback"] = recording_status_callback_url
        data["RecordingStatusCallbackMethod"] = "POST"
        data["RecordingStatusCallbackEvent"] = "completed"
    if enable_amd:
        data["MachineDetection"] = "DetectMessageEnd"

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, data=data, headers=headers)

    if resp.status_code >= 400:
        raise RuntimeError(
            f"Telnyx call placement failed: HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    # Telnyx response shape varies by endpoint + account tier:
    #   TeXML:        {"call_sid": "v3:...", "from": "...", "status": "queued", "to": "..."}
    #   Call Control: {"data": {"call_control_id": "v3:..."}, "errors": [...]}
    # We try all known keys.
    data = body.get("data") or {}
    call_sid = (
        body.get("call_sid")
        or data.get("call_control_id")
        or data.get("sid")
        or body.get("sid")
        or ""
    )
    # Errors can appear even with a 200 response (e.g. pre-flight validation).
    if body.get("errors"):
        err = body["errors"][0]
        detail = err.get("detail", "")
        code = err.get("code") or body.get("telnyx_error", {}).get("error_code", "")
        raise RuntimeError(
            f"Telnyx call placement rejected [{code}]: {detail}"
        )
    if not call_sid:
        raise RuntimeError(
            f"Telnyx call placement succeeded but returned no call SID: {body}"
        )
    logger.info(f"Telnyx call placed: SID={call_sid}, to={to_number}")
    return call_sid


async def play_voicemail_and_hangup_telnyx(
    call_control_id: str,
    message: str,
    *,
    audio_url: Optional[str] = None,
) -> bool:
    """Play a VM via Telnyx Call Control, then hang up when done.

    When `audio_url` is provided (points to our Gemini-TTS WAV), use
    /actions/playback_start to stream it — natural voice. If the
    playback action errors or audio_url is missing, fall back to
    /actions/speak with Polly (robotic but reliable). Either way we
    then estimate duration and POST /actions/hangup.

    Not using the playback.ended / speak.ended webhooks for simplicity
    — the duration estimate is within 2-3s for a 30s script, and the
    buffer absorbs the error.
    """
    api_key = _api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    playback_url = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/playback_start"
    speak_url = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/speak"
    hangup_url = f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/hangup"

    played_natural = False
    if audio_url:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                pb_resp = await client.post(
                    playback_url,
                    headers=headers,
                    json={"audio_url": audio_url},
                )
            if pb_resp.status_code < 300:
                played_natural = True
                logger.info(
                    "Telnyx /playback_start ok for %s (url=%s)",
                    call_control_id, audio_url,
                )
            else:
                logger.warning(
                    "Telnyx /playback_start HTTP %s: %s — falling back to Polly",
                    pb_resp.status_code, pb_resp.text[:200],
                )
        except Exception as e:
            logger.warning(
                "Telnyx /playback_start raised %s — falling back to Polly", e,
            )

    if not played_natural:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                speak_resp = await client.post(
                    speak_url,
                    headers=headers,
                    json={
                        "payload": message,
                        "voice": "Polly.Joanna-Neural",
                        "language": "en-US",
                    },
                )
            if speak_resp.status_code >= 300:
                logger.error(
                    "Telnyx /speak failed %s: %s",
                    speak_resp.status_code, speak_resp.text[:300],
                )
                return False
        except Exception as e:
            logger.error("Telnyx /speak raised: %s", e)
            return False

    # Estimate playback duration + buffer. ~160 WPM = 2.67 wps.
    words = max(1, len(message.split()))
    est_seconds = max(18.0, words / 2.5) + 3.0
    try:
        await asyncio.sleep(est_seconds)
    except asyncio.CancelledError:
        # If the task gets cancelled (e.g., daemon shutdown), still try
        # to hang up to avoid leaving the call leg dangling.
        pass

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(hangup_url, headers=headers, json={})
        if resp.status_code >= 300:
            logger.warning(
                "Telnyx /hangup after VM %s HTTP %s: %s",
                call_control_id, resp.status_code, resp.text[:200],
            )
    except Exception as e:
        logger.warning("Telnyx /hangup after VM raised: %s", e)
    return True


def hangup_telnyx_call(call_sid: str) -> None:
    """Best-effort sync hangup (kept for back-compat paths that can't await).

    For the atomic-teardown path prefer `hangup_telnyx_call_async` which
    retries + returns a boolean ack so the orchestrator can gate
    `ended_at` on carrier confirmation. See `docs/production-readiness.md`
    Carrier Reconciliation section.
    """
    api_key = _api_key()
    url = f"{TELNYX_API_BASE}/calls/{call_sid}/actions/hangup"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json={}, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "Telnyx hangup %s failed: HTTP %s: %s",
                call_sid, resp.status_code, resp.text[:200],
            )
    except Exception as e:
        logger.warning("Telnyx hangup %s raised: %s", call_sid, e)


async def hangup_telnyx_call_async(call_sid: str) -> tuple[bool, str]:
    """Async hangup with one retry. Returns (ok, error_detail).

    `ok=True`: Telnyx returned 2xx or 404 (404 means the call is already
    gone from their side — effectively a success for our purposes).
    `ok=False`: both attempts failed; reconciler will sweep.
    """
    try:
        api_key = _api_key()
    except Exception as e:
        return False, f"api_key_missing: {e!r}"
    url = f"{TELNYX_API_BASE}/calls/{call_sid}/actions/hangup"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_err = ""
    last_status: Optional[int] = None
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={}, headers=headers)
            if resp.status_code < 300 or resp.status_code == 404:
                logger.info(
                    "Telnyx hangup %s HTTP %s (attempt %d) — ack",
                    call_sid, resp.status_code, attempt,
                )
                return True, ""
            last_status = resp.status_code
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning(
                "Telnyx hangup %s attempt %d: %s",
                call_sid, attempt, last_err,
            )
            if 500 <= resp.status_code < 600 and attempt == 1:
                await asyncio.sleep(0.25)
                continue
            # 4xx (other than 404) — not transient, don't retry.
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e!r}"
            logger.warning(
                "Telnyx hangup %s attempt %d raised %s",
                call_sid, attempt, last_err,
            )
            if attempt == 1:
                await asyncio.sleep(0.25)
                continue
            break
    return False, last_err or f"last_status={last_status}"


async def get_telnyx_call_state(call_sid: str) -> tuple[str, str]:
    """Query Telnyx for the current state of a call_control_id.

    Returns (state, raw). Possible states (normalised):
      'live'     — call_state is one of active non-terminal values
                   (parked, ringing, bridged, hangup_pending, ...)
      'terminal' — call_state is hangup/ended OR Telnyx returns 404
                   (they've already cleaned up the record)
      'unknown'  — API error, timeout, parse failure. Caller should
                   retry on next reconciliation tick.

    Used by the reconciler to decide whether a locally-orphaned row
    should be force-hung-up or just marked confirmed-ended.
    """
    try:
        api_key = _api_key()
    except Exception as e:
        return "unknown", f"api_key_missing: {e!r}"
    url = f"{TELNYX_API_BASE}/calls/{call_sid}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        return "unknown", f"{type(e).__name__}: {e!r}"
    if resp.status_code == 404:
        return "terminal", "not_found"
    if resp.status_code >= 400:
        return "unknown", f"HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        payload = resp.json()
    except Exception as e:
        return "unknown", f"json_decode: {e!r}"
    data = payload.get("data") or {}
    call_state = str(data.get("call_state") or "").lower()
    terminal_markers = {"hangup", "ended", "completed", "failed"}
    if call_state in terminal_markers or not call_state:
        return "terminal", call_state or "empty"
    return "live", call_state


def generate_stream_id() -> str:
    return uuid.uuid4().hex[:12]
