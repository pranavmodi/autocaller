"""Public AI Audit redirect and attribution endpoints."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AuditLinkClickRow,
    FirmCompetitiveFeatureRow,
    FirmContactRow,
    FrontFirmActivityRow,
    LeadGenBatchItemRow,
    PifFirmRow,
)
from app.services.aiaudit_prefill import audit_preanswer_params
from app.services.aiaudit_links import resolve_short_audit_code, verify_audit_token
from app.services.firm_contacts_service import resolve_firm_name
from app.services.lead_gen_cybernetic import record_observation


router = APIRouter(tags=["ai-audit"])

CLICK_ANALYTICS_GROUPS = {
    "app_name": "App",
    "source": "Source",
    "firm_name": "Firm",
    "contact": "Contact",
    "persona": "Persona",
    "pif_id": "PIF ID",
    "batch_item": "Batch item",
    "day": "Day",
}


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
    contact_tech_signals: dict[str, Any] | None = None
    activity_tech_signals: dict[str, Any] | None = None
    activity_behavioral_json: dict[str, Any] | None = None

    async with AsyncSessionLocal() as session:
        contact = await session.get(FirmContactRow, contact_id)
        item = await session.get(LeadGenBatchItemRow, batch_item_id) if batch_item_id else None
        if item:
            firm = _clean(item.firm_name)
            pif_id = pif_id or item.pif_id
        if contact:
            pif_id = pif_id or contact.pif_id
            contact_tech_signals = contact.tech_signals or {}
            case_mgmt = _clean(contact_tech_signals.get("case_mgmt"), 128)
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
                activity_tech_signals = activity.tech_signals or {}
                activity_behavioral_json = activity.behavioral_json or {}
                case_mgmt = _clean(activity_tech_signals.get("case_mgmt"), 128)
    preanswers = audit_preanswer_params(
        contact_tech_signals=contact_tech_signals,
        activity_tech_signals=activity_tech_signals,
        behavioral_json=activity_behavioral_json,
        pif_directory_firm=pif_firm,
    )
    return {"firm": firm, "city": city, "case_mgmt": case_mgmt, **preanswers}


async def _audit_redirect_for_payload(
    request: Request,
    payload: dict[str, Any] | None,
) -> RedirectResponse:
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
                "link_code": _clean(payload.get("link_code"), 64) or None,
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


@router.get("/a/{code}")
async def aiaudit_short_go(code: str, request: Request) -> RedirectResponse:
    return await _audit_redirect_for_payload(request, await resolve_short_audit_code(code))


@router.get("/aiaudit/go")
async def aiaudit_go(request: Request) -> RedirectResponse:
    return await _audit_redirect_for_payload(request, verify_audit_token(request.query_params.get("t")))


def _app_name_expr():
    return case(
        (AuditLinkClickRow.source.in_(["ai_audit_signature", "ai_audit_email"]), "AI Audit"),
        else_="Unknown",
    )


def _group_expression(group_by: str):
    firm_name = func.coalesce(LeadGenBatchItemRow.firm_name, PifFirmRow.firm_name, "Unknown firm")
    contact_name = func.coalesce(FirmContactRow.full_name, FirmContactRow.email, "Unknown contact")
    persona = func.coalesce(LeadGenBatchItemRow.persona, FirmContactRow.persona, "unknown")
    if group_by == "app_name":
        return _app_name_expr()
    if group_by == "source":
        return AuditLinkClickRow.source
    if group_by == "firm_name":
        return firm_name
    if group_by == "contact":
        return contact_name
    if group_by == "persona":
        return persona
    if group_by == "pif_id":
        return func.coalesce(AuditLinkClickRow.pif_id, "unknown")
    if group_by == "batch_item":
        return func.coalesce(AuditLinkClickRow.batch_item_id, "unknown")
    if group_by == "day":
        return func.to_char(AuditLinkClickRow.clicked_at, "YYYY-MM-DD")
    raise HTTPException(status_code=400, detail=f"unsupported_group_by:{group_by}")


def _click_base_select():
    return (
        select(AuditLinkClickRow, FirmContactRow, LeadGenBatchItemRow, PifFirmRow)
        .join(FirmContactRow, FirmContactRow.id == AuditLinkClickRow.contact_id)
        .outerjoin(LeadGenBatchItemRow, LeadGenBatchItemRow.id == AuditLinkClickRow.batch_item_id)
        .outerjoin(PifFirmRow, PifFirmRow.id == AuditLinkClickRow.pif_id)
    )


def _click_where(stmt, *, since_days: int):
    if since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        stmt = stmt.where(AuditLinkClickRow.clicked_at >= cutoff)
    return stmt


def _source_label(source: str) -> str:
    labels = {
        "ai_audit_signature": "Signature CTA",
        "ai_audit_email": "AI Audit email",
    }
    return labels.get(source or "", source or "Unknown")


@router.get("/api/aiaudit/click-analytics")
async def audit_click_analytics(
    since_days: int = Query(30, ge=0, le=3650),
    group_by: str = Query("firm_name"),
    limit: int = Query(50, ge=1, le=500),
):
    if group_by not in CLICK_ANALYTICS_GROUPS:
        raise HTTPException(status_code=400, detail=f"unsupported_group_by:{group_by}")
    group_expr = _group_expression(group_by).label("group_key")
    rollup_stmt = (
        select(
            group_expr,
            func.count(AuditLinkClickRow.id).label("click_count"),
            func.count(func.distinct(AuditLinkClickRow.contact_id)).label("contact_count"),
            func.count(func.distinct(AuditLinkClickRow.pif_id)).label("firm_count"),
            func.min(AuditLinkClickRow.clicked_at).label("first_clicked_at"),
            func.max(AuditLinkClickRow.clicked_at).label("last_clicked_at"),
        )
        .join(FirmContactRow, FirmContactRow.id == AuditLinkClickRow.contact_id)
        .outerjoin(LeadGenBatchItemRow, LeadGenBatchItemRow.id == AuditLinkClickRow.batch_item_id)
        .outerjoin(PifFirmRow, PifFirmRow.id == AuditLinkClickRow.pif_id)
        .group_by(group_expr)
        .order_by(desc("click_count"), desc("last_clicked_at"))
        .limit(limit)
    )
    rollup_stmt = _click_where(rollup_stmt, since_days=since_days)
    recent_stmt = _click_where(_click_base_select(), since_days=since_days).order_by(
        desc(AuditLinkClickRow.clicked_at)
    ).limit(limit)
    summary_stmt = _click_where(
        select(
            func.count(AuditLinkClickRow.id),
            func.count(func.distinct(AuditLinkClickRow.contact_id)),
            func.count(func.distinct(AuditLinkClickRow.pif_id)),
            func.min(AuditLinkClickRow.clicked_at),
            func.max(AuditLinkClickRow.clicked_at),
        ),
        since_days=since_days,
    )

    async with AsyncSessionLocal() as session:
        rollup_rows = (await session.execute(rollup_stmt)).all()
        recent_rows = (await session.execute(recent_stmt)).all()
        summary_row = (await session.execute(summary_stmt)).one()

    groups = []
    for row in rollup_rows:
        key = str(row.group_key or "Unknown")
        groups.append({
            "key": key,
            "label": key,
            "click_count": int(row.click_count or 0),
            "contact_count": int(row.contact_count or 0),
            "firm_count": int(row.firm_count or 0),
            "first_clicked_at": row.first_clicked_at.isoformat() if row.first_clicked_at else None,
            "last_clicked_at": row.last_clicked_at.isoformat() if row.last_clicked_at else None,
        })

    clicks = []
    for click, contact, item, firm in recent_rows:
        firm_name = (
            (item.firm_name if item else None)
            or (firm.firm_name if firm else None)
            or "Unknown firm"
        )
        clicks.append({
            "id": click.id,
            "clicked_at": click.clicked_at.isoformat() if click.clicked_at else None,
            "app_name": "AI Audit",
            "source": click.source,
            "source_label": _source_label(click.source),
            "firm_name": firm_name,
            "contact_name": contact.full_name or "",
            "contact_email": contact.email or "",
            "persona": (item.persona if item else None) or contact.persona or "",
            "pif_id": click.pif_id,
            "batch_item_id": click.batch_item_id,
            "ip": click.ip,
            "user_agent": click.user_agent,
        })

    total_clicks, total_contacts, total_firms, first_click, last_click = summary_row
    return {
        "since_days": since_days,
        "group_by": group_by,
        "group_label": CLICK_ANALYTICS_GROUPS[group_by],
        "available_groups": [
            {"key": key, "label": label}
            for key, label in CLICK_ANALYTICS_GROUPS.items()
        ],
        "summary": {
            "click_count": int(total_clicks or 0),
            "contact_count": int(total_contacts or 0),
            "firm_count": int(total_firms or 0),
            "first_clicked_at": first_click.isoformat() if first_click else None,
            "last_clicked_at": last_click.isoformat() if last_click else None,
        },
        "groups": groups,
        "recent_clicks": clicks,
    }
