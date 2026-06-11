"""Horizontal lead-gen email-agent slice.

This service stitches together the existing deterministic contact selector,
lead email composer skill, lead-gen batch rows, and durable action executor.
It deliberately stops before execution: generated emails are stored as
approval-ready drafts and optional no-send action records.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmContactRow, LeadGenBatchItemRow, LeadGenBatchRow, PatientRow
from app.services.action_execution import check_action_policy, create_send_email_action
from app.services.contact_selection import classify_email_quality
from app.services.lead_email_composer import compose_lead_email
from app.services.lead_gen_cybernetic import TARGET_METRIC, ensure_default_policy, get_batch
from app.services.product_traces import safe_record_product_trace
from app.services.sequence_recommendations import recommend_sequence_contacts
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY


def _pif_patient_ids(pif_id: str) -> list[str]:
    return [f"pif-{pif_id}", f"mc-{pif_id}"] if pif_id else []


def _new_id() -> str:
    return uuid.uuid4().hex


def _source_url(label: str, url: str | None) -> dict[str, str] | None:
    value = (url or "").strip()
    if not value:
        return None
    return {"label": label, "url": value}


async def research_contact_context(
    *,
    contact: FirmContactRow,
    firm_name: str,
    selection_reason: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact evidence packet for composing and review.

    V1 intentionally uses internal evidence only. If a contact has no usable
    email, the packet records that external/web research would be required, but
    this slice will not guess or fabricate one.
    """
    patient: PatientRow | None = None
    async with AsyncSessionLocal() as session:
        if contact.pif_id:
            patient = (await session.execute(
                select(PatientRow)
                .where(PatientRow.patient_id.in_(_pif_patient_ids(contact.pif_id)))
                .order_by(PatientRow.patient_id.asc())
                .limit(1)
            )).scalar_one_or_none()

    source_urls = [
        x for x in (
            _source_url("firm_website", getattr(patient, "website", None)),
            _source_url("contact_linkedin", contact.linkedin_url),
        )
        if x
    ]
    email = (contact.email or "").strip().lower()
    email_quality = classify_email_quality(email, contact.full_name)
    needs_context_research = not source_urls or email_quality in {"generic_inbox", "role_inbox"}
    evidence_summary = [
        f"Selected from firm_contacts source={contact.source or 'unknown'}.",
        f"Role/title evidence: {contact.title or 'missing title'}.",
        f"Email evidence: {email or 'missing email'} ({email_quality}).",
    ]
    if patient and patient.website:
        evidence_summary.append(f"Firm website available in patients table: {patient.website}.")
    if contact.linkedin_url:
        evidence_summary.append(f"LinkedIn URL available on contact row: {contact.linkedin_url}.")
    if selection_reason:
        evidence_summary.append(f"Selection reason: {selection_reason.get('reason') or ''}".strip())
    remaining_uncertainty = []
    if not source_urls:
        remaining_uncertainty.append("No website or LinkedIn evidence is stored for this contact in v1.")
    if email_quality in {"generic_inbox", "role_inbox"}:
        remaining_uncertainty.append("Email is not a direct named address; use extra caution.")
    if not email:
        remaining_uncertainty.append("No usable email is stored; external research would be required before outreach.")

    return {
        "status": "internal_evidence_collected",
        "research_scope": "internal_db_v1",
        "person": contact.full_name or "",
        "role": contact.title or "",
        "firm_name": firm_name,
        "pif_id": contact.pif_id,
        "email": email,
        "email_confidence": "high" if email_quality == "direct_named_email" else "medium",
        "email_quality": email_quality,
        "source_urls": source_urls,
        "evidence_summary": evidence_summary,
        "remaining_uncertainty": remaining_uncertainty,
        "needs_context_research": needs_context_research,
    }


def _agent_sequence_stub(template_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=None,
        template_key=template_key,
        current_step=0,
        steps_total=1,
        variant="agent_slice",
        status="drafting",
    )


async def create_lead_gen_email_agent_slice(
    *,
    limit: int = 3,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    created_by: str = "master-agent",
    composer_variant_key: str | None = None,
    approve_actions: bool = False,
    policy_check_first_action: bool = False,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Select contacts, compose drafts, and create no-send durable actions.

    With ``batch_id``, skip selection and compose for that batch's pending
    items that have no agent draft yet (operator- or agent-curated batches).
    """
    safe_limit = max(1, min(int(limit), 10))
    existing_batch = bool(batch_id)
    if not existing_batch:
        policy = await ensure_default_policy()
        rec_data = await recommend_sequence_contacts(template_key=template_key, limit=safe_limit)
        batch_id = _new_id()
    if existing_batch:
        existing = await get_batch(batch_id, include_observations=False)
        if not existing or not existing.get("batch"):
            raise ValueError(f"Batch not found: {batch_id}")
        return await _compose_batch_items(
            batch_id=batch_id,
            created_by=created_by,
            composer_variant_key=composer_variant_key,
            approve_actions=approve_actions,
            policy_check_first_action=policy_check_first_action,
            template_key=template_key,
            only_undrafted_pending=True,
            limit=safe_limit,
        )
    async with AsyncSessionLocal() as session:
        batch_row = LeadGenBatchRow(
            id=batch_id,
            name=f"Lead-gen email agent slice - {safe_limit} drafts",
            target_metric=TARGET_METRIC,
            template_key=template_key,
            policy_version=policy.version,
            status="recommended",
            counts_json={
                **(rec_data.get("counts") or {}),
                "agent_slice": True,
                "requested": safe_limit,
            },
            created_by=created_by,
        )
        session.add(batch_row)
        await session.flush()
        for rec in rec_data.get("recommended") or []:
            reason_json = {
                "reason": rec.get("reason") or "",
                "contact_source": rec.get("contact_source") or "",
                "policy_version": policy.version,
                "action_type": "first_touch",
                "priority_bucket": "new_conversation",
                "source_type": "lead_gen_email_agent_slice",
                "source_id": rec.get("contact_id"),
                "signals": rec.get("selection_signals") or rec.get("signals") or [],
                "next_operator_action": "review_edit_approve_send",
                "selection_policy_version": rec.get("policy_version") or policy.version,
                "score_breakdown": rec.get("score_breakdown") or {},
                "selection_features": rec.get("selection_features") or {},
                "suppressions": rec.get("suppressions") or [],
            }
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
            ))
        await session.commit()

    return await _compose_batch_items(
        batch_id=batch_id,
        created_by=created_by,
        composer_variant_key=composer_variant_key,
        approve_actions=approve_actions,
        policy_check_first_action=policy_check_first_action,
        template_key=template_key,
        only_undrafted_pending=False,
        limit=safe_limit,
    )


async def _compose_batch_items(
    *,
    batch_id: str,
    created_by: str,
    composer_variant_key: str | None,
    approve_actions: bool,
    policy_check_first_action: bool,
    template_key: str,
    only_undrafted_pending: bool,
    limit: int,
) -> dict[str, Any]:
    """Compose drafts + create no-send actions for a batch's items."""
    batch_data = await get_batch(batch_id, include_observations=False)
    batch = batch_data["batch"]
    items = batch_data.get("items") or []
    if only_undrafted_pending:
        items = [
            i for i in items
            if i.get("approval_status") in ("pending", "approved")
            and not (i.get("reason") or {}).get("agent_draft")
        ][: max(1, limit)]
    drafts: list[dict[str, Any]] = []
    action_ids: list[str] = []
    first_policy: dict[str, Any] | None = None

    for item in items:
        async with AsyncSessionLocal() as session:
            contact = await session.get(FirmContactRow, item["contact_id"])
        if not contact:
            continue
        research = await research_contact_context(
            contact=contact,
            firm_name=item["firm_name"],
            selection_reason=item.get("reason") or {},
        )
        selection_evidence = {
            "why_this_contact_was_selected": item.get("reason", {}).get("reason")
            or item.get("reason", {}).get("basis")
            or "",
            "persona": item.get("persona") or "",
            "score": item.get("score"),
            "score_breakdown": item.get("reason", {}).get("score_breakdown") or {},
            "selection_features": item.get("reason", {}).get("selection_features") or {},
            "signals": item.get("reason", {}).get("signals") or [],
            "suppressions": item.get("reason", {}).get("suppressions") or [],
        }
        composition = await compose_lead_email(
            contact=contact,
            firm_name=item["firm_name"],
            sequence=_agent_sequence_stub(item["template_key"]),
            step_num=1,
            composer_variant_key=composer_variant_key,
            research_evidence=research,
            selection_evidence=selection_evidence,
        )
        action = await create_send_email_action(
            mode="lead_gen",
            to=item["contact_email"],
            subject=composition.subject,
            body=composition.body,
            requested_by=created_by,
            approved_by="operator" if approve_actions else None,
            contact_id=item["contact_id"],
            batch_item_id=item["id"],
            pif_id=item["pif_id"],
            firm_name=item["firm_name"],
            composer_experiment_key=composition.composer_experiment_key,
            composer_variant_key=composition.composer_variant_key,
            skill_path=composition.skill_path,
            skill_sha256=composition.skill_sha256,
            brief_version=composition.brief_version,
        )
        action_ids.append(action["id"])
        if policy_check_first_action and first_policy is None:
            first_policy = await check_action_policy(action["id"], actor=created_by)
        draft_payload = {
            "subject": composition.subject,
            "body": composition.body,
            "rationale": composition.reasoning,
            "angle": composition.angle,
            "cta": composition.cta,
            "risk_flags": composition.risk_flags,
            "requires_human_review": composition.requires_human_review,
            "blog_link_used": composition.blog_link_used,
            "composer_experiment_key": composition.composer_experiment_key,
            "composer_variant_key": composition.composer_variant_key,
            "skill_path": composition.skill_path,
            "skill_sha256": composition.skill_sha256,
            "brief_version": composition.brief_version,
            "action_id": action["id"],
            "action_status": action["status"],
            "research": research,
            "selection": selection_evidence,
        }
        async with AsyncSessionLocal() as session:
            row = await session.get(LeadGenBatchItemRow, item["id"])
            if row:
                reason = dict(row.reason_json or {})
                reason["agent_draft"] = draft_payload
                reason["research_evidence"] = research
                reason["send_email_action_id"] = action["id"]
                reason["next_operator_action"] = "review_edit_approve_send"
                row.reason_json = reason
                await session.commit()
        drafts.append({
            "batch_item_id": item["id"],
            "contact_id": item["contact_id"],
            "firm_name": item["firm_name"],
            "contact_name": item.get("contact_name") or "",
            "contact_email": item["contact_email"],
            "persona": item.get("persona") or "",
            "subject": composition.subject,
            "rationale": composition.reasoning,
            "action_id": action["id"],
            "action_status": action["status"],
            "research_status": research["status"],
        })

    await safe_record_product_trace(
        actor_type="agent" if created_by != "operator" else "user",
        actor_id=created_by,
        event_type="lead_gen_email_agent_slice_created",
        surface="lead-gen",
        entity_type="lead_gen_batch",
        entity_id=batch["id"],
        input_json={
            "limit": limit,
            "template_key": template_key,
            "composer_variant_key": composer_variant_key,
            "approve_actions": approve_actions,
            "existing_batch": only_undrafted_pending,
        },
        output_json={
            "draft_count": len(drafts),
            "action_ids": action_ids,
            "first_policy": first_policy,
        },
    )
    final_batch = await get_batch(batch["id"], include_observations=True)
    return {
        "batch": final_batch["batch"],
        "items": final_batch["items"],
        "observations": final_batch["observations"],
        "drafts": drafts,
        "action_ids": action_ids,
        "first_policy": first_policy,
        "no_email_sent": True,
    }
