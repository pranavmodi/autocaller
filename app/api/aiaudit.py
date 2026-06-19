"""Public AI Audit redirect and attribution endpoints."""
from __future__ import annotations

import os
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AuditLinkClickRow,
    FirmCompetitiveFeatureRow,
    FirmContactRow,
    FrontFirmActivityRow,
    LeadGenBatchItemRow,
    PifFirmRow,
)
from app.services.aiaudit_links import verify_audit_token
from app.services.firm_contacts_service import resolve_firm_name
from app.services.lead_gen_cybernetic import record_observation


router = APIRouter(tags=["ai-audit"])


def _audit_public_url() -> str:
    return os.getenv("AIAUDIT_PUBLIC_URL", "https://getpossibleminds.com").rstrip("/")


def _new_id() -> str:
    return f"auditclick_{secrets.token_urlsafe(12)}"


def _clean(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def _city_from_addresses(addresses: Any) -> str:
    if not isinstance(addresses, list):
        return ""
    for item in addresses:
        if isinstance(item, dict):
            city = _clean(item.get("city"), 128)
            if city:
                return city
            raw = _clean(item.get("address") or item.get("full_address"), 512)
        else:
            raw = _clean(item, 512)
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) >= 2 and parts[-2]:
            return parts[-2][:128]
    return ""


async def _prefill_for_payload(payload: dict[str, Any]) -> dict[str, str]:
    contact_id = _clean(payload.get("contact_id"), 64)
    batch_item_id = _clean(payload.get("batch_item_id"), 64) or None
    pif_id = _clean(payload.get("pif_id"), 64) or None
    firm = ""
    city = ""
    case_mgmt = ""

    async with AsyncSessionLocal() as session:
        contact = await session.get(FirmContactRow, contact_id)
        item = await session.get(LeadGenBatchItemRow, batch_item_id) if batch_item_id else None
        if item:
            firm = _clean(item.firm_name)
            pif_id = pif_id or item.pif_id
        if contact:
            pif_id = pif_id or contact.pif_id
            case_mgmt = _clean((contact.tech_signals or {}).get("case_mgmt"), 128)
        if not firm and pif_id:
            firm = _clean(await resolve_firm_name(pif_id))
        pif_firm = await session.get(PifFirmRow, pif_id) if pif_id else None
        if not firm and pif_firm:
            firm = _clean(pif_firm.firm_name)
        feature = await session.get(FirmCompetitiveFeatureRow, pif_id) if pif_id else None
        if feature:
            city = _clean(feature.city, 128)
        if not city and pif_firm:
            city = _city_from_addresses(pif_firm.addresses)
        if not case_mgmt and pif_id:
            activity = (await session.execute(
                select(FrontFirmActivityRow)
                .where(FrontFirmActivityRow.pif_id == pif_id)
                .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
                .limit(1)
            )).scalar_one_or_none()
            if activity:
                case_mgmt = _clean((activity.tech_signals or {}).get("case_mgmt"), 128)
    return {"firm": firm, "city": city, "case_mgmt": case_mgmt}


@router.get("/aiaudit/go")
async def aiaudit_go(request: Request) -> RedirectResponse:
    payload = verify_audit_token(request.query_params.get("t"))
    base = _audit_public_url()
    if not payload:
        return RedirectResponse(url=base, status_code=302)

    click_id = _new_id()
    contact_id = _clean(payload.get("contact_id"), 64)
    batch_item_id = _clean(payload.get("batch_item_id"), 64) or None
    pif_id = _clean(payload.get("pif_id"), 64) or None
    source = _clean(payload.get("source"), 64)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    referer = request.headers.get("referer")

    try:
        async with AsyncSessionLocal() as session:
            click = AuditLinkClickRow(
                id=click_id,
                contact_id=contact_id,
                batch_item_id=batch_item_id,
                pif_id=pif_id,
                source=source,
                ip=(ip or "")[:64] or None,
                user_agent=(ua or "")[:512] or None,
                referer=(referer or "")[:1024] or None,
            )
            session.add(click)
            await session.commit()
        await record_observation(
            event_type="link_clicked",
            raw_event={
                "source": source,
                "channel": "ai_audit",
                "click_id": click_id,
                "pif_id": pif_id,
            },
            contact_id=contact_id,
            batch_item_id=batch_item_id,
        )
        prefill = await _prefill_for_payload(payload)
    except Exception:
        prefill = {}

    query = {key: value for key, value in (prefill or {}).items() if value}
    query["c"] = click_id
    return RedirectResponse(url=f"{base}/?{urlencode(query)}", status_code=302)

