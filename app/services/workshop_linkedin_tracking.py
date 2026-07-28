"""Create or reuse person-attributed workshop links for LinkedIn outreach."""
from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import AuditLinkRow, FirmContactRow, PifFirmRow
from app.services.aiaudit_links import _link_public_base_url, build_short_workshop_link


LINKEDIN_PROFILE_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9%._~\-/]+",
    re.IGNORECASE,
)


class WorkshopLinkedInTrackingError(ValueError):
    """Raised when a person cannot safely be mapped to a tracked link."""


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _firm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _linkedin_slug(value: str) -> str:
    match = LINKEDIN_PROFILE_RE.search(value or "")
    if not match:
        return ""
    url = match.group(0).rstrip("/.,;:)")
    return url.split("/in/", 1)[1].strip("/").lower()


def canonical_linkedin_url(value: str) -> str:
    slug = _linkedin_slug(value)
    return f"https://www.linkedin.com/in/{slug}" if slug else ""


async def _find_or_create_firm(session, firm_name: str) -> tuple[PifFirmRow, bool]:
    exact = (await session.execute(
        select(PifFirmRow)
        .where(func.lower(PifFirmRow.firm_name) == firm_name.lower())
        .order_by(PifFirmRow.source_updated_at.desc().nullslast())
        .limit(1)
    )).scalar_one_or_none()
    if exact is not None:
        return exact, False

    firm_key = _firm_key(firm_name)
    candidates = (await session.execute(
        select(PifFirmRow)
        .where(PifFirmRow.firm_name.ilike(f"%{firm_name}%"))
        .order_by(PifFirmRow.source_updated_at.desc().nullslast())
        .limit(20)
    )).scalars().all()
    normalized = [row for row in candidates if _firm_key(row.firm_name or "") == firm_key]
    if len(normalized) == 1:
        return normalized[0], False

    firm = PifFirmRow(
        id=f"linkedin-{uuid.uuid4().hex[:32]}",
        firm_name=firm_name,
        profile_source="manual",
        entity_type="law_firm",
        source_json={"source": "linkedin_workshop"},
        raw_json={"firm_name": firm_name, "source": "linkedin_workshop"},
    )
    session.add(firm)
    await session.flush()
    return firm, True


async def _find_contact(session, *, pif_id: str, full_name: str, linkedin_url: str):
    slug = _linkedin_slug(linkedin_url)
    if slug:
        matches = (await session.execute(
            select(FirmContactRow)
            .where(FirmContactRow.linkedin_url.ilike(f"%/in/{slug}%"))
            .limit(5)
        )).scalars().all()
        canonical_matches = [
            row for row in matches if _linkedin_slug(row.linkedin_url or "") == slug
        ]
        if len(canonical_matches) == 1:
            return canonical_matches[0]
    return (await session.execute(
        select(FirmContactRow).where(
            FirmContactRow.pif_id == pif_id,
            func.lower(FirmContactRow.full_name) == full_name.lower(),
        ).limit(1)
    )).scalar_one_or_none()


async def _upsert_contact(
    *,
    full_name: str,
    firm_name: str,
    title: str,
    linkedin_url: str,
) -> tuple[dict[str, str], bool, bool]:
    async with AsyncSessionLocal() as session:
        firm, firm_created = await _find_or_create_firm(session, firm_name)
        contact = await _find_contact(
            session,
            pif_id=firm.id,
            full_name=full_name,
            linkedin_url=linkedin_url,
        )
        contact_created = contact is None
        if contact is None:
            contact = FirmContactRow(
                id=uuid.uuid4().hex,
                pif_id=firm.id,
                full_name=full_name,
                first_name=full_name.split()[0],
                title=title or None,
                linkedin_url=linkedin_url or None,
                source="linkedin_workshop",
                persona="case_manager" if "case manager" in title.lower() else None,
                tech_signals={"linkedin_workshop": {"firm_name": firm_name}},
            )
            session.add(contact)
        else:
            if title:
                contact.title = title
            if linkedin_url:
                contact.linkedin_url = linkedin_url
            signals = dict(contact.tech_signals or {})
            signals["linkedin_workshop"] = {"firm_name": firm_name}
            contact.tech_signals = signals
        await session.commit()
        return {
            "id": contact.id,
            "pif_id": contact.pif_id,
            "full_name": contact.full_name,
            "first_name": contact.first_name,
            "title": contact.title or "",
            "linkedin_url": contact.linkedin_url or "",
            "firm_name": firm.firm_name or firm_name,
        }, contact_created, firm_created


async def _tracked_link(contact_id: str) -> tuple[str, bool]:
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(AuditLinkRow).where(
                AuditLinkRow.contact_id == contact_id,
                AuditLinkRow.kind == "workshop",
                AuditLinkRow.source == "workshop_linkedin",
            ).order_by(AuditLinkRow.created_at.asc()).limit(1)
        )).scalar_one_or_none()
        if existing:
            return f"{_link_public_base_url('workshop')}/w/{existing.code}", True
        contact = await session.get(FirmContactRow, contact_id)
        if contact is None:
            raise WorkshopLinkedInTrackingError("contact_missing_after_upsert")
    return await build_short_workshop_link(contact, source="workshop_linkedin"), False


async def create_workshop_linkedin_tracking_link(
    *,
    full_name: str,
    firm_name: str,
    title: str = "",
    linkedin_url: str = "",
) -> dict[str, Any]:
    clean_name = _clean(full_name, 255)
    clean_firm = _clean(firm_name, 512)
    clean_title = _clean(title, 255)
    clean_linkedin = canonical_linkedin_url(linkedin_url)
    if not clean_name:
        raise WorkshopLinkedInTrackingError("contact_name_required")
    if not clean_firm:
        raise WorkshopLinkedInTrackingError("firm_name_required")
    contact, contact_created, firm_created = await _upsert_contact(
        full_name=clean_name,
        firm_name=clean_firm,
        title=clean_title,
        linkedin_url=clean_linkedin,
    )
    tracking_url, link_reused = await _tracked_link(contact["id"])
    return {
        "tracking_url": tracking_url,
        "contact": contact,
        "contact_created": contact_created,
        "firm_created": firm_created,
        "tracking_link_reused": link_reused,
    }
