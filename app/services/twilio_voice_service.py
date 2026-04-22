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

        # When True, drop AI-generated audio instead of sending it to Twilio.
        # Set during IVR navigation so the AI doesn't pitch a phone tree.
        self._ai_audio_muted: bool = False

        # Listener sockets for live monitoring (listen-only, no push-to-talk).
        self._listeners: set[WebSocket] = set()

        # Wire OpenAI audio output → Twilio
        self._original_on_audio = voice_service.on_audio
        voice_service.on_audio = self._forward_audio_to_twilio

        # AI audio is paced to listeners at real-time (8000 bps µ-law),
        # mirroring what Twilio does for the prospect. Raw OpenAI/Gemini
        # output can burst 2-4× real-time — without pacing, listeners
        # either hear mangled audio (drop-cap) or desync against the
        # caller stream.
        self._ai_pacer_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._ai_pacer_task: Optional[asyncio.Task] = None

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

    async def _broadcast_audio(self, mulaw: bytes, source: str = "unknown"):
        """Fan out µ-law audio to listeners.

        Caller → direct. AI → pacer queue, BUT dropped entirely when
        `_ai_audio_muted` is set (IVR nav / human takeover). Operator
        does not want to hear the AI reasoning in the browser during
        takeover. See telnyx_voice_service for the full rationale.
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
        # 2-byte header for PCM16 alignment: [tag, 0xAC magic].
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
        """Drain AI queue at real-time. See telnyx bridge for details."""
        import time
        FRAME_BYTES = 160
        FRAME_DT = 0.02
        MAX_BACKLOG_BYTES = 8000 * 10
        buf = bytearray()
        t_next = time.monotonic()
        try:
            while True:
                while True:
                    try:
                        chunk = self._ai_pacer_queue.get_nowait()
                        buf.extend(chunk)
                    except asyncio.QueueEmpty:
                        break
                if len(buf) > MAX_BACKLOG_BYTES:
                    del buf[: len(buf) - MAX_BACKLOG_BYTES]
                if len(buf) >= FRAME_BYTES:
                    frame = bytes(buf[:FRAME_BYTES])
                    del buf[:FRAME_BYTES]
                    await self._send_to_listeners(frame, source="ai")
                t_next += FRAME_DT
                sleep_dt = t_next - time.monotonic()
                if sleep_dt < -0.2:
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

    async def _forward_audio_to_twilio(self, audio_data: bytes):
        """Send OpenAI audio to Twilio media stream + listeners.

        If `_ai_audio_muted` is set (e.g. during IVR navigation), the audio
        is dropped on the Twilio side — the caller still sees it in the
        listener feed for debugging but the phone line stays silent.
        """
        if not self._ai_audio_muted and self._twilio_ws and self._stream_sid:
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

        # Fan out to listeners (AI-side audio) regardless of mute, so the
        # operator can hear what the model WOULD say in the browser even when
        # we've silenced the phone line.
        await self._broadcast_audio(audio_data, source="ai")

        if self._original_on_audio:
            await self._original_on_audio(audio_data)

    # ------------------------------------------------------------------
    # Control — used by IVRNavigator
    # ------------------------------------------------------------------

    def mute_ai_audio(self) -> None:
        """Stop forwarding AI audio to the phone line."""
        self._ai_audio_muted = True
        if self._verbose:
            logger.info("[TwilioMedia] AI audio MUTED (IVR nav active)")

    def unmute_ai_audio(self) -> None:
        """Resume forwarding AI audio to the phone line."""
        self._ai_audio_muted = False
        if self._verbose:
            logger.info("[TwilioMedia] AI audio UNMUTED")

    async def inject_inbound_audio(self, mulaw: bytes) -> None:
        """Inject operator audio (µ-law 8kHz mono) into the Twilio media stream.

        Used during human-takeover: the operator's browser captures mic audio,
        downsamples to 8kHz, µ-law encodes, and ships frames here. We forward
        them to Twilio as `media` events so the prospect hears the operator.

        No-op if the stream isn't live. Caller is responsible for muting the
        AI side (via `mute_ai_audio`) before sending — we don't gate here so
        the same pipe can be used for other inject-audio cases later.
        """
        if not self._twilio_ws or not self._stream_sid or not mulaw:
            return
        payload = base64.b64encode(mulaw).decode("utf-8")
        msg = {
            "event": "media",
            "streamSid": self._stream_sid,
            "media": {"payload": payload},
        }
        try:
            await self._twilio_ws.send_json(msg)
        except Exception as e:
            logger.error(f"inject_inbound_audio failed: {e}")

    async def send_dtmf(self, digit: str) -> None:
        """Send a single DTMF tone to the phone tree over the Twilio media
        stream. Accepts 0-9, *, #. No-op if the stream isn't live yet.

        Twilio MS protocol: {"event":"dtmf","streamSid":...,"dtmf":{"digit":"N"}}.
        """
        d = (digit or "").strip()[:1]
        if d not in "0123456789*#":
            logger.warning("[TwilioMedia] refusing DTMF digit %r (invalid)", digit)
            return
        if not self._twilio_ws or not self._stream_sid:
            logger.warning("[TwilioMedia] DTMF %s dropped — stream not live", d)
            return
        msg = {
            "event": "dtmf",
            "streamSid": self._stream_sid,
            "dtmf": {"digit": d},
        }
        try:
            await self._twilio_ws.send_json(msg)
            if self._verbose:
                logger.info(f"[TwilioMedia] DTMF sent: {d}")
        except Exception as e:
            logger.error("DTMF send failed: %s", e)

    # Inter-digit gap when streaming a multi-digit batch over the Twilio WS.
    # 80ms keeps us under the "one input" threshold most phone trees use.
    _DTMF_INTER_DIGIT_GAP_SECS: float = 0.08

    async def send_dtmf_batch(self, digits: str) -> bool:
        """Send one OR MORE DTMF tones. Twilio's Media Streams protocol is
        one-digit-per-event; we loop with an 80ms gap so the phone tree
        registers the whole string as one input.

        Returns True if every digit was sent successfully.
        """
        import asyncio
        cleaned = "".join(c for c in (digits or "").strip() if c in "0123456789*#")
        if not cleaned:
            logger.warning("[TwilioMedia] refusing DTMF batch %r (empty/invalid)", digits)
            return False
        if not self._twilio_ws or not self._stream_sid:
            logger.warning("[TwilioMedia] DTMF batch %r dropped — stream not live", cleaned)
            return False
        for i, d in enumerate(cleaned):
            if i:
                await asyncio.sleep(self._DTMF_INTER_DIGIT_GAP_SECS)
            msg = {
                "event": "dtmf",
                "streamSid": self._stream_sid,
                "dtmf": {"digit": d},
            }
            try:
                await self._twilio_ws.send_json(msg)
            except Exception as e:
                logger.error(
                    "[TwilioMedia] DTMF batch send failed on digit %d/%d (%r): %s",
                    i + 1, len(cleaned), d, e,
                )
                return False
        if self._verbose:
            logger.info(f"[TwilioMedia] DTMF batch sent: {cleaned}")
        return True

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
                    # Forward Twilio audio → OpenAI. Keep feeding even
                    # during mute so transcription keeps running; AI
                    # responses get suppressed at the egress side.
                    payload = msg["media"]["payload"]
                    audio_bytes = base64.b64decode(payload)
                    if self.voice_service.is_connected:
                        await self.voice_service.send_audio(audio_bytes)
                    # Fan out to listeners (caller-side audio)
                    await self._broadcast_audio(audio_bytes, source="caller")

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
            if self._ai_pacer_task is not None and not self._ai_pacer_task.done():
                self._ai_pacer_task.cancel()
            self._ai_pacer_task = None
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
