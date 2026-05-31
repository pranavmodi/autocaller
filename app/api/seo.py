"""SEO and agent-optimization endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.seo_audit import generate_seo_action_notifications, run_seo_audit


router = APIRouter(prefix="/api/seo", tags=["seo"])


class SeoActionRequest(BaseModel):
    site_url: str | None = Field(None, max_length=500)
    limit: int = Field(20, ge=1, le=50)
    action_limit: int = Field(20, ge=1, le=50)


@router.get("/audit")
async def seo_audit(site_url: str | None = None, limit: int = 20):
    return await run_seo_audit(site_url=site_url, limit=limit)


@router.post("/actions")
async def seo_actions(payload: SeoActionRequest | None = None):
    request = payload or SeoActionRequest()
    return await generate_seo_action_notifications(
        site_url=request.site_url,
        limit=request.limit,
        action_limit=request.action_limit,
    )
