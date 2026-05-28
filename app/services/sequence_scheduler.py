"""Email-sequence scheduler. Polls `email_sequences` for rows whose
`next_step_due_at <= now()` and `status='active'`, renders the next
step against the contact's data, sends via `_send_email` (which
auto-logs into `email_logs`), and advances state.

Safety:
  - Gated by `ALLOW_SEQUENCE_SEND=true`. When closed, due rows are
    left alone and re-evaluated next tick. The gate is checked at
    every send so flipping the env var takes effect within one
    polling interval.
  - Render failures pause the row with a `paused_reason` instead of
    looping. The scheduler never auto-resumes a paused row.
  - One sequence per (contact, template_key) — invariant enforced by
    the unique constraint on email_sequences. Restarts unsupported.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update

from app.db import AsyncSessionLocal
from app.db.models import (
    EmailSequenceRow, FirmContactRow, PatientRow,
)
from app.services.email_notification_service import _send_email
from app.services.lead_email_composer import LeadEmailComposerError, compose_lead_email
from app.services.sequences.common import Ctx
from app.services.sequences.registry import (
    DEFAULT_TEMPLATE_KEY,
    cadence_for,
    is_dynamic_template,
    normalize_template_key,
    render_step,
    steps_total,
    variant_for,
)

logger = logging.getLogger(__name__)


def _is_truthy(v: str) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def _gate_open() -> bool:
    return _is_truthy(os.getenv("ALLOW_SEQUENCE_SEND", "false"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# sequence lifecycle (called by the API + CLI to start a new sequence)
# ---------------------------------------------------------------------------

async def start_sequence(
    *,
    contact_id: str,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    pain_quote: Optional[str],
    reviewer_name: Optional[str],
    review_date: Optional[str],
    pain_point_key: Optional[str],
    started_by: str = "operator",
    first_step_due_at: Optional[datetime] = None,
) -> EmailSequenceRow:
    """Create and persist a new sequence row. Variant is decided by the
    selected template. Step 1 is queued for immediate dispatch by the next
    scheduler tick (`next_step_due_at = now()`).

    Raises ValueError if a sequence already exists for this
    (contact, template) — restarts are not supported in v1.
    """
    template_key = normalize_template_key(template_key)
    variant = variant_for(template_key, pain_quote=pain_quote)
    async with AsyncSessionLocal() as session:
        # Reject duplicates explicitly (the unique constraint would too,
        # but a clear message helps).
        existing = (await session.execute(
            select(EmailSequenceRow).where(
                EmailSequenceRow.contact_id == contact_id,
                EmailSequenceRow.template_key == template_key,
            )
        )).scalar_one_or_none()
        if existing:
            raise ValueError(
                f"Sequence already exists for contact {contact_id} "
                f"(status={existing.status}, step={existing.current_step}). "
                f"Restarts not supported in v1."
            )

        row = EmailSequenceRow(
            id=uuid.uuid4().hex,
            contact_id=contact_id,
            template_key=template_key,
            status="active",
            current_step=0,
            steps_total=steps_total(template_key, variant),
            variant=variant,
            last_sent_at=None,
            next_step_due_at=first_step_due_at or _utcnow(),
            paused_reason=None,
            pain_point_key=pain_point_key if variant == "with_quote" else None,
            frozen_pain_quote=pain_quote if variant == "with_quote" else None,
            frozen_reviewer_name=reviewer_name if variant == "with_quote" else None,
            frozen_review_date=review_date if variant == "with_quote" else None,
            started_by=started_by,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def get_active_sequence(contact_id: str) -> Optional[EmailSequenceRow]:
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(EmailSequenceRow).where(
                EmailSequenceRow.contact_id == contact_id,
                EmailSequenceRow.template_key == DEFAULT_TEMPLATE_KEY,
            )
        )).scalar_one_or_none()


async def get_sequence(
    contact_id: str,
    template_key: str = DEFAULT_TEMPLATE_KEY,
) -> Optional[EmailSequenceRow]:
    template_key = normalize_template_key(template_key)
    async with AsyncSessionLocal() as session:
        return (await session.execute(
            select(EmailSequenceRow).where(
                EmailSequenceRow.contact_id == contact_id,
                EmailSequenceRow.template_key == template_key,
            )
        )).scalar_one_or_none()


# ---------------------------------------------------------------------------
# tick: pick due rows, render + send, advance state
# ---------------------------------------------------------------------------

def _build_ctx(contact: FirmContactRow, firm_name: str, seq: EmailSequenceRow) -> Ctx:
    rep_name = os.getenv("SALES_REP_NAME", "").strip() or "Alex"
    return Ctx(
        first_name=(contact.first_name or "").strip()
            or (contact.full_name or "there").split()[0],
        firm_name=firm_name or "your firm",
        rep_name=rep_name,
        pain_quote=seq.frozen_pain_quote,
        reviewer_name=seq.frozen_reviewer_name,
        review_date=seq.frozen_review_date,
    )


async def _firm_name_for(pif_id: str) -> str:
    """Best-effort firm name. Walks both `pif-{id}` and `mc-{id}`
    patient rows, since the two sync paths use different prefixes."""
    from app.services.firm_contacts_service import resolve_firm_name
    return await resolve_firm_name(pif_id)


async def _process_one(seq_id: str, dry_run: bool = False) -> dict:
    """Render + (optionally) send the next step for one sequence row.
    Returns a dict describing what happened — useful for CLI output."""
    async with AsyncSessionLocal() as session:
        seq = (await session.execute(
            select(EmailSequenceRow).where(EmailSequenceRow.id == seq_id)
        )).scalar_one_or_none()
        if not seq or seq.status != "active":
            return {"id": seq_id, "skipped": "not_active"}

        contact = (await session.execute(
            select(FirmContactRow).where(FirmContactRow.id == seq.contact_id)
        )).scalar_one_or_none()
        if not contact or not contact.email:
            seq.status = "paused"
            seq.paused_reason = "no_email_on_contact"
            await session.commit()
            return {"id": seq_id, "paused": "no_email_on_contact"}

        firm_name = await _firm_name_for(contact.pif_id)
        next_step = seq.current_step + 1
        if next_step > seq.steps_total:
            seq.status = "completed"
            seq.next_step_due_at = None
            await session.commit()
            return {"id": seq_id, "completed": True}

        if is_dynamic_template(seq.template_key):
            try:
                composed = await compose_lead_email(
                    contact=contact,
                    firm_name=firm_name,
                    sequence=seq,
                    step_num=next_step,
                )
                if composed.requires_human_review and not dry_run:
                    seq.status = "paused"
                    seq.paused_reason = (
                        "composer_requires_human_review: "
                        f"{'; '.join(composed.risk_flags)[:180]}"
                    )
                    await session.commit()
                    return {
                        "id": seq_id,
                        "paused": "composer_requires_human_review",
                        "subject": composed.subject,
                        "reasoning": composed.reasoning,
                        "risk_flags": composed.risk_flags,
                    }
                rendered_subject = composed.subject
                rendered_body = composed.body
                rendered_message_type = "dynamic_lead_email"
                render_meta = {
                    "angle": composed.angle,
                    "cta": composed.cta,
                    "blog_link_used": composed.blog_link_used,
                    "reasoning": composed.reasoning,
                    "model": composed.model,
                }
            except LeadEmailComposerError as e:
                seq.status = "paused"
                seq.paused_reason = f"compose_failed: {str(e)[:200]}"
                await session.commit()
                return {"id": seq_id, "paused": "compose_failed", "error": str(e)}
        else:
            try:
                ctx = _build_ctx(contact, firm_name, seq)
                rendered = render_step(seq.template_key, next_step, seq.variant, ctx)
                rendered_subject = rendered.subject
                rendered_body = rendered.body
                rendered_message_type = rendered.message_type
                render_meta = {}
            except Exception as e:
                seq.status = "paused"
                seq.paused_reason = f"render_failed: {type(e).__name__}: {e}"
                await session.commit()
                return {"id": seq_id, "paused": "render_failed", "error": str(e)}

        if dry_run:
            return {
                "id": seq_id,
                "dry_run": True,
                "next_step": next_step,
                "subject": rendered_subject,
                "body_chars": len(rendered_body),
                "to": contact.email,
                "render_meta": render_meta,
            }

        try:
            await asyncio.to_thread(
                _send_email,
                rendered_subject,
                rendered_body,
                to=contact.email,
                message_type=rendered_message_type,
                pif_id=contact.pif_id,
                recipient_name=contact.full_name,
            )
        except Exception as e:
            seq.status = "paused"
            seq.paused_reason = f"send_failed: {type(e).__name__}: {str(e)[:200]}"
            await session.commit()
            return {"id": seq_id, "paused": "send_failed", "error": str(e)}

        # Advance state.
        seq.current_step = next_step
        seq.last_sent_at = _utcnow()
        if next_step >= seq.steps_total:
            seq.status = "completed"
            seq.next_step_due_at = None
        else:
            cadence = cadence_for(seq.template_key, seq.variant)
            # cadence[i] = days from sequence start to send step (i+1).
            # next due = cadence[next_step] - cadence[next_step - 1] days from now.
            gap_days = cadence[next_step] - cadence[next_step - 1]
            seq.next_step_due_at = _utcnow() + timedelta(days=gap_days)
        await session.commit()
        return {
            "id": seq_id,
            "step_sent": next_step,
            "next_due": (
                seq.next_step_due_at.isoformat() if seq.next_step_due_at else None
            ),
            "status": seq.status,
        }


async def tick(limit: int = 25, dry_run: bool = False) -> list[dict]:
    """Pick all due active rows and process up to `limit` of them. Each
    is independent — a render or send failure pauses just that row,
    not the whole tick."""
    if not _gate_open() and not dry_run:
        return [{"skipped_all": "ALLOW_SEQUENCE_SEND=false"}]

    async with AsyncSessionLocal() as session:
        due_ids = (await session.execute(
            select(EmailSequenceRow.id).where(
                EmailSequenceRow.status == "active",
                EmailSequenceRow.next_step_due_at != None,  # noqa: E711
                EmailSequenceRow.next_step_due_at <= _utcnow(),
            ).order_by(EmailSequenceRow.next_step_due_at.asc()).limit(limit)
        )).scalars().all()

    results = []
    for sid in due_ids:
        try:
            results.append(await _process_one(sid, dry_run=dry_run))
        except Exception as e:
            logger.exception("sequence tick failed for %s", sid)
            results.append({"id": sid, "error": str(e)})
    return results


async def sequence_loop(interval_seconds: int = 60):
    """Background loop. Wired into app.main lifespan."""
    logger.info("sequence_loop starting (interval=%ss)", interval_seconds)
    while True:
        try:
            results = await tick()
            sent = sum(1 for r in results if r.get("step_sent"))
            paused = sum(1 for r in results if r.get("paused"))
            if sent or paused:
                logger.info(
                    "sequence tick: %d sent, %d paused (of %d due)",
                    sent, paused, len(results),
                )
        except Exception:
            logger.exception("sequence_loop tick raised")
        await asyncio.sleep(interval_seconds)
