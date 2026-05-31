"""Trace-based learning loop endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.product_learning import (
    analyze_recent_activity,
    create_eval_case_for_finding,
    create_task_packet_for_finding,
    get_learning_measurements,
    list_eval_cases,
    list_findings,
    list_task_packets,
    review_finding,
    sync_outcome_traces,
)


router = APIRouter(prefix="/api/learning", tags=["learning"])


class AnalyzeRequest(BaseModel):
    limit: int = Field(500, ge=1, le=1000)


class SyncOutcomesRequest(BaseModel):
    limit: int = Field(100, ge=1, le=500)


class ReviewFindingRequest(BaseModel):
    status: str = Field(..., max_length=16)
    reviewed_by: str = Field("operator", max_length=128)


@router.get("/findings")
async def findings(status: str | None = None, workflow: str | None = None, limit: int = 100):
    return {"findings": await list_findings(status=status, workflow=workflow, limit=limit)}


@router.get("/measurements")
async def measurements():
    return await get_learning_measurements()


@router.post("/analyze")
async def analyze(payload: AnalyzeRequest | None = None):
    request = payload or AnalyzeRequest()
    return await analyze_recent_activity(limit=request.limit)


@router.post("/sync-outcomes")
async def sync_outcomes(payload: SyncOutcomesRequest | None = None):
    request = payload or SyncOutcomesRequest()
    return await sync_outcome_traces(limit=request.limit)


@router.post("/findings/{finding_id}/review")
async def review(finding_id: str, payload: ReviewFindingRequest):
    try:
        finding = await review_finding(
            finding_id,
            status=payload.status,
            reviewed_by=payload.reviewed_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not finding:
        raise HTTPException(status_code=404, detail="finding not found")
    return {"finding": finding}


@router.post("/findings/{finding_id}/eval-case")
async def create_eval_case(finding_id: str):
    eval_case = await create_eval_case_for_finding(finding_id)
    if not eval_case:
        raise HTTPException(status_code=404, detail="finding not found")
    return {"eval_case": eval_case}


@router.get("/eval-cases")
async def eval_cases(limit: int = 100):
    return {"eval_cases": await list_eval_cases(limit=limit)}


@router.post("/findings/{finding_id}/task-packet")
async def create_task_packet(finding_id: str):
    packet = await create_task_packet_for_finding(finding_id)
    if not packet:
        raise HTTPException(status_code=404, detail="finding not found")
    return {"task_packet": packet}


@router.get("/task-packets")
async def task_packets(limit: int = 100):
    return {"task_packets": await list_task_packets(limit=limit)}
