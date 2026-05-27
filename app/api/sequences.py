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

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import EmailSequenceRow, FirmContactRow, EmailLogRow
from app.services.firm_contacts_service import (
    backfill_all,
    fetch_pain_quote_for_firm,
    get_contact,
    list_contacts_for_firm,
    list_firms_with_contacts,
)
from app.services.sequences.common import Ctx
from app.services.sequences.registry import (
    DEFAULT_TEMPLATE_KEY,
    list_templates,
    normalize_template_key,
    render_step,
    steps_total,
    variant_for,
)
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


class RenderedStepDTO(BaseModel):
    step: int
    subject: str
    body: str
    message_type: str


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
                pattern = (
                    "records_audit_step_%"
                    if template_key == "precise_records_audit"
                    else "sequence_step_%"
                )
                rows = (await session.execute(
                    select(EmailLogRow).where(
                        EmailLogRow.recipient_email == contact["email"].lower(),
                        EmailLogRow.message_type.like(pattern),
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


@router.get(
    "/api/contacts/{contact_id}/sequence/preview",
    response_model=list[RenderedStepDTO],
)
async def preview_sequence(
    contact_id: str,
    template_key: str = Query(DEFAULT_TEMPLATE_KEY),
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

    import os
    rep_name = os.getenv("SALES_REP_NAME", "").strip() or "Alex"
    ctx = Ctx(
        first_name=(contact.get("first_name") or "").strip()
            or (contact.get("full_name") or "there").split()[0],
        firm_name=firm_name or "your firm",
        rep_name=rep_name,
        pain_quote=pain.get("pain_quote"),
        reviewer_name=pain.get("reviewer_name"),
        review_date=pain.get("review_date"),
    )

    out = []
    for i in range(1, n + 1):
        rendered = render_step(template_key, i, variant, ctx)
        out.append(RenderedStepDTO(
            step=i,
            subject=rendered.subject,
            body=rendered.body,
            message_type=rendered.message_type,
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
