"""Cybernetic lead-generation loop endpoints."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import ipaddress
from typing import Any, Optional
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AgentActionRow,
    EmailLogRow,
    FirmContactRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenObservationRow,
)
from app.services.action_execution import (
    approve_lead_gen_batch_send_actions,
    create_send_email_action,
    execute_action,
    find_live_scheduled_action_for_item,
    load_lead_gen_draft_for_edit,
    rotate_lead_gen_batch_subjects,
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
    provider_daily_caps_from_policy,
    record_observation,
    set_daily_send_budget,
    set_lead_gen_transport,
)
from app.services.lead_gen_curated import (
    add_contacts_to_batch,
    create_curated_batch,
    move_items_to_batch,
    recount_batch,
)
from app.services.lead_gen_email_agent import (
    create_founder_profile_email_batch,
    create_lead_gen_email_agent_slice,
    recompose_item_draft,
)
from app.services.linkedin_resolver import resolve_linkedin_for_batch
from app.services.lead_gen_daily import (
    daily_channel_plan,
    get_daily_run_enabled,
    get_daily_run_throughput,
    list_daily_runs,
    run_daily_pipeline,
    schedule_drafted_batch_items,
    set_daily_run_enabled,
    top_up_daily_run,
)
from app.services.lead_gen_experiments import (
    close_batch_experiment,
    experiment_rollup,
    list_experiment_batches,
    set_batch_experiment,
)
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY


router = APIRouter(tags=["lead-gen"])
PT = ZoneInfo("America/Los_Angeles")

COUNTRY_NAMES = {
    "IN": "India",
    "US": "United States",
}


class CreateBatchRequest(BaseModel):
    name: Optional[str] = None
    template_key: str = DEFAULT_TEMPLATE_KEY
    target_metric: str = "meetings_booked"
    limit: int = Field(default=50, ge=1, le=200)
    created_by: str = "operator"
    curated: bool = False


class AddContactsToBatchRequest(BaseModel):
    contacts: list[str] = Field(default_factory=list)
    actor: str = Field(default="operator", max_length=128)


class ResolveBatchLinkedInRequest(BaseModel):
    force: bool = False
    only_decision_makers: bool = True
    limit: int = Field(default=25, ge=1, le=25)


class MoveItemsToBatchRequest(BaseModel):
    source_batch_ids: list[str] = Field(default_factory=list)
    actor: str = Field(default="operator", max_length=128)


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
    resend_daily_budget: Optional[int] = Field(default=None, ge=0, le=200)
    updated_by: str = "operator"


class TransportSettingsRequest(BaseModel):
    strategy: Optional[str] = Field(
        default=None,
        description="zoho_first_then_resend | resend_first_then_zoho",
    )
    zoho_cap: Optional[int] = Field(default=None, ge=0, le=200)
    resend_cap: Optional[int] = Field(default=None, ge=0, le=200)
    updated_by: str = "operator"


class ExperimentCardRequest(BaseModel):
    actor: str = "operator"
    card: dict[str, Any] = Field(default_factory=dict)


class ExperimentCloseRequest(BaseModel):
    actor: str = "operator"
    verdict: str
    learning: str
    why: str
    next_hypothesis: str
    next_recommended_wave: str
    confidence_note: str
    superseded: bool = False


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


class FounderProfileBatchRequest(BaseModel):
    limit: int = Field(default=40, ge=1, le=40)
    template_key: str = DEFAULT_TEMPLATE_KEY
    created_by: str = Field("operator", max_length=128)
    composer_variant_key: Optional[str] = Field("intake-demo", max_length=120)
    name: Optional[str] = Field(default=None, max_length=255)
    approve_actions: bool = False


class RecomposeBatchItemDraftRequest(BaseModel):
    actor: str = Field("operator", max_length=128)
    composer_variant_key: Optional[str] = None


class DailyRunRequest(BaseModel):
    dry_run: bool = False
    force: bool = False
    # On a forced re-run, cancel the superseded same-day batch's still-pending
    # (approved/waiting) sends first, so the day's leads aren't double-emailed.
    cancel_existing: bool = False
    created_by: str = Field("operator", max_length=128)
    # Pin one composer variant for every email in this run (first-touch + follow-
    # up), overriding the per-item default / A/B. Empty/None = normal behavior.
    composer_variant_key: Optional[str] = Field(None, max_length=120)


class DailyRunTopUpRequest(BaseModel):
    n: int = Field(..., ge=1, le=40)
    composer_variant_key: Optional[str] = Field(None, max_length=120)


class ScheduleDraftedBatchRequest(BaseModel):
    start: str = Field(default="09:00", max_length=5)
    end: str = Field(default="12:00", max_length=5)
    timezone: str = Field(default="America/Los_Angeles", max_length=80)
    date: Optional[str] = Field(default=None, max_length=10)
    actor: str = Field(default="operator", max_length=128)
    approve: bool = True


class RotateBatchSubjectsRequest(BaseModel):
    subjects: list[str] = Field(default_factory=list)
    actor: str = Field(default="operator", max_length=128)


class DailyRunEnabledRequest(BaseModel):
    enabled: bool


def _validate_composer_variant_key(raw_key: Optional[str]) -> Optional[str]:
    variant_key = (raw_key or "").strip() or None
    if variant_key:
        from app.services.lead_email_composer_variants import (
            discover_composer_skill_variants,
            get_composer_skill_variant,
        )
        if get_composer_skill_variant(variant_key) is None:
            valid = [v.key for v in discover_composer_skill_variants() if v.active]
            raise HTTPException(
                status_code=400,
                detail=f"unknown or inactive composer variant '{variant_key}'. Active: {', '.join(valid)}",
            )
    return variant_key


def _pt_day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min, tzinfo=PT)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _format_pt(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.astimezone(PT).strftime("%Y-%m-%d %H:%M %Z")


def _action_email_log_id(action: AgentActionRow) -> str | None:
    result = action.execution_result_json or {}
    value = result.get("email_log_id")
    return str(value) if value is not None else None


def _lead_gen_reason_string(item: LeadGenBatchItemRow, *keys: str) -> str | None:
    reason = item.reason_json or {}
    for key in keys:
        value = reason.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lead_gen_send_plan_item(
    action: AgentActionRow,
    item: LeadGenBatchItemRow,
    batch: LeadGenBatchRow,
    contact: FirmContactRow | None,
    *,
    predicted: dict[str, Any] | None,
    email_log: EmailLogRow | None,
) -> dict[str, Any]:
    payload = action.input_json or {}
    sent_at = (
        email_log.sent_at
        if email_log and email_log.sent_at
        else action.completed_at
        if action.status == "succeeded"
        else None
    )
    channel = None
    if predicted:
        channel = predicted.get("channel")
    if not channel and email_log:
        channel = f"sent:{email_log.transport}"
    linkedin_url = (
        (contact.linkedin_url if contact else None)
        or _lead_gen_reason_string(
            item,
            "contact_linkedin_url",
            "linkedin_url",
            "linkedin",
            "contact_linkedin",
        )
    )
    action_type = payload.get("lead_gen_action_type") or _lead_gen_reason_string(item, "action_type")
    return {
        "action_id": action.id,
        "action_status": action.status,
        "batch_id": batch.id,
        "batch_name": batch.name,
        "batch_item_id": item.id,
        "contact_id": item.contact_id,
        "pif_id": item.pif_id,
        "firm_name": item.firm_name,
        "contact_name": item.contact_name,
        "contact_email": item.contact_email,
        "contact_title": item.contact_title,
        "persona": item.persona,
        "linkedin_url": linkedin_url,
        "action_type": action_type or "first_touch",
        "subject": payload.get("subject"),
        "composer_variant_key": payload.get("composer_variant_key"),
        "scheduled_for": action.scheduled_for.isoformat() if action.scheduled_for else None,
        "scheduled_for_pt": _format_pt(action.scheduled_for),
        "sent_at": sent_at.isoformat() if sent_at else None,
        "sent_at_pt": _format_pt(sent_at),
        "transport": (email_log.transport if email_log else None),
        "channel": channel,
        "message_id": email_log.message_id if email_log else None,
        "email_log_status": email_log.status if email_log else None,
    }


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
    row = await set_daily_send_budget(
        budget=req.budget,
        updated_by=req.updated_by,
        resend_daily_budget=req.resend_daily_budget,
    )
    return {
        "daily_send_budget": daily_send_budget_from_policy(row),
        "policy_version": row.version,
        "weights": row.weights_json,
    }


def _transport_settings_payload(row) -> dict:
    weights = row.weights_json or {}
    return {
        "policy_version": row.version,
        "strategy": weights.get("lead_gen_transport_strategy"),
        "provider_daily_caps": provider_daily_caps_from_policy(row),
        "daily_send_budget": daily_send_budget_from_policy(row),
        "updated_by": weights.get("lead_gen_transport_updated_by"),
        "updated_at": weights.get("lead_gen_transport_updated_at"),
    }


@router.get("/api/lead-gen/settings/transport")
async def get_transport_settings():
    row = await ensure_default_policy()
    return _transport_settings_payload(row)


@router.put("/api/lead-gen/settings/transport")
async def update_transport_settings(req: TransportSettingsRequest):
    try:
        row = await set_lead_gen_transport(
            strategy=req.strategy,
            zoho_cap=req.zoho_cap,
            resend_cap=req.resend_cap,
            updated_by=req.updated_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _transport_settings_payload(row)


@router.post("/api/lead-gen/batches")
async def create_batch(req: CreateBatchRequest):
    try:
        if req.curated:
            batch = await create_curated_batch(
                name=req.name or "Curated operator batch",
                template_key=req.template_key,
                target_metric=req.target_metric,
                created_by=req.created_by,
            )
            return {"batch": batch, "items": [], "observations": []}
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


@router.post("/api/lead-gen/founder-profile-batch")
async def create_founder_profile_batch(req: FounderProfileBatchRequest):
    variant_key = _validate_composer_variant_key(req.composer_variant_key)
    try:
        return await create_founder_profile_email_batch(
            limit=req.limit,
            template_key=req.template_key,
            created_by=req.created_by,
            composer_variant_key=variant_key or "intake-demo",
            name=req.name,
            approve_actions=req.approve_actions,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"founder_profile_batch_failed: {type(e).__name__}: {str(e)[:300]}",
        )


@router.get("/api/lead-gen/batches")
async def get_batches(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    return {"batches": await list_batches(limit=limit, status=status)}


@router.get("/api/lead-gen/experiments")
async def get_experiments(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    return await list_experiment_batches(limit=limit, status=status)


@router.get("/api/lead-gen/batches/{batch_id}/experiment-rollup")
async def get_batch_experiment_rollup(batch_id: str):
    try:
        return await experiment_rollup(batch_id)
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.put("/api/lead-gen/batches/{batch_id}/experiment")
async def put_batch_experiment(batch_id: str, req: ExperimentCardRequest):
    try:
        return await set_batch_experiment(batch_id, req.card, actor=req.actor)
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/batches/{batch_id}/experiment/close")
async def close_experiment(batch_id: str, req: ExperimentCloseRequest):
    try:
        return await close_batch_experiment(
            batch_id,
            {
                "verdict": req.verdict,
                "learning": req.learning,
                "why": req.why,
                "next_hypothesis": req.next_hypothesis,
                "next_recommended_wave": req.next_recommended_wave,
                "confidence_note": req.confidence_note,
            },
            actor=req.actor,
            superseded=req.superseded,
        )
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/daily-run")
async def run_daily_lead_gen(req: DailyRunRequest):
    variant_key = _validate_composer_variant_key(req.composer_variant_key)
    return await run_daily_pipeline(
        dry_run=req.dry_run,
        force=req.force,
        cancel_existing=req.cancel_existing,
        created_by=req.created_by,
        composer_variant_key=variant_key,
    )


@router.post("/api/lead-gen/daily-run/top-up")
async def top_up_daily_lead_gen(req: DailyRunTopUpRequest):
    variant_key = _validate_composer_variant_key(req.composer_variant_key)
    return await top_up_daily_run(
        n=req.n,
        composer_variant_key=variant_key,
        created_by="operator",
    )


@router.get("/api/lead-gen/daily-runs")
async def get_daily_runs(
    limit: int = Query(20, ge=1, le=100),
):
    return {"runs": await list_daily_runs(limit=limit)}


@router.get("/api/lead-gen/daily-run/throughput")
async def get_daily_throughput(run_date: Optional[str] = Query(None)):
    parsed_date = None
    if run_date:
        try:
            parsed_date = date.fromisoformat(run_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid_run_date") from e
    return await get_daily_run_throughput(run_date=parsed_date)


@router.get("/api/lead-gen/send-plan")
async def get_send_plan(send_date: Optional[str] = Query(None)):
    """Emails sent or scheduled to send on a selected PT date, across batches."""
    if send_date:
        try:
            target_date = date.fromisoformat(send_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid_send_date") from e
    else:
        target_date = datetime.now(timezone.utc).astimezone(PT).date()
    start_utc, end_utc = _pt_day_bounds(target_date)
    channel_plan = await daily_channel_plan(run_date=target_date)

    async with AsyncSessionLocal() as session:
        pending_rows = (await session.execute(
            select(AgentActionRow, LeadGenBatchItemRow, LeadGenBatchRow, FirmContactRow)
            .join(LeadGenBatchItemRow, AgentActionRow.entity_id == LeadGenBatchItemRow.id)
            .join(LeadGenBatchRow, LeadGenBatchRow.id == LeadGenBatchItemRow.batch_id)
            .outerjoin(FirmContactRow, FirmContactRow.id == LeadGenBatchItemRow.contact_id)
            .where(AgentActionRow.action_type == "send_email")
            .where(AgentActionRow.entity_type == "lead_gen_email")
            .where(AgentActionRow.status == "approved")
            .where(AgentActionRow.started_at.is_(None))
            .where(AgentActionRow.completed_at.is_(None))
            .where(AgentActionRow.scheduled_for >= start_utc)
            .where(AgentActionRow.scheduled_for < end_utc)
            .order_by(AgentActionRow.scheduled_for.asc(), AgentActionRow.id.asc())
        )).all()
        sent_rows = (await session.execute(
            select(AgentActionRow, LeadGenBatchItemRow, LeadGenBatchRow, FirmContactRow)
            .join(LeadGenBatchItemRow, AgentActionRow.entity_id == LeadGenBatchItemRow.id)
            .join(LeadGenBatchRow, LeadGenBatchRow.id == LeadGenBatchItemRow.batch_id)
            .outerjoin(FirmContactRow, FirmContactRow.id == LeadGenBatchItemRow.contact_id)
            .where(AgentActionRow.action_type == "send_email")
            .where(AgentActionRow.entity_type == "lead_gen_email")
            .where(AgentActionRow.status == "succeeded")
            .where(AgentActionRow.completed_at >= start_utc)
            .where(AgentActionRow.completed_at < end_utc)
            .order_by(AgentActionRow.completed_at.asc(), AgentActionRow.id.asc())
        )).all()
        email_log_ids = [
            _action_email_log_id(action)
            for action, _, _, _ in sent_rows
            if _action_email_log_id(action)
        ]
        email_logs_by_id: dict[str, EmailLogRow] = {}
        if email_log_ids:
            logs = (await session.execute(
                select(EmailLogRow).where(EmailLogRow.id.in_(email_log_ids))
            )).scalars().all()
            email_logs_by_id = {str(row.id): row for row in logs}

    items: list[dict[str, Any]] = []
    for action, item, batch, contact in sent_rows:
        predicted = channel_plan.get(item.id)
        log_id = _action_email_log_id(action)
        items.append(_lead_gen_send_plan_item(
            action,
            item,
            batch,
            contact,
            predicted=predicted,
            email_log=email_logs_by_id.get(str(log_id)) if log_id else None,
        ))
    for action, item, batch, contact in pending_rows:
        items.append(_lead_gen_send_plan_item(
            action,
            item,
            batch,
            contact,
            predicted=channel_plan.get(item.id),
            email_log=None,
        ))
    items.sort(key=lambda row: row.get("sent_at") or row.get("scheduled_for") or "")
    return {
        "date": target_date.isoformat(),
        "timezone": "America/Los_Angeles",
        "summary": {
            "sent": len(sent_rows),
            "scheduled": len(pending_rows),
            "total": len(items),
        },
        "items": items,
    }


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
        batch = await get_batch(batch_id, include_observations=include_observations)
        channel_plan = await daily_channel_plan()
        for item in batch.get("items") or []:
            predicted = channel_plan.get(item.get("id"))
            if not predicted and (item.get("reason") or {}).get("last_sent_transport"):
                predicted = {
                    "channel": f"sent:{(item.get('reason') or {}).get('last_sent_transport')}",
                    "scheduled_for": None,
                    "sent_at": (item.get("reason") or {}).get("last_sent_at"),
                    "action_id": (item.get("reason") or {}).get("send_email_action_id"),
                    "status": "succeeded",
                }
            item["predicted_transport"] = predicted
        return batch
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/lead-gen/batches/{batch_id}/add-contacts")
async def add_contacts_to_one_batch(batch_id: str, req: AddContactsToBatchRequest):
    if not req.contacts:
        raise HTTPException(status_code=400, detail="contacts_required")
    try:
        return await add_contacts_to_batch(
            batch_id=batch_id,
            contact_refs=req.contacts,
            actor=req.actor,
        )
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/batches/{batch_id}/resolve-linkedin")
async def resolve_batch_linkedin_endpoint(batch_id: str, req: ResolveBatchLinkedInRequest):
    try:
        return await resolve_linkedin_for_batch(
            batch_id,
            force=req.force,
            only_decision_makers=req.only_decision_makers,
            limit=req.limit,
        )
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/batches/{batch_id}/move-items")
async def move_items_into_batch(batch_id: str, req: MoveItemsToBatchRequest):
    if not req.source_batch_ids:
        raise HTTPException(status_code=400, detail="source_batch_ids_required")
    try:
        return await move_items_to_batch(
            target_batch_id=batch_id,
            source_batch_ids=req.source_batch_ids,
            actor=req.actor,
        )
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/batches/{batch_id}/recount")
async def recount_one_batch(batch_id: str):
    try:
        return await recount_batch(batch_id)
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


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
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.post("/api/lead-gen/batches/{batch_id}/approve-actions")
async def approve_batch_send_actions(batch_id: str, req: ApproveBatchRequest):
    """Approve the reviewed send_email actions for a batch (NOT the legacy
    sequence flow). The scheduler then sends each exact reviewed draft at its
    existing scheduled_for slot."""
    try:
        return await approve_lead_gen_batch_send_actions(
            batch_id=batch_id, approved_by=req.approved_by
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/lead-gen/batches/{batch_id}/schedule-drafts")
async def schedule_batch_drafts(batch_id: str, req: ScheduleDraftedBatchRequest):
    try:
        target_date = None
        if req.date:
            try:
                target_date = date.fromisoformat(req.date)
            except ValueError as e:
                raise HTTPException(status_code=400, detail="invalid_schedule_date") from e
        return await schedule_drafted_batch_items(
            batch_id=batch_id,
            created_by=req.actor,
            start=req.start,
            end=req.end,
            timezone_name=req.timezone,
            approve=req.approve,
            target_date=target_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"schedule_drafts_failed: {type(e).__name__}: {str(e)[:300]}",
        )


@router.post("/api/lead-gen/batches/{batch_id}/rotate-subjects")
async def rotate_batch_subjects(batch_id: str, req: RotateBatchSubjectsRequest):
    subjects = req.subjects or [
        "after-hours cases slipping away",
        "the caller who does not wait",
        "not Miss Havisham",
        "missed signed cases after hours",
        "2-minute intake demo",
    ]
    try:
        return await rotate_lead_gen_batch_subjects(
            batch_id=batch_id,
            subjects=subjects,
            actor=req.actor,
        )
    except ValueError as e:
        detail = str(e)
        if detail == "batch_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"rotate_subjects_failed: {type(e).__name__}: {str(e)[:300]}",
        )


class BackfillConsultLinksRequest(BaseModel):
    scope: str = Field(default="today", pattern="^(today|all)$")
    actor: str = "operator"
    dry_run: bool = False


class ProductInterestRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    firm: Optional[str] = Field(default=None, max_length=300)
    name: Optional[str] = Field(default=None, max_length=200)
    product: str = Field(default="outbound-voice-ai", max_length=64)
    link_code: Optional[str] = Field(default=None, max_length=64)
    source: str = Field(default="solution_page_early_access", max_length=64)


@router.post("/api/lead-gen/product-interest")
async def product_interest(req: ProductInterestRequest):
    """Early-access / design-partner signup from a product solution page. When
    a tracked solution link code (`link_code`, the /s/ `lc` param) is supplied,
    the signup is attributed to that recipient and lands as a lead-gen
    `product_interest` observation so it joins the funnel."""
    email = req.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="invalid_email")
    contact_id = batch_item_id = pif_id = None
    if req.link_code:
        from app.services.aiaudit_links import resolve_short_audit_code
        payload = await resolve_short_audit_code(req.link_code)
        if payload:
            contact_id = payload.get("contact_id")
            batch_item_id = payload.get("batch_item_id")
            pif_id = payload.get("pif_id")
    await record_observation(
        event_type="product_interest",
        raw_event={
            "email": email,
            "firm": (req.firm or "").strip() or None,
            "name": (req.name or "").strip() or None,
            "product": req.product,
            "channel": "solution",
            "source": req.source,
            "link_code": req.link_code,
            "pif_id": pif_id,
        },
        contact_id=contact_id,
        batch_item_id=batch_item_id,
    )
    return {"ok": True, "attributed": bool(contact_id)}


class PageEventRequest(BaseModel):
    event: str = Field(default="session_ready", max_length=32)
    page: str = Field(default="", max_length=64)
    link_code: Optional[str] = Field(default=None, max_length=64)
    click_id: Optional[str] = Field(default=None, max_length=96)
    source: Optional[str] = Field(default=None, max_length=64)
    firm_name: Optional[str] = Field(default=None, max_length=300)
    pif_id: Optional[str] = Field(default=None, max_length=64)
    contact_id: Optional[str] = Field(default=None, max_length=64)
    contact_name: Optional[str] = Field(default=None, max_length=200)
    contact_email: Optional[str] = Field(default=None, max_length=320)
    utm_source: Optional[str] = Field(default=None, max_length=128)
    utm_medium: Optional[str] = Field(default=None, max_length=128)
    utm_campaign: Optional[str] = Field(default=None, max_length=256)
    utm_term: Optional[str] = Field(default=None, max_length=256)
    utm_content: Optional[str] = Field(default=None, max_length=512)
    engagement_type: Optional[str] = Field(default=None, max_length=64)
    click_text: Optional[str] = Field(default=None, max_length=240)
    click_href: Optional[str] = Field(default=None, max_length=2048)
    click_tag: Optional[str] = Field(default=None, max_length=64)
    click_id_attr: Optional[str] = Field(default=None, max_length=128)
    url: Optional[str] = Field(default=None, max_length=2048)
    referrer: Optional[str] = Field(default=None, max_length=1024)
    session_id: Optional[str] = Field(default=None, max_length=64)
    time_on_page_ms: Optional[int] = Field(default=None, ge=0, le=86_400_000)
    ip_address: Optional[str] = Field(default=None, max_length=128)
    country_code: Optional[str] = Field(default=None, max_length=8)
    country_name: Optional[str] = Field(default=None, max_length=128)
    region: Optional[str] = Field(default=None, max_length=128)
    city: Optional[str] = Field(default=None, max_length=128)
    user_agent: Optional[str] = Field(default=None, max_length=512)


def _first_clean_header(request: Request, names: list[str]) -> str | None:
    for name in names:
        value = (request.headers.get(name) or "").strip()
        if value:
            return value
    return None


def _first_forwarded_ip(value: str | None) -> str | None:
    if not value:
        return None
    for candidate in value.split(","):
        clean = candidate.strip()
        if clean:
            return clean
    return None


def _request_ip(request: Request, body_ip: str | None = None) -> str | None:
    candidate = (
        body_ip
        or _first_forwarded_ip(request.headers.get("x-forwarded-for"))
        or (request.headers.get("x-real-ip") or "").strip()
        or (request.client.host if request.client else None)
    )
    if not candidate:
        return None
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return candidate[:128]
    return str(parsed)


def _country_code(request: Request, body_country: str | None = None) -> str | None:
    value = (
        body_country
        or _first_clean_header(request, [
            "x-vercel-ip-country",
            "cf-ipcountry",
            "cloudfront-viewer-country",
            "x-country-code",
        ])
    )
    if not value:
        return None
    code = value.strip().upper()
    if code in {"XX", "T1"}:
        return None
    return code[:8]


def _country_name(country_code: str | None, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit[:128]
    if not country_code:
        return None
    return COUNTRY_NAMES.get(country_code, country_code)


def _masked_ip(ip_address: str | None) -> str | None:
    if not ip_address:
        return None
    try:
        parsed = ipaddress.ip_address(ip_address)
    except ValueError:
        return ip_address[:32]
    if parsed.version == 4:
        parts = str(parsed).split(".")
        return ".".join([*parts[:3], "x"])
    hextets = parsed.exploded.split(":")
    return ":".join([*hextets[:4], "xxxx", "xxxx", "xxxx", "xxxx"])


def _geo_value(value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    try:
        return unquote(clean)
    except Exception:
        return clean


@router.post("/api/lead-gen/page-event")
async def page_event(req: PageEventRequest, request: Request):
    """Bot-resistant human-session beacon from a tracked landing page (consult,
    solution, ...). A `session_ready` event only fires when a real browser runs
    JS, which email-security scanners do not, so this is the human-confirmation
    signal the redirect click cannot give. Attributed to a contact via the `/s/`
    or `/c/` link code (`lc`). Recorded as a `page_session` lead-gen observation.
    Public (auth-exempt), like the early-access form."""
    def clean(value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None

    contact_id = batch_item_id = None
    pif_id = clean(req.pif_id)
    if req.link_code:
        from app.services.aiaudit_links import resolve_short_audit_code
        resolved = await resolve_short_audit_code(req.link_code)
        if resolved:
            contact_id = resolved.get("contact_id")
            batch_item_id = resolved.get("batch_item_id")
            pif_id = resolved.get("pif_id")
    source = clean(req.source) or clean(req.utm_source)
    ip_address = _request_ip(request, clean(req.ip_address))
    country_code = _country_code(request, clean(req.country_code))
    country_name = _country_name(country_code, clean(req.country_name))
    region = _geo_value(clean(req.region) or _first_clean_header(request, ["x-vercel-ip-country-region", "x-region"]))
    city = _geo_value(clean(req.city) or _first_clean_header(request, ["x-vercel-ip-city", "x-city"]))
    user_agent = clean(req.user_agent) or clean(request.headers.get("user-agent"))
    await record_observation(
        event_type="page_session",
        raw_event={
            "event": clean(req.event) or "session_ready",
            "page": clean(req.page),
            "session_id": clean(req.session_id),
            "time_on_page_ms": req.time_on_page_ms,
            "channel": "page_beacon",
            "link_code": clean(req.link_code),
            "click_id": clean(req.click_id),
            "source": source,
            "firm_name": clean(req.firm_name),
            "contact_id": clean(req.contact_id),
            "contact_name": clean(req.contact_name),
            "contact_email": clean(req.contact_email),
            "utm_source": clean(req.utm_source),
            "utm_medium": clean(req.utm_medium),
            "utm_campaign": clean(req.utm_campaign),
            "utm_term": clean(req.utm_term),
            "utm_content": clean(req.utm_content),
            "engagement_type": clean(req.engagement_type),
            "click_text": clean(req.click_text),
            "click_href": clean(req.click_href),
            "click_tag": clean(req.click_tag),
            "click_id_attr": clean(req.click_id_attr),
            "url": clean(req.url),
            "referrer": clean(req.referrer),
            "pif_id": pif_id,
            "ip_address": ip_address,
            "ip_address_display": _masked_ip(ip_address),
            "country_code": country_code,
            "country_name": country_name,
            "region": region,
            "city": city,
            "user_agent": user_agent,
        },
        contact_id=contact_id,
        batch_item_id=batch_item_id,
    )
    return {"ok": True, "attributed": bool(contact_id)}


def _page_event_time_ms(raw_event: dict[str, Any] | None) -> int | None:
    if not raw_event:
        return None
    value = raw_event.get("time_on_page_ms")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _normalized_country_filter(value: str | None) -> str:
    country = (value or "all").strip().upper()
    if country in {"ALL", ""}:
        return "all"
    if country in {"IN", "INDIA"}:
        return "IN"
    if country in {"US", "USA", "UNITED_STATES", "UNITED STATES"}:
        return "US"
    if country in {"UNKNOWN", "UNSET", "NONE"}:
        return "unknown"
    if country == "OTHER":
        return "other"
    return country[:8]


def _page_event_conditions(since_days: int, country: str):
    page_value = func.coalesce(
        LeadGenObservationRow.raw_event_json["page"].astext,
        "unknown",
    )
    country_value = func.upper(func.coalesce(
        LeadGenObservationRow.raw_event_json["country_code"].astext,
        "",
    ))
    conditions = [
        LeadGenObservationRow.event_type == "page_session",
        page_value.notlike("admin%"),
    ]
    if since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        conditions.append(LeadGenObservationRow.created_at >= cutoff)
    if country == "unknown":
        conditions.append(country_value == "")
    elif country == "other":
        conditions.append(country_value.notin_(["", "US", "IN"]))
    elif country != "all":
        conditions.append(country_value == country)
    return conditions


@router.get("/api/lead-gen/engagement-analytics")
async def engagement_analytics(
    since_days: int = Query(30, ge=0, le=3650),
    limit: int = Query(100, ge=1, le=500),
    country: str = Query("all", max_length=32),
):
    """Detailed human-session analytics for the Possible Minds website.

    Page events come from the marketing-site ClickBeacon and are attributed via
    the persisted `lc` code from tracked outreach/intake links.
    """
    country_filter = _normalized_country_filter(country)
    conditions = _page_event_conditions(since_days, country_filter)
    stmt = (
        select(LeadGenObservationRow, FirmContactRow, LeadGenBatchItemRow)
        .outerjoin(FirmContactRow, FirmContactRow.id == LeadGenObservationRow.contact_id)
        .outerjoin(LeadGenBatchItemRow, LeadGenBatchItemRow.id == LeadGenObservationRow.batch_item_id)
        .where(*conditions)
        .order_by(desc(LeadGenObservationRow.created_at))
        .limit(limit * 10)
    )

    page_expr = func.coalesce(
        LeadGenObservationRow.raw_event_json["page"].astext,
        "unknown",
    ).label("page")
    country_expr = func.coalesce(
        func.nullif(func.upper(func.coalesce(
            LeadGenObservationRow.raw_event_json["country_code"].astext,
            "",
        )), ""),
        "unknown",
    ).label("country_code")
    by_page_stmt = (
        select(
            page_expr,
            func.count(LeadGenObservationRow.id).label("events"),
            func.count(func.distinct(LeadGenObservationRow.raw_event_json["session_id"].astext)).label("sessions"),
        )
        .where(*conditions)
        .group_by(page_expr)
        .order_by(desc("events"))
        .limit(limit)
    )
    by_country_stmt = (
        select(
            country_expr,
            func.count(LeadGenObservationRow.id).label("events"),
            func.count(func.distinct(LeadGenObservationRow.raw_event_json["session_id"].astext)).label("sessions"),
        )
        .where(*_page_event_conditions(since_days, "all"))
        .group_by(country_expr)
        .order_by(desc("events"))
    )

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).all()
        by_page_rows = (await session.execute(by_page_stmt)).all()
        by_country_rows = (await session.execute(by_country_stmt)).all()

    journeys: dict[str, dict[str, Any]] = {}
    total_events = 0
    total_time_ms = 0
    contacts: set[str] = set()
    firms: set[str] = set()

    for obs, contact, item in rows:
        raw_event = obs.raw_event_json or {}
        session_id = str(raw_event.get("session_id") or obs.id)
        page = str(raw_event.get("page") or "unknown")
        time_ms = _page_event_time_ms(raw_event)
        region = _geo_value(raw_event.get("region"))
        city = _geo_value(raw_event.get("city"))
        total_events += 1
        if time_ms:
            total_time_ms += time_ms
        if obs.contact_id:
            contacts.add(obs.contact_id)
        if obs.pif_id:
            firms.add(obs.pif_id)

        firm_name = (
            (item.firm_name if item else None)
            or str(raw_event.get("firm_name") or "")
            or "Unknown firm"
        )
        contact_name = (
            (contact.full_name if contact else None)
            or (item.contact_name if item else None)
            or str(raw_event.get("contact_name") or "")
            or ""
        )
        contact_email = (
            (contact.email if contact else None)
            or (item.contact_email if item else None)
            or str(raw_event.get("contact_email") or "")
            or ""
        )

        journey = journeys.setdefault(session_id, {
            "session_id": session_id,
            "contact_id": obs.contact_id,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "firm_name": firm_name,
            "pif_id": obs.pif_id or raw_event.get("pif_id"),
            "link_code": raw_event.get("link_code"),
            "click_id": raw_event.get("click_id"),
            "source": raw_event.get("source") or raw_event.get("utm_source"),
            "ip_address_display": raw_event.get("ip_address_display") or _masked_ip(raw_event.get("ip_address")),
            "country_code": raw_event.get("country_code"),
            "country_name": raw_event.get("country_name"),
            "region": region,
            "city": city,
            "first_seen_at": obs.created_at.isoformat() if obs.created_at else None,
            "last_seen_at": obs.created_at.isoformat() if obs.created_at else None,
            "total_time_on_page_ms": 0,
            "pages": [],
        })
        for key in ("ip_address_display", "country_code", "country_name"):
            if not journey.get(key) and raw_event.get(key):
                journey[key] = raw_event.get(key)
        if not journey.get("region") and region:
            journey["region"] = region
        if not journey.get("city") and city:
            journey["city"] = city

        if obs.created_at:
            iso = obs.created_at.isoformat()
            journey["first_seen_at"] = min(journey["first_seen_at"] or iso, iso)
            journey["last_seen_at"] = max(journey["last_seen_at"] or iso, iso)
        if time_ms:
            journey["total_time_on_page_ms"] += time_ms
        journey["pages"].append({
            "page": page,
            "event": raw_event.get("event"),
            "url": raw_event.get("url"),
            "referrer": raw_event.get("referrer"),
            "engagement_type": raw_event.get("engagement_type"),
            "click_text": raw_event.get("click_text"),
            "click_href": raw_event.get("click_href"),
            "click_tag": raw_event.get("click_tag"),
            "utm_campaign": raw_event.get("utm_campaign"),
            "ip_address_display": raw_event.get("ip_address_display") or _masked_ip(raw_event.get("ip_address")),
            "country_code": raw_event.get("country_code"),
            "country_name": raw_event.get("country_name"),
            "region": region,
            "city": city,
            "time_on_page_ms": time_ms,
            "created_at": obs.created_at.isoformat() if obs.created_at else None,
        })

    session_rows = sorted(
        journeys.values(),
        key=lambda row: row.get("last_seen_at") or "",
        reverse=True,
    )[:limit]
    for journey in session_rows:
        journey["pages"] = sorted(
            journey["pages"],
            key=lambda row: row.get("created_at") or "",
        )

    return {
        "since_days": since_days,
        "country": country_filter,
        "summary": {
            "event_count": total_events,
            "distinct_sessions": len(journeys),
            "distinct_contacts": len(contacts),
            "distinct_firms": len(firms),
            "total_time_on_page_ms": total_time_ms,
        },
        "pages": [
            {
                "page": row.page,
                "events": int(row.events or 0),
                "sessions": int(row.sessions or 0),
            }
            for row in by_page_rows
        ],
        "countries": [
            {
                "country_code": row.country_code,
                "country_name": COUNTRY_NAMES.get(row.country_code, "Unknown" if row.country_code == "unknown" else row.country_code),
                "events": int(row.events or 0),
                "sessions": int(row.sessions or 0),
            }
            for row in by_country_rows
        ],
        "sessions": session_rows,
    }


@router.post("/api/lead-gen/backfill-consult-links")
async def backfill_consult_links(req: BackfillConsultLinksRequest):
    """Swap the bare consult URL for a per-recipient tracked /c/{code} link in
    unsent lead-gen sends, re-approving each at its existing slot. scope=today
    targets the live daily batch; scope=all covers every unsent lead-gen send."""
    from app.services.action_execution import backfill_consult_short_links
    return await backfill_consult_short_links(
        scope=req.scope, actor=req.actor, dry_run=req.dry_run
    )


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


@router.post("/api/lead-gen/batch-items/{batch_item_id}/recompose-draft")
async def recompose_batch_item_draft(batch_item_id: str, req: RecomposeBatchItemDraftRequest):
    try:
        return await recompose_item_draft(
            batch_item_id=batch_item_id,
            actor=req.actor,
            composer_variant_key=req.composer_variant_key,
        )
    except ValueError as e:
        detail = str(e)
        if detail in {"batch_item_not_found", "contact_not_found"}:
            raise HTTPException(status_code=404, detail=detail)
        if detail == "email_already_sent" or detail.startswith("action_cannot_be_recomposed"):
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"recompose_draft_failed: {type(e).__name__}: {str(e)[:300]}",
        )


@router.post("/api/lead-gen/batch-items/{batch_item_id}/compose-variants")
async def compose_batch_item_variants(batch_item_id: str):
    """Compose this item's email with every active composer variant (on-demand)
    so the preview can show all options. Persists reason_json.variant_drafts."""
    from app.services.lead_gen_email_agent import compose_item_all_variants

    try:
        return await compose_item_all_variants(batch_item_id)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not_found" in str(e) else 400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"compose_variants_failed: {type(e).__name__}: {str(e)[:300]}")


class SelectVariantRequest(BaseModel):
    variant_key: str
    actor: str = "operator"


@router.post("/api/lead-gen/batch-items/{batch_item_id}/select-variant")
async def select_batch_item_variant(batch_item_id: str, req: SelectVariantRequest):
    """Promote a composed variant to the item's active draft + send action."""
    from app.services.lead_gen_email_agent import select_item_variant

    try:
        return await select_item_variant(batch_item_id, req.variant_key, actor=req.actor)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not_found" in str(e) else 400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"select_variant_failed: {type(e).__name__}: {str(e)[:300]}")


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
