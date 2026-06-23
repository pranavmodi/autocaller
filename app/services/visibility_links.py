"""Short AI Visibility report links for lead-gen email attribution."""
from __future__ import annotations

import os
import secrets
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal
from app.db.models import VisibilityLinkRow

VALID_SOURCES = {"visibility_report_email"}


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
        os.getenv("VISIBILITY_LINK_BASE_URL", "").strip().rstrip("/")
        or _public_base_url()
    )


def visibility_report_base_url() -> str:
    value = os.getenv("AIVIS_REPORT_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError(
            "AIVIS_REPORT_BASE_URL is not set. Set it to the AI Visibility "
            "report hostname recipients should land on."
        )
    return value


def _new_short_code() -> str:
    return secrets.token_urlsafe(6).rstrip("_-")


async def build_short_visibility_link(
    contact: Any,
    *,
    scan_id: str,
    batch_item_id: str | None = None,
    source: str,
) -> str:
    clean_source = str(source or "").strip()
    if clean_source not in VALID_SOURCES:
        raise ValueError(f"invalid AI Visibility link source: {source}")
    contact_id = str(getattr(contact, "id", "") or "").strip()
    if not contact_id:
        raise ValueError("contact_id_required")
    clean_scan_id = str(scan_id or "").strip()
    if not clean_scan_id:
        raise ValueError("scan_id_required")
    pif_id = str(getattr(contact, "pif_id", "") or "").strip() or None
    clean_batch_item_id = str(batch_item_id or "").strip() or None

    async with AsyncSessionLocal() as session:
        for _ in range(8):
            code = _new_short_code()
            session.add(VisibilityLinkRow(
                code=code,
                contact_id=contact_id,
                batch_item_id=clean_batch_item_id,
                pif_id=pif_id,
                scan_id=clean_scan_id,
                source=clean_source,
            ))
            try:
                await session.commit()
                return f"{_link_public_base_url()}/v/{code}"
            except IntegrityError:
                await session.rollback()
    raise RuntimeError("visibility_short_code_collision")


async def resolve_visibility_code(code: str | None) -> dict[str, Any] | None:
    clean_code = str(code or "").strip()
    if not clean_code:
        return None
    async with AsyncSessionLocal() as session:
        row = await session.get(VisibilityLinkRow, clean_code)
    if not row:
        return None
    return {
        "contact_id": row.contact_id,
        "batch_item_id": row.batch_item_id,
        "pif_id": row.pif_id,
        "scan_id": row.scan_id,
        "source": row.source,
        "link_code": row.code,
    }
