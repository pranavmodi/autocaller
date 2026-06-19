"""Signed AI Audit links for lead-gen email attribution."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

VALID_SOURCES = {"ai_audit_signature", "ai_audit_email"}


def _secret() -> bytes:
    secret = os.getenv("AIAUDIT_LINK_SECRET", "").strip()
    if not secret:
        raise RuntimeError("AIAUDIT_LINK_SECRET is not set")
    return secret.encode("utf-8")


def _public_base_url() -> str:
    value = os.getenv("OUTREACH_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError(
            "OUTREACH_PUBLIC_BASE_URL is not set. Set it to the hostname "
            "possibleos is reachable at from email clients."
        )
    return value


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign(encoded_payload: str) -> str:
    digest = hmac.new(_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def _encode_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _b64encode(raw)


def build_audit_token(
    *,
    contact_id: str,
    pif_id: str | None = None,
    batch_item_id: str | None = None,
    source: str,
) -> str:
    clean_source = str(source or "").strip()
    if clean_source not in VALID_SOURCES:
        raise ValueError(f"invalid AI Audit link source: {source}")
    payload = {
        "contact_id": str(contact_id or "").strip(),
        "batch_item_id": str(batch_item_id or "").strip() or None,
        "pif_id": str(pif_id or "").strip() or None,
        "source": clean_source,
        "nonce": secrets.token_urlsafe(9),
    }
    if not payload["contact_id"]:
        raise ValueError("contact_id_required")
    encoded_payload = _encode_payload(payload)
    return f"{encoded_payload}.{_sign(encoded_payload)}"


def verify_audit_token(token: str | None) -> dict[str, Any] | None:
    value = str(token or "").strip()
    if "." not in value:
        return None
    encoded_payload, encoded_sig = value.rsplit(".", 1)
    if not encoded_payload or not encoded_sig:
        return None
    expected = _sign(encoded_payload)
    if not hmac.compare_digest(encoded_sig, expected):
        return None
    try:
        payload = json.loads(_b64decode(encoded_payload))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if not str(payload.get("contact_id") or "").strip():
        return None
    if payload.get("source") not in VALID_SOURCES:
        return None
    return payload


def build_audit_link(contact: Any, *, batch_item_id: str | None = None, source: str) -> str:
    token = build_audit_token(
        contact_id=getattr(contact, "id", None),
        pif_id=getattr(contact, "pif_id", None),
        batch_item_id=batch_item_id,
        source=source,
    )
    return f"{_public_base_url()}/aiaudit/go?t={token}"
