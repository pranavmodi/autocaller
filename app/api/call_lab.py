"""Manual operator calling workspace."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.call_lab import (
    get_call_lab_contact,
    list_call_lab_firms,
    upsert_call_lab_patient,
)
from app.services.call_orchestrator import get_orchestrator


router = APIRouter(prefix="/api/call-lab", tags=["call-lab"])


class StartCallLabCallRequest(BaseModel):
    pif_id: str = Field(..., min_length=1, max_length=64)
    contact_id: str = Field(..., min_length=1, max_length=64)


@router.get("/firms")
async def get_call_lab_firms(
    q: str = Query("", max_length=255),
    limit: int = Query(50, ge=1, le=50),
):
    return await list_call_lab_firms(query=q, limit=limit)


@router.post("/calls")
async def start_call_lab_call(body: StartCallLabCallRequest):
    contact = await get_call_lab_contact(body.pif_id, body.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Callable contact not found or no longer available")

    patient_id = await upsert_call_lab_patient(contact)
    orchestrator = get_orchestrator()
    call = await orchestrator.start_call(
        patient_id,
        call_mode="twilio",
        operator_mode=True,
    )
    if call is None:
        detail = orchestrator._last_start_error or "Call could not be started"
        raise HTTPException(status_code=409, detail=detail)
    return {"call": call.to_dict(), "contact": contact}
