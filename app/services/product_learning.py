"""Learning layer built on product traces and existing outcome tables."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.db.models import (
    CodexTaskPacketRow,
    ConsultBookingRow,
    EmailLogRow,
    EvalCaseRow,
    ImprovementFindingRow,
    InboundEmailRow,
    LeadGenObservationRow,
    LinkEventRow,
    OutreachCampaignRow,
    OutreachSendRow,
    ProductTraceRow,
)
from app.services.product_traces import create_product_trace, trace_to_dict


TASK_PACKET_ROOT = Path("data/codex_tasks")
MEASUREMENT_WINDOWS = (1, 7, 30, 90)


@dataclass
class FindingDraft:
    finding_key: str
    workflow: str
    finding_type: str
    summary: str
    details: str
    evidence_trace_ids: list[str]
    evidence_json: dict[str, Any]
    severity: str
    confidence: int
    suggested_change_json: dict[str, Any]


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _excerpt(value: str | None, limit: int = 600) -> str:
    return " ".join((value or "").split())[:limit]


def _contains_precise(value: str | None) -> bool:
    return bool(re.search(r"\bprecise(?:\s+imaging)?\b", value or "", re.IGNORECASE))


def _unique_traces(rows: list[ProductTraceRow]) -> list[ProductTraceRow]:
    seen: set[tuple[str | None, str | None, str]] = set()
    unique = []
    for row in rows:
        key = (row.entity_type, row.entity_id, row.event_type)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _trace_ids(rows: list[ProductTraceRow], limit: int = 20) -> list[str]:
    return list(dict.fromkeys(row.trace_id for row in rows if row.trace_id))[:limit]


def finding_to_dict(row: ImprovementFindingRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "finding_key": row.finding_key,
        "workflow": row.workflow,
        "finding_type": row.finding_type,
        "summary": row.summary,
        "details": row.details,
        "evidence_trace_ids": row.evidence_trace_ids or [],
        "evidence": row.evidence_json or {},
        "severity": row.severity,
        "confidence": row.confidence,
        "suggested_change": row.suggested_change_json or {},
        "status": row.status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": _row_time(row.reviewed_at),
        "created_at": _row_time(row.created_at),
        "updated_at": _row_time(row.updated_at),
    }


def eval_case_to_dict(row: EvalCaseRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "finding_id": row.finding_id,
        "workflow": row.workflow,
        "name": row.name,
        "input": row.input_json or {},
        "expected": row.expected_json or {},
        "status": row.status,
        "created_at": _row_time(row.created_at),
    }


def task_packet_to_dict(row: CodexTaskPacketRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "finding_id": row.finding_id,
        "eval_case_id": row.eval_case_id,
        "title": row.title,
        "status": row.status,
        "packet_path": row.packet_path,
        "task_markdown": row.task_markdown,
        "traces": row.traces_json or [],
        "eval_cases": row.eval_cases_json or [],
        "relevant_files": row.relevant_files_json or [],
        "validation_commands": row.validation_commands_json or [],
        "created_at": _row_time(row.created_at),
        "exported_at": _row_time(row.exported_at),
    }


def link_event_trace_kwargs(
    row: LinkEventRow,
    *,
    send: OutreachSendRow | None = None,
    campaign: OutreachCampaignRow | None = None,
) -> dict[str, Any]:
    observed_link = row.url or ("open_pixel" if row.kind == "open" else None)
    return {
        "actor_type": "external",
        "event_type": "link_event_observed",
        "surface": "outreach",
        "entity_type": "link_event",
        "entity_id": str(row.id),
        "input_json": {
            "kind": row.kind,
            "url": row.url,
            "observed_link": observed_link,
            "ip": row.ip,
            "user_agent": _excerpt(row.user_agent, 300),
            "referer": row.referer,
            "ts": _row_time(row.ts),
        },
        "context_json": {
            "send_id": row.send_id,
            "campaign_id": send.campaign_id if send else None,
            "contact_id": send.contact_id if send else None,
            "pif_id": send.pif_id if send else None,
            "recipient_email": send.recipient_email if send else None,
            "recipient_name": send.recipient_name if send else None,
            "recipient_first_name": send.recipient_first_name if send else None,
            "recipient_title": send.recipient_title if send else None,
            "firm_name": send.firm_name if send else None,
            "send_status": send.status if send else None,
            "send_sent_at": _row_time(send.sent_at) if send else None,
            "send_message_id": send.message_id if send else None,
            "campaign_name": campaign.name if campaign else None,
            "campaign_post_url": campaign.post_url if campaign else None,
            "campaign_post_title": campaign.post_title if campaign else None,
        },
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


async def get_learning_measurements() -> dict[str, Any]:
    """Calculate post-change learning metrics for common dashboard windows."""
    now = _now()
    windows = []
    async with AsyncSessionLocal() as session:
        for days in MEASUREMENT_WINDOWS:
            since = now - timedelta(days=days)

            generated_entities = (await session.execute(
                select(ProductTraceRow.entity_id)
                .where(
                    ProductTraceRow.created_at >= since,
                    ProductTraceRow.event_type.in_([
                        "email_draft_generated",
                        "email_send_requested",
                        "email_sent",
                    ]),
                    ProductTraceRow.entity_type == "operator_notification",
                    ProductTraceRow.entity_id.isnot(None),
                )
                .distinct()
            )).scalars().all()
            edited_entities = (await session.execute(
                select(ProductTraceRow.entity_id)
                .where(
                    ProductTraceRow.created_at >= since,
                    ProductTraceRow.event_type == "email_draft_edited",
                    ProductTraceRow.entity_type == "operator_notification",
                    ProductTraceRow.entity_id.isnot(None),
                )
                .distinct()
            )).scalars().all()
            generated_set = set(generated_entities)
            edited_set = set(edited_entities)
            reviewed_drafts = len(generated_set | edited_set)
            edited_drafts = len(edited_set)

            sent_emails = (await session.execute(
                select(func.count())
                .select_from(EmailLogRow)
                .where(EmailLogRow.sent_at >= since)
            )).scalar_one()
            bounced_emails = (await session.execute(
                select(func.count())
                .select_from(EmailLogRow)
                .where(
                    EmailLogRow.sent_at >= since,
                    func.lower(EmailLogRow.status) == "bounced",
                )
            )).scalar_one()
            failed_emails = (await session.execute(
                select(func.count())
                .select_from(EmailLogRow)
                .where(
                    EmailLogRow.sent_at >= since,
                    func.lower(EmailLogRow.status) == "failed",
                )
            )).scalar_one()

            matched_replies = (await session.execute(
                select(func.count())
                .select_from(InboundEmailRow)
                .where(
                    InboundEmailRow.ingested_at >= since,
                    or_(
                        InboundEmailRow.matched_contact_id.isnot(None),
                        InboundEmailRow.matched_batch_item_id.isnot(None),
                        InboundEmailRow.matched_sequence_id.isnot(None),
                    ),
                )
            )).scalar_one()
            all_inbound = (await session.execute(
                select(func.count())
                .select_from(InboundEmailRow)
                .where(InboundEmailRow.ingested_at >= since)
            )).scalar_one()

            consult_bookings = (await session.execute(
                select(func.count())
                .select_from(ConsultBookingRow)
                .where(
                    ConsultBookingRow.created_at >= since,
                    ConsultBookingRow.status == "booked",
                )
            )).scalar_one()
            qualified_observations = (await session.execute(
                select(func.count())
                .select_from(LeadGenObservationRow)
                .where(
                    LeadGenObservationRow.created_at >= since,
                    LeadGenObservationRow.classified_outcome == "booked_qualified_conversation",
                )
            )).scalar_one()

            windows.append({
                "days": days,
                "since": since.isoformat(),
                "until": now.isoformat(),
                "manual_edit_rate": _rate(edited_drafts, reviewed_drafts),
                "edited_draft_count": edited_drafts,
                "reviewed_draft_count": reviewed_drafts,
                "bounce_rate": _rate(bounced_emails, sent_emails),
                "bounced_email_count": bounced_emails,
                "failed_email_count": failed_emails,
                "sent_email_count": sent_emails,
                "reply_rate": _rate(matched_replies, sent_emails),
                "matched_reply_count": matched_replies,
                "all_inbound_email_count": all_inbound,
                "booked_qualified_conversation_count": consult_bookings + qualified_observations,
                "consult_booking_count": consult_bookings,
                "qualified_observation_count": qualified_observations,
            })
    return {
        "generated_at": now.isoformat(),
        "windows": windows,
        "definitions": {
            "manual_edit_rate": "email_draft_edited notification count divided by reviewed email draft notification count",
            "bounce_rate": "email_logs rows with status=bounced divided by all email_logs rows sent in the window",
            "reply_rate": "matched inbound Zoho emails divided by all email_logs rows sent in the window",
            "booked_qualified_conversation_count": "consult bookings plus lead_gen_observations classified as booked_qualified_conversation",
        },
    }


async def _upsert_finding(session: AsyncSession, draft: FindingDraft) -> ImprovementFindingRow:
    existing = (await session.execute(
        select(ImprovementFindingRow).where(
            ImprovementFindingRow.finding_key == draft.finding_key,
        )
    )).scalar_one_or_none()
    if existing:
        existing.summary = draft.summary
        existing.details = draft.details
        existing.evidence_trace_ids = draft.evidence_trace_ids
        existing.evidence_json = draft.evidence_json
        existing.severity = draft.severity
        existing.confidence = draft.confidence
        existing.suggested_change_json = draft.suggested_change_json
        existing.updated_at = _now()
        return existing

    row = ImprovementFindingRow(
        id=_id("find"),
        finding_key=draft.finding_key,
        workflow=draft.workflow,
        finding_type=draft.finding_type,
        summary=draft.summary,
        details=draft.details,
        evidence_trace_ids=draft.evidence_trace_ids,
        evidence_json=draft.evidence_json,
        severity=draft.severity,
        confidence=draft.confidence,
        suggested_change_json=draft.suggested_change_json,
        status="proposed",
    )
    session.add(row)
    return row


async def list_findings(
    *,
    status: str | None = None,
    workflow: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 250))
    async with AsyncSessionLocal() as session:
        stmt = select(ImprovementFindingRow).order_by(desc(ImprovementFindingRow.updated_at)).limit(limit)
        if status and status != "all":
            stmt = stmt.where(ImprovementFindingRow.status == status)
        if workflow and workflow != "all":
            stmt = stmt.where(ImprovementFindingRow.workflow == workflow)
        rows = (await session.execute(stmt)).scalars().all()
    return [finding_to_dict(row) for row in rows]


async def review_finding(
    finding_id: str,
    *,
    status: str,
    reviewed_by: str = "operator",
) -> dict[str, Any] | None:
    if status not in {"accepted", "rejected", "implemented", "proposed"}:
        raise ValueError("invalid finding status")
    async with AsyncSessionLocal() as session:
        row = await session.get(ImprovementFindingRow, finding_id)
        if not row:
            return None
        row.status = status
        row.reviewed_by = reviewed_by
        row.reviewed_at = _now()
        row.updated_at = _now()
        await session.commit()
        await session.refresh(row)
        return finding_to_dict(row)


async def _trace_exists(
    session: AsyncSession,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
) -> bool:
    row = (await session.execute(
        select(ProductTraceRow.id)
        .where(
            ProductTraceRow.event_type == event_type,
            ProductTraceRow.entity_type == entity_type,
            ProductTraceRow.entity_id == entity_id,
        )
        .limit(1)
    )).first()
    return row is not None


async def _find_trace(
    session: AsyncSession,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
) -> ProductTraceRow | None:
    return (await session.execute(
        select(ProductTraceRow)
        .where(
            ProductTraceRow.event_type == event_type,
            ProductTraceRow.entity_type == entity_type,
            ProductTraceRow.entity_id == entity_id,
        )
        .order_by(desc(ProductTraceRow.created_at))
        .limit(1)
    )).scalar_one_or_none()


async def sync_outcome_traces(*, limit: int = 100) -> dict[str, Any]:
    """Backfill trace rows for already-existing outcome tables.

    This is idempotent by event type + entity type + entity id.
    """
    limit = max(1, min(limit, 500))
    created = 0
    async with AsyncSessionLocal() as session:
        email_rows = (await session.execute(
            select(EmailLogRow).order_by(desc(EmailLogRow.sent_at)).limit(limit)
        )).scalars().all()
        for row in email_rows:
            if await _trace_exists(
                session,
                event_type="email_transport_result",
                entity_type="email_log",
                entity_id=row.id,
            ):
                continue
            await create_product_trace(
                session,
                actor_type="system",
                event_type="email_transport_result",
                surface="email",
                entity_type="email_log",
                entity_id=row.id,
                input_json={
                    "recipient_email": row.recipient_email,
                    "recipient_name": row.recipient_name,
                    "subject": row.subject,
                    "message_type": row.message_type,
                    "transport": row.transport,
                },
                output_json={
                    "status": row.status,
                    "message_id": row.message_id,
                    "error": row.error,
                    "sent_at": _row_time(row.sent_at),
                },
                context_json={"pif_id": row.pif_id, "call_id": row.call_id},
            )
            created += 1

        inbound_rows = (await session.execute(
            select(InboundEmailRow).order_by(desc(InboundEmailRow.ingested_at)).limit(limit)
        )).scalars().all()
        for row in inbound_rows:
            if await _trace_exists(
                session,
                event_type="inbound_email_received",
                entity_type="inbound_email",
                entity_id=row.id,
            ):
                continue
            await create_product_trace(
                session,
                actor_type="external",
                event_type="inbound_email_received",
                surface="inbound-email",
                entity_type="inbound_email",
                entity_id=row.id,
                input_json={
                    "from_email": row.from_email,
                    "from_name": row.from_name,
                    "subject": row.subject,
                    "excerpt": _excerpt(row.text_excerpt or row.body_text),
                    "received_at": _row_time(row.received_at),
                },
                output_json={"classification_status": row.classification_status},
                context_json={
                    "matched_contact_id": row.matched_contact_id,
                    "matched_pif_id": row.matched_pif_id,
                    "matched_batch_item_id": row.matched_batch_item_id,
                    "matched_sequence_id": row.matched_sequence_id,
                },
            )
            created += 1

        observation_rows = (await session.execute(
            select(LeadGenObservationRow)
            .order_by(desc(LeadGenObservationRow.created_at))
            .limit(limit)
        )).scalars().all()
        for row in observation_rows:
            if await _trace_exists(
                session,
                event_type="lead_gen_observation_received",
                entity_type="lead_gen_observation",
                entity_id=row.id,
            ):
                continue
            await create_product_trace(
                session,
                actor_type="system",
                event_type="lead_gen_observation_received",
                surface="lead-gen",
                entity_type="lead_gen_observation",
                entity_id=row.id,
                input_json=row.raw_event_json or {},
                output_json={
                    "classified_outcome": row.classified_outcome,
                    "confidence": row.confidence,
                    "next_action": row.next_action,
                    "llm_reasoning": _excerpt(row.llm_reasoning, 800),
                },
                context_json={
                    "batch_id": row.batch_id,
                    "batch_item_id": row.batch_item_id,
                    "contact_id": row.contact_id,
                    "pif_id": row.pif_id,
                    "event_type": row.event_type,
                },
            )
            created += 1

        consult_rows = (await session.execute(
            select(ConsultBookingRow).order_by(desc(ConsultBookingRow.created_at)).limit(limit)
        )).scalars().all()
        for row in consult_rows:
            entity_id = str(row.id)
            if await _trace_exists(
                session,
                event_type="consult_booked",
                entity_type="consult_booking",
                entity_id=entity_id,
            ):
                continue
            await create_product_trace(
                session,
                actor_type="external",
                event_type="consult_booked",
                surface="consults",
                entity_type="consult_booking",
                entity_id=entity_id,
                input_json={
                    "name": row.name,
                    "email": row.email,
                    "firm_name": row.firm_name,
                    "notes": _excerpt(row.notes, 800),
                    "slot_start": _row_time(row.slot_start),
                },
                output_json={"status": row.status},
            )
            created += 1

        link_rows = (await session.execute(
            select(LinkEventRow, OutreachSendRow, OutreachCampaignRow)
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .join(OutreachCampaignRow, OutreachSendRow.campaign_id == OutreachCampaignRow.id)
            .order_by(desc(LinkEventRow.ts))
            .limit(limit)
        )).all()
        for row, send, campaign in link_rows:
            entity_id = str(row.id)
            existing_trace = await _find_trace(
                session,
                event_type="link_event_observed",
                entity_type="link_event",
                entity_id=entity_id,
            )
            if existing_trace:
                has_recipient_context = bool((existing_trace.context_json or {}).get("recipient_email"))
                already_enriched = await _trace_exists(
                    session,
                    event_type="link_event_context_enriched",
                    entity_type="link_event",
                    entity_id=entity_id,
                )
                if not has_recipient_context and not already_enriched:
                    kwargs = link_event_trace_kwargs(row, send=send, campaign=campaign)
                    await create_product_trace(
                        session,
                        **{
                            **kwargs,
                            "event_type": "link_event_context_enriched",
                            "parent_trace_id": existing_trace.trace_id,
                        },
                    )
                    created += 1
                continue
            await create_product_trace(session, **link_event_trace_kwargs(row, send=send, campaign=campaign))
            created += 1

        await session.commit()
    return {"created_count": created, "limit": limit}


async def analyze_recent_activity(*, limit: int = 500) -> dict[str, Any]:
    """Create/update deterministic findings from recent traces and outcomes."""
    await sync_outcome_traces(limit=min(limit, 200))
    limit = max(1, min(limit, 1000))
    drafts: list[FindingDraft] = []
    async with AsyncSessionLocal() as session:
        traces = (await session.execute(
            select(ProductTraceRow)
            .order_by(desc(ProductTraceRow.created_at))
            .limit(limit)
        )).scalars().all()

        edited = [row for row in traces if row.event_type == "email_draft_edited"]
        precise_edits = []
        for row in edited:
            before = (row.input_json or {}).get("body") or ""
            after = (row.output_json or {}).get("body") or ""
            if _contains_precise(after) and not _contains_precise(before):
                precise_edits.append(row)
        precise_edits = _unique_traces(precise_edits)

        if precise_edits:
            drafts.append(FindingDraft(
                finding_key="email_composer.precise_opener_added_by_user",
                workflow="lead-gen",
                finding_type="email_composer_skill",
                summary="Users are manually adding the Precise Imaging proof point to generated emails.",
                details=(
                    "Repeated draft edits added or strengthened Precise Imaging language. "
                    "This suggests the composer skill should include the proof point earlier "
                    "when the lead source is the Precise Imaging inbox or the recipient is a PI firm."
                ),
                evidence_trace_ids=_trace_ids(precise_edits),
                evidence_json={
                    "count": len(precise_edits),
                    "examples": [
                        {
                            "trace_id": row.trace_id,
                            "entity_id": row.entity_id,
                            "before_excerpt": _excerpt((row.input_json or {}).get("body"), 260),
                            "after_excerpt": _excerpt((row.output_json or {}).get("body"), 260),
                        }
                        for row in precise_edits[:5]
                    ],
                },
                severity="high" if len(precise_edits) >= 3 else "normal",
                confidence=min(95, 55 + len(precise_edits) * 10),
                suggested_change_json={
                    "target": "app/skills/possible-minds-lead-email-composer/SKILL.md",
                    "change_type": "skill_instruction",
                    "instruction": (
                        "For first-touch PI firm emails sourced from Precise Imaging inbox context, "
                        "introduce Possible Minds using the Precise autoresponder proof point near the top."
                    ),
                    "guardrails": [
                        "Do not overclaim a direct client relationship with the recipient.",
                        "Do not use em dashes.",
                        "Always include https://getpossibleminds.com/consult in the signature.",
                    ],
                },
            ))

        if len(edited) >= 3:
            drafts.append(FindingDraft(
                finding_key="actions.email_drafts_need_frequent_manual_edits",
                workflow="actions",
                finding_type="draft_quality",
                summary="Email drafts are being edited frequently before send.",
                details=(
                    "Frequent manual edits mean the system should inspect the diffs, cluster common "
                    "corrections, and update the composer skill or context builder."
                ),
                evidence_trace_ids=_trace_ids(edited),
                evidence_json={
                    "edited_count": len(edited),
                    "examples": [
                        {
                            "trace_id": row.trace_id,
                            "entity_id": row.entity_id,
                            "diff": row.diff_json or {},
                        }
                        for row in edited[:8]
                    ],
                },
                severity="normal",
                confidence=min(90, 45 + len(edited) * 5),
                suggested_change_json={
                    "target": "email_composer_and_action_ui",
                    "change_type": "diff_cluster_analysis",
                    "instruction": "Cluster repeated draft edits and convert accepted patterns into evals.",
                },
            ))

        failures = [row for row in traces if row.event_type in {"email_send_failed", "email_transport_result"}]
        failed_outputs = _unique_traces([
            row for row in failures
            if str((row.output_json or {}).get("status") or "").lower() in {"failed", "error"}
            or (row.output_json or {}).get("error")
        ])
        if failed_outputs:
            drafts.append(FindingDraft(
                finding_key="email_transport.failures_need_operational_review",
                workflow="email",
                finding_type="technical_reliability",
                summary="Some outbound email sends are failing or returning transport errors.",
                details=(
                    "Email send failures directly reduce the daily lead-gen loop. The transport, "
                    "credentials, provider API, and user-visible retry path should be reviewed."
                ),
                evidence_trace_ids=_trace_ids(failed_outputs),
                evidence_json={
                    "failure_count": len(failed_outputs),
                    "examples": [
                        {
                            "trace_id": row.trace_id,
                            "entity_type": row.entity_type,
                            "entity_id": row.entity_id,
                            "output": row.output_json or {},
                        }
                        for row in failed_outputs[:10]
                    ],
                },
                severity="high",
                confidence=min(95, 60 + len(failed_outputs) * 10),
                suggested_change_json={
                    "target": "email_transport",
                    "change_type": "reliability_fix",
                    "instruction": "Review failed transport traces and add retries, clearer UI errors, or provider-specific fixes.",
                },
            ))

        rows = []
        for draft in drafts:
            rows.append(await _upsert_finding(session, draft))
        await session.commit()
        for row in rows:
            await session.refresh(row)

    return {
        "created_or_updated_count": len(drafts),
        "findings": [finding_to_dict(row) for row in rows],
    }


def _eval_payload_for_finding(finding: ImprovementFindingRow) -> tuple[dict[str, Any], dict[str, Any]]:
    if finding.finding_key == "email_composer.precise_opener_added_by_user":
        return (
            {
                "scenario": "first_touch_precise_sourced_pi_firm",
                "firm": {"name": "Example PI Firm", "source": "Precise Imaging inbox"},
                "contact": {"title": "Founder", "email": "founder@example-law.test"},
                "conversation_state": {"is_first_touch": True, "prior_outbound_count": 0},
            },
            {
                "must_include": [
                    "Pranav from Possible Minds",
                    "automated email replies",
                    "Precise Imaging",
                    "https://getpossibleminds.com/consult",
                ],
                "must_not_include": ["—"],
                "tone": "short, diagnostic, no hard meeting ask",
            },
        )
    return (
        {
            "finding_key": finding.finding_key,
            "evidence": finding.evidence_json or {},
        },
        {
            "behavior": finding.suggested_change_json or {},
            "must_be_human_reviewed": True,
        },
    )


async def create_eval_case_for_finding(finding_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        finding = await session.get(ImprovementFindingRow, finding_id)
        if not finding:
            return None
        existing = (await session.execute(
            select(EvalCaseRow)
            .where(EvalCaseRow.finding_id == finding_id)
            .order_by(desc(EvalCaseRow.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if existing:
            return eval_case_to_dict(existing)
        input_json, expected_json = _eval_payload_for_finding(finding)
        row = EvalCaseRow(
            id=_id("eval"),
            finding_id=finding.id,
            workflow=finding.workflow,
            name=finding.summary[:240],
            input_json=input_json,
            expected_json=expected_json,
            status="active",
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return eval_case_to_dict(row)


async def list_eval_cases(*, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 250))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(EvalCaseRow).order_by(desc(EvalCaseRow.created_at)).limit(limit)
        )).scalars().all()
    return [eval_case_to_dict(row) for row in rows]


def _relevant_files_for_finding(finding: ImprovementFindingRow) -> list[str]:
    if finding.finding_type == "email_composer_skill":
        return [
            "app/skills/possible-minds-lead-email-composer/SKILL.md",
            "app/services/lead_email_composer.py",
            "tests/test_lead_email_composer.py",
        ]
    if finding.finding_type == "technical_reliability":
        return [
            "app/services/email_notification_service.py",
            "app/services/operator_notifications.py",
            "tests/test_email_sender_config.py",
            "tests/test_operator_notifications.py",
        ]
    return [
        "app/services/product_learning.py",
        "app/services/product_traces.py",
        "frontend/app/actions/page.tsx",
    ]


def _validation_commands_for_finding(finding: ImprovementFindingRow) -> list[str]:
    commands = [
        "python3 -m py_compile app/services/product_learning.py app/services/product_traces.py",
        "cd frontend && npx tsc --noEmit",
    ]
    if finding.finding_type == "email_composer_skill":
        commands.append(".venv/bin/pytest tests/test_lead_email_composer.py -q")
    elif finding.finding_type == "technical_reliability":
        commands.append(".venv/bin/pytest tests/test_email_sender_config.py tests/test_operator_notifications.py -q")
    else:
        commands.append(".venv/bin/pytest tests/test_product_traces.py -q")
    return commands


async def create_task_packet_for_finding(finding_id: str) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        finding = await session.get(ImprovementFindingRow, finding_id)
        if not finding:
            return None
        eval_case = (await session.execute(
            select(EvalCaseRow)
            .where(EvalCaseRow.finding_id == finding_id)
            .order_by(desc(EvalCaseRow.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if not eval_case:
            input_json, expected_json = _eval_payload_for_finding(finding)
            eval_case = EvalCaseRow(
                id=_id("eval"),
                finding_id=finding.id,
                workflow=finding.workflow,
                name=finding.summary[:240],
                input_json=input_json,
                expected_json=expected_json,
                status="active",
            )
            session.add(eval_case)
            await session.flush()

        traces = []
        if finding.evidence_trace_ids:
            trace_rows = (await session.execute(
                select(ProductTraceRow)
                .where(ProductTraceRow.trace_id.in_(finding.evidence_trace_ids[:25]))
                .order_by(ProductTraceRow.created_at.asc())
            )).scalars().all()
            traces = [trace_to_dict(row) for row in trace_rows]

        relevant_files = _relevant_files_for_finding(finding)
        validation_commands = _validation_commands_for_finding(finding)
        task_markdown = _task_markdown(
            finding=finding,
            eval_case=eval_case,
            relevant_files=relevant_files,
            validation_commands=validation_commands,
        )
        packet_id = _id("task")
        packet_dir = TASK_PACKET_ROOT / f"{datetime.now().strftime('%Y-%m-%d')}-{packet_id}"
        packet_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "TASK.md": task_markdown,
            "traces.json": json.dumps(traces, indent=2, sort_keys=True),
            "eval_cases.json": json.dumps([eval_case_to_dict(eval_case)], indent=2, sort_keys=True),
            "relevant_files.md": "\n".join(f"- `{path}`" for path in relevant_files) + "\n",
            "validation_commands.md": "\n".join(f"- `{cmd}`" for cmd in validation_commands) + "\n",
        }
        for name, content in files.items():
            (packet_dir / name).write_text(content, encoding="utf-8")

        row = CodexTaskPacketRow(
            id=packet_id,
            finding_id=finding.id,
            eval_case_id=eval_case.id,
            title=finding.summary[:240],
            status="exported",
            packet_path=str(packet_dir),
            task_markdown=task_markdown,
            traces_json=traces,
            eval_cases_json=[eval_case_to_dict(eval_case)],
            relevant_files_json=relevant_files,
            validation_commands_json=validation_commands,
            exported_at=_now(),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return task_packet_to_dict(row)


def _task_markdown(
    *,
    finding: ImprovementFindingRow,
    eval_case: EvalCaseRow,
    relevant_files: list[str],
    validation_commands: list[str],
) -> str:
    return f"""# Codex Task: {finding.summary}

## Problem

{finding.details or finding.summary}

## Evidence

Finding id: `{finding.id}`

Finding key: `{finding.finding_key}`

Evidence trace ids:

{chr(10).join(f"- `{trace_id}`" for trace_id in (finding.evidence_trace_ids or [])) or "- None recorded"}

Evidence JSON:

```json
{json.dumps(finding.evidence_json or {}, indent=2, sort_keys=True)}
```

## Goal

Implement the suggested change below without weakening existing guardrails.

```json
{json.dumps(finding.suggested_change_json or {}, indent=2, sort_keys=True)}
```

## Eval Case

Eval id: `{eval_case.id}`

Input:

```json
{json.dumps(eval_case.input_json or {}, indent=2, sort_keys=True)}
```

Expected:

```json
{json.dumps(eval_case.expected_json or {}, indent=2, sort_keys=True)}
```

## Relevant Files

{chr(10).join(f"- `{path}`" for path in relevant_files)}

## Validation

{chr(10).join(f"- `{cmd}`" for cmd in validation_commands)}
"""


async def list_task_packets(*, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 250))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(CodexTaskPacketRow).order_by(desc(CodexTaskPacketRow.created_at)).limit(limit)
        )).scalars().all()
    return [task_packet_to_dict(row) for row in rows]
