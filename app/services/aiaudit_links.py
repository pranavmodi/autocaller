"""Signed AI Audit links for lead-gen email attribution."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal
from app.db.models import AuditLinkRow

VALID_SOURCES = {"ai_audit_signature", "ai_audit_email"}
# Consult short links reuse the audit_links table (kind="consult"); they share
# the click/observation machinery but redirect to the consult page instead.
VALID_CONSULT_SOURCES = {"consult_email", "consult_signature"}
# Solution/product short links (kind="solution") redirect to a product solution
# page (e.g. the outbound voice-AI page) with the same per-recipient attribution.
VALID_SOLUTION_SOURCES = {"solution_email", "solution_signature"}


def _secret() -> bytes:
    # Signed attribution prevents forged /aiaudit/go URLs from polluting
    # lead-gen observations. Use the existing app session secret by default so
    # AI Audit tracking does not require a second operational secret.
    secret = (
        os.getenv("AIAUDIT_LINK_SECRET", "").strip()
        or os.getenv("AUTH_SESSION_SECRET", "").strip()
    )
    if not secret:
        raise RuntimeError("AUTH_SESSION_SECRET is not set")
    return secret.encode("utf-8")


def _public_base_url() -> str:
    value = os.getenv("OUTREACH_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError(
            "OUTREACH_PUBLIC_BASE_URL is not set. Set it to the hostname "
            "possibleos is reachable at from email clients."
        )
    return value


def _link_public_base_url() -> str:
    return (
        os.getenv("AIAUDIT_LINK_BASE_URL", "").strip().rstrip("/")
        or _public_base_url()
    )


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


def _new_short_code() -> str:
    return secrets.token_urlsafe(6).rstrip("_-")


async def build_short_audit_link(
    contact: Any,
    *,
    batch_item_id: str | None = None,
    source: str,
) -> str:
    clean_source = str(source or "").strip()
    if clean_source not in VALID_SOURCES:
        raise ValueError(f"invalid AI Audit link source: {source}")
    contact_id = str(getattr(contact, "id", "") or "").strip()
    if not contact_id:
        raise ValueError("contact_id_required")
    pif_id = str(getattr(contact, "pif_id", "") or "").strip() or None
    clean_batch_item_id = str(batch_item_id or "").strip() or None

    async with AsyncSessionLocal() as session:
        for _ in range(8):
            code = _new_short_code()
            session.add(AuditLinkRow(
                code=code,
                contact_id=contact_id,
                batch_item_id=clean_batch_item_id,
                pif_id=pif_id,
                source=clean_source,
                kind="audit",
            ))
            try:
                await session.commit()
                return f"{_link_public_base_url()}/a/{code}"
            except IntegrityError:
                await session.rollback()
    raise RuntimeError("audit_short_code_collision")


async def build_short_consult_link(
    contact: Any,
    *,
    batch_item_id: str | None = None,
    source: str = "consult_email",
) -> str:
    """Per-recipient tracked consult link (kind="consult") -> /c/{code}.

    Mirrors build_short_audit_link so the consult CTA gets the same
    per-recipient click attribution the audit link already has.
    """
    clean_source = str(source or "").strip()
    if clean_source not in VALID_CONSULT_SOURCES:
        raise ValueError(f"invalid consult link source: {source}")
    contact_id = str(getattr(contact, "id", "") or "").strip()
    if not contact_id:
        raise ValueError("contact_id_required")
    pif_id = str(getattr(contact, "pif_id", "") or "").strip() or None
    clean_batch_item_id = str(batch_item_id or "").strip() or None

    async with AsyncSessionLocal() as session:
        for _ in range(8):
            code = _new_short_code()
            session.add(AuditLinkRow(
                code=code,
                contact_id=contact_id,
                batch_item_id=clean_batch_item_id,
                pif_id=pif_id,
                source=clean_source,
                kind="consult",
            ))
            try:
                await session.commit()
                return f"{_link_public_base_url()}/c/{code}"
            except IntegrityError:
                await session.rollback()
    raise RuntimeError("consult_short_code_collision")


async def build_short_solution_link(
    contact: Any,
    *,
    batch_item_id: str | None = None,
    source: str = "solution_email",
) -> str:
    """Per-recipient tracked product/solution link (kind="solution") -> /s/{code}.

    Same per-recipient attribution as the audit/consult links; the /s/ route
    redirects to the configured solution page (default: the outbound voice-AI
    solution page on getpossibleminds.com)."""
    clean_source = str(source or "").strip()
    if clean_source not in VALID_SOLUTION_SOURCES:
        raise ValueError(f"invalid solution link source: {source}")
    contact_id = str(getattr(contact, "id", "") or "").strip()
    if not contact_id:
        raise ValueError("contact_id_required")
    pif_id = str(getattr(contact, "pif_id", "") or "").strip() or None
    clean_batch_item_id = str(batch_item_id or "").strip() or None

    async with AsyncSessionLocal() as session:
        for _ in range(8):
            code = _new_short_code()
            session.add(AuditLinkRow(
                code=code,
                contact_id=contact_id,
                batch_item_id=clean_batch_item_id,
                pif_id=pif_id,
                source=clean_source,
                kind="solution",
            ))
            try:
                await session.commit()
                return f"{_link_public_base_url()}/s/{code}"
            except IntegrityError:
                await session.rollback()
    raise RuntimeError("solution_short_code_collision")


async def resolve_short_audit_code(code: str | None) -> dict[str, Any] | None:
    clean_code = str(code or "").strip()
    if not clean_code:
        return None
    async with AsyncSessionLocal() as session:
        row = await session.get(AuditLinkRow, clean_code)
    if not row:
        return None
    return {
        "contact_id": row.contact_id,
        "batch_item_id": row.batch_item_id,
        "pif_id": row.pif_id,
        "source": row.source,
        "kind": getattr(row, "kind", "audit") or "audit",
        "link_code": row.code,
    }
