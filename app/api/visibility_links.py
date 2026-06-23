"""Public AI Visibility report redirect and attribution endpoint."""
from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.db import AsyncSessionLocal
from app.db.models import AuditLinkClickRow
from app.services.lead_gen_cybernetic import record_observation
from app.services.visibility_links import resolve_visibility_code, visibility_report_base_url


router = APIRouter(tags=["ai-visibility"])


def _new_id() -> str:
    return f"visibilityclick_{secrets.token_urlsafe(12)}"


def _clean(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


@router.get("/v/{code}")
async def visibility_short_go(code: str, request: Request) -> RedirectResponse:
    base = visibility_report_base_url()
    try:
        payload = await resolve_visibility_code(code)
    except Exception:
        payload = None
    if not payload:
        return RedirectResponse(url=base, status_code=302)

    click_id = _new_id()
    contact_id = _clean(payload.get("contact_id"), 64)
    batch_item_id = _clean(payload.get("batch_item_id"), 64) or None
    pif_id = _clean(payload.get("pif_id"), 64) or None
    scan_id = _clean(payload.get("scan_id"), 128)
    source = "visibility_report_email"
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
                "channel": "ai_visibility",
                "click_id": click_id,
                "scan_id": scan_id,
                "link_code": _clean(payload.get("link_code"), 64) or code,
            },
            contact_id=contact_id,
            batch_item_id=batch_item_id,
        )
    except Exception:
        pass

    query = urlencode({"c": click_id, "src": source})
    return RedirectResponse(url=f"{base}/r/{scan_id}?{query}", status_code=302)
