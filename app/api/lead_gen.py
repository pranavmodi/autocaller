"""Cybernetic lead-generation loop endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import AsyncSessionLocal
from app.db.models import FirmContactRow, LeadGenBatchItemRow
from app.services.action_execution import (
    create_send_email_action,
    execute_action,
    find_live_scheduled_action_for_item,
    load_lead_gen_draft_for_edit,
    save_edited_lead_gen_draft,
)
from app.services.lead_gen_cybernetic import (
    approve_batch,
    classify_and_store_observation,
    create_policy_proposal_from_batch,
    create_recommendation_batch,
    daily_send_budget_from_policy,
    ensure_default_policy,
    get_batch,
    list_batches,
    set_daily_send_budget,
)
from app.services.lead_gen_email_agent import create_lead_gen_email_agent_slice
from app.services.lead_gen_daily import (
    get_daily_run_enabled,
    list_daily_runs,
    run_daily_pipeline,
    set_daily_run_enabled,
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


class DailySendBudgetRequest(BaseModel):
    budget: int = Field(default=50, ge=1, le=200)
    updated_by: str = "operator"


class SendBatchItemDraftRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=20000)
    sent_by: str = Field("operator", max_length=128)
    composer_experiment_key: Optional[str] = None
    composer_variant_key: Optional[str] = None
    skill_path: Optional[str] = None
    skill_sha256: Optional[str] = None


class EditBatchItemDraftRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=20000)
    actor: str = Field("operator", max_length=128)
    scheduled_for: Optional[str] = None
    execute_now: bool = False


class LeadGenEmailAgentSliceRequest(BaseModel):
    limit: int = Field(default=3, ge=1, le=10)
    template_key: str = DEFAULT_TEMPLATE_KEY
    created_by: str = Field("master-agent", max_length=128)
    composer_variant_key: Optional[str] = None
    approve_actions: bool = False
    policy_check_first_action: bool = False
    batch_id: Optional[str] = Field(default=None, max_length=64)


class DailyRunRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    created_by: str = Field("operator", max_length=128)


class DailyRunEnabledRequest(BaseModel):
    enabled: bool


@router.get("/api/lead-gen/policy/current")
async def current_policy():
    row = await ensure_default_policy()
    return {
        "version": row.version,
        "label": row.label,
        "target_metric": row.target_metric,
        "weights": row.weights_json,
        "daily_send_budget": daily_send_budget_from_policy(row),
        "suppressions": row.suppressions_json,
        "active": row.active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.put("/api/lead-gen/settings/daily-send-budget")
async def update_daily_send_budget(req: DailySendBudgetRequest):
    row = await set_daily_send_budget(budget=req.budget, updated_by=req.updated_by)
    return {
        "daily_send_budget": daily_send_budget_from_policy(row),
        "policy_version": row.version,
        "weights": row.weights_json,
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


@router.post("/api/lead-gen/email-agent/slice")
async def create_email_agent_slice(req: LeadGenEmailAgentSliceRequest):
    try:
        return await create_lead_gen_email_agent_slice(
            limit=req.limit,
            template_key=req.template_key,
            created_by=req.created_by,
            composer_variant_key=req.composer_variant_key,
            approve_actions=req.approve_actions,
            policy_check_first_action=req.policy_check_first_action,
            batch_id=req.batch_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"lead_gen_email_agent_slice_failed: {type(e).__name__}: {str(e)[:300]}",
        )


@router.get("/api/lead-gen/batches")
async def get_batches(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    return {"batches": await list_batches(limit=limit, status=status)}


@router.post("/api/lead-gen/daily-run")
async def run_daily_lead_gen(req: DailyRunRequest):
    return await run_daily_pipeline(
        dry_run=req.dry_run,
        force=req.force,
        created_by=req.created_by,
    )


@router.get("/api/lead-gen/daily-runs")
async def get_daily_runs(
    limit: int = Query(20, ge=1, le=100),
):
    return {"runs": await list_daily_runs(limit=limit)}


@router.get("/api/lead-gen/daily-run/enabled")
async def get_daily_enabled():
    return await get_daily_run_enabled()


@router.put("/api/lead-gen/daily-run/enabled")
async def put_daily_enabled(req: DailyRunEnabledRequest):
    return await set_daily_run_enabled(req.enabled)


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


@router.post("/api/lead-gen/batch-items/{batch_item_id}/send-draft")
async def send_batch_item_preview_draft(
    batch_item_id: str,
    req: SendBatchItemDraftRequest,
):
    try:
        async with AsyncSessionLocal() as session:
            item = await session.get(LeadGenBatchItemRow, batch_item_id)
            if not item:
                raise ValueError("batch_item_not_found")
            contact = await session.get(FirmContactRow, item.contact_id)
            if not contact or not contact.email:
                raise ValueError("contact_email_not_found")
            scheduled = await find_live_scheduled_action_for_item(session, batch_item_id)
            if scheduled is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "already_scheduled: this draft is queued for auto-send at "
                        f"{scheduled['scheduled_for_pt']} (action {scheduled['id']}). "
                        "Cancel or reschedule it instead of sending again."
                    ),
                )
        action = await create_send_email_action(
            mode="lead_gen",
            to=contact.email,
            subject=req.subject,
            body=req.body,
            requested_by=req.sent_by,
            approved_by=req.sent_by,
            contact_id=item.contact_id,
            batch_item_id=batch_item_id,
            pif_id=item.pif_id,
            firm_name=item.firm_name,
            composer_experiment_key=req.composer_experiment_key,
            composer_variant_key=req.composer_variant_key,
            skill_path=req.skill_path,
            skill_sha256=req.skill_sha256,
        )
        execution = await execute_action(action["id"], actor=req.sent_by)
        result = dict(execution.get("result") or {})
        result["agent_action"] = execution.get("action")
        result["agent_action_policy"] = execution.get("policy")
        return result
    except HTTPException:
        raise
    except ValueError as e:
        detail = str(e)
        if detail in {"batch_item_not_found", "contact_email_not_found"}:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"send_failed: {type(e).__name__}: {str(e)[:300]}",
        )


@router.get("/api/lead-gen/batch-items/{batch_item_id}/draft")
async def get_batch_item_editable_draft(batch_item_id: str):
    try:
        return await load_lead_gen_draft_for_edit(batch_item_id)
    except ValueError as e:
        detail = str(e)
        if detail in {"batch_item_not_found", "agent_draft_not_found"}:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/batch-items/{batch_item_id}/edit-draft")
async def edit_batch_item_draft(batch_item_id: str, req: EditBatchItemDraftRequest):
    try:
        scheduled_for = None
        if req.scheduled_for:
            from datetime import datetime

            scheduled_for = datetime.fromisoformat(req.scheduled_for.replace("Z", "+00:00"))
        return await save_edited_lead_gen_draft(
            batch_item_id=batch_item_id,
            subject=req.subject,
            body=req.body,
            actor=req.actor,
            scheduled_for=scheduled_for,
            execute_now=req.execute_now,
        )
    except ValueError as e:
        detail = str(e)
        if detail in {"batch_item_not_found", "agent_draft_not_found"}:
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"edit_draft_failed: {type(e).__name__}: {str(e)[:300]}",
        )


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
