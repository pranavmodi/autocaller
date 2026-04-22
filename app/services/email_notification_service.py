"""Email notifications for call outcome issues."""
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

from app.models import CallLog


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_wrong_number_subject(patient_id: str) -> str:
    return f"Scheduling Call Issue - Wrong Number (Patient ID: {patient_id})"


def _build_disconnected_subject(patient_id: str) -> str:
    return f"Scheduling Call Issue - Invalid/Disconnected Number (Patient ID: {patient_id})"


def _format_body(call: CallLog, status: Optional[str] = None) -> str:
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Patient ID: {call.patient_id}",
        f"Order ID: {call.order_id or 'N/A'}",
        f"Phone: {call.phone or 'N/A'}",
        f"Timestamp: {timestamp}",
        f"Call ID: {call.call_id}",
    ]
    if status:
        lines.append(f"Error/Status: {status}")
    return "\n".join(lines)


def send_wrong_number_email(call: CallLog) -> str:
    """Send wrong-number notification email. Returns message-id."""
    subject = _build_wrong_number_subject(call.patient_id)
    body = _format_body(call)
    return _send_email(subject, body)


def send_disconnected_number_email(call: CallLog, status: str) -> str:
    """Send disconnected/invalid-number notification email. Returns message-id."""
    subject = _build_disconnected_subject(call.patient_id)
    body = _format_body(call, status=status)
    return _send_email(subject, body)


def _send_email(subject: str, body: str, *, to: str | None = None) -> str:
    """Send an email via SMTP. `to` defaults to EMAIL_NOTIFICATION_RECIPIENT
    (the operator inbox). Pass `to` to target a specific recipient (e.g.
    a consult-booker's confirmation email).
    """
    recipient = (to or os.getenv("EMAIL_NOTIFICATION_RECIPIENT", "")).strip()
    if not recipient:
        raise RuntimeError("Email recipient is not configured. Set EMAIL_NOTIFICATION_RECIPIENT.")
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM_EMAIL", "").strip() or smtp_user
    smtp_use_tls = _is_truthy(os.getenv("SMTP_USE_TLS", "true"))

    if not smtp_host or not smtp_from:
        raise RuntimeError("Email is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL (or SMTP_USERNAME).")

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        if smtp_use_tls:
            server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    return msg.get("Message-ID", "")


# ---------------------------------------------------------------------------
# Consult booking confirmation
# ---------------------------------------------------------------------------

CONSULT_MEET_URL = os.getenv(
    "CONSULT_MEET_URL", "https://meet.google.com/xoy-mwvo-thf"
)


def send_consult_confirmation(
    *,
    to_email: str,
    name: str,
    firm_name: str | None,
    slot_local_str: str,
    notes: str | None = None,
) -> str:
    """Send a booking confirmation to the consult booker. Includes the
    Google Meet link and the PT-formatted slot time. Raises RuntimeError
    if SMTP isn't configured — caller catches and logs, booking still
    succeeds (the operator is separately pinged via Telnyx SMS).
    """
    firm_clause = f" at {firm_name}" if firm_name else ""
    subject = f"Your Possible Minds consult is booked — {slot_local_str}"
    body_lines = [
        f"Hi {name.split()[0] if name else 'there'},",
        "",
        f"You're booked for a 30-minute AI-consult{firm_clause} on:",
        "",
        f"    {slot_local_str}",
        "",
        "Join via Google Meet:",
        f"    {CONSULT_MEET_URL}",
        "",
        "What we'll cover: how the same AI tech that handles Precise "
        "Imaging's email triage (~100 hrs/week saved) and outbound "
        "calls (~20 hrs/week) could plug into your intake and records "
        "workflow. No slides — we'll look at what fits and what doesn't.",
        "",
        "Need to reschedule? Just reply to this email.",
        "",
        "— Possible Minds",
    ]
    if notes:
        body_lines.insert(
            7,
            f'\nYou mentioned you wanted to focus on: "{notes}"\n',
        )
    return _send_email(subject, "\n".join(body_lines), to=to_email)


# ---------------------------------------------------------------------------
# Autocaller follow-up email
# ---------------------------------------------------------------------------

_ONE_PAGER_BODY = (
    "Hi {lead_name},\n\n"
    "Thanks for taking my cold call. As promised, here's a quick one-pager on "
    "how {rep_company} helps personal injury firms cut the repetitive, "
    "high-friction work that eats partner and paralegal time:\n\n"
    "- Custom case intake + lead-conversion automation\n"
    "- Medical-record retrieval and chasing\n"
    "- Lien processing and negotiation tooling\n"
    "- Demand letter drafting (first-draft in minutes, not days)\n"
    "- Client communication and status update automation\n\n"
    "If any of this sounds worth twenty minutes, reply here and I'll send over "
    "a calendar link.\n\n"
    "Thanks,\n{rep_name}\n{rep_company}\n{rep_email}\n"
)


async def send_followup_email(
    *,
    to_email: str,
    lead_name: str,
    firm_name: str = "",
    message_type: str = "one_pager",
    custom_note: str = "",
    rep_name: str = "",
    rep_company: str = "",
    rep_email: str = "",
) -> bool:
    """Send a lightweight follow-up email. Returns True on success."""
    if not to_email:
        return False
    import asyncio

    subject = f"Quick follow-up from {rep_company or 'our team'}"
    body = _ONE_PAGER_BODY.format(
        lead_name=(lead_name or "there").split()[0] if lead_name else "there",
        rep_name=rep_name or "the team",
        rep_company=rep_company or "our team",
        rep_email=rep_email or "",
    )
    if custom_note:
        body = f"{custom_note}\n\n{body}"

    recipient = to_email.strip()
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_from = os.getenv("SMTP_FROM_EMAIL", "").strip() or os.getenv("SMTP_USERNAME", "").strip()
    if not smtp_host or not smtp_from:
        # SMTP not configured — log-only "send".
        return False

    def _send():
        smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
        smtp_user = os.getenv("SMTP_USERNAME", "").strip()
        smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
        smtp_use_tls = _is_truthy(os.getenv("SMTP_USE_TLS", "true"))
        msg = EmailMessage()
        msg["From"] = smtp_from
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _send)
    except Exception:
        return False
