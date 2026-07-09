"""Cybernetic lead-generation loop services.

This module keeps the control loop deterministic:
- recommendations come from explicit policy + DB state;
- LLMs only classify observations or propose changes;
- sequence execution remains behind a batch approval gate.
"""
from __future__ import annotations

import uuid
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError

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
from app.services.lead_gen_transport import (
    DEFAULT_LEAD_GEN_TRANSPORT_STRATEGY,
    DEFAULT_ZOHO_DAILY_CAP,
    choose_lead_gen_transport,
    provider_daily_caps_from_weights,
)
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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _observation_dedupe_key(event_type: str, raw_event: dict[str, Any]) -> str:
    explicit = str(raw_event.get("dedupe_key") or "").strip()
    if explicit:
        return explicit[:128]
    for key in (
        "action_id",
        "inbound_email_id",
        "link_event_id",
        "consult_booking_id",
        "booking_id",
        "call_id",
        "provider_event_id",
        "email_log_id",
        "sent_message_id",
        "message_id",
    ):
        value = raw_event.get(key)
        if value:
            return f"{key}:{value}"[:128]
    digest = hashlib.sha256(_canonical_json(raw_event).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"[:128]


DETERMINISTIC_OBSERVATION_CLASSIFICATIONS: dict[str, dict[str, Any]] = {
    "email_sent": {
        "outcome": "neutral",
        "confidence": 100,
        "next_action": "continue_sequence",
        "reasoning": "Deterministic observation: lead-gen email send succeeded.",
        "model": "deterministic",
    },
    "email_send_failed": {
        # A send failure is operational (policy refusal, transient SMTP,
        # timeout) — NOT a delivery bounce or any lead disposition. 'neutral'
        # keeps it out of the item.outcome terminal-label set so a later
        # successful resend isn't masked. Genuine bounces arrive as the
        # distinct email_bounce event. The deliverability circuit-breaker
        # still counts email_send_failed by event_type, not by this outcome.
        "outcome": "neutral",
        "confidence": 100,
        "next_action": "human_reply",
        "reasoning": "Deterministic observation: lead-gen email send failed before or during transport (operational, not a bounce).",
        "model": "deterministic",
    },
    "link_clicked": {
        "outcome": "opened_or_clicked",
        "confidence": 80,
        "next_action": "continue_sequence",
        "reasoning": "Deterministic observation: tracked recipient clicked a link.",
        "model": "deterministic",
    },
    "consult_booked": {
        "outcome": "booked_qualified_conversation",
        "confidence": 100,
        "next_action": "confirm_booking",
        "reasoning": "Deterministic observation: a consult booking was created.",
        "model": "deterministic",
    },
    "call_disposition": {
        "outcome": "neutral",
        "confidence": 70,
        "next_action": "no_action",
        "reasoning": "Deterministic observation: outbound call disposition finalized.",
        "model": "deterministic",
    },
    "email_action_cancelled": {
        "outcome": "neutral",
        "confidence": 100,
        "next_action": "no_action",
        "reasoning": "Deterministic observation: scheduled/approved lead-gen email action was cancelled.",
        "model": "deterministic",
    },
    "email_rescheduled": {
        "outcome": "neutral",
        "confidence": 100,
        "next_action": "no_action",
        "reasoning": "Deterministic observation: scheduled lead-gen email action was rescheduled.",
        "model": "deterministic",
    },
}


def _classification_value(classification: Any, key: str, default: Any = None) -> Any:
    if classification is None:
        return default
    if isinstance(classification, dict):
        return classification.get(key, default)
    attr = {
        "outcome": "outcome",
        "confidence": "confidence",
        "next_action": "next_action",
        "reasoning": "reasoning",
        "model": "model",
        "raw_response": "raw_response",
    }.get(key, key)
    return getattr(classification, attr, default)


def _normalize_observation_classification(
    event_type: str,
    classification: Any | None,
) -> dict[str, Any]:
    base = dict(DETERMINISTIC_OBSERVATION_CLASSIFICATIONS.get(event_type) or {})
    if classification is None and base:
        return base
    return {
        "outcome": _classification_value(classification, "outcome", base.get("outcome")),
        "confidence": _classification_value(classification, "confidence", base.get("confidence")),
        "next_action": _classification_value(classification, "next_action", base.get("next_action")),
        "reasoning": _classification_value(classification, "reasoning", base.get("reasoning")),
        "model": _classification_value(classification, "model", base.get("model") or "manual"),
        "raw_response": _classification_value(classification, "raw_response", ""),
    }


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
        "provider_daily_caps": {"zoho_api": DEFAULT_ZOHO_DAILY_CAP},
        "lead_gen_transport_strategy": DEFAULT_LEAD_GEN_TRANSPORT_STRATEGY,
    })
    return weights


def _effective_weights(weights: dict[str, Any] | None) -> dict[str, Any]:
    merged = contact_selection_weights(weights or {})
    merged.setdefault("target_metric", TARGET_METRIC)
    merged.setdefault("daily_send_budget", DEFAULT_DAILY_SEND_BUDGET)
    merged.setdefault("provider_daily_caps", {"zoho_api": DEFAULT_ZOHO_DAILY_CAP})
    merged.setdefault("lead_gen_transport_strategy", DEFAULT_LEAD_GEN_TRANSPORT_STRATEGY)
    return merged


def daily_send_budget_from_policy(policy: LeadGenPolicyVersionRow) -> int:
    weights = policy.weights_json or {}
    raw = weights.get("daily_send_budget", DEFAULT_DAILY_SEND_BUDGET)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_DAILY_SEND_BUDGET
    return max(1, min(200, value))


def provider_daily_caps_from_policy(policy: LeadGenPolicyVersionRow) -> dict[str, int]:
    return provider_daily_caps_from_weights(
        policy.weights_json or {},
        total_daily_budget=daily_send_budget_from_policy(policy),
    )


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


async def set_daily_send_budget(
    *,
    budget: int,
    updated_by: str = "operator",
    resend_daily_budget: int | None = None,
) -> LeadGenPolicyVersionRow:
    safe_budget = max(1, min(200, int(budget)))
    safe_resend_budget = (
        None
        if resend_daily_budget is None
        else max(0, min(200, int(resend_daily_budget)))
    )
    policy = await ensure_default_policy()
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(LeadGenPolicyVersionRow).where(
                LeadGenPolicyVersionRow.version == policy.version
            )
        )).scalar_one()
        weights = dict(row.weights_json or {})
        weights["daily_send_budget"] = safe_budget
        caps = dict(weights.get("provider_daily_caps") or {})
        # Preserve an operator-set Zoho cap / transport strategy (see
        # set_lead_gen_transport). Only fall back to the defaults when nothing
        # has been explicitly configured, so saving the daily budget in the UI
        # doesn't silently revert a deliberate Resend-first deliverability choice.
        caps.setdefault("zoho_api", DEFAULT_ZOHO_DAILY_CAP)
        if safe_resend_budget is not None:
            caps["resend"] = safe_resend_budget
        weights["provider_daily_caps"] = caps
        weights.setdefault("lead_gen_transport_strategy", DEFAULT_LEAD_GEN_TRANSPORT_STRATEGY)
        weights["daily_send_budget_updated_by"] = updated_by
        weights["daily_send_budget_updated_at"] = _utcnow().isoformat()
        row.weights_json = weights
        await session.commit()
        await session.refresh(row)
        return row


VALID_TRANSPORT_STRATEGIES = {
    "zoho_first_then_resend",
    "resend_first_then_zoho",
}


async def set_lead_gen_transport(
    *,
    strategy: str | None = None,
    zoho_cap: int | None = None,
    resend_cap: int | None = None,
    updated_by: str = "operator",
) -> LeadGenPolicyVersionRow:
    """Set the lead-gen email transport strategy and/or per-provider daily caps.

    Deliverability lever: choose whether sends fill Zoho first
    (``zoho_first_then_resend``, the default) or Resend first
    (``resend_first_then_zoho``), and cap each provider. Setting ``zoho_cap`` to
    0 forces the Resend-only path. Any argument left as ``None`` is unchanged.
    """
    if strategy is not None and strategy not in VALID_TRANSPORT_STRATEGIES:
        raise ValueError(f"invalid_transport_strategy: {strategy}")
    policy = await ensure_default_policy()
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(LeadGenPolicyVersionRow).where(
                LeadGenPolicyVersionRow.version == policy.version
            )
        )).scalar_one()
        weights = dict(row.weights_json or {})
        if strategy is not None:
            weights["lead_gen_transport_strategy"] = strategy
        caps = dict(weights.get("provider_daily_caps") or {})
        if zoho_cap is not None:
            caps["zoho_api"] = max(0, min(200, int(zoho_cap)))
        if resend_cap is not None:
            caps["resend"] = max(0, min(200, int(resend_cap)))
        weights["provider_daily_caps"] = caps
        weights["lead_gen_transport_updated_by"] = updated_by
        weights["lead_gen_transport_updated_at"] = _utcnow().isoformat()
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
    composer_experiment_key: str | None = None,
    composer_variant_key: str | None = None,
    skill_path: str | None = None,
    skill_sha256: str | None = None,
    brief_version: int | None = None,
    transport: str | None = None,
) -> dict[str, Any]:
    draft_subject = _sanitize_email_copy(subject)
    draft_body = _sanitize_email_copy(body)
    if not draft_subject:
        raise ValueError("draft_subject_empty")
    if not draft_body:
        raise ValueError("draft_body_empty")
    transport_override = (transport or "").strip().lower() or None
    if transport_override and transport_override not in {"resend", "zoho_api", "smtp"}:
        raise ValueError("transport_must_be_resend_zoho_api_or_smtp")

    async with AsyncSessionLocal() as session:
        item = await session.get(LeadGenBatchItemRow, batch_item_id)
        if not item:
            raise ValueError("batch_item_not_found")
        original_reason = dict(item.reason_json or {})
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

    # An explicit transport is authoritative; only auto-select when none given.
    transport = transport_override
    if transport is None:
        policy = await ensure_default_policy()
        transport = await choose_lead_gen_transport(
            policy.weights_json or {},
            total_daily_budget=daily_send_budget_from_policy(policy),
        )
    msg_id = _send_email(
        draft_subject,
        draft_body,
        to=contact.email,
        message_type="dynamic_lead_email",
        pif_id=contact.pif_id,
        recipient_name=contact.full_name,
        transport=transport,
        brief_version=brief_version,
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
            reason["last_sent_transport"] = transport
            if composer_experiment_key:
                reason["last_sent_composer_experiment_key"] = composer_experiment_key
            if composer_variant_key:
                reason["last_sent_composer_variant_key"] = composer_variant_key
            if skill_path:
                reason["last_sent_skill_path"] = skill_path
            if skill_sha256:
                reason["last_sent_skill_sha256"] = skill_sha256
            if brief_version:
                reason["last_sent_brief_version"] = brief_version
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
        )).scalars().first()
        if not notification:
            notification_id = original_reason.get("notification_id") or original_reason.get("operator_notification_id")
            source_id = str(original_reason.get("source_id") or "").strip()
            notification_filters = [
                OperatorNotificationRow.notification_type == "lead_sequence_email_approval",
                OperatorNotificationRow.status == "pending",
                OperatorNotificationRow.acknowledged_at.is_(None),
            ]
            explicit_matches = []
            if notification_id:
                try:
                    explicit_matches.append(OperatorNotificationRow.id == int(notification_id))
                except (TypeError, ValueError):
                    pass
            if source_id:
                explicit_matches.append(OperatorNotificationRow.source_id == source_id)
            explicit_matches.append(
                OperatorNotificationRow.context_json["batch_item_id"].as_string() == batch_item_id
            )
            notification = (await session.execute(
                select(OperatorNotificationRow).where(
                    *notification_filters,
                    or_(*explicit_matches),
                ).order_by(OperatorNotificationRow.created_at.desc())
            )).scalars().first()
        if notification:
            suggested = dict(notification.suggested_action_json or {})
            suggested.update({
                "sent_at": sent_at.isoformat(),
                "sent_by": sent_by or "operator",
                "sent_message_id": msg_id,
                "sent_transport": transport,
                "sent_to": contact.email,
                "sent_subject": draft_subject,
                "sent_body": draft_body,
                "composer_experiment_key": composer_experiment_key,
                "composer_variant_key": composer_variant_key,
                "skill_path": skill_path,
                "skill_sha256": skill_sha256,
                "brief_version": brief_version,
            })
            notification.suggested_action_json = suggested
            notification.status = "actioned"
            notification.acknowledged_at = sent_at
            notification.acknowledged_by = (sent_by or "operator")[:128]
        await session.commit()

    from app.services.product_traces import safe_record_product_trace

    await safe_record_product_trace(
        actor_type="user",
        actor_id=sent_by or "operator",
        event_type="email_sent",
        surface="lead-gen",
        entity_type="lead_gen_batch_item",
        entity_id=batch_item_id,
        input_json={
            "subject": draft_subject,
            "body": draft_body,
        },
        output_json={
            "message_id": msg_id,
            "sent_at": sent_at.isoformat(),
            "sent_to": contact.email,
            "brief_version": brief_version,
        },
        context_json={
            "batch_id": item.batch_id,
            "contact_id": item.contact_id,
            "contact_email": contact.email,
            "firm_name": item.firm_name,
            "composer_experiment_key": composer_experiment_key,
            "composer_variant_key": composer_variant_key,
            "skill_path": skill_path,
            "skill_sha256": skill_sha256,
            "brief_version": brief_version,
        },
    )

    return {
        "batch_item_id": batch_item_id,
        "sequence_id": seq.id,
        "sent_to": contact.email,
        "sent_subject": draft_subject,
        "sent_message_id": msg_id,
        "sent_at": sent_at.isoformat(),
        "step": step_num,
        "composer_experiment_key": composer_experiment_key,
        "composer_variant_key": composer_variant_key,
        "brief_version": brief_version,
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


def _item_to_dict(item: LeadGenBatchItemRow, linkedin_url: str | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "batch_id": item.batch_id,
        "contact_id": item.contact_id,
        "pif_id": item.pif_id,
        "firm_name": item.firm_name,
        "contact_name": item.contact_name,
        "contact_email": item.contact_email,
        "contact_title": item.contact_title,
        "linkedin_url": linkedin_url,
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
        "dedupe_key": obs.dedupe_key,
        "raw_event": obs.raw_event_json or {},
        "classified_outcome": obs.classified_outcome,
        "confidence": obs.confidence,
        "next_action": obs.next_action,
        "llm_reasoning": obs.llm_reasoning,
        "llm_model": obs.llm_model,
        "created_at": obs.created_at.isoformat() if obs.created_at else None,
    }


async def record_observation(
    event_type: str,
    raw_event: dict[str, Any],
    *,
    contact_id: str | None = None,
    batch_id: str | None = None,
    batch_item_id: str | None = None,
    classification: Any | None = None,
) -> dict[str, Any]:
    """Store one deduped lead-gen observation.

    Deterministic event callers pass a deterministic classification. Reply
    ingestion passes the existing LLM classifier result.
    """
    clean_event_type = str(event_type or "").strip()
    if not clean_event_type:
        raise ValueError("event_type_required")
    event = raw_event if isinstance(raw_event, dict) else {"value": raw_event}
    dedupe_key = _observation_dedupe_key(clean_event_type, event)
    classified = _normalize_observation_classification(clean_event_type, classification)
    lookup_batch_id = batch_id
    lookup_batch_item_id = batch_item_id
    lookup_contact_id = contact_id
    pif_id = str(event.get("pif_id") or "").strip() or None

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(LeadGenObservationRow).where(
                LeadGenObservationRow.event_type == clean_event_type,
                LeadGenObservationRow.dedupe_key == dedupe_key,
            )
        )).scalar_one_or_none()
        if existing:
            result = _observation_to_dict(existing)
            result["existing"] = True
            return result

        item = None
        if lookup_batch_item_id:
            item = await session.get(LeadGenBatchItemRow, lookup_batch_item_id)
        elif lookup_batch_id and lookup_contact_id:
            item = (await session.execute(
                select(LeadGenBatchItemRow).where(
                    LeadGenBatchItemRow.batch_id == lookup_batch_id,
                    LeadGenBatchItemRow.contact_id == lookup_contact_id,
                )
            )).scalar_one_or_none()
        elif lookup_contact_id:
            item = (await session.execute(
                select(LeadGenBatchItemRow)
                .where(LeadGenBatchItemRow.contact_id == lookup_contact_id)
                .order_by(desc(LeadGenBatchItemRow.updated_at))
                .limit(1)
            )).scalar_one_or_none()

        contact = None
        if item:
            lookup_batch_id = lookup_batch_id or item.batch_id
            lookup_batch_item_id = lookup_batch_item_id or item.id
            lookup_contact_id = lookup_contact_id or item.contact_id
            pif_id = item.pif_id
        if lookup_contact_id:
            contact = await session.get(FirmContactRow, lookup_contact_id)
            if contact and not pif_id:
                pif_id = contact.pif_id

        obs = LeadGenObservationRow(
            id=_new_id(),
            batch_id=lookup_batch_id,
            batch_item_id=lookup_batch_item_id,
            contact_id=lookup_contact_id,
            pif_id=pif_id,
            event_type=clean_event_type,
            dedupe_key=dedupe_key,
            raw_event_json=event,
            classified_outcome=classified.get("outcome"),
            confidence=classified.get("confidence"),
            next_action=classified.get("next_action"),
            llm_reasoning=classified.get("reasoning"),
            llm_model=classified.get("model"),
            llm_raw_response=classified.get("raw_response") or "",
        )
        session.add(obs)
        if item and classified.get("outcome") in {
            "booked_qualified_conversation",
            "positive_reply",
            "referral",
            "forwarded_internally",
            "owner_introduction",
            "wrong_person",
            "not_interested",
            "do_not_contact",
            "bounce",
            "opened_or_clicked",
            "needs_human_review",
        }:
            item.outcome = classified.get("outcome")
            item.outcome_confidence = classified.get("confidence")
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = (await session.execute(
                select(LeadGenObservationRow).where(
                    LeadGenObservationRow.event_type == clean_event_type,
                    LeadGenObservationRow.dedupe_key == dedupe_key,
                )
            )).scalar_one()
            result = _observation_to_dict(existing)
            result["existing"] = True
            return result
        await session.refresh(obs)
        result = _observation_to_dict(obs)
        result["existing"] = False
        return result


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
        # Join firm_contacts to surface the resolved LinkedIn URL per item so the
        # batch-detail ("open batch") view can render a clickable link.
        contact_ids = [item.contact_id for item in items if item.contact_id]
        linkedin_by_contact: dict[str, str] = {}
        if contact_ids:
            rows = (await session.execute(
                select(FirmContactRow.id, FirmContactRow.linkedin_url)
                .where(FirmContactRow.id.in_(contact_ids))
            )).all()
            linkedin_by_contact = {
                cid: url for cid, url in rows if url
            }
        observations: list[LeadGenObservationRow] = []
        if include_observations:
            observations = (await session.execute(
                select(LeadGenObservationRow)
                .where(LeadGenObservationRow.batch_id == batch_id)
                .order_by(desc(LeadGenObservationRow.created_at))
            )).scalars().all()
    return {
        "batch": _batch_to_dict(batch),
        "items": [
            _item_to_dict(item, linkedin_by_contact.get(item.contact_id))
            for item in items
        ],
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
                        notification = await session.get(
                            OperatorNotificationRow,
                            int(result["notification_id"]),
                        )
                        if notification:
                            context = dict(notification.context_json or {})
                            context["batch_id"] = batch_id
                            context["batch_item_id"] = item.id
                            notification.context_json = context
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

    return await record_observation(
        event_type,
        raw_event,
        batch_id=batch_id or (item.batch_id if item else None),
        batch_item_id=batch_item_id or (item.id if item else None),
        contact_id=lookup_contact_id,
        classification=classification,
    )


def parse_observation_since(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    now = _utcnow()
    unit = raw[-1].lower()
    amount = raw[:-1]
    try:
        if unit == "d":
            return now - timedelta(days=float(amount))
        if unit == "h":
            return now - timedelta(hours=float(amount))
        if unit == "m":
            return now - timedelta(minutes=float(amount))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("invalid_since") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def list_observations(
    *,
    since: datetime | None = None,
    event_type: str | None = None,
    contact_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 1000))
    async with AsyncSessionLocal() as session:
        stmt = select(LeadGenObservationRow)
        if since:
            stmt = stmt.where(LeadGenObservationRow.created_at >= since)
        if event_type:
            stmt = stmt.where(LeadGenObservationRow.event_type == event_type)
        if contact_id:
            stmt = stmt.where(LeadGenObservationRow.contact_id == contact_id)
        rows = (await session.execute(
            stmt.order_by(desc(LeadGenObservationRow.created_at)).limit(safe_limit)
        )).scalars().all()
    return [_observation_to_dict(row) for row in rows]


async def summarize_observations(
    *,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        count_expr = func.count(LeadGenObservationRow.id).label("count")
        stmt = select(
            LeadGenObservationRow.event_type,
            count_expr,
        )
        if since:
            stmt = stmt.where(LeadGenObservationRow.created_at >= since)
        rows = (await session.execute(
            stmt.group_by(LeadGenObservationRow.event_type)
            .order_by(count_expr.desc(), LeadGenObservationRow.event_type.asc())
        )).all()
    return [{"event_type": row[0], "count": int(row[1] or 0)} for row in rows]


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
        # champion-dynamic outcomes: a staff contact carried us upstairs
        "forwarded_internally",
        "owner_introduction",
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
