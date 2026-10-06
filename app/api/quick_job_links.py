"""Quick company and job-link capture endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from app.services.quick_job_links import (
    create_quick_job_link,
    delete_quick_job_link,
    list_quick_job_links,
)


router = APIRouter(prefix="/api/quick-job-links", tags=["quick-job-links"])
LinkType = Literal["job", "portal"]


class QuickJobLinkCreateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    job_url: HttpUrl
    link_type: LinkType = "job"
    actor: str = Field("operator", max_length=128)


@router.get("")
async def get_quick_job_links(
    link_type: LinkType | None = None,
    limit: int = Query(200, ge=1, le=500),
):
    links = await list_quick_job_links(link_type=link_type, limit=limit)
    return {"links": links, "count": len(links)}


@router.post("", status_code=201)
async def post_quick_job_link(req: QuickJobLinkCreateRequest):
    try:
        return {
            "link": await create_quick_job_link(
                company_name=req.company_name,
                job_url=str(req.job_url),
                link_type=req.link_type,
                actor=req.actor,
            )
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{link_id}")
async def remove_quick_job_link(link_id: int):
    if not await delete_quick_job_link(link_id):
        raise HTTPException(status_code=404, detail="quick_job_link_not_found")
    return {"deleted": True, "id": link_id}
