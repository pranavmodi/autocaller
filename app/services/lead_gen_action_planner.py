"""Daily lead-generation action planner.

The planner spends a fixed daily email budget across two buckets:
- existing conversations that need action now;
- new first-touch conversations for untouched eligible firms.

It does not send email. It produces explainable action candidates that the
batch approval flow can queue or surface for operator review.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from app.db import AsyncSessionLocal
from app.db.models import (
    EmailSequenceRow,
    FirmContactRow,
    LeadGenBatchItemRow,
    OperatorNotificationRow,
)
from app.services.firm_contacts_service import resolve_firm_name
from app.services.contact_selection import is_target_lead_persona
from app.services.sequence_recommendations import recommend_sequence_contacts
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY, normalize_template_key


CONTINUATION_ACTIONS = {
    "reply_to_inbound",
    "approve_existing_draft",
    "follow_up",
}
QUEUEABLE_ACTIONS = {
    "first_touch",
    "follow_up",
}


@dataclass
class LeadGenActionCandidate:
    action_type: str
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
    template_key: str
    source_type: str
    source_id: str
    sequence_id: str | None = None
    notification_id: int | None = None
    priority_bucket: str = "new"
    signals: list[str] | None = None
    next_operator_action: str = "review_and_approve"
    score_breakdown: dict[str, int] | None = None
    selection_features: dict[str, Any] | None = None
    suppressions: list[str] | None = None
    selection_policy_version: str | None = None

    def to_batch_reason(self, *, policy_version: str) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "priority_bucket": self.priority_bucket,
            "reason": self.reason,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "sequence_id": self.sequence_id,
            "notification_id": self.notification_id,
            "signals": self.signals or [],
            "next_operator_action": self.next_operator_action,
            "contact_source": self.contact_source,
            "policy_version": policy_version,
            "selection_policy_version": self.selection_policy_version or policy_version,
            "score_breakdown": self.score_breakdown or {},
            "selection_features": self.selection_features or {},
            "suppressions": self.suppressions or [],
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _contact_payload(contact: FirmContactRow | None) -> dict[str, str]:
    if not contact:
        return {}
    return {
        "contact_id": contact.id,
        "pif_id": contact.pif_id,
        "contact_name": contact.full_name or "",
        "contact_email": contact.email or "",
        "contact_title": contact.title or "",
        "contact_source": contact.source or "",
    }


def _notification_action_type(row: OperatorNotificationRow) -> tuple[str, int, str]:
    suggested = row.suggested_action_json or {}
    outcome = _clean(suggested.get("outcome")).lower()
    if row.notification_type == "lead_email_reply":
        if outcome in {"positive_reply", "booked_qualified_conversation", "referral"}:
            return "reply_to_inbound", 980, "active_conversation"
        if outcome in {"do_not_contact", "not_interested", "bounce"}:
            return "reply_to_inbound", 920, "active_conversation"
        return "reply_to_inbound", 940, "active_conversation"
    return "approve_existing_draft", 860, "active_conversation"


async def _candidates_from_pending_notifications(
    *,
    session,
    template_key: str,
    limit: int,
) -> list[LeadGenActionCandidate]:
    rows = list((await session.execute(
        select(OperatorNotificationRow)
        .where(
            OperatorNotificationRow.status == "pending",
            OperatorNotificationRow.acknowledged_at.is_(None),
            OperatorNotificationRow.notification_type.in_([
                "lead_email_reply",
                "lead_sequence_email_approval",
            ]),
        )
        .order_by(OperatorNotificationRow.created_at.asc())
        .limit(max(limit * 2, limit + 10))
    )).scalars().all())

    out: list[LeadGenActionCandidate] = []
    for row in rows:
        context = row.context_json or {}
        contact: FirmContactRow | None = None
        item: LeadGenBatchItemRow | None = None
        contact_id = _clean(context.get("contact_id"))
        batch_item_id = _clean(context.get("batch_item_id"))
        if contact_id:
            contact = await session.get(FirmContactRow, contact_id)
        if batch_item_id:
            item = await session.get(LeadGenBatchItemRow, batch_item_id)
            if item and not contact:
                contact = await session.get(FirmContactRow, item.contact_id)
        payload = _contact_payload(contact)
        if not contact or not payload.get("contact_email"):
            continue
        if not is_target_lead_persona(contact.title, contact.source):
            continue

        action_type, base_score, bucket = _notification_action_type(row)
        suggested = row.suggested_action_json or {}
        context_template_key = _clean(context.get("template_key"))
        if context_template_key and context_template_key != DEFAULT_TEMPLATE_KEY:
            continue
        firm_name = _clean(context.get("firm_name")) or (item.firm_name if item else "")
        reason = _clean(suggested.get("reasoning")) or row.title
        out.append(LeadGenActionCandidate(
            action_type=action_type,
            contact_id=contact.id,
            pif_id=contact.pif_id,
            firm_name=firm_name or "Unknown firm",
            contact_name=contact.full_name or _clean(context.get("contact_name")),
            contact_email=contact.email or _clean(context.get("contact_email")),
            contact_title=contact.title or _clean(context.get("contact_title")),
            contact_source=contact.source or "",
            persona="active conversation",
            score=base_score,
            reason=reason,
            template_key=template_key,
            source_type=row.source_type,
            source_id=row.source_id,
            sequence_id=_clean(context.get("sequence_id")) or None,
            notification_id=row.id,
            priority_bucket=bucket,
            signals=[
                row.notification_type,
                _clean(suggested.get("outcome")) or "pending_operator_notification",
            ],
            next_operator_action=(
                "open_operator_action_center_and_send_reply"
                if action_type == "reply_to_inbound"
                else "open_operator_action_center_and_approve_draft"
            ),
        ))
    return out


async def _candidates_from_due_sequences(
    *,
    session,
    template_key: str,
    limit: int,
) -> list[LeadGenActionCandidate]:
    rows = list((await session.execute(
        select(EmailSequenceRow)
        .where(
            EmailSequenceRow.template_key == template_key,
            EmailSequenceRow.status == "active",
            EmailSequenceRow.next_step_due_at.isnot(None),
            EmailSequenceRow.next_step_due_at <= _utcnow(),
        )
        .order_by(EmailSequenceRow.next_step_due_at.asc())
        .limit(max(limit, 10))
    )).scalars().all())
    out: list[LeadGenActionCandidate] = []
    for seq in rows:
        contact = await session.get(FirmContactRow, seq.contact_id)
        if not contact or not contact.email:
            continue
        if not is_target_lead_persona(contact.title, contact.source):
            continue
        firm_name = await resolve_firm_name(contact.pif_id)
        next_step = seq.current_step + 1
        out.append(LeadGenActionCandidate(
            action_type="follow_up",
            contact_id=contact.id,
            pif_id=contact.pif_id,
            firm_name=firm_name or "Unknown firm",
            contact_name=contact.full_name or "",
            contact_email=contact.email or "",
            contact_title=contact.title or "",
            contact_source=contact.source or "",
            persona="active no reply",
            score=max(700 - (next_step * 15), 620),
            reason=(
                f"Existing outreach run is due for step {next_step} of "
                f"{seq.steps_total}; no blocking reply is recorded on the run."
            ),
            template_key=template_key,
            source_type="email_sequence",
            source_id=seq.id,
            sequence_id=seq.id,
            priority_bucket="active_conversation",
            signals=["due_follow_up", f"step_{next_step}"],
            next_operator_action="queue_due_follow_up_for_composer_approval",
        ))
    return out


async def plan_daily_lead_gen_actions(
    *,
    template_key: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Return a ranked daily action plan within the fixed send budget."""
    template_key = normalize_template_key(template_key)
    limit = max(1, min(limit, 200))
    candidates: list[LeadGenActionCandidate] = []

    async with AsyncSessionLocal() as session:
        candidates.extend(await _candidates_from_pending_notifications(
            session=session,
            template_key=template_key,
            limit=limit,
        ))
        candidates.extend(await _candidates_from_due_sequences(
            session=session,
            template_key=template_key,
            limit=limit,
        ))

    used_contacts: set[str] = set()
    used_emails: set[str] = set()
    ranked: list[LeadGenActionCandidate] = []
    for candidate in sorted(candidates, key=lambda c: (-c.score, c.firm_name.lower())):
        email_key = candidate.contact_email.strip().lower()
        if candidate.contact_id in used_contacts or email_key in used_emails:
            continue
        used_contacts.add(candidate.contact_id)
        used_emails.add(email_key)
        ranked.append(candidate)
        if len(ranked) >= limit:
            break

    remaining = limit - len(ranked)
    new_counts: dict[str, Any] = {}
    if remaining > 0:
        rec_data = await recommend_sequence_contacts(
            template_key=template_key,
            limit=max(remaining * 2, remaining),
        )
        new_counts = rec_data.get("counts") or {}
        for rec in rec_data.get("recommended") or []:
            email_key = _clean(rec.get("contact_email")).lower()
            contact_id = _clean(rec.get("contact_id"))
            if not email_key or contact_id in used_contacts or email_key in used_emails:
                continue
            ranked.append(LeadGenActionCandidate(
                action_type="first_touch",
                contact_id=contact_id,
                pif_id=_clean(rec.get("pif_id")),
                firm_name=_clean(rec.get("firm_name")),
                contact_name=_clean(rec.get("contact_name")),
                contact_email=_clean(rec.get("contact_email")),
                contact_title=_clean(rec.get("contact_title")),
                contact_source=_clean(rec.get("contact_source")),
                persona=_clean(rec.get("persona")),
                score=int(rec.get("score") or 0),
                reason=_clean(rec.get("reason")),
                template_key=template_key,
                source_type="new_recommendation",
                source_id=contact_id,
                priority_bucket="new_conversation",
                signals=["eligible_new_contact", *list(rec.get("selection_signals") or [])],
                next_operator_action="approve_batch_to_start_outreach_run",
                score_breakdown=rec.get("score_breakdown") or {},
                selection_features=rec.get("selection_features") or {},
                suppressions=rec.get("suppressions") or [],
                selection_policy_version=_clean(rec.get("policy_version")) or None,
            ))
            used_contacts.add(contact_id)
            used_emails.add(email_key)
            if len(ranked) >= limit:
                break

    action_counts: dict[str, int] = {}
    bucket_counts: dict[str, int] = {}
    for candidate in ranked:
        action_counts[candidate.action_type] = action_counts.get(candidate.action_type, 0) + 1
        bucket_counts[candidate.priority_bucket] = bucket_counts.get(candidate.priority_bucket, 0) + 1

    return {
        "template_key": template_key,
        "limit": limit,
        "recommended": [candidate.__dict__ for candidate in ranked],
        "counts": {
            "budget": limit,
            "returned": len(ranked),
            "active_conversation_actions": sum(
                count for action, count in action_counts.items()
                if action in CONTINUATION_ACTIONS
            ),
            "new_conversation_actions": action_counts.get("first_touch", 0),
            "action_counts": action_counts,
            "priority_bucket_counts": bucket_counts,
            "new_recommendation_counts": new_counts,
        },
    }
