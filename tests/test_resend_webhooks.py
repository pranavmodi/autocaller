import base64
import hashlib
import hmac
import json

import pytest

from app.services.resend_webhooks import (
    ResendWebhookVerificationError,
    classify_resend_event,
    parse_resend_event,
    verify_svix_signature,
)


def _signature(secret: str, webhook_id: str, timestamp: str, payload: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{webhook_id}.{timestamp}.".encode("utf-8") + payload
    digest = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return f"v1,{digest}"


def test_verify_svix_signature_accepts_valid_resend_headers():
    secret = "whsec_" + base64.b64encode(b"test-secret").decode()
    payload = b'{"type":"email.bounced","data":{"email_id":"email_123"}}'
    headers = {
        "svix-id": "msg_123",
        "svix-timestamp": "1000",
        "svix-signature": _signature(secret, "msg_123", "1000", payload),
    }

    verify_svix_signature(payload=payload, headers=headers, secret=secret, now=1000)


def test_verify_svix_signature_rejects_changed_body():
    secret = "whsec_" + base64.b64encode(b"test-secret").decode()
    payload = b'{"type":"email.bounced","data":{"email_id":"email_123"}}'
    headers = {
        "svix-id": "msg_123",
        "svix-timestamp": "1000",
        "svix-signature": _signature(secret, "msg_123", "1000", payload),
    }

    with pytest.raises(ResendWebhookVerificationError, match="invalid_svix_signature"):
        verify_svix_signature(
            payload=b'{"type":"email.delivered","data":{"email_id":"email_123"}}',
            headers=headers,
            secret=secret,
            now=1000,
        )


def test_parse_resend_event_requires_data_object():
    payload = {"type": "email.bounced", "data": {"email_id": "email_123"}}

    assert parse_resend_event(json.dumps(payload).encode()) == payload

    with pytest.raises(ValueError, match="missing_data"):
        parse_resend_event(b'{"type":"email.bounced"}')


def test_classify_resend_delivery_failures_pause_sequence():
    bounced = classify_resend_event("email.bounced")
    delayed = classify_resend_event("email.delivery_delayed")
    clicked = classify_resend_event("email.clicked")
    suppressed = classify_resend_event("email.suppressed")

    assert bounced.log_status == "bounced"
    assert bounced.outcome == "bounce"
    assert bounced.pause_sequence
    assert delayed.log_status == "delayed"
    assert delayed.next_action == "pause_sequence"
    assert clicked.outcome == "opened_or_clicked"
    assert not clicked.pause_sequence
    assert suppressed.log_status == "suppressed"
    assert suppressed.pause_sequence
