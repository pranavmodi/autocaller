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
    """Return callback number shown in SMS messages (from the Twilio from-number)."""
    return os.getenv("SMS_CALLBACK_NUMBER", "").strip() or os.getenv("TWILIO_FROM_NUMBER", "").strip()


def get_main_number() -> str:
    """Kept for backward-compat — returns the callback number."""
    return get_callback_number()


def _rep_name() -> str:
    return os.getenv("SALES_REP_NAME", "").strip() or "our team"


def _rep_company() -> str:
    return os.getenv("SALES_REP_COMPANY", "").strip() or "our team"


def _booking_link() -> str:
    """Public self-serve booking link shown in SMS when Cal.com event is public."""
    return os.getenv("CALCOM_PUBLIC_BOOKING_URL", "").strip()


def build_sms_message(message_type: str, **context) -> str:
    """Build an SMS body for the attorney cold-call autocaller.

    Context:
      - demo_meeting_url: optional URL returned by Cal.com after booking.
      - lead_first_name: optional first-name override.
    """
    rep = _rep_name()
    company = _rep_company()
    callback = get_callback_number() or ""
    first_name = str(context.get("lead_first_name") or "").strip()
    salutation = f"Hi {first_name}," if first_name else "Hi,"

    if message_type == "demo_confirmation":
        url = str(context.get("demo_meeting_url") or "").strip()
        tail = f" Meeting link: {url}" if url else ""
        return (
            f"{salutation} thanks for booking time with {rep} at {company}.{tail} "
            f"Reply STOP to opt out."
        )

    if message_type == "appointment_reminder":
        url = str(context.get("demo_meeting_url") or "").strip()
        tail = f" Meeting link: {url}" if url else ""
        return (
            f"{salutation} quick reminder about your meeting with {rep} at {company}.{tail} "
            f"Reply STOP to opt out."
        )

    # Default / callback_info — used when a call didn't complete. Keep it
    # short and B2B; no product pitch, no false urgency.
    booking = _booking_link()
    booking_line = f" If easier, you can book a time here: {booking}." if booking else ""
    contact = f" Or reach me at {callback}." if callback else ""
    return (
        f"{salutation} this is {rep} from {company}. I tried reaching you about how we help "
        f"personal injury firms automate intake, medical-records retrieval, and demand letters."
        f"{booking_line}{contact} Reply STOP to opt out."
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
