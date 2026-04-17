"""Carrier abstraction — one choke point for Twilio vs Telnyx.

The orchestrator asks `get_carrier(name)` for a set of callables that
match across providers, then uses them identically. No carrier-specific
branching elsewhere in the orchestrator.

Both carriers expose the same shape:
  - `place_call(...)` → returns call SID
  - `hangup(call_sid)` → best-effort
  - `MediaBridge` class with the same constructor + methods
  - `register_bridge(stream_id, bridge)` / `pop_bridge(stream_id)`
  - `twiml_endpoint` / `status_endpoint` / `recording_endpoint` / `ws_path`
     describing where this carrier's webhooks live

The media-stream WebSocket URL differs per carrier (`/ws/twilio-media/...`
vs `/ws/telnyx-media/...`) because the JSON event field names differ
slightly. The TeXML vs TwiML XML is identical for the `<Stream>` shape.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from app.services import twilio_voice_service as _twilio
from app.services import telnyx_voice_service as _telnyx


VALID_CARRIERS = ("twilio", "telnyx")


@dataclass
class CarrierAdapter:
    name: str
    place_call: Callable[..., str]
    hangup: Callable[[str], None]
    register_bridge: Callable
    pop_bridge: Callable
    MediaBridge: type
    generate_stream_id: Callable[[], str]
    twiml_path: str              # orchestrator substitutes /{stream_id}
    status_path: str
    recording_path: str          # orchestrator substitutes /{call_id}
    ws_media_path: str           # orchestrator substitutes /{stream_id}


def _twilio_hangup_noop(call_sid: str) -> None:
    # Twilio service uses client.calls.update(...) via SDK; expose a safe noop
    # wrapper so carrier code doesn't assume an import path. The existing
    # orchestrator hangup path still reaches Twilio via the SDK directly.
    try:
        from twilio.rest import Client
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        tok = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not (sid and tok):
            return
        Client(sid, tok).calls(call_sid).update(status="completed")
    except Exception:
        return


_TWILIO = CarrierAdapter(
    name="twilio",
    place_call=_twilio.place_twilio_call,
    hangup=_twilio_hangup_noop,
    register_bridge=_twilio.register_bridge,
    pop_bridge=_twilio.pop_bridge,
    MediaBridge=_twilio.TwilioMediaBridge,
    generate_stream_id=_twilio.generate_stream_id,
    twiml_path="/api/twilio/twiml",
    status_path="/api/twilio/status",
    recording_path="/api/twilio/recording-status",
    ws_media_path="/ws/twilio-media",
)


_TELNYX = CarrierAdapter(
    name="telnyx",
    place_call=_telnyx.place_telnyx_call,
    hangup=_telnyx.hangup_telnyx_call,
    register_bridge=_telnyx.register_bridge,
    pop_bridge=_telnyx.pop_bridge,
    MediaBridge=_telnyx.TelnyxMediaBridge,
    generate_stream_id=_telnyx.generate_stream_id,
    twiml_path="/api/telnyx/twiml",
    status_path="/api/telnyx/status",
    recording_path="/api/telnyx/recording-status",
    ws_media_path="/ws/telnyx-media",
)


def get_carrier(name: Optional[str]) -> CarrierAdapter:
    """Resolve a carrier adapter by name. Defaults to twilio if unknown/None."""
    n = (name or "").strip().lower() or "twilio"
    if n == "telnyx":
        return _TELNYX
    return _TWILIO


def resolve_carrier_name(
    per_call: Optional[str],
    db_default: Optional[str],
    env_default: Optional[str] = None,
) -> str:
    """Apply the precedence chain: per-call → DB default → env default → twilio."""
    for candidate in (per_call, db_default, env_default):
        if candidate:
            n = candidate.strip().lower()
            if n in VALID_CARRIERS:
                return n
    return "twilio"
