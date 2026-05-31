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
    EmailSequenceRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenObservationRow,
    LeadGenPolicyProposalRow,
    LeadGenPolicyVersionRow,
    OperatorNotificationRow,
)
from app.services.contact_selection import contact_selection_weights
from app.services.firm_contacts_service import fetch_pain_quote_for_firm
from app.services.lead_gen_action_planner import QUEUEABLE_ACTIONS, plan_daily_lead_gen_actions
from app.services.lead_email_composer import _sanitize_email_copy
from app.services.lead_feedback_classifier import classify_feedback_event
from app.services.email_notification_service import _send_email
from app.services.sequence_scheduler import (
    create_sequence_approval_placeholder,
    get_sequence,
    start_sequence,
)
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY, cadence_for, normalize_template_key


TARGET_METRIC = "booked_qualified_conversations"
DEFAULT_POLICY_VERSION = "lead-gen-v1"
DEFAULT_BATCH_STAGGER_MINUTES = 60
DEFAULT_DAILY_SEND_BUDGET = 50


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
    weights = contact_selection_weights({
        "bonuses": {
            "pif_leadership": 3,
            "known_state": 2,
        },
        "target_metric": TARGET_METRIC,
        "daily_send_budget": DEFAULT_DAILY_SEND_BUDGET,
    })
    return weights


def _effective_weights(weights: dict[str, Any] | None) -> dict[str, Any]:
    merged = contact_selection_weights(weights or {})
    merged.setdefault("target_metric", TARGET_METRIC)
    merged.setdefault("daily_send_budget", DEFAULT_DAILY_SEND_BUDGET)
    return merged


def daily_send_budget_from_policy(policy: LeadGenPolicyVersionRow) -> int:
    weights = policy.weights_json or {}
    raw = weights.get("daily_send_budget", DEFAULT_DAILY_SEND_BUDGET)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_DAILY_SEND_BUDGET
    return max(1, min(200, value))


async def ensure_default_policy() -> LeadGenPolicyVersionRow:
    async with AsyncSessionLocal() as session:
        active = (await session.execute(
            select(LeadGenPolicyVersionRow)
            .where(LeadGenPolicyVersionRow.active.is_(True))
            .order_by(desc(LeadGenPolicyVersionRow.created_at))
        )).scalars().first()
        if active:
            effective = _effective_weights(active.weights_json)
            if effective != (active.weights_json or {}):
                active.weights_json = effective
                await session.commit()
                await session.refresh(active)
            return active
        existing = (await session.execute(
            select(LeadGenPolicyVersionRow).where(
                LeadGenPolicyVersionRow.version == DEFAULT_POLICY_VERSION
            )
        )).scalar_one_or_none()
        if existing:
            existing.active = True
            existing.weights_json = _effective_weights(existing.weights_json)
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


async def set_daily_send_budget(*, budget: int, updated_by: str = "operator") -> LeadGenPolicyVersionRow:
    safe_budget = max(1, min(200, int(budget)))
    policy = await ensure_default_policy()
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(LeadGenPolicyVersionRow).where(
                LeadGenPolicyVersionRow.version == policy.version
            )
        )).scalar_one()
        weights = dict(row.weights_json or {})
        weights["daily_send_budget"] = safe_budget
        weights["daily_send_budget_updated_by"] = updated_by
        weights["daily_send_budget_updated_at"] = _utcnow().isoformat()
        row.weights_json = weights
        await session.commit()
        await session.refresh(row)
        return row


async def send_batch_item_draft(
    *,
    batch_item_id: str,
    subject: str,
    body: str,
    sent_by: str = "operator",
) -> dict[str, Any]:
    draft_subject = _sanitize_email_copy(subject)
    draft_body = _sanitize_email_copy(body)
    if not draft_subject:
        raise ValueError("draft_subject_empty")
    if not draft_body:
        raise ValueError("draft_body_empty")

    async with AsyncSessionLocal() as session:
        item = await session.get(LeadGenBatchItemRow, batch_item_id)
        if not item:
            raise ValueError("batch_item_not_found")
        contact = await session.get(FirmContactRow, item.contact_id)
        if not contact or not contact.email:
            raise ValueError("contact_email_not_found")

    existing = await get_sequence(item.contact_id, item.template_key)
    if existing:
        seq = existing
    else:
        pain = await fetch_pain_quote_for_firm(item.pif_id)
        seq = await start_sequence(
            contact_id=item.contact_id,
            template_key=item.template_key,
            pain_quote=pain.get("quote"),
            reviewer_name=pain.get("reviewer_name"),
            review_date=pain.get("review_date"),
            pain_point_key=pain.get("pain_point_key"),
            started_by=f"lead_gen_preview_send:{item.batch_id}",
            first_step_due_at=_utcnow(),
        )

    step_num = seq.current_step + 1
    if step_num > seq.steps_total:
        raise ValueError("sequence_completed")

    msg_id = _send_email(
        draft_subject,
        draft_body,
        to=contact.email,
        message_type="dynamic_lead_email",
        pif_id=contact.pif_id,
        recipient_name=contact.full_name,
        transport="zoho_api",
    )

    sent_at = _utcnow()
    async with AsyncSessionLocal() as session:
        item_row = await session.get(LeadGenBatchItemRow, batch_item_id)
        seq_row = await session.get(EmailSequenceRow, seq.id)
        if item_row:
            item_row.sequence_id = seq.id
            item_row.approval_status = "started"
            reason = dict(item_row.reason_json or {})
            reason["last_sent_by"] = sent_by or "operator"
            reason["last_sent_at"] = sent_at.isoformat()
            reason["last_sent_message_id"] = msg_id
            reason["last_sent_subject"] = draft_subject
            item_row.reason_json = reason
        if seq_row:
            seq_row.current_step = step_num
            seq_row.last_sent_at = sent_at
            if step_num >= seq_row.steps_total:
                seq_row.status = "completed"
                seq_row.next_step_due_at = None
            else:
                cadence = cadence_for(seq_row.template_key, seq_row.variant)
                gap_days = cadence[step_num] - cadence[step_num - 1]
                seq_row.status = "active"
                seq_row.next_step_due_at = sent_at + timedelta(days=gap_days)
            seq_row.paused_reason = None
        notification = (await session.execute(
            select(OperatorNotificationRow).where(
                OperatorNotificationRow.notification_type == "lead_sequence_email_approval",
                OperatorNotificationRow.source_type == "email_sequence_step",
                OperatorNotificationRow.source_id == f"{seq.id}:{step_num}",
                OperatorNotificationRow.status == "pending",
                OperatorNotificationRow.acknowledged_at.is_(None),
            )
        )).scalar_one_or_none()
        if notification:
            suggested = dict(notification.suggested_action_json or {})
            suggested.update({
                "sent_at": sent_at.isoformat(),
                "sent_by": sent_by or "operator",
                "sent_message_id": msg_id,
                "sent_transport": "zoho_api",
                "sent_to": contact.email,
                "sent_subject": draft_subject,
                "sent_body": draft_body,
            })
            notification.suggested_action_json = suggested
            notification.status = "actioned"
            notification.acknowledged_at = sent_at
            notification.acknowledged_by = (sent_by or "operator")[:128]
        await session.commit()

    return {
        "batch_item_id": batch_item_id,
        "sequence_id": seq.id,
        "sent_to": contact.email,
        "sent_subject": draft_subject,
        "sent_message_id": msg_id,
        "sent_at": sent_at.isoformat(),
        "step": step_num,
    }


async def create_recommendation_batch(
    *,
    name: str | None = None,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    limit: int = 50,
    created_by: str = "operator",
) -> dict[str, Any]:
    template_key = normalize_template_key(template_key)
    policy = await ensure_default_policy()
    rec_data = await plan_daily_lead_gen_actions(template_key=template_key, limit=limit)
    batch_id = _new_id()
    batch_name = name or f"{template_key} daily action plan"

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
            reason_json = {
                "reason": rec.get("reason") or "",
                "contact_source": rec.get("contact_source") or "",
                "policy_version": policy.version,
            }
            reason_json.update({
                "action_type": rec.get("action_type") or "first_touch",
                "priority_bucket": rec.get("priority_bucket") or "new_conversation",
                "source_type": rec.get("source_type") or "new_recommendation",
                "source_id": rec.get("source_id") or rec.get("contact_id"),
                "sequence_id": rec.get("sequence_id"),
                "notification_id": rec.get("notification_id"),
                "signals": rec.get("signals") or [],
                "next_operator_action": rec.get("next_operator_action") or "review_and_approve",
                "selection_policy_version": (
                    rec.get("selection_policy_version") or rec.get("policy_version") or policy.version
                ),
                "score_breakdown": rec.get("score_breakdown") or {},
                "selection_features": rec.get("selection_features") or {},
                "suppressions": rec.get("suppressions") or [],
            })
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
                reason_json=reason_json,
                approval_status="pending",
                sequence_id=rec.get("sequence_id"),
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
        has_queueable_items = any(
            (item.reason_json or {}).get("action_type", "first_touch") in QUEUEABLE_ACTIONS
            for item in items
        )
        batch.status = "sequencing" if start_sequences and has_queueable_items else "approved"
        batch.approved_by = approved_by
        batch.approved_at = now
        if start_sequences:
            batch.started_at = now
        for item in items:
            if item.approval_status == "pending":
                item.approval_status = "approved"
        await session.commit()

    if start_sequences:
        queueable_items = [
            item for item in items
            if (item.reason_json or {}).get("action_type", "first_touch") in QUEUEABLE_ACTIONS
        ]
        total = len(queueable_items)
        for idx, item in enumerate(queueable_items):
            action_type = (item.reason_json or {}).get("action_type", "first_touch")
            create_approval_action = False
            existing = await get_sequence(item.contact_id, item.template_key)
            if existing:
                seq_id = existing.id
                create_approval_action = (existing.paused_reason or "").startswith(
                    "awaiting_operator_send_approval:"
                )
                if action_type == "follow_up":
                    first_step_due_at = staggered_due_at(
                        start_at=queue_start_at,
                        index=idx,
                        total=total,
                        window_minutes=stagger_minutes,
                    )
                    async with AsyncSessionLocal() as session:
                        seq_row = await session.get(EmailSequenceRow, existing.id)
                        if seq_row and seq_row.status == "active":
                            seq_row.next_step_due_at = first_step_due_at
                            await session.commit()
                            create_approval_action = True
            else:
                if action_type != "first_touch":
                    seq_id = None
                    async with AsyncSessionLocal() as session:
                        row = (await session.execute(
                            select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.id == item.id)
                        )).scalar_one()
                        row.approval_status = "skipped"
                        await session.commit()
                    continue
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
                    create_approval_action = True
                except ValueError:
                    seq_id = None
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.id == item.id)
                )).scalar_one()
                row.sequence_id = seq_id
                row.approval_status = "started" if seq_id else "skipped"
                await session.commit()
            if seq_id and create_approval_action:
                result = await create_sequence_approval_placeholder(seq_id)
                if result.get("notification_id"):
                    async with AsyncSessionLocal() as session:
                        row = (await session.execute(
                            select(LeadGenBatchItemRow).where(
                                LeadGenBatchItemRow.id == item.id
                            )
                        )).scalar_one()
                        reason = dict(row.reason_json or {})
                        reason["operator_notification_id"] = result["notification_id"]
                        reason["operator_notification_created_at"] = _utcnow().isoformat()
                        row.reason_json = reason
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
    by_email_quality: dict[str, dict[str, int]] = {}
    by_top_score_component: dict[str, dict[str, int]] = {}
    item_by_contact = {item["contact_id"]: item for item in items}

    def bump(bucket_map: dict[str, dict[str, int]], key: str, outcome: str | None) -> None:
        bucket = bucket_map.setdefault(key or "unknown", {"positive": 0, "negative": 0, "total": 0})
        bucket["total"] += 1
        if outcome in positive:
            bucket["positive"] += 1
        if outcome in negative:
            bucket["negative"] += 1

    for obs in observations:
        item = item_by_contact.get(obs.get("contact_id") or "")
        if not item:
            continue
        persona = item.get("persona") or "unknown"
        outcome = obs.get("classified_outcome")
        bump(by_persona, persona, outcome)
        reason = item.get("reason") or {}
        features = reason.get("selection_features") or {}
        if isinstance(features, dict):
            bump(by_email_quality, str(features.get("email_quality") or "unknown"), outcome)
        breakdown = reason.get("score_breakdown") or {}
        if isinstance(breakdown, dict) and breakdown:
            positive_components = {
                str(k): int(v)
                for k, v in breakdown.items()
                if isinstance(v, (int, float)) and int(v) > 0
            }
            if positive_components:
                top_component = max(positive_components.items(), key=lambda kv: kv[1])[0]
                bump(by_top_score_component, top_component, outcome)

    proposed = {
        "kind": "contact_selection_policy_review",
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

    for email_quality, stats in sorted(by_email_quality.items()):
        total = stats["total"]
        if total < 3:
            continue
        if stats["positive"] >= 2:
            proposed["suggestions"].append({
                "action": "consider_boost_email_quality",
                "email_quality": email_quality,
                "evidence": stats,
            })
        if stats["negative"] >= 3 and stats["positive"] == 0:
            proposed["suggestions"].append({
                "action": "consider_deprioritize_email_quality",
                "email_quality": email_quality,
                "evidence": stats,
            })

    for component, stats in sorted(by_top_score_component.items()):
        total = stats["total"]
        if total < 3:
            continue
        if stats["positive"] >= 2:
            proposed["suggestions"].append({
                "action": "consider_boost_score_component",
                "component": component,
                "evidence": stats,
            })
        if stats["negative"] >= 3 and stats["positive"] == 0:
            proposed["suggestions"].append({
                "action": "consider_deprioritize_score_component",
                "component": component,
                "evidence": stats,
            })

    async with AsyncSessionLocal() as session:
        row = LeadGenPolicyProposalRow(
            id=_new_id(),
            source_batch_id=batch_id,
            proposal_type="contact_selection_policy_review",
            proposed_change_json=proposed,
            evidence_json={
                "by_persona": by_persona,
                "by_email_quality": by_email_quality,
                "by_top_score_component": by_top_score_component,
                "observation_count": len(observations),
            },
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
