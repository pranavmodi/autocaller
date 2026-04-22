"""Email notifications for call outcome issues."""
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

import httpx

from app.models import CallLog

logger = logging.getLogger(__name__)


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


def _send_via_resend(*, subject: str, body: str, from_addr: str, to: str) -> str:
    """Send via Resend's HTTPS API. Works in environments where cloud
    providers block outbound SMTP (port 25/587/465).
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not set")
    # Resend requires the FROM to be on a verified domain (or use
    # onboarding@resend.dev for testing). If the user hasn't verified
    # their Zoho domain on Resend yet, RESEND_FALLBACK_FROM lets them
    # keep emails flowing from the generic address.
    fallback_from = os.getenv("RESEND_FALLBACK_FROM", "").strip()

    reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()
    bcc = os.getenv("BCC_EMAIL", "").strip()

    def _post(this_from: str) -> httpx.Response:
        payload: dict = {
            "from": this_from,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        if reply_to:
            payload["reply_to"] = reply_to
        # BCC every outbound email to the operator (audit trail + "did
        # the thing I expect get sent" visibility). Only add the BCC if
        # it's not the same address as the primary recipient, so a
        # test-send to yourself doesn't double-deliver.
        if bcc and bcc.lower() != to.lower():
            payload["bcc"] = [bcc]
        with httpx.Client(timeout=15.0) as client:
            return client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

    resp = _post(from_addr)
    if resp.status_code == 403 and fallback_from:
        # Domain unverified — retry with the fallback sender.
        logger.warning(
            "Resend 403 on from=%s (domain probably unverified) — "
            "retrying with RESEND_FALLBACK_FROM=%s",
            from_addr, fallback_from,
        )
        resp = _post(fallback_from)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Resend HTTP {resp.status_code}: {resp.text[:300]}"
        )
    data = resp.json() if resp.content else {}
    return str(data.get("id", ""))


def _send_via_smtp(*, subject: str, body: str, from_addr: str, to: str) -> str:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_use_tls = _is_truthy(os.getenv("SMTP_USE_TLS", "true"))
    reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()
    bcc = os.getenv("BCC_EMAIL", "").strip()
    if not smtp_host:
        raise RuntimeError("SMTP_HOST not set")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    # BCC: include in the SMTP envelope RCPT list but NOT in headers.
    # Otherwise "BCC" is visible to recipients, which defeats the point.
    envelope_to = [to]
    if bcc and bcc.lower() != to.lower():
        envelope_to.append(bcc)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
        if smtp_use_tls:
            server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg, to_addrs=envelope_to)

    return msg.get("Message-ID", "")


def _send_email(subject: str, body: str, *, to: str | None = None) -> str:
    """Send an email. Prefers Resend (HTTPS) when RESEND_API_KEY is set,
    falls back to SMTP otherwise. Raises if neither is configured.

    `to` defaults to EMAIL_NOTIFICATION_RECIPIENT (the operator inbox).
    Pass `to` for a specific recipient (e.g. consult booker).
    """
    recipient = (to or os.getenv("EMAIL_NOTIFICATION_RECIPIENT", "")).strip()
    if not recipient:
        raise RuntimeError("Email recipient is not configured. Set EMAIL_NOTIFICATION_RECIPIENT.")
    from_addr = (
        os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
        or os.getenv("RESEND_FALLBACK_FROM", "").strip()
    )
    if not from_addr:
        raise RuntimeError("Sender address not configured — set SMTP_FROM_EMAIL.")

    if os.getenv("RESEND_API_KEY", "").strip():
        try:
            return _send_via_resend(
                subject=subject, body=body, from_addr=from_addr, to=recipient,
            )
        except Exception as e:
            # Only fall back to SMTP if it's actually plausible to
            # succeed — we know it probably won't if the host is
            # behind a provider SMTP block. Log and re-raise.
            logger.warning("Resend send failed: %s — attempting SMTP", e)
            return _send_via_smtp(
                subject=subject, body=body, from_addr=from_addr, to=recipient,
            )
    return _send_via_smtp(
        subject=subject, body=body, from_addr=from_addr, to=recipient,
    )


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


# ---------------------------------------------------------------------------
# Post-call voicemail / no-reach follow-up (Pranav as founder, Possible Minds)
# ---------------------------------------------------------------------------

_VM_FOLLOWUP_SUBJECT_VM_LEFT = (
    "The free consult I mentioned in my voicemail"
)
_VM_FOLLOWUP_SUBJECT_NO_VM = (
    "Tried to reach you — free AI consult for your PI firm"
)

_VM_FOLLOWUP_BODY = (
    "Hi {first_name},\n\n"
    "{opener} Quick intro — my firm Possible Minds builds the AI systems "
    "Precise Imaging uses. The responses you get from Precise on "
    "imaging-status questions come from our software. Precise is saving "
    "about 100 hours a week on email triage using it.\n\n"
    "We're running free 30-minute consults with PI firms that work with "
    "Precise, on how the same tech can handle your intake and records "
    "workflow.\n\n"
    "Grab a time: https://getpossibleminds.com/consult\n"
    "Or just reply to this email and I'll find one that works.\n\n"
    "Thanks,\n"
    "Pranav Modi\n"
    "Founder, Possible Minds\n"
)


def send_voicemail_followup_email(
    *, to_email: str, first_name: str = "", voicemail_left: bool = True,
) -> tuple[bool, str]:
    """Send the post-call follow-up email.

    Subject + opener vary by whether we actually left a voicemail:
      voicemail_left=True  -> mirrors the VM script ("left you a voicemail")
      voicemail_left=False -> "tried to reach you" (no VM was recorded)

    Gated by ALLOW_VOICEMAIL_EMAIL=true so SMTP mis-config or mid-test
    flips cannot accidentally blast. Returns (delivered, note_or_message_id).
    """
    if not _is_truthy(os.getenv("ALLOW_VOICEMAIL_EMAIL", "false")):
        return False, "gate_closed: ALLOW_VOICEMAIL_EMAIL=false"
    email = (to_email or "").strip()
    if not email or "@" not in email:
        return False, f"invalid_email: {email!r}"

    first = (first_name or "").split()[0] if first_name else "there"
    if voicemail_left:
        subject = _VM_FOLLOWUP_SUBJECT_VM_LEFT
        opener = "I just left you a voicemail."
    else:
        subject = _VM_FOLLOWUP_SUBJECT_NO_VM
        opener = "Just tried you on the phone and didn't get a chance to leave a message."
    body = _VM_FOLLOWUP_BODY.format(first_name=first, opener=opener)

    try:
        msg_id = _send_email(subject, body, to=email)
        return True, msg_id or "sent"
    except Exception as e:
        logger.warning("VM follow-up email failed to %s: %s", email, e)
        return False, f"error: {e}"


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
