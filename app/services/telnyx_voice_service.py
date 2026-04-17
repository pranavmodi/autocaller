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

    async def _broadcast_audio(self, mulaw: bytes):
        if not self._listeners:
            return
        try:
            import audioop
            pcm16 = audioop.ulaw2lin(mulaw, 2)
        except Exception as e:
            logger.debug("audioop.ulaw2lin failed: %s", e)
            return
        dead: list[WebSocket] = []
        for ws in list(self._listeners):
            try:
                await ws.send_bytes(pcm16)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._listeners.discard(ws)

    # ------------------------------------------------------------------
    # Audio paths
    # ------------------------------------------------------------------

    async def _forward_audio_to_carrier(self, audio_data: bytes):
        if not self._ai_audio_muted and self._ws and self._stream_sid:
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

        await self._broadcast_audio(audio_data)

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

    async def send_dtmf(self, digit: str) -> None:
        d = (digit or "").strip()[:1]
        if d not in "0123456789*#":
            logger.warning("[TelnyxMedia] refusing DTMF digit %r (invalid)", digit)
            return
        if not self._ws or not self._stream_sid:
            logger.warning("[TelnyxMedia] DTMF %s dropped — stream not live", d)
            return
        msg = {
            "event": "dtmf",
            "stream_id": self._stream_sid,
            "streamSid": self._stream_sid,
            "dtmf": {"digit": d},
        }
        try:
            await self._ws.send_json(msg)
            if self._verbose:
                logger.info(f"[TelnyxMedia] DTMF sent: {d}")
        except Exception as e:
            logger.error("DTMF send failed: %s", e)

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
                            # Caller audio → voice service (Gemini/OpenAI)
                            if self.voice_service.is_connected:
                                await self.voice_service.send_audio(audio_bytes)
                            # Broadcast caller-side to listeners
                            await self._broadcast_audio(audio_bytes)
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


def hangup_telnyx_call(call_sid: str) -> None:
    """Hang up an active Telnyx call via Call Control API.

    Telnyx uses call_control_id as the call handle (returned by place_call).
    Hangup is a native Call Control action, not TeXML — simpler than the
    Twilio-compat REST shape.
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


def generate_stream_id() -> str:
    return uuid.uuid4().hex[:12]
