"""Twilio outbound call + media stream bridge to OpenAI Realtime API."""
import asyncio
import base64
import html
import json
import logging
import os
import uuid
from typing import Optional, Callable, Any

from twilio.rest import Client
from fastapi import WebSocket

from app.services.realtime_voice import RealtimeVoiceService

logger = logging.getLogger(__name__)

# Lazily-cached Twilio REST client (one per process).
_twilio_client: Optional[Client] = None


def _get_twilio_client() -> Client:
    """Return a cached Twilio Client, creating one on first use."""
    global _twilio_client
    if _twilio_client is None:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not account_sid or not auth_token:
            raise RuntimeError("Twilio is not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.")
        _twilio_client = Client(account_sid, auth_token)
    return _twilio_client


# Registry of pending Twilio streams keyed by stream_id.
# When the orchestrator places a call it registers a bridge here;
# when Twilio connects the media stream WS, we look it up.
_pending_bridges: dict[str, "TwilioMediaBridge"] = {}


def register_bridge(stream_id: str, bridge: "TwilioMediaBridge"):
    _pending_bridges[stream_id] = bridge


def pop_bridge(stream_id: str) -> Optional["TwilioMediaBridge"]:
    return _pending_bridges.pop(stream_id, None)


class TwilioMediaBridge:
    """Bridges a Twilio media stream WebSocket with an OpenAI RealtimeVoiceService.

    Also fans out both audio streams (caller + AI) to any "listener" clients
    that have connected via /ws/listen/{call_id}. Listeners receive 16-bit
    PCM little-endian mono @ 8kHz (mulaw → PCM16 via audioop.ulaw2lin), so
    the browser can play it with a plain AudioContext.
    """

    def __init__(self, voice_service: RealtimeVoiceService, verbose: bool = False):
        self.voice_service = voice_service
        self._verbose = verbose
        self._twilio_ws: Optional[WebSocket] = None
        self._stream_sid: Optional[str] = None
        self._call_sid: Optional[str] = None
        self._connected = asyncio.Event()

        # Listener sockets for live monitoring (listen-only, no push-to-talk).
        self._listeners: set[WebSocket] = set()

        # Wire OpenAI audio output → Twilio
        self._original_on_audio = voice_service.on_audio
        voice_service.on_audio = self._forward_audio_to_twilio

    # ------------------------------------------------------------------
    # Listener fan-out
    # ------------------------------------------------------------------

    def add_listener(self, ws: WebSocket):
        self._listeners.add(ws)

    def remove_listener(self, ws: WebSocket):
        self._listeners.discard(ws)

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def _broadcast_audio(self, mulaw: bytes):
        """Decode mulaw → PCM16 and send to every listener. Safe if none."""
        if not self._listeners:
            return
        try:
            import audioop
            pcm16 = audioop.ulaw2lin(mulaw, 2)  # width=2 → int16
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

    async def _forward_audio_to_twilio(self, audio_data: bytes):
        """Send OpenAI audio to Twilio media stream + listeners."""
        if self._twilio_ws and self._stream_sid:
            payload = base64.b64encode(audio_data).decode("utf-8")
            msg = {
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": payload},
            }
            try:
                await self._twilio_ws.send_json(msg)
            except Exception as e:
                logger.error(f"Error sending audio to Twilio: {e}")

        # Fan out to listeners (AI-side audio)
        await self._broadcast_audio(audio_data)

        if self._original_on_audio:
            await self._original_on_audio(audio_data)

    async def handle_twilio_ws(self, websocket: WebSocket):
        """Handle an incoming Twilio media stream WebSocket."""
        self._twilio_ws = websocket
        logger.info("Twilio media stream WebSocket connected")

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                event = msg.get("event")

                if event == "connected":
                    if self._verbose:
                        logger.info("Twilio stream connected")

                elif event == "start":
                    self._stream_sid = msg["start"]["streamSid"]
                    self._call_sid = msg["start"].get("callSid")
                    if self._verbose:
                        logger.info(f"Twilio stream started: streamSid={self._stream_sid}")
                    self._connected.set()

                elif event == "media":
                    # Forward Twilio audio → OpenAI
                    payload = msg["media"]["payload"]
                    audio_bytes = base64.b64decode(payload)
                    if self.voice_service.is_connected:
                        await self.voice_service.send_audio(audio_bytes)
                    # Fan out to listeners (caller-side audio)
                    await self._broadcast_audio(audio_bytes)

                elif event == "stop":
                    reason = msg.get("stop", {}).get("reason", "unknown")
                    print(f"[TwilioMedia] Twilio sent stop event: reason={reason}, callSid={self._call_sid}")
                    break

                elif event not in ("connected", "start", "media"):
                    print(f"[TwilioMedia] Unexpected event: {event}")

        except Exception as e:
            print(f"[TwilioMedia] Bridge error: {type(e).__name__}: {e}")
        finally:
            self._twilio_ws = None
            self._connected.clear()
            # Close any remaining listener sockets
            for ws in list(self._listeners):
                try:
                    await ws.close(code=1000, reason="call ended")
                except Exception:
                    pass
            self._listeners.clear()

    async def wait_for_connection(self, timeout: float = 30.0) -> bool:
        """Wait for Twilio to connect the media stream."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


def place_twilio_call(
    to_number: str,
    twiml_url: str,
    status_callback_url: Optional[str] = None,
    recording_status_callback_url: Optional[str] = None,
    enable_amd: bool = True,
) -> str:
    """Place an outbound call via Twilio REST API. Returns Call SID.

    Raises RuntimeError if ALLOW_TWILIO_CALLS env var is not set to 'true'.

    AMD (answering-machine detection) is on by default for real production
    calls so we can detect voicemail. It MUST be disabled when:
    - mock_mode is on (our own phone will always be human; AMD adds latency
      and can abort calls if classification times out),
    - TWILIO_DISABLE_AMD=true in env (escape hatch).
    """
    if os.getenv("ALLOW_TWILIO_CALLS", "false").lower() != "true":
        raise RuntimeError(
            "Twilio calls are disabled. Set ALLOW_TWILIO_CALLS=true to enable."
        )

    env_disable = os.getenv("TWILIO_DISABLE_AMD", "false").lower() in ("1", "true", "yes")
    use_amd = enable_amd and not env_disable

    from_number = os.getenv("TWILIO_FROM_NUMBER", "")

    client = _get_twilio_client()
    create_kwargs = {
        "to": to_number,
        "from_": from_number,
        "url": twiml_url,
    }
    if use_amd:
        create_kwargs["machine_detection"] = "DetectMessageEnd"
    if status_callback_url:
        create_kwargs["status_callback"] = status_callback_url
        create_kwargs["status_callback_method"] = "POST"
        create_kwargs["status_callback_event"] = ["answered", "completed"]

    # Enable call recording (dual-channel for transcript debugging)
    if recording_status_callback_url:
        create_kwargs["record"] = True
        create_kwargs["recording_channels"] = "dual"
        create_kwargs["recording_status_callback"] = recording_status_callback_url
        create_kwargs["recording_status_callback_method"] = "POST"
        create_kwargs["recording_status_callback_event"] = ["completed"]

    call = client.calls.create(**create_kwargs)
    logger.info(f"Twilio call placed: SID={call.sid}, to={to_number}")
    return call.sid


def generate_stream_id() -> str:
    return uuid.uuid4().hex[:12]


def hangup_twilio_call(call_sid: str):
    """Hang up an in-progress Twilio call by setting its status to completed."""
    client = _get_twilio_client()
    client.calls(call_sid).update(status="completed")
    logger.info(f"Twilio call hung up: SID={call_sid}")


def play_voicemail_and_hangup(call_sid: str, message: str):
    """Update an in-progress Twilio call to play voicemail then hang up."""
    escaped = html.escape(message, quote=True)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Say voice=\"alice\">{escaped}</Say>"
        "<Hangup/>"
        "</Response>"
    )

    client = _get_twilio_client()
    client.calls(call_sid).update(twiml=twiml)


def _normalize_to_e164(phone: str, default_country_code: str = "1") -> str:
    """Normalize a phone number to E.164 format (e.g. +16692253551).

    Accepts formats like:
      - "6692253551"       (10 digits, assume US)
      - "16692253551"      (11 digits starting with 1)
      - "+16692253551"     (already E.164)
      - "(669) 225-3551"   (formatted with separators)
    Returns "" if the input doesn't look like a valid phone number.
    """
    if not phone:
        return ""
    # Preserve a leading + but strip all other non-digits
    has_plus = phone.strip().startswith("+")
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return ""
    if has_plus:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"
    if len(digits) == 11 and digits.startswith(default_country_code):
        return f"+{digits}"
    # Unknown format — return with + if it looks international
    if len(digits) > 10:
        return f"+{digits}"
    return ""


def transfer_call_to_destination(
    call_sid: str,
    destination: str,
    caller_id: Optional[str] = None,
):
    """Transfer an in-progress Twilio call to a PSTN/SIP destination.

    Args:
        call_sid: Twilio CallSid of the active call to update.
        destination: SIP URI or PSTN number to dial.
        caller_id: Number to present as caller ID on the new leg.  Typically
            the original patient's phone number so the scheduler sees who is
            calling.  Falls back to TWILIO_FROM_NUMBER if unset/invalid.
    """
    fallback_from_number = os.getenv("TWILIO_FROM_NUMBER", "")
    if not destination or not destination.strip():
        raise RuntimeError("Missing transfer destination")

    destination = destination.strip()
    escaped_destination = html.escape(destination, quote=True)

    # Normalize the caller ID — prefer the provided one (patient's phone),
    # fall back to our Twilio number if that fails.
    normalized_caller_id = _normalize_to_e164(caller_id or "") or fallback_from_number
    escaped_caller_id = html.escape(normalized_caller_id, quote=True) if normalized_caller_id else ""

    # Build dial action URL for debugging transfer outcomes
    backend_host = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not backend_host:
        backend_host = os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
    action_url = html.escape(f"{backend_host}/api/twilio/dial-status", quote=True)

    # Build inner target: <Sip> for SIP endpoints, <Number> for PSTN.
    # Only offer codecs that FreePBX has enabled on its end (per Bill Simon: G722, PCMU).
    sip_codecs = os.getenv("SIP_TRANSFER_CODECS", "G722,PCMU").strip()
    dial_attrs = f' action="{action_url}" method="POST"'
    if escaped_caller_id:
        dial_attrs += f' callerId="{escaped_caller_id}"'

    if destination.lower().startswith("sip:"):
        escaped_codecs = html.escape(sip_codecs, quote=True)
        inner = f'<Sip codecs="{escaped_codecs}">{escaped_destination}</Sip>'
    else:
        inner = f"<Number>{escaped_destination}</Number>"

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Dial{dial_attrs}>{inner}</Dial>"
        "</Response>"
    )
    print(f"[Transfer] TwiML: {twiml}")

    client = _get_twilio_client()
    client.calls(call_sid).update(twiml=twiml)
