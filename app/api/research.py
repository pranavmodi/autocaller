"""Firm research orchestration endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.firm_research import orchestrate_warm_research, research_coverage


router = APIRouter(tags=["research"])


class ResearchWarmRequest(BaseModel):
    top_n: int = Field(default=50, ge=1, le=100)
    kinds: list[str] = Field(default_factory=lambda: ["research", "staff"])
    timeout_seconds: Optional[int] = Field(default=1800, ge=1, le=1800)


@router.post("/api/research/warm")
async def post_research_warm(req: ResearchWarmRequest):
    try:
        return await orchestrate_warm_research(
            top_n=req.top_n,
            kinds=req.kinds,
            timeout_seconds=req.timeout_seconds or 1800,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/research/status")
async def get_research_status():
    return await research_coverage()
