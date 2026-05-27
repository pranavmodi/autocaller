"""Cybernetic lead-generation loop endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.lead_gen_cybernetic import (
    approve_batch,
    classify_and_store_observation,
    create_policy_proposal_from_batch,
    create_recommendation_batch,
    ensure_default_policy,
    get_batch,
    list_batches,
)
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY


router = APIRouter(tags=["lead-gen"])


class CreateBatchRequest(BaseModel):
    name: Optional[str] = None
    template_key: str = DEFAULT_TEMPLATE_KEY
    limit: int = Field(default=50, ge=1, le=200)
    created_by: str = "operator"


class ApproveBatchRequest(BaseModel):
    approved_by: str = "operator"
    start_sequences: bool = False
    stagger_minutes: int = Field(default=60, ge=0, le=1440)
    scheduled_start_at: Optional[str] = None
    scheduled_timezone: str = "America/Los_Angeles"


class ObservationRequest(BaseModel):
    event_type: str
    raw_event: dict
    batch_id: Optional[str] = None
    contact_id: Optional[str] = None
    batch_item_id: Optional[str] = None
    model: Optional[str] = None


class ProposalRequest(BaseModel):
    created_by: str = "system"


@router.get("/api/lead-gen/policy/current")
async def current_policy():
    row = await ensure_default_policy()
    return {
        "version": row.version,
        "label": row.label,
        "target_metric": row.target_metric,
        "weights": row.weights_json,
        "suppressions": row.suppressions_json,
        "active": row.active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/api/lead-gen/batches")
async def create_batch(req: CreateBatchRequest):
    try:
        return await create_recommendation_batch(
            name=req.name,
            template_key=req.template_key,
            limit=req.limit,
            created_by=req.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/lead-gen/batches")
async def get_batches(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    return {"batches": await list_batches(limit=limit, status=status)}


@router.get("/api/lead-gen/batches/{batch_id}")
async def get_one_batch(
    batch_id: str,
    include_observations: bool = Query(False),
):
    try:
        return await get_batch(batch_id, include_observations=include_observations)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/lead-gen/batches/{batch_id}/approve")
async def approve_one_batch(batch_id: str, req: ApproveBatchRequest):
    try:
        return await approve_batch(
            batch_id=batch_id,
            approved_by=req.approved_by,
            start_sequences=req.start_sequences,
            stagger_minutes=req.stagger_minutes,
            scheduled_start_at=req.scheduled_start_at,
            scheduled_timezone=req.scheduled_timezone,
        )
    except ValueError as e:
        if str(e) in {"invalid_scheduled_start_at", "invalid_scheduled_timezone"}:
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/lead-gen/observations/classify")
async def classify_observation(req: ObservationRequest):
    if not req.batch_item_id and not (req.batch_id and req.contact_id):
        raise HTTPException(
            status_code=400,
            detail="Provide batch_item_id or both batch_id and contact_id.",
        )
    try:
        return await classify_and_store_observation(
            event_type=req.event_type,
            raw_event=req.raw_event,
            batch_id=req.batch_id,
            contact_id=req.contact_id,
            batch_item_id=req.batch_item_id,
            model=req.model,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/lead-gen/batches/{batch_id}/proposal")
async def propose_from_batch(batch_id: str, req: ProposalRequest):
    try:
        return await create_policy_proposal_from_batch(
            batch_id=batch_id,
            created_by=req.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
