"""Inbound PI after-hours intake over Telnyx media streams.

This is the narrow freeware-product proof: answer a dedicated Telnyx number,
collect the facts a PI firm needs after hours, and email an attorney-review
packet. It reuses the existing Telnyx media bridge and realtime voice backend.
"""
from __future__ import annotations

import html
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import IntakeCallSessionRow
from app.services.email_notification_service import _send_email
from app.services.telnyx_voice_service import TelnyxMediaBridge, register_bridge
from app.services.voice.factory import get_voice_backend

logger = logging.getLogger(__name__)


INTAKE_DISCLOSURE = (
    "This call is handled by an AI intake assistant for after-hours screening. "
    "It may be transcribed and summarized for attorney review. By continuing, "
    "you consent to that processing. If you do not consent, please hang up and "
    "call the firm during business hours."
)


FINISH_INTAKE_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "finish_intake",
    "description": (
        "Call this when the caller has given enough information for an attorney "
        "to review the potential personal-injury matter, or when the caller "
        "needs urgent human follow-up."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "caller_name": {"type": "string"},
            "callback_phone": {"type": "string"},
            "email": {"type": "string"},
            "preferred_language": {"type": "string"},
            "incident_date": {"type": "string"},
            "incident_location": {"type": "string"},
            "incident_type": {
                "type": "string",
                "description": "Auto accident, premises liability, dog bite, work injury, wrongful death, etc.",
            },
            "incident_summary": {"type": "string"},
            "injuries": {"type": "string"},
            "medical_treatment": {"type": "string"},
            "witnesses": {"type": "string"},
            "police_or_report": {"type": "string"},
            "insurance_info": {"type": "string"},
            "employment_or_financial_impact": {"type": "string"},
            "prior_attorney": {"type": "string"},
            "urgent_reason": {"type": "string"},
            "consent_to_recording": {"type": "boolean"},
            "recommended_next_step": {"type": "string"},
        },
        "required": [
            "caller_name",
            "callback_phone",
            "incident_summary",
            "injuries",
            "consent_to_recording",
            "recommended_next_step",
        ],
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _env_truthy(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def build_intake_prompt(*, firm_name: str = "", source: str = "after-hours intake") -> str:
    firm = (firm_name or os.getenv("INTAKE_FIRM_NAME", "") or "the law firm").strip()
    return f"""
You are an AI after-hours intake assistant for {firm}. Your job is to collect
the facts needed for a personal-injury attorney to review a potential matter.

You are not a lawyer. Do not give legal advice, do not promise representation,
do not estimate case value, and do not say a claim is valid. Say the call will
be reviewed by the firm. If the caller asks legal questions, explain that an
attorney must answer them.

Start by confirming consent to AI handling, transcription, and attorney-review
summarization. If the caller does not consent, politely stop and ask them to
call during business hours. Keep the tone calm, human, and efficient.

Collect, when available:
- caller name, callback phone, email, and preferred language
- incident date, location, and incident type
- concise incident narrative
- injuries, current symptoms, and medical treatment
- police report, incident report, witnesses, photos/video, and insurance facts
- whether another attorney already represents them
- employment, wage, transportation, or caregiving disruption
- urgency indicators: hospitalization, surgery, severe pain, fatality, child
  injured, caller feels unsafe, same-day incident, or statute/deadline concerns

Do not over-interrogate. Once you have enough information for a human review,
call finish_intake with the structured packet, then tell the caller the firm
will review it and follow up. Source: {source}.
""".strip()


def urgency_flags_from_packet(packet: dict[str, Any]) -> list[str]:
    text = " ".join(str(packet.get(k) or "") for k in (
        "incident_summary",
        "injuries",
        "medical_treatment",
        "urgent_reason",
        "recommended_next_step",
    )).lower()
    flags: list[str] = []
    checks = {
        "hospital_or_er": ("hospital", "er", "emergency room", "ambulance"),
        "surgery_or_fracture": ("surgery", "surgical", "fracture", "broken"),
        "fatality": ("death", "fatal", "died", "wrongful death"),
        "child_injured": ("child", "minor", "kid", "son", "daughter"),
        "unsafe_now": ("unsafe", "danger", "threat", "domestic"),
        "same_day": ("today", "tonight", "this morning", "this afternoon"),
        "deadline_concern": ("deadline", "statute", "limitations", "expires"),
    }
    for name, needles in checks.items():
        if any(needle in text for needle in needles):
            flags.append(name)
    return flags


def normalize_intake_packet(args: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "caller_name",
        "callback_phone",
        "email",
        "preferred_language",
        "incident_date",
        "incident_location",
        "incident_type",
        "incident_summary",
        "injuries",
        "medical_treatment",
        "witnesses",
        "police_or_report",
        "insurance_info",
        "employment_or_financial_impact",
        "prior_attorney",
        "urgent_reason",
        "recommended_next_step",
    ]
    packet = {key: str(args.get(key) or "").strip() for key in keys}
    packet["consent_to_recording"] = bool(args.get("consent_to_recording"))
    packet["urgency_flags"] = urgency_flags_from_packet(packet)
    return packet


def build_intake_email_subject(packet: dict[str, Any], caller_number: str | None) -> str:
    name = packet.get("caller_name") or caller_number or "unknown caller"
    incident_type = packet.get("incident_type") or "PI intake"
    flags = packet.get("urgency_flags") or []
    prefix = "URGENT after-hours intake" if flags else "After-hours intake"
    return f"{prefix}: {name} - {incident_type}"[:240]


def _field(label: str, value: Any) -> str:
    text = str(value or "").strip() or "Not captured"
    return f"{label}: {text}"


def build_intake_email_body(
    *,
    session_id: str,
    caller_number: str | None,
    dialed_number: str | None,
    packet: dict[str, Any],
    transcript: list[dict[str, Any]],
    stream_reason: str | None = None,
) -> str:
    flags = packet.get("urgency_flags") or []
    transcript_lines = []
    for item in transcript[-80:]:
        speaker = item.get("speaker") or "unknown"
        text = str(item.get("text") or "").strip()
        if text:
            transcript_lines.append(f"{speaker}: {text}")
    transcript_text = "\n".join(transcript_lines) or "No transcript captured."
    lines = [
        "AI after-hours PI intake packet",
        "",
        _field("Session ID", session_id),
        _field("Caller number", caller_number),
        _field("Dialed number", dialed_number),
        _field("Consent to recording/transcription", packet.get("consent_to_recording")),
        _field("Urgency flags", ", ".join(flags) if flags else "None detected"),
        _field("Stream end reason", stream_reason),
        "",
        "Caller",
        _field("Name", packet.get("caller_name")),
        _field("Callback phone", packet.get("callback_phone") or caller_number),
        _field("Email", packet.get("email")),
        _field("Preferred language", packet.get("preferred_language")),
        "",
        "Incident",
        _field("Date", packet.get("incident_date")),
        _field("Location", packet.get("incident_location")),
        _field("Type", packet.get("incident_type")),
        _field("Summary", packet.get("incident_summary")),
        "",
        "Case Facts",
        _field("Injuries", packet.get("injuries")),
        _field("Medical treatment", packet.get("medical_treatment")),
        _field("Witnesses/evidence", packet.get("witnesses")),
        _field("Police or incident report", packet.get("police_or_report")),
        _field("Insurance", packet.get("insurance_info")),
        _field("Employment/financial impact", packet.get("employment_or_financial_impact")),
        _field("Prior attorney", packet.get("prior_attorney")),
        "",
        "Recommended Next Step",
        str(packet.get("recommended_next_step") or "Attorney review and callback.").strip(),
        "",
        "Compliance reminder: this is an AI-prepared intake summary, not legal advice or a representation decision. Review transcript/facts before contacting caller.",
        "",
        "Transcript",
        transcript_text,
    ]
    return "\n".join(lines)


class InboundIntakeRuntime:
    def __init__(
        self,
        *,
        session_id: str,
        caller_number: str | None,
        dialed_number: str | None,
        voice_backend: Any,
    ):
        self.session_id = session_id
        self.caller_number = caller_number
        self.dialed_number = dialed_number
        self.voice = voice_backend
        self.transcript: list[dict[str, Any]] = []
        self.finished = False

    async def on_transcript(self, speaker: str, text: str) -> None:
        if speaker == "ai":
            return
        role = "assistant" if speaker == "ai_complete" else "caller"
        entry = {"speaker": role, "text": text, "at": _utcnow().isoformat()}
        self.transcript.append(entry)
        async with AsyncSessionLocal() as session:
            row = await session.get(IntakeCallSessionRow, self.session_id)
            if row:
                row.transcript = list(self.transcript)
                row.updated_at = _utcnow()
                await session.commit()

    async def on_error(self, message: str) -> None:
        logger.warning("Inbound intake voice error session=%s: %s", self.session_id, message)
        async with AsyncSessionLocal() as session:
            row = await session.get(IntakeCallSessionRow, self.session_id)
            if row:
                row.status = "error"
                row.error_message = message[:2000]
                row.updated_at = _utcnow()
                await session.commit()

    async def on_function_call(self, name: str, args: dict[str, Any], tool_call_id: str) -> None:
        if name != "finish_intake":
            await self.voice.send_function_result(tool_call_id, {"ok": False, "error": "unknown tool"})
            return
        packet = normalize_intake_packet(args or {})
        await self.complete(packet=packet, stream_reason="finish_intake_tool")
        await self.voice.send_function_result(
            tool_call_id,
            {"ok": True, "message": "Intake packet sent for attorney review. Close the call politely."},
        )

    async def on_stream_end(self, carrier_call_control_id: str | None, reason: str) -> None:
        async with AsyncSessionLocal() as session:
            row = await session.get(IntakeCallSessionRow, self.session_id)
            if row:
                row.carrier_call_control_id = carrier_call_control_id or row.carrier_call_control_id
                row.transcript = list(self.transcript)
                if row.status not in {"completed", "error"}:
                    row.status = "ended"
                    row.ended_at = _utcnow()
                row.updated_at = _utcnow()
                await session.commit()
        try:
            await self.voice.disconnect()
        except Exception as exc:
            logger.warning("Inbound intake voice disconnect failed session=%s: %s", self.session_id, exc)

    async def complete(self, *, packet: dict[str, Any], stream_reason: str | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        subject = build_intake_email_subject(packet, self.caller_number)
        body = build_intake_email_body(
            session_id=self.session_id,
            caller_number=self.caller_number,
            dialed_number=self.dialed_number,
            packet=packet,
            transcript=self.transcript,
            stream_reason=stream_reason,
        )
        recipient = os.getenv("INTAKE_NOTIFICATION_EMAIL", "").strip() or None
        sent_at = None
        notification_error = None
        try:
            _send_email(
                subject,
                body,
                to=recipient,
                message_type="inbound_intake",
                call_id=self.session_id,
                recipient_name="PI intake reviewer",
            )
            sent_at = _utcnow()
        except Exception as exc:
            notification_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            logger.warning("Inbound intake email failed session=%s: %s", self.session_id, notification_error)

        async with AsyncSessionLocal() as session:
            row = await session.get(IntakeCallSessionRow, self.session_id)
            if row:
                row.status = "completed"
                row.consent_recording = bool(packet.get("consent_to_recording"))
                row.transcript = list(self.transcript)
                row.intake_packet = dict(packet)
                row.urgency_flags = list(packet.get("urgency_flags") or [])
                row.summary_text = body
                row.notification_recipient = recipient or os.getenv("EMAIL_NOTIFICATION_RECIPIENT", "").strip() or None
                row.notification_sent_at = sent_at
                row.notification_error = notification_error
                row.ended_at = row.ended_at or _utcnow()
                row.updated_at = _utcnow()
                await session.commit()


async def prepare_telnyx_intake_call(
    *,
    caller_number: str | None,
    dialed_number: str | None,
    base_url: str,
    firm_name: str = "",
    connect_voice: bool | None = None,
) -> tuple[str, str]:
    """Create session + bridge, then return (session_id, TeXML)."""
    session_id = f"intake_{uuid.uuid4().hex[:18]}"
    stream_id = f"intake_{uuid.uuid4().hex}"
    base = base_url.rstrip("/")
    ws_url = base.replace("https://", "wss://").replace("http://", "ws://")
    language = os.getenv("INTAKE_LANGUAGE", "en").strip() or "en"

    async with AsyncSessionLocal() as session:
        row = IntakeCallSessionRow(
            id=session_id,
            stream_id=stream_id,
            carrier="telnyx",
            caller_number=caller_number,
            dialed_number=dialed_number,
            status="started",
            language=language,
            intake_packet={},
            transcript=[],
            urgency_flags=[],
        )
        session.add(row)
        await session.commit()

    provider = os.getenv("INTAKE_VOICE_PROVIDER", "openai").strip() or "openai"
    model = os.getenv("INTAKE_VOICE_MODEL", "").strip() or None
    voice_name = os.getenv("INTAKE_VOICE_NAME", "").strip() or None
    voice = get_voice_backend(
        provider,
        audio_format="g711_ulaw",
        verbose=_env_truthy("INTAKE_VERBOSE", "false"),
        model=model,
        voice_name=voice_name,
    )
    runtime = InboundIntakeRuntime(
        session_id=session_id,
        caller_number=caller_number,
        dialed_number=dialed_number,
        voice_backend=voice,
    )
    voice.on_transcript = runtime.on_transcript
    voice.on_function_call = runtime.on_function_call
    voice.on_error = runtime.on_error

    bridge = TelnyxMediaBridge(voice, verbose=_env_truthy("INTAKE_VERBOSE", "false"))
    bridge.on_stream_end = runtime.on_stream_end

    should_connect = _env_truthy("INTAKE_CONNECT_VOICE", "true") if connect_voice is None else connect_voice
    if should_connect:
        connected = await voice.connect(
            session_id,
            "after-hours caller",
            language,
            system_prompt=build_intake_prompt(firm_name=firm_name),
            tools=[FINISH_INTAKE_TOOL],
        )
        if not connected:
            async with AsyncSessionLocal() as session:
                row = await session.get(IntakeCallSessionRow, session_id)
                if row:
                    row.status = "error"
                    row.error_message = "voice backend connection failed"
                    row.updated_at = _utcnow()
                    await session.commit()
            return session_id, _error_texml()

    register_bridge(stream_id, bridge)
    disclosure = html.escape(os.getenv("INTAKE_DISCLOSURE", "").strip() or INTAKE_DISCLOSURE)
    stream_url = f"{ws_url}/ws/telnyx-media/{stream_id}"
    texml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="female">{disclosure}</Say>
  <Connect>
    <Stream url="{html.escape(stream_url)}" track="inbound_track" bidirectionalMode="rtp" bidirectionalCodec="PCMU" bidirectionalSamplingRate="8000" />
  </Connect>
</Response>"""
    return session_id, texml


def _error_texml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="female">Sorry, the intake assistant is unavailable. Please call the firm during business hours.</Say>
  <Hangup />
</Response>"""


async def list_intake_sessions(limit: int = 20) -> list[dict[str, Any]]:
    stmt = (
        select(IntakeCallSessionRow)
        .order_by(IntakeCallSessionRow.started_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [serialize_intake_session(row, include_transcript=False) for row in rows]


async def get_intake_session(session_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(IntakeCallSessionRow, session_id)
    return serialize_intake_session(row, include_transcript=True) if row else None


def serialize_intake_session(row: IntakeCallSessionRow, *, include_transcript: bool) -> dict[str, Any]:
    data = {
        "id": row.id,
        "status": row.status,
        "caller_number": row.caller_number,
        "dialed_number": row.dialed_number,
        "carrier": row.carrier,
        "carrier_call_control_id": row.carrier_call_control_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "consent_recording": row.consent_recording,
        "urgency_flags": row.urgency_flags or [],
        "intake_packet": row.intake_packet or {},
        "notification_recipient": row.notification_recipient,
        "notification_sent_at": row.notification_sent_at.isoformat() if row.notification_sent_at else None,
        "notification_error": row.notification_error,
        "error_message": row.error_message,
    }
    if include_transcript:
        data["transcript"] = row.transcript or []
        data["summary_text"] = row.summary_text
    return data
