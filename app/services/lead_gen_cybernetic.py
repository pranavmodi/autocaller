"""Cybernetic lead-generation loop services.

This module keeps the control loop deterministic:
- recommendations come from explicit policy + DB state;
- LLMs only classify observations or propose changes;
- sequence execution remains behind a batch approval gate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, select

from app.db import AsyncSessionLocal
from app.db.models import (
    FirmContactRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenObservationRow,
    LeadGenPolicyProposalRow,
    LeadGenPolicyVersionRow,
)
from app.services.firm_contacts_service import fetch_pain_quote_for_firm
from app.services.lead_feedback_classifier import classify_feedback_event
from app.services.sequence_recommendations import recommend_sequence_contacts
from app.services.sequence_scheduler import get_sequence, start_sequence
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY, normalize_template_key


TARGET_METRIC = "booked_qualified_conversations"
DEFAULT_POLICY_VERSION = "lead-gen-v1"
DEFAULT_BATCH_STAGGER_MINUTES = 60


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def staggered_due_at(
    *,
    start_at: datetime,
    index: int,
    total: int,
    window_minutes: int = DEFAULT_BATCH_STAGGER_MINUTES,
) -> datetime:
    """Return a deterministic due time for an item inside a batch window."""
    if total <= 1:
        return start_at
    safe_index = max(0, min(index, total - 1))
    safe_window = max(0, window_minutes)
    offset_seconds = (safe_window * 60 * safe_index) / (total - 1)
    return start_at + timedelta(seconds=offset_seconds)


def parse_scheduled_start_at(
    scheduled_start_at: str | None,
    scheduled_timezone: str = "America/Los_Angeles",
) -> datetime:
    """Parse operator-entered schedule time and return UTC.

    Naive datetime strings from `datetime-local` are interpreted in the
    supplied IANA timezone. Aware strings are honored and converted to UTC.
    """
    if not scheduled_start_at:
        return _utcnow()
    raw = scheduled_start_at.strip()
    if not raw:
        return _utcnow()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("invalid_scheduled_start_at") from e
    if parsed.tzinfo is None:
        try:
            tz = ZoneInfo(scheduled_timezone)
        except ZoneInfoNotFoundError as e:
            raise ValueError("invalid_scheduled_timezone") from e
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def _default_weights() -> dict[str, Any]:
    return {
        "persona": {
            "founder_owner": 100,
            "coo": 98,
            "managing_partner": 94,
            "operations_leader": 88,
            "partner": 82,
            "known_decision_maker": 70,
        },
        "bonuses": {
            "pif_leadership": 3,
            "known_state": 2,
        },
        "target_metric": TARGET_METRIC,
    }


async def ensure_default_policy() -> LeadGenPolicyVersionRow:
    async with AsyncSessionLocal() as session:
        active = (await session.execute(
            select(LeadGenPolicyVersionRow)
            .where(LeadGenPolicyVersionRow.active.is_(True))
            .order_by(desc(LeadGenPolicyVersionRow.created_at))
        )).scalars().first()
        if active:
            return active
        existing = (await session.execute(
            select(LeadGenPolicyVersionRow).where(
                LeadGenPolicyVersionRow.version == DEFAULT_POLICY_VERSION
            )
        )).scalar_one_or_none()
        if existing:
            existing.active = True
            await session.commit()
            await session.refresh(existing)
            return existing
        row = LeadGenPolicyVersionRow(
            version=DEFAULT_POLICY_VERSION,
            label="Lead generation v1",
            target_metric=TARGET_METRIC,
            weights_json=_default_weights(),
            suppressions_json={
                "exclude_comms_history": True,
                "exclude_existing_sequences": True,
                "exclude_unusable_email": True,
                "dedupe_by_email": True,
                "human_approval_required": True,
            },
            notes="Initial explicit policy for records-audit lead generation.",
            active=True,
            created_by="system",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def create_recommendation_batch(
    *,
    name: str | None = None,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    limit: int = 50,
    created_by: str = "operator",
) -> dict[str, Any]:
    template_key = normalize_template_key(template_key)
    policy = await ensure_default_policy()
    rec_data = await recommend_sequence_contacts(template_key=template_key, limit=limit)
    batch_id = _new_id()
    batch_name = name or f"{template_key} recommendation batch"

    async with AsyncSessionLocal() as session:
        batch = LeadGenBatchRow(
            id=batch_id,
            name=batch_name,
            target_metric=TARGET_METRIC,
            template_key=template_key,
            policy_version=policy.version,
            status="recommended",
            counts_json=rec_data.get("counts") or {},
            created_by=created_by,
        )
        session.add(batch)
        await session.flush()
        for rec in rec_data.get("recommended") or []:
            session.add(LeadGenBatchItemRow(
                id=_new_id(),
                batch_id=batch_id,
                contact_id=rec["contact_id"],
                pif_id=rec["pif_id"],
                firm_name=rec["firm_name"],
                contact_name=rec.get("contact_name") or "",
                contact_email=rec["contact_email"],
                contact_title=rec.get("contact_title") or "",
                persona=rec.get("persona") or "",
                template_key=template_key,
                score=int(rec.get("score") or 0),
                reason_json={
                    "reason": rec.get("reason") or "",
                    "contact_source": rec.get("contact_source") or "",
                    "policy_version": policy.version,
                },
                approval_status="pending",
            ))
        await session.commit()

    return await get_batch(batch_id)


def _batch_to_dict(batch: LeadGenBatchRow) -> dict[str, Any]:
    return {
        "id": batch.id,
        "name": batch.name,
        "target_metric": batch.target_metric,
        "template_key": batch.template_key,
        "policy_version": batch.policy_version,
        "status": batch.status,
        "counts": batch.counts_json or {},
        "created_by": batch.created_by,
        "approved_by": batch.approved_by,
        "approved_at": batch.approved_at.isoformat() if batch.approved_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _item_to_dict(item: LeadGenBatchItemRow) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "contact_id": item.contact_id,
        "pif_id": item.pif_id,
        "firm_name": item.firm_name,
        "contact_name": item.contact_name,
        "contact_email": item.contact_email,
        "contact_title": item.contact_title,
        "persona": item.persona,
        "template_key": item.template_key,
        "score": item.score,
        "reason": item.reason_json or {},
        "approval_status": item.approval_status,
        "sequence_id": item.sequence_id,
        "outcome": item.outcome,
        "outcome_confidence": item.outcome_confidence,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _observation_to_dict(obs: LeadGenObservationRow) -> dict[str, Any]:
    return {
        "id": obs.id,
        "batch_id": obs.batch_id,
        "batch_item_id": obs.batch_item_id,
        "contact_id": obs.contact_id,
        "pif_id": obs.pif_id,
        "event_type": obs.event_type,
        "raw_event": obs.raw_event_json or {},
        "classified_outcome": obs.classified_outcome,
        "confidence": obs.confidence,
        "next_action": obs.next_action,
        "llm_reasoning": obs.llm_reasoning,
        "llm_model": obs.llm_model,
        "created_at": obs.created_at.isoformat() if obs.created_at else None,
    }


async def list_batches(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    async with AsyncSessionLocal() as session:
        q = select(LeadGenBatchRow).order_by(desc(LeadGenBatchRow.created_at)).limit(limit)
        if status:
            q = q.where(LeadGenBatchRow.status == status)
        rows = (await session.execute(q)).scalars().all()
    return [_batch_to_dict(row) for row in rows]


async def get_batch(batch_id: str, *, include_observations: bool = False) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        batch = (await session.execute(
            select(LeadGenBatchRow).where(LeadGenBatchRow.id == batch_id)
        )).scalar_one_or_none()
        if not batch:
            raise ValueError("batch_not_found")
        items = (await session.execute(
            select(LeadGenBatchItemRow)
            .where(LeadGenBatchItemRow.batch_id == batch_id)
            .order_by(desc(LeadGenBatchItemRow.score), LeadGenBatchItemRow.firm_name.asc())
        )).scalars().all()
        observations: list[LeadGenObservationRow] = []
        if include_observations:
            observations = (await session.execute(
                select(LeadGenObservationRow)
                .where(LeadGenObservationRow.batch_id == batch_id)
                .order_by(desc(LeadGenObservationRow.created_at))
            )).scalars().all()
    return {
        "batch": _batch_to_dict(batch),
        "items": [_item_to_dict(item) for item in items],
        "observations": [_observation_to_dict(obs) for obs in observations],
    }


async def approve_batch(
    *,
    batch_id: str,
    approved_by: str = "operator",
    start_sequences: bool = False,
    stagger_minutes: int = DEFAULT_BATCH_STAGGER_MINUTES,
    scheduled_start_at: str | None = None,
    scheduled_timezone: str = "America/Los_Angeles",
) -> dict[str, Any]:
    now = _utcnow()
    queue_start_at = parse_scheduled_start_at(scheduled_start_at, scheduled_timezone)
    async with AsyncSessionLocal() as session:
        batch = (await session.execute(
            select(LeadGenBatchRow).where(LeadGenBatchRow.id == batch_id)
        )).scalar_one_or_none()
        if not batch:
            raise ValueError("batch_not_found")
        items = (await session.execute(
            select(LeadGenBatchItemRow)
            .where(LeadGenBatchItemRow.batch_id == batch_id)
            .order_by(desc(LeadGenBatchItemRow.score), LeadGenBatchItemRow.firm_name.asc())
        )).scalars().all()
        batch.status = "sequencing" if start_sequences else "approved"
        batch.approved_by = approved_by
        batch.approved_at = now
        if start_sequences:
            batch.started_at = now
        for item in items:
            if item.approval_status == "pending":
                item.approval_status = "approved"
        await session.commit()

    if start_sequences:
        total = len(items)
        for idx, item in enumerate(items):
            existing = await get_sequence(item.contact_id, item.template_key)
            if existing:
                seq_id = existing.id
            else:
                pain = await fetch_pain_quote_for_firm(item.pif_id)
                first_step_due_at = staggered_due_at(
                    start_at=queue_start_at,
                    index=idx,
                    total=total,
                    window_minutes=stagger_minutes,
                )
                try:
                    seq = await start_sequence(
                        contact_id=item.contact_id,
                        template_key=item.template_key,
                        pain_quote=pain.get("quote"),
                        reviewer_name=pain.get("reviewer_name"),
                        review_date=pain.get("review_date"),
                        pain_point_key=pain.get("pain_point_key"),
                        started_by=f"lead_gen_batch:{batch_id}",
                        first_step_due_at=first_step_due_at,
                    )
                    seq_id = seq.id
                except ValueError:
                    seq_id = None
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.id == item.id)
                )).scalar_one()
                row.sequence_id = seq_id
                row.approval_status = "started" if seq_id else "skipped"
                await session.commit()

    return await get_batch(batch_id)


async def classify_and_store_observation(
    *,
    event_type: str,
    raw_event: dict[str, Any],
    batch_id: str | None = None,
    contact_id: str | None = None,
    batch_item_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        item: Optional[LeadGenBatchItemRow] = None
        if batch_item_id:
            item = (await session.execute(
                select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.id == batch_item_id)
            )).scalar_one_or_none()
        elif batch_id and contact_id:
            item = (await session.execute(
                select(LeadGenBatchItemRow).where(
                    LeadGenBatchItemRow.batch_id == batch_id,
                    LeadGenBatchItemRow.contact_id == contact_id,
                )
            )).scalar_one_or_none()
        contact: Optional[FirmContactRow] = None
        lookup_contact_id = contact_id or (item.contact_id if item else None)
        if lookup_contact_id:
            contact = (await session.execute(
                select(FirmContactRow).where(FirmContactRow.id == lookup_contact_id)
            )).scalar_one_or_none()

    contact_payload = {}
    firm_payload = {}
    sequence_payload = {}
    if item:
        firm_payload = {"pif_id": item.pif_id, "firm_name": item.firm_name}
        sequence_payload = {
            "batch_id": item.batch_id,
            "batch_item_id": item.id,
            "template_key": item.template_key,
        }
    if contact:
        contact_payload = {
            "id": contact.id,
            "name": contact.full_name,
            "email": contact.email,
            "title": contact.title,
            "source": contact.source,
        }
        firm_payload.setdefault("pif_id", contact.pif_id)

    classification = await classify_feedback_event(
        event_type=event_type,
        raw_event=raw_event,
        contact=contact_payload,
        firm=firm_payload,
        sequence=sequence_payload,
        target_metric=TARGET_METRIC,
        model=model,
    )

    async with AsyncSessionLocal() as session:
        obs = LeadGenObservationRow(
            id=_new_id(),
            batch_id=batch_id or (item.batch_id if item else None),
            batch_item_id=batch_item_id or (item.id if item else None),
            contact_id=lookup_contact_id,
            pif_id=(item.pif_id if item else (contact.pif_id if contact else None)),
            event_type=event_type,
            raw_event_json=raw_event,
            classified_outcome=classification.outcome,
            confidence=classification.confidence,
            next_action=classification.next_action,
            llm_reasoning=classification.reasoning,
            llm_model=classification.model,
            llm_raw_response=classification.raw_response,
        )
        session.add(obs)
        if item:
            item_row = (await session.execute(
                select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.id == item.id)
            )).scalar_one()
            item_row.outcome = classification.outcome
            item_row.outcome_confidence = classification.confidence
        await session.commit()
        await session.refresh(obs)
    return _observation_to_dict(obs)


async def create_policy_proposal_from_batch(
    *,
    batch_id: str,
    created_by: str = "system",
) -> dict[str, Any]:
    """Create an inspectable heuristic proposal from observed batch outcomes.

    This is intentionally conservative: it summarizes evidence and proposes
    score adjustments, but does not apply them.
    """
    batch_data = await get_batch(batch_id, include_observations=True)
    items = batch_data["items"]
    observations = batch_data["observations"]
    positive = {
        "booked_qualified_conversation",
        "positive_reply",
        "referral",
    }
    negative = {"not_interested", "do_not_contact", "bounce"}
    by_persona: dict[str, dict[str, int]] = {}
    item_by_contact = {item["contact_id"]: item for item in items}
    for obs in observations:
        item = item_by_contact.get(obs.get("contact_id") or "")
        if not item:
            continue
        persona = item.get("persona") or "unknown"
        bucket = by_persona.setdefault(persona, {"positive": 0, "negative": 0, "total": 0})
        bucket["total"] += 1
        if obs.get("classified_outcome") in positive:
            bucket["positive"] += 1
        if obs.get("classified_outcome") in negative:
            bucket["negative"] += 1

    proposed = {
        "kind": "persona_weight_review",
        "policy": "human_review_required",
        "suggestions": [],
    }
    for persona, stats in sorted(by_persona.items()):
        total = stats["total"]
        if total < 3:
            continue
        if stats["positive"] >= 2:
            proposed["suggestions"].append({
                "action": "consider_boost",
                "persona": persona,
                "evidence": stats,
            })
        if stats["negative"] >= 3 and stats["positive"] == 0:
            proposed["suggestions"].append({
                "action": "consider_deprioritize",
                "persona": persona,
                "evidence": stats,
            })

    async with AsyncSessionLocal() as session:
        row = LeadGenPolicyProposalRow(
            id=_new_id(),
            source_batch_id=batch_id,
            proposal_type="persona_weight_review",
            proposed_change_json=proposed,
            evidence_json={"by_persona": by_persona, "observation_count": len(observations)},
            status="pending",
            created_by=created_by,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return {
        "id": row.id,
        "source_batch_id": row.source_batch_id,
        "proposal_type": row.proposal_type,
        "proposed_change": row.proposed_change_json,
        "evidence": row.evidence_json,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
