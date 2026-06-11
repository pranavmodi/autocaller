"""Durable action execution endpoints for Possible OS."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.action_execution import (
    check_action_policy,
    create_and_execute_send_approved_lead_gen_draft,
    create_send_email_action,
    create_and_execute_send_test_email,
    create_send_approved_lead_gen_draft_action,
    create_send_test_email_action,
    execute_action,
    execute_approved_lead_gen_email_actions,
    get_action,
    list_actions,
)
from app.services.action_scheduler import count_pending_scheduled_actions, scheduler_status


router = APIRouter(prefix="/api/actions", tags=["actions"])


class LeadGenDraftActionRequest(BaseModel):
    batch_item_id: str = Field(..., min_length=1, max_length=64)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    requested_by: str = Field("operator", max_length=128)
    approved_by: str = Field("operator", max_length=128)
    composer_experiment_key: str | None = None
    composer_variant_key: str | None = None
    skill_path: str | None = None
    skill_sha256: str | None = None
    brief_version: int | None = None
    scheduled_for: datetime | None = None


class TestEmailActionRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    requested_by: str = Field("operator", max_length=128)
    approved_by: str = Field("operator", max_length=128)
    from_addr: str | None = None


class EmailActionRequest(TestEmailActionRequest):
    mode: str = Field("test", max_length=32)
    contact_id: str | None = Field(None, max_length=64)
    batch_item_id: str | None = Field(None, max_length=64)
    pif_id: str | None = Field(None, max_length=64)
    firm_name: str | None = Field(None, max_length=255)
    composer_experiment_key: str | None = None
    composer_variant_key: str | None = None
    skill_path: str | None = None
    skill_sha256: str | None = None
    brief_version: int | None = None
    scheduled_for: datetime | None = None


class ExecuteActionRequest(BaseModel):
    actor: str = Field("operator", max_length=128)


class ExecuteApprovedLeadGenActionsRequest(BaseModel):
    actor: str = Field("operator", max_length=128)
    limit: int = Field(1, ge=1, le=25)


@router.get("")
async def actions(
    status: str | None = Query(None),
    action_type: str | None = Query(None),
    scheduled: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
):
    return {
        "actions": await list_actions(
            status=status,
            action_type=action_type,
            scheduled=scheduled,
            limit=limit,
        ),
        "pending_scheduled_count": await count_pending_scheduled_actions(),
    }


@router.get("/scheduler/status")
async def scheduler():
    return await scheduler_status()


@router.get("/{action_id}")
async def action(action_id: str):
    result = await get_action(action_id)
    if not result:
        raise HTTPException(status_code=404, detail="action_not_found")
    return result


@router.post("/{action_id}/policy-check")
async def policy_check(action_id: str, req: ExecuteActionRequest | None = None):
    try:
        return {"policy": await check_action_policy(action_id, actor=(req.actor if req else "operator"))}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{action_id}/execute")
async def execute(action_id: str, req: ExecuteActionRequest | None = None):
    try:
        return await execute_action(action_id, actor=(req.actor if req else "operator"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {str(exc)[:500]}")


@router.post("/lead-gen/send-approved-draft")
async def create_lead_gen_send_action(req: LeadGenDraftActionRequest, execute_now: bool = Query(False)):
    kwargs: dict[str, Any] = req.model_dump()
    try:
        if execute_now:
            return await create_and_execute_send_approved_lead_gen_draft(**kwargs)
        action = await create_send_approved_lead_gen_draft_action(**kwargs)
        if kwargs.get("scheduled_for"):
            return {
                "action": action,
                "policy": await check_action_policy(action["id"], actor=kwargs.get("approved_by") or "operator"),
            }
        return {"action": action}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {str(exc)[:500]}")


@router.post("/lead-gen/execute-approved")
async def execute_approved_lead_gen_actions(req: ExecuteApprovedLeadGenActionsRequest):
    try:
        return await execute_approved_lead_gen_email_actions(
            actor=req.actor,
            limit=req.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {str(exc)[:500]}")


@router.post("/email/send")
async def create_email_action(req: EmailActionRequest, execute_now: bool = Query(False)):
    kwargs: dict[str, Any] = req.model_dump()
    try:
        if execute_now:
            action = await create_send_email_action(**kwargs)
            return await execute_action(action["id"], actor=kwargs.get("approved_by") or "operator")
        action = await create_send_email_action(**kwargs)
        if kwargs.get("scheduled_for"):
            return {
                "action": action,
                "policy": await check_action_policy(action["id"], actor=kwargs.get("approved_by") or "operator"),
            }
        return {"action": action}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {str(exc)[:500]}")


@router.post("/email/send-test")
async def create_test_email_action(req: TestEmailActionRequest, execute_now: bool = Query(False)):
    kwargs: dict[str, Any] = req.model_dump()
    try:
        if execute_now:
            return await create_and_execute_send_test_email(**kwargs)
        return {"action": await create_send_test_email_action(**kwargs)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {str(exc)[:500]}")
