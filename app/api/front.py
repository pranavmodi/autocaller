"""Front observability and Front-warm batch endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.front_sync import (
    create_front_warm_batch,
    front_signals,
    front_status,
    front_warm_firms,
    list_front_contacts,
)
from app.services.competitor_graph import (
    competitor_summary,
    get_competitors,
    rebuild_competitor_graph,
)
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY


router = APIRouter(tags=["front"])


class FrontWarmBatchRequest(BaseModel):
    domains: list[str] = Field(default_factory=list, min_length=1, max_length=100)
    name: Optional[str] = Field(default=None, max_length=255)
    template_key: str = DEFAULT_TEMPLATE_KEY
    created_by: str = Field(default="operator", max_length=128)


@router.get("/api/front/status")
async def get_front_status():
    return await front_status()


@router.get("/api/front/warm-list")
async def get_front_warm_list(limit: int = Query(20, ge=1, le=100)):
    return {"warm_list": await front_warm_firms(limit=limit)}


@router.get("/api/front/contacts")
async def get_front_contacts(
    domain: str = Query("", max_length=255),
    q: str = Query("", max_length=255),
    limit: int = Query(50, ge=1, le=500),
):
    return {"contacts": await list_front_contacts(domain=domain, q=q, limit=limit)}


@router.get("/api/front/signals")
async def get_front_signals():
    return await front_signals()


@router.post("/api/front/warm-batch")
async def post_front_warm_batch(req: FrontWarmBatchRequest):
    try:
        return await create_front_warm_batch(
            domains=req.domains,
            name=req.name,
            template_key=req.template_key,
            created_by=req.created_by,
        )
    except ValueError as e:
        detail = str(e)
        status = 404 if detail in {"no_matched_front_warm_domains", "no_eligible_named_contacts"} else 400
        raise HTTPException(status_code=status, detail=detail)


@router.post("/api/front/competitors/rebuild")
async def post_front_competitors_rebuild():
    return await rebuild_competitor_graph()


@router.get("/api/front/competitors")
async def get_front_competitors(
    domain: str = Query("", max_length=255),
    pif_id: str = Query("", max_length=64),
    limit: int = Query(10, ge=1, le=50),
):
    if not domain and not pif_id:
        raise HTTPException(status_code=400, detail="domain_or_pif_id_required")
    return await get_competitors(domain=domain, pif_id=pif_id, limit=limit)


@router.get("/api/front/competitors/summary")
async def get_front_competitors_summary():
    return await competitor_summary()
