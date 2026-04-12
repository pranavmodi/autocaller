"""Twilio SMS helper for outbound callback notifications."""
import os
from typing import Optional
from twilio.rest import Client


TWILIO_OPTOUT_ERROR_CODE = 21610

# Lazily-cached Twilio REST client (one per process).
_twilio_client: Optional[Client] = None


def _get_twilio_client() -> Client:
    """Return a cached Twilio Client, creating one on first use."""
    global _twilio_client
    if _twilio_client is None:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not account_sid or not auth_token:
            raise RuntimeError(
                "Twilio SMS is not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
            )
        _twilio_client = Client(account_sid, auth_token)
    return _twilio_client


def normalize_phone_number(phone: str) -> str:
    """Normalize a phone number for list membership checks."""
    return "".join(c for c in (phone or "").strip() if c.isdigit() or c == "+")


def get_opted_out_numbers() -> set[str]:
    """Numbers configured as opted-out (comma-separated env var)."""
    raw = os.getenv("SMS_OPTOUT_NUMBERS", "")
    if not raw.strip():
        return set()
    return {
        normalized
        for part in raw.split(",")
        if (normalized := normalize_phone_number(part))
    }


def is_number_opted_out(phone: str) -> bool:
    """Return whether number is configured as opted-out."""
    normalized = normalize_phone_number(phone)
    return bool(normalized) and normalized in get_opted_out_numbers()


def is_twilio_opt_out_error(error: Exception) -> bool:
    """Best-effort check for Twilio STOP/opt-out delivery failures."""
    code = getattr(error, "code", None)
    if code == TWILIO_OPTOUT_ERROR_CODE:
        return True
    text = str(error).lower()
    return "21610" in text or "opted out" in text or "stop" in text


def get_callback_number() -> str:
    """Return callback number shown in SMS messages."""
    return os.getenv("PRECISE_CALLBACK_NUMBER", "").strip()


def get_main_number() -> str:
    """Return main office number shown in SMS messages."""
    return os.getenv("PRECISE_MAIN_NUMBER", "").strip()


def build_sms_message(message_type: str) -> str:
    """Build a non-PHI SMS message body."""
    callback_number = get_callback_number() or "800-558-2223"

    if message_type == "appointment_reminder":
        return (
            f"Precise Imaging reminder: please contact us to review scheduling details. "
            f"Please call us back at {callback_number}."
        )

    # Default and callback_info
    return (
        f"Precise Imaging: We received your doctor's imaging order. "
        f"Call us at {callback_number} M-F 8 AM to 5PM PST, or go to "
        f"https://app.radflow360.com/patient-portal to answer your pre-screening "
        f"questions, sign your pending documents and schedule your exam on the portal."
    )


def send_sms(to_number: str, message_body: str) -> str:
    """Send an SMS via Twilio and return the message SID.

    Raises:
        RuntimeError: If Twilio credentials/config are missing.
    """
    from_number = os.getenv("TWILIO_SMS_FROM_NUMBER", "") or os.getenv("TWILIO_FROM_NUMBER", "")
    if not from_number:
        raise RuntimeError(
            "Twilio SMS is not configured. Set TWILIO_SMS_FROM_NUMBER (or TWILIO_FROM_NUMBER)."
        )

    client = _get_twilio_client()
    message = client.messages.create(
        to=to_number,
        from_=from_number,
        body=message_body,
    )
    return message.sid
