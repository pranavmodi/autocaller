"""Inbound email ingestion endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.inbound_email import (
    ingest_zoho_inbox,
    list_inbound_emails,
    masked_inbound_config,
)


router = APIRouter(tags=["inbound-email"])


class InboundPollRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=200)
    unseen_only: bool = True
    since_days: Optional[int] = Field(default=14, ge=0, le=365)
    classify: bool = False
    mark_seen: Optional[bool] = None


@router.get("/api/inbound-email/config")
async def inbound_email_config():
    return masked_inbound_config()


@router.post("/api/inbound-email/poll")
async def poll_inbound_email(req: InboundPollRequest):
    try:
        return await ingest_zoho_inbox(
            limit=req.limit,
            unseen_only=req.unseen_only,
            since_days=req.since_days,
            classify=req.classify,
            mark_seen=req.mark_seen,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/inbound-email")
async def get_inbound_email(
    limit: int = Query(50, ge=1, le=200),
    matched: Optional[bool] = Query(None),
):
    return {"messages": await list_inbound_emails(limit=limit, matched=matched)}
