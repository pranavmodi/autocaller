"""Public AI Audit redirect and attribution endpoints."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import Integer, case, cast, desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AuditLinkClickRow,
    FirmCompetitiveFeatureRow,
    FirmContactRow,
    FrontFirmActivityRow,
    LeadGenObservationRow,
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


def _consult_public_url() -> str:
    # The consult page lives on the main marketing site, NOT the aiaudit
    # subdomain, so do not derive this from AIAUDIT_PUBLIC_URL.
    return os.getenv("CONSULT_URL", "https://getpossibleminds.com/consult").rstrip("/")


def _solution_public_url() -> str:
    # The product/solution page lives on the main marketing site.
    return os.getenv(
        "OUTBOUND_VOICE_SOLUTION_URL",
        "https://getpossibleminds.com/solutions/outbound-voice-ai",
    ).rstrip("/")


def _intake_demo_public_url() -> str:
    return os.getenv(
        "INTAKE_DEMO_PUBLIC_URL",
        "https://intake.getpossibleminds.com",
    ).rstrip("/")


async def _firm_name_for_payload(payload: dict[str, Any]) -> str:
    batch_item_id = _clean(payload.get("batch_item_id"), 64) or None
    pif_id = _clean(payload.get("pif_id"), 64) or None
    firm = ""
    async with AsyncSessionLocal() as session:
        item = await session.get(LeadGenBatchItemRow, batch_item_id) if batch_item_id else None
        if item:
            firm = _clean(item.firm_name)
            pif_id = pif_id or item.pif_id
        if not firm and pif_id:
            firm = _clean(await resolve_firm_name(pif_id))
        pif_firm = await session.get(PifFirmRow, pif_id) if pif_id else None
        if not firm and pif_firm:
            firm = _clean(pif_firm.firm_name)
    return firm


async def _record_link_click(
    request: Request,
    payload: dict[str, Any],
    *,
    channel: str,
) -> str | None:
    """Persist a click row + lead-gen link_clicked observation. Returns the
    click_id (or None on failure). Shared by the audit and consult redirects."""
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
            session.add(AuditLinkClickRow(
                id=click_id,
                contact_id=contact_id,
                batch_item_id=batch_item_id,
                pif_id=pif_id,
                source=source,
                ip=(ip or "")[:64] or None,
                user_agent=(ua or "")[:512] or None,
                referer=(referer or "")[:1024] or None,
            ))
            await session.commit()
        await record_observation(
            event_type="link_clicked",
            raw_event={
                "source": source,
                "channel": channel,
                "click_id": click_id,
                "pif_id": pif_id,
                "link_code": _clean(payload.get("link_code"), 64) or None,
            },
            contact_id=contact_id,
            batch_item_id=batch_item_id,
        )
        return click_id
    except Exception:
        return None


async def _audit_redirect_for_payload(
    request: Request,
    payload: dict[str, Any] | None,
) -> RedirectResponse:
    base = _audit_public_url()
    if not payload:
        return RedirectResponse(url=base, status_code=302)

    click_id = await _record_link_click(request, payload, channel="ai_audit")
    prefill: dict[str, Any] = {}
    if click_id:
        try:
            prefill = await _prefill_for_payload(payload)
        except Exception:
            prefill = {}

    query = {key: value for key, value in (prefill or {}).items() if value}
    if click_id:
        query["c"] = click_id
    return RedirectResponse(url=f"{base}/?{urlencode(query)}", status_code=302)


async def _consult_redirect_for_payload(
    request: Request,
    payload: dict[str, Any] | None,
) -> RedirectResponse:
    """Consult link redirect: record the click, then send to the consult page.
    Unknown/forged codes still redirect to consult (never error the visitor)."""
    dest = _consult_public_url()
    if not payload:
        return RedirectResponse(url=dest, status_code=302)
    click_id = await _record_link_click(request, payload, channel="consult")
    # Carry the link code (+click id) so the consult page's beacon can attribute
    # a human session back to this recipient, same as the /s/ redirect.
    code = _clean(payload.get("link_code"), 64)
    params = {}
    if code:
        params["lc"] = code
    if click_id:
        params["c"] = click_id
    if params:
        sep = "&" if "?" in dest else "?"
        dest = f"{dest}{sep}{urlencode(params)}"
    return RedirectResponse(url=dest, status_code=302)


async def _solution_redirect_for_payload(
    request: Request,
    payload: dict[str, Any] | None,
) -> RedirectResponse:
    """Solution/product link redirect: record the click, then send to the
    solution page. Carries the link code as a query param so the page's
    early-access form can attribute the signup back to this recipient."""
    dest = _solution_public_url()
    if not payload:
        return RedirectResponse(url=dest, status_code=302)
    click_id = await _record_link_click(request, payload, channel="solution")
    code = _clean(payload.get("link_code"), 64)
    params = {}
    if code:
        params["lc"] = code
    if click_id:
        params["c"] = click_id
    sep = "&" if "?" in dest else "?"
    url = f"{dest}{sep}{urlencode(params)}" if params else dest
    return RedirectResponse(url=url, status_code=302)


async def _intake_redirect_for_payload(
    request: Request,
    payload: dict[str, Any] | None,
) -> RedirectResponse:
    """Intake-demo redirect: record the click, then send to the browser-call
    demo with firm attribution so the page and assistant can personalize."""
    dest = _intake_demo_public_url()
    if not payload:
        return RedirectResponse(url=dest, status_code=302)
    click_id = await _record_link_click(request, payload, channel="intake_demo")
    code = _clean(payload.get("link_code"), 64)
    params = {}
    try:
        firm = await _firm_name_for_payload(payload)
    except Exception:
        firm = ""
    if firm:
        params["firm"] = firm
    if code:
        params["lc"] = code
    if click_id:
        params["c"] = click_id
    sep = "&" if "?" in dest else "?"
    url = f"{dest}{sep}{urlencode(params)}" if params else dest
    return RedirectResponse(url=url, status_code=302)


@router.get("/a/{code}")
async def aiaudit_short_go(code: str, request: Request) -> RedirectResponse:
    return await _audit_redirect_for_payload(request, await resolve_short_audit_code(code))


@router.get("/c/{code}")
async def consult_short_go(code: str, request: Request) -> RedirectResponse:
    payload = await resolve_short_audit_code(code)
    # Defensive: a code that exists but is not a consult code should not leak
    # the audit prefill flow; treat only kind="consult" as a consult click.
    if payload and payload.get("kind") != "consult":
        payload = None
    return await _consult_redirect_for_payload(request, payload)


@router.get("/s/{code}")
async def solution_short_go(code: str, request: Request) -> RedirectResponse:
    payload = await resolve_short_audit_code(code)
    if payload and payload.get("kind") != "solution":
        payload = None
    return await _solution_redirect_for_payload(request, payload)


@router.get("/i/{code}")
async def intake_demo_short_go(code: str, request: Request) -> RedirectResponse:
    payload = await resolve_short_audit_code(code)
    if payload and payload.get("kind") != "intake":
        payload = None
    return await _intake_redirect_for_payload(request, payload)


@router.get("/aiaudit/go")
async def aiaudit_go(request: Request) -> RedirectResponse:
    return await _audit_redirect_for_payload(request, verify_audit_token(request.query_params.get("t")))


def _app_name_expr():
    return case(
        (AuditLinkClickRow.source.in_(["ai_audit_signature", "ai_audit_email"]), "AI Audit"),
        (AuditLinkClickRow.source.in_(["consult_email", "consult_signature"]), "Consult"),
        (AuditLinkClickRow.source.in_(["solution_email", "solution_signature"]), "Solution"),
        (AuditLinkClickRow.source.in_(["intake_demo_email", "intake_demo_signature"]), "Intake Demo"),
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


def _human_session_where(stmt, *, since_days: int):
    stmt = stmt.where(LeadGenObservationRow.event_type == "page_session")
    if since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        stmt = stmt.where(LeadGenObservationRow.created_at >= cutoff)
    return stmt


def _human_session_time_ms_expr():
    value = LeadGenObservationRow.raw_event_json["time_on_page_ms"].astext
    return case(
        (value.op("~")(r"^[0-9]+$"), cast(value, Integer)),
        else_=None,
    )


async def _human_session_analytics(session, *, since_days: int, limit: int, click_count: int):
    page_expr = func.coalesce(
        LeadGenObservationRow.raw_event_json["page"].astext,
        "unknown",
    ).label("page")
    day_expr = func.to_char(LeadGenObservationRow.created_at, "YYYY-MM-DD").label("day")
    session_id_expr = LeadGenObservationRow.raw_event_json["session_id"].astext
    time_ms_expr = _human_session_time_ms_expr()
    median_time_expr = (
        func.percentile_cont(0.5)
        .within_group(time_ms_expr)
        .filter(time_ms_expr > 0)
        .label("median_time_on_page_ms")
    )

    summary_stmt = _human_session_where(
        select(
            func.count(LeadGenObservationRow.id).label("human_session_count"),
            func.count(func.distinct(session_id_expr)).label("distinct_human_sessions"),
        ),
        since_days=since_days,
    )
    by_page_stmt = _human_session_where(
        select(
            page_expr,
            func.count(LeadGenObservationRow.id).label("sessions"),
            func.count(func.distinct(session_id_expr)).label("distinct_sessions"),
            median_time_expr,
        )
        .group_by(page_expr)
        .order_by(desc("sessions"))
        .limit(limit),
        since_days=since_days,
    )
    by_day_stmt = _human_session_where(
        select(
            day_expr,
            func.count(func.distinct(session_id_expr)).label("distinct_sessions"),
        )
        .group_by(day_expr)
        .order_by(day_expr),
        since_days=since_days,
    )

    summary_row = (await session.execute(summary_stmt)).one()
    by_page_rows = (await session.execute(by_page_stmt)).all()
    by_day_rows = (await session.execute(by_day_stmt)).all()

    human_session_count = int(summary_row.human_session_count or 0)
    distinct_human_sessions = int(summary_row.distinct_human_sessions or 0)
    ratio = round(distinct_human_sessions / click_count, 3) if click_count else 0

    return {
        "summary": {
            "human_session_count": human_session_count,
            "distinct_human_sessions": distinct_human_sessions,
            "human_to_click_ratio": ratio,
        },
        "human_sessions_by_page": [
            {
                "page": row.page or "unknown",
                "sessions": int(row.sessions or 0),
                "distinct_sessions": int(row.distinct_sessions or 0),
                "median_time_on_page_ms": (
                    float(row.median_time_on_page_ms)
                    if row.median_time_on_page_ms is not None
                    else None
                ),
            }
            for row in by_page_rows
        ],
        "human_sessions_by_day": [
            {
                "day": row.day,
                "distinct_sessions": int(row.distinct_sessions or 0),
            }
            for row in by_day_rows
        ],
    }


def _source_label(source: str) -> str:
    labels = {
        "ai_audit_signature": "Signature CTA",
        "ai_audit_email": "AI Audit email",
        "consult_email": "Consult email",
        "consult_signature": "Consult signature",
        "solution_email": "Solution email",
        "solution_signature": "Solution signature",
        "intake_demo_email": "Intake demo email",
        "intake_demo_signature": "Intake demo signature",
    }
    return labels.get(source or "", source or "Unknown")


def _app_name_for_source(source: str) -> str:
    if source in {"ai_audit_signature", "ai_audit_email"}:
        return "AI Audit"
    if source in {"consult_email", "consult_signature"}:
        return "Consult"
    if source in {"solution_email", "solution_signature"}:
        return "Solution"
    if source in {"intake_demo_email", "intake_demo_signature"}:
        return "Intake Demo"
    return "Unknown"


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
        total_clicks, total_contacts, total_firms, first_click, last_click = summary_row
        total_click_count = int(total_clicks or 0)
        human_session_analytics = await _human_session_analytics(
            session,
            since_days=since_days,
            limit=limit,
            click_count=total_click_count,
        )

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
            "app_name": _app_name_for_source(click.source),
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

    return {
        "since_days": since_days,
        "group_by": group_by,
        "group_label": CLICK_ANALYTICS_GROUPS[group_by],
        "available_groups": [
            {"key": key, "label": label}
            for key, label in CLICK_ANALYTICS_GROUPS.items()
        ],
        "summary": {
            "click_count": total_click_count,
            "contact_count": int(total_contacts or 0),
            "firm_count": int(total_firms or 0),
            "first_clicked_at": first_click.isoformat() if first_click else None,
            "last_clicked_at": last_click.isoformat() if last_click else None,
            **human_session_analytics["summary"],
        },
        "human_sessions_by_page": human_session_analytics["human_sessions_by_page"],
        "human_sessions_by_day": human_session_analytics["human_sessions_by_day"],
        "groups": groups,
        "recent_clicks": clicks,
    }
