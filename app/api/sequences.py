"""Email sequence dashboard endpoints.

Backs the /sequences UI page and the `autocaller sequences` /
`autocaller contacts` CLI groups.

Strict v1 invariant — surfaces of action are limited to:
  - list firms with contacts
  - list contacts for one firm
  - preview the rendered emails for one contact
  - start the sequence for one contact (idempotent — second click 409s)

No pause/resume/restart/multi-contact-fanout in v1.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import EmailSequenceRow, FirmContactRow, EmailLogRow, OperatorNotificationRow
from app.services.firm_contacts_service import (
    backfill_all,
    fetch_pain_quote_for_firm,
    get_contact,
    list_contacts_for_firm,
    list_firms_with_contacts,
)
from app.services.lead_email_composer import LeadEmailComposerError, compose_lead_email
from app.services.linkedin_resolver import resolve_linkedin_for_contact
from app.services.sequences.registry import (
    DEFAULT_TEMPLATE_KEY,
    list_templates,
    normalize_template_key,
    steps_total,
    variant_for,
)
from app.services.sequences.possible_minds_dynamic import objective_for
from app.services.sequence_recommendations import recommend_sequence_contacts
from app.services.sequence_scheduler import (
    get_sequence,
    start_sequence,
)


router = APIRouter(tags=["sequences"])


class FirmListItem(BaseModel):
    pif_id: str
    firm_name: str
    contact_count: int
    has_pain_quote: bool
    extracted_at: Optional[str] = None


class ContactListItem(BaseModel):
    id: str
    pif_id: str
    full_name: str
    first_name: str
    email: Optional[str]
    phone: Optional[str]
    title: Optional[str]
    source: str


class ResolveLinkedInRequest(BaseModel):
    force: bool = False


class RenderedStepDTO(BaseModel):
    step: int
    subject: str
    body: str
    message_type: str
    reasoning: Optional[str] = None
    angle: Optional[str] = None
    cta: Optional[str] = None
    blog_link_used: Optional[str] = None
    model: Optional[str] = None
    composer_experiment_key: Optional[str] = None
    composer_variant_key: Optional[str] = None
    skill_path: Optional[str] = None
    skill_sha256: Optional[str] = None
    brief_version: Optional[int] = None
    requires_human_review: bool = False
    risk_flags: list[str] = Field(default_factory=list)


class SequenceTemplateDTO(BaseModel):
    template_key: str
    label: str
    description: str
    steps_total: int
    default_variant: str


class SequenceStateDTO(BaseModel):
    id: str
    contact_id: str
    template_key: str
    status: str
    current_step: int
    steps_total: int
    variant: str
    last_sent_at: Optional[str]
    next_step_due_at: Optional[str]
    paused_reason: Optional[str]
    pain_point_key: Optional[str]
    frozen_pain_quote: Optional[str]
    frozen_reviewer_name: Optional[str]
    frozen_review_date: Optional[str]


class ContactDetailDTO(BaseModel):
    contact: ContactListItem
    pain: dict
    sequence: Optional[SequenceStateDTO]
    sent_steps: list[dict]


class SequenceRecommendationDTO(BaseModel):
    contact_id: str
    pif_id: str
    firm_name: str
    contact_name: str
    contact_email: str
    contact_title: str
    contact_source: str
    persona: str
    score: int
    reason: str


class SequenceRecommendationResponse(BaseModel):
    template_key: str
    limit: int
    recommended: list[SequenceRecommendationDTO]
    counts: dict


# ---------------------------------------------------------------------------

@router.get("/api/sequences/templates", response_model=list[SequenceTemplateDTO])
async def get_sequence_templates():
    return [SequenceTemplateDTO(**t.__dict__) for t in list_templates()]


@router.get(
    "/api/sequences/recommendations",
    response_model=SequenceRecommendationResponse,
)
async def get_sequence_recommendations(
    template_key: str = Query(DEFAULT_TEMPLATE_KEY),
    limit: int = Query(50, ge=1, le=200),
):
    try:
        data = await recommend_sequence_contacts(
            template_key=template_key,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SequenceRecommendationResponse(**data)

@router.get("/api/firms/with-contacts", response_model=list[FirmListItem])
async def get_firms_with_contacts():
    return await list_firms_with_contacts()


@router.get(
    "/api/firms/{pif_id}/contacts",
    response_model=list[ContactListItem],
)
async def get_contacts_for_firm(pif_id: str):
    return await list_contacts_for_firm(pif_id)


@router.get("/api/contacts/{contact_id}", response_model=ContactDetailDTO)
async def get_contact_detail(
    contact_id: str,
    template_key: str = Query(DEFAULT_TEMPLATE_KEY),
):
    try:
        template_key = normalize_template_key(template_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    contact = await get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="contact_not_found")

    pain = await fetch_pain_quote_for_firm(contact["pif_id"])
    seq = await get_sequence(contact_id, template_key)
    sequence_dto = None
    sent_steps: list[dict] = []
    if seq:
        sequence_dto = SequenceStateDTO(
            id=seq.id,
            contact_id=seq.contact_id,
            template_key=seq.template_key,
            status=seq.status,
            current_step=seq.current_step,
            steps_total=seq.steps_total,
            variant=seq.variant,
            last_sent_at=seq.last_sent_at.isoformat() if seq.last_sent_at else None,
            next_step_due_at=(
                seq.next_step_due_at.isoformat() if seq.next_step_due_at else None
            ),
            paused_reason=seq.paused_reason,
            pain_point_key=seq.pain_point_key,
            frozen_pain_quote=seq.frozen_pain_quote,
            frozen_reviewer_name=seq.frozen_reviewer_name,
            frozen_review_date=seq.frozen_review_date,
        )
        # Pull the email_logs rows for this sequence's sends. We tag every
        # send with `message_type='sequence_step_N'` so a recipient+message_type
        # filter is enough to recover the history.
        if contact.get("email"):
            async with AsyncSessionLocal() as session:
                rows = (await session.execute(
                    select(EmailLogRow).where(
                        EmailLogRow.recipient_email == contact["email"].lower(),
                        EmailLogRow.message_type.in_([
                            "dynamic_lead_email",
                            "lead_reply_draft",
                        ]),
                    ).order_by(EmailLogRow.sent_at.asc())
                )).scalars().all()
            for r in rows:
                sent_steps.append({
                    "id": r.id,
                    "message_type": r.message_type,
                    "subject": r.subject,
                    "status": r.status,
                    "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                })

    return ContactDetailDTO(
        contact=ContactListItem(**contact),
        pain=pain,
        sequence=sequence_dto,
        sent_steps=sent_steps,
    )


@router.post("/api/contacts/{contact_id}/resolve-linkedin")
async def resolve_contact_linkedin_endpoint(contact_id: str, req: ResolveLinkedInRequest):
    try:
        return await resolve_linkedin_for_contact(contact_id, force=req.force)
    except ValueError as e:
        detail = str(e)
        if detail == "contact_not_found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)


@router.get(
    "/api/contacts/{contact_id}/sequence/preview",
    response_model=list[RenderedStepDTO],
)
async def preview_sequence(
    contact_id: str,
    template_key: str = Query(DEFAULT_TEMPLATE_KEY),
    notification_id: int | None = Query(None),
    source_id: str | None = Query(None),
    composer_variant_key: str | None = Query(None),
):
    """Render every step of the sequence as it would land for this
    contact's data. No DB write, no send."""
    try:
        template_key = normalize_template_key(template_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    contact = await get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="contact_not_found")

    pain = await fetch_pain_quote_for_firm(contact["pif_id"])
    variant = variant_for(template_key, pain_quote=pain.get("pain_quote"))
    n = steps_total(template_key, variant)

    # Firm name lookup — resolves across pif-/mc- keying.
    from app.services.firm_contacts_service import resolve_firm_name
    firm_name = await resolve_firm_name(contact['pif_id'])

    out = []
    async with AsyncSessionLocal() as session:
        contact_row = await session.get(FirmContactRow, contact_id)
    if not contact_row:
        raise HTTPException(status_code=404, detail="contact_not_found")
    existing = await get_sequence(contact_id, template_key)
    if existing and existing.current_step >= existing.steps_total:
        return []
    next_step = existing.current_step + 1 if existing else 1
    sequence_context = existing or SimpleNamespace(
        template_key=template_key,
        current_step=0,
        steps_total=n,
        variant=variant,
    )
    async with AsyncSessionLocal() as session:
        notification_filters = [
            OperatorNotificationRow.notification_type == "lead_sequence_email_approval",
            OperatorNotificationRow.source_type == "email_sequence_step",
            OperatorNotificationRow.status == "pending",
            OperatorNotificationRow.acknowledged_at.is_(None),
        ]
        if notification_id:
            notification_filters.append(OperatorNotificationRow.id == notification_id)
        elif source_id:
            notification_filters.append(OperatorNotificationRow.source_id == source_id)
        elif existing:
            notification_filters.append(
                OperatorNotificationRow.source_id == f"{existing.id}:{next_step}"
            )
        else:
            notification_filters = []

        stored_notification = None
        if notification_filters:
            stored_notification = (await session.execute(
                select(OperatorNotificationRow).where(
                    *notification_filters,
                ).order_by(OperatorNotificationRow.created_at.desc())
            )).scalars().first()
    if stored_notification:
        suggested = stored_notification.suggested_action_json or {}
        notification_context = stored_notification.context_json or {}
        context_contact_id = str(notification_context.get("contact_id") or "").strip()
        context_template_key = str(notification_context.get("template_key") or "").strip()
        if (
            (context_contact_id and context_contact_id != contact_id)
            or (context_template_key and context_template_key != DEFAULT_TEMPLATE_KEY)
        ):
            stored_notification = None
        else:
            draft_subject = str(suggested.get("draft_subject") or "").strip()
            draft_body = str(suggested.get("draft_body") or "").strip()
            if draft_subject and draft_body:
                out.append(RenderedStepDTO(
                    step=next_step,
                    subject=draft_subject,
                    body=draft_body,
                    message_type=str(suggested.get("message_type") or "dynamic_lead_email"),
                    reasoning=suggested.get("reasoning"),
                    angle=suggested.get("angle"),
                    cta=suggested.get("cta"),
                    blog_link_used=suggested.get("blog_link_used"),
                    model=suggested.get("composer_model"),
                    composer_experiment_key=suggested.get("composer_experiment_key"),
                    composer_variant_key=suggested.get("composer_variant_key"),
                    skill_path=suggested.get("skill_path"),
                    skill_sha256=suggested.get("skill_sha256"),
                    brief_version=suggested.get("brief_version"),
                    requires_human_review=bool(suggested.get("requires_human_review", True)),
                    risk_flags=suggested.get("risk_flags") or [],
                ))
                return out
    try:
        composed = await compose_lead_email(
            contact=contact_row,
            firm_name=firm_name,
            sequence=sequence_context,
            step_num=next_step,
            composer_variant_key=composer_variant_key,
        )
    except LeadEmailComposerError as e:
        raise HTTPException(status_code=502, detail=f"compose_failed: {str(e)}")
    out.append(RenderedStepDTO(
        step=next_step,
        subject=composed.subject,
        body=composed.body,
        message_type="dynamic_lead_email",
        reasoning=composed.reasoning,
        angle=composed.angle,
        cta=composed.cta,
        blog_link_used=composed.blog_link_used,
        model=composed.model,
        composer_experiment_key=composed.composer_experiment_key,
        composer_variant_key=composed.composer_variant_key,
        skill_path=composed.skill_path,
        skill_sha256=composed.skill_sha256,
        brief_version=composed.brief_version,
        requires_human_review=composed.requires_human_review,
        risk_flags=composed.risk_flags,
    ))
    return out


class StartSequenceResponse(BaseModel):
    sequence_id: str
    template_key: str
    variant: str
    steps_total: int
    next_step_due_at: Optional[str]


class StartSequenceRequest(BaseModel):
    template_key: str = DEFAULT_TEMPLATE_KEY


@router.post(
    "/api/contacts/{contact_id}/sequence/start",
    response_model=StartSequenceResponse,
)
async def start_sequence_endpoint(
    contact_id: str,
    body: Optional[StartSequenceRequest] = Body(default=None),
):
    try:
        template_key = normalize_template_key(
            body.template_key if body else DEFAULT_TEMPLATE_KEY
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    contact = await get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="contact_not_found")
    if not contact.get("email"):
        raise HTTPException(
            status_code=400,
            detail="contact_has_no_email — cannot start a sequence",
        )

    pain = await fetch_pain_quote_for_firm(contact["pif_id"])
    try:
        seq = await start_sequence(
            contact_id=contact_id,
            template_key=template_key,
            pain_quote=pain.get("pain_quote"),
            reviewer_name=pain.get("reviewer_name"),
            review_date=pain.get("review_date"),
            pain_point_key=pain.get("pain_point_key"),
        )
    except ValueError as e:
        # Existing sequence — return 409 with state so the UI can show
        # what's already running.
        raise HTTPException(status_code=409, detail=str(e))
    return StartSequenceResponse(
        sequence_id=seq.id,
        template_key=seq.template_key,
        variant=seq.variant,
        steps_total=seq.steps_total,
        next_step_due_at=seq.next_step_due_at.isoformat() if seq.next_step_due_at else None,
    )


class SequenceListItem(BaseModel):
    sequence_id: str
    contact_id: str
    contact_name: str
    contact_email: Optional[str]
    pif_id: str
    firm_name: Optional[str]
    template_key: str
    status: str
    current_step: int
    steps_total: int
    variant: str
    last_sent_at: Optional[str]
    next_step_due_at: Optional[str]
    paused_reason: Optional[str]


@router.get("/api/sequences", response_model=list[SequenceListItem])
async def list_sequences(
    status: Optional[str] = Query(
        None, description="active | paused | completed (omit for all)",
    ),
    limit: int = Query(200, ge=1, le=1000),
):
    """All sequences across all contacts. Used by the global 'active
    sequences' panel on the dashboard."""
    from app.db.models import PatientRow
    async with AsyncSessionLocal() as session:
        q = (
            select(EmailSequenceRow, FirmContactRow)
            .join(
                FirmContactRow,
                EmailSequenceRow.contact_id == FirmContactRow.id,
            )
            .order_by(EmailSequenceRow.updated_at.desc())
            .limit(limit)
        )
        if status:
            q = q.where(EmailSequenceRow.status == status.strip().lower())
        rows = list((await session.execute(q)).all())
        if not rows:
            return []

        # One round-trip for firm names — covers both keying conventions.
        pif_ids = list({c.pif_id for _, c in rows})
        all_keys = [f"pif-{p}" for p in pif_ids] + [f"mc-{p}" for p in pif_ids]
        rows_n = (await session.execute(
            select(PatientRow.patient_id, PatientRow.firm_name).where(
                PatientRow.patient_id.in_(all_keys)
            )
        )).all()
        # Prefer pif- name when both exist.
        firm_map: dict[str, str] = {}
        for pid, fname in rows_n:
            if not pid or not fname:
                continue
            raw = pid[4:] if pid.startswith("pif-") else (pid[3:] if pid.startswith("mc-") else pid)
            if raw not in firm_map or pid.startswith("pif-"):
                firm_map[raw] = fname

    out = []
    for seq, c in rows:
        out.append(SequenceListItem(
            sequence_id=seq.id,
            contact_id=c.id,
            contact_name=c.full_name,
            contact_email=c.email,
            pif_id=c.pif_id,
            firm_name=firm_map.get(c.pif_id),
            template_key=seq.template_key,
            status=seq.status,
            current_step=seq.current_step,
            steps_total=seq.steps_total,
            variant=seq.variant,
            last_sent_at=seq.last_sent_at.isoformat() if seq.last_sent_at else None,
            next_step_due_at=(
                seq.next_step_due_at.isoformat() if seq.next_step_due_at else None
            ),
            paused_reason=seq.paused_reason,
        ))
    return out


class PauseRequest(BaseModel):
    reason: Optional[str] = None


class PauseResumeResponse(BaseModel):
    sequence_id: str
    status: str
    paused_reason: Optional[str]
    next_step_due_at: Optional[str]


@router.post(
    "/api/contacts/{contact_id}/sequence/pause",
    response_model=PauseResumeResponse,
)
async def pause_sequence(
    contact_id: str,
    body: PauseRequest,
    template_key: str = Query(DEFAULT_TEMPLATE_KEY),
):
    """Mark a sequence paused. Scheduler skips paused rows; no further
    sends fire. Idempotent — pausing an already-paused row updates
    paused_reason."""
    try:
        template_key = normalize_template_key(template_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as session:
        seq = (await session.execute(
            select(EmailSequenceRow).where(
                EmailSequenceRow.contact_id == contact_id,
                EmailSequenceRow.template_key == template_key,
            )
        )).scalar_one_or_none()
        if not seq:
            raise HTTPException(status_code=404, detail="sequence_not_found")
        if seq.status == "completed":
            raise HTTPException(
                status_code=409,
                detail="sequence already completed — nothing to pause",
            )
        seq.status = "paused"
        seq.paused_reason = (body.reason or "").strip() or "operator: no reason given"
        seq.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(seq)
    return PauseResumeResponse(
        sequence_id=seq.id,
        status=seq.status,
        paused_reason=seq.paused_reason,
        next_step_due_at=seq.next_step_due_at.isoformat() if seq.next_step_due_at else None,
    )


@router.post(
    "/api/contacts/{contact_id}/sequence/resume",
    response_model=PauseResumeResponse,
)
async def resume_sequence(
    contact_id: str,
    template_key: str = Query(DEFAULT_TEMPLATE_KEY),
):
    """Flip a paused sequence back to active. The next due send fires
    on the scheduler's next tick (≤60s). If `next_step_due_at` was in
    the past while paused, step N goes out immediately."""
    try:
        template_key = normalize_template_key(template_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as session:
        seq = (await session.execute(
            select(EmailSequenceRow).where(
                EmailSequenceRow.contact_id == contact_id,
                EmailSequenceRow.template_key == template_key,
            )
        )).scalar_one_or_none()
        if not seq:
            raise HTTPException(status_code=404, detail="sequence_not_found")
        if seq.status == "completed":
            raise HTTPException(
                status_code=409,
                detail="sequence already completed — cannot resume",
            )
        if seq.status == "active":
            # idempotent — no-op
            return PauseResumeResponse(
                sequence_id=seq.id,
                status=seq.status,
                paused_reason=seq.paused_reason,
                next_step_due_at=(
                    seq.next_step_due_at.isoformat() if seq.next_step_due_at else None
                ),
            )
        seq.status = "active"
        seq.paused_reason = None
        seq.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(seq)
    return PauseResumeResponse(
        sequence_id=seq.id,
        status=seq.status,
        paused_reason=seq.paused_reason,
        next_step_due_at=seq.next_step_due_at.isoformat() if seq.next_step_due_at else None,
    )


class BackfillResponse(BaseModel):
    firms: int
    inserted: int
    updated: int
    skipped: int
    errors: int


@router.post("/api/firm-contacts/backfill", response_model=BackfillResponse)
async def backfill_endpoint(limit: Optional[int] = Query(None, ge=1, le=2000)):
    return BackfillResponse(**(await backfill_all(limit=limit)))


class DeleteContactResponse(BaseModel):
    deleted: bool
    contact_id: str
    sequences_deleted: int


@router.delete("/api/contacts/{contact_id}", response_model=DeleteContactResponse)
async def delete_contact_endpoint(contact_id: str):
    """Hard-delete a contact. The `email_sequences.contact_id` FK has
    ON DELETE CASCADE so the row's sequences go with it. Outbound
    email/sms/call logs key on pif_id and are preserved as history."""
    async with AsyncSessionLocal() as session:
        contact = await session.get(FirmContactRow, contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="contact_not_found")
        seq_count = (await session.execute(
            select(EmailSequenceRow).where(EmailSequenceRow.contact_id == contact_id)
        )).scalars().all()
        n_sequences = len(seq_count)
        await session.delete(contact)
        await session.commit()
    return DeleteContactResponse(
        deleted=True, contact_id=contact_id, sequences_deleted=n_sequences,
    )
