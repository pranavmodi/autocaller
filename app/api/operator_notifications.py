"""Operator notification endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.operator_notifications import (
    acknowledge_notification,
    list_pending_notifications,
    send_notification_draft_reply,
)


router = APIRouter(prefix="/api/operator-notifications", tags=["operator-notifications"])


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str = Field("operator", max_length=128)


class SendDraftRequest(BaseModel):
    subject: str | None = Field(None, max_length=500)
    body: str | None = Field(None, max_length=20000)
    sent_by: str = Field("operator", max_length=128)


@router.get("/pending")
async def pending_operator_notifications(limit: int = 10):
    return {"pending": await list_pending_notifications(limit=limit)}


@router.post("/{notification_id}/acknowledge")
async def acknowledge_operator_notification(
    notification_id: int,
    payload: AcknowledgeRequest | None = None,
):
    result = await acknowledge_notification(
        notification_id,
        acknowledged_by=(payload.acknowledged_by if payload else "operator"),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"notification": result}


@router.post("/{notification_id}/send-draft")
async def send_operator_notification_draft(
    notification_id: int,
    payload: SendDraftRequest,
):
    try:
        result = await send_notification_draft_reply(
            notification_id,
            subject=payload.subject,
            body=payload.body,
            sent_by=payload.sent_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"notification": result}
