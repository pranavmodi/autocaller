"""Durable, policy-checked action execution for Possible OS."""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AgentActionEventRow,
    AgentActionRow,
    EmailLogRow,
    FirmContactRow,
    LeadGenBatchItemRow,
)
from app.services.contact_selection import has_usable_email
from app.services.email_notification_service import _send_email
from app.services.lead_email_composer import _sanitize_email_copy
from app.services.lead_gen_cybernetic import (
    daily_send_budget_from_policy,
    ensure_default_policy,
    send_batch_item_draft,
)
from app.services.master_agent import ensure_agent_tables
from app.services.product_traces import safe_record_product_trace


SEND_APPROVED_LEAD_GEN_DRAFT = "send_approved_lead_gen_draft"
SEND_EMAIL = "send_email"
SEND_TEST_EMAIL = "send_test_email"  # Legacy action type kept readable for old rows.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _json_object(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _email_log_snapshot(row: EmailLogRow | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "email_log_id": row.id,
        "recipient_email": row.recipient_email,
        "recipient_name": row.recipient_name,
        "subject": row.subject,
        "message_type": row.message_type,
        "transport": row.transport,
        "message_id": row.message_id,
        "status": row.status,
        "error": row.error,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "pif_id": row.pif_id,
        "call_id": row.call_id,
    }


def action_to_dict(row: AgentActionRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "action_type": row.action_type,
        "status": row.status,
        "risk_level": row.risk_level,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "input": row.input_json or {},
        "policy_result": row.policy_result_json or {},
        "execution_result": row.execution_result_json or {},
        "error": row.error,
        "trace_id": row.trace_id,
        "scheduled_for": row.scheduled_for.isoformat() if row.scheduled_for else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _enrich_action_email_log_evidence_in_session(session, row: AgentActionRow) -> bool:
    """Backfill durable email-log evidence for older successful send actions."""
    if row.action_type != SEND_EMAIL or row.status != "succeeded":
        return False
    payload = row.input_json if isinstance(row.input_json, dict) else {}
    result = row.execution_result_json if isinstance(row.execution_result_json, dict) else {}
    if result.get("email_log_id"):
        return False
    recipient = str(result.get("sent_to") or payload.get("to") or "").strip().lower()
    if not recipient:
        return False
    subject = str(result.get("sent_subject") or payload.get("subject") or "").strip()
    message_type = str(result.get("message_type") or f"possible_os_action_{payload.get('mode') or 'test'}").strip()
    msg_id = str(result.get("sent_message_id") or "").strip()

    email_log: EmailLogRow | None = None
    if msg_id:
        email_log = (await session.execute(
            select(EmailLogRow)
            .where(
                EmailLogRow.recipient_email == recipient,
                EmailLogRow.message_id == msg_id,
            )
            .order_by(desc(EmailLogRow.sent_at))
            .limit(1)
        )).scalar_one_or_none()
    if email_log is None and subject:
        email_log = (await session.execute(
            select(EmailLogRow)
            .where(
                EmailLogRow.recipient_email == recipient,
                EmailLogRow.subject == subject,
            )
            .order_by(desc(EmailLogRow.sent_at))
            .limit(1)
        )).scalar_one_or_none()
    if email_log is None:
        return False

    email_log_data = _email_log_snapshot(email_log)
    updated = dict(result)
    updated.update({
        "transport": email_log_data.get("transport"),
        "email_log_id": email_log_data.get("email_log_id"),
        "email_log_status": email_log_data.get("status"),
        "email_log": email_log_data,
    })
    if not updated.get("sent_at") and email_log_data.get("sent_at"):
        updated["sent_at"] = email_log_data["sent_at"]
    if not updated.get("sent_message_id") and email_log_data.get("message_id"):
        updated["sent_message_id"] = email_log_data["message_id"]
    if not updated.get("message_type") and message_type:
        updated["message_type"] = message_type
    row.execution_result_json = updated
    row.updated_at = _utcnow()
    await _record_action_event(
        session,
        action_id=row.id,
        event_type="action_email_log_evidence_linked",
        actor="system",
        message="Linked existing email log evidence to successful send action.",
        output_json=email_log_data,
    )
    return True


def action_event_to_dict(row: AgentActionEventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "action_id": row.action_id,
        "event_type": row.event_type,
        "actor": row.actor,
        "message": row.message,
        "input": row.input_json or {},
        "output": row.output_json or {},
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _record_action_event(
    session,
    *,
    action_id: str,
    event_type: str,
    actor: str,
    message: str = "",
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> AgentActionEventRow:
    row = AgentActionEventRow(
        action_id=action_id,
        event_type=event_type[:64],
        actor=(actor or "system")[:128],
        message=message,
        input_json=_json_object(input_json),
        output_json=_json_object(output_json),
        metadata_json=_json_object(metadata_json),
    )
    session.add(row)
    return row


async def list_actions(
    *,
    status: str | None = None,
    action_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        stmt = select(AgentActionRow).order_by(desc(AgentActionRow.created_at)).limit(max(1, min(limit, 500)))
        if status:
            stmt = stmt.where(AgentActionRow.status == status)
        if action_type:
            stmt = stmt.where(AgentActionRow.action_type == action_type)
        rows = (await session.execute(stmt)).scalars().all()
        changed = False
        for row in rows:
            changed = await _enrich_action_email_log_evidence_in_session(session, row) or changed
        if changed:
            await session.commit()
        return [action_to_dict(row) for row in rows]


async def get_action(action_id: str) -> dict[str, Any] | None:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentActionRow, action_id)
        if not row:
            return None
        changed = await _enrich_action_email_log_evidence_in_session(session, row)
        if changed:
            await session.commit()
            await session.refresh(row)
        events = (await session.execute(
            select(AgentActionEventRow)
            .where(AgentActionEventRow.action_id == action_id)
            .order_by(AgentActionEventRow.created_at.asc(), AgentActionEventRow.id.asc())
        )).scalars().all()
        return {
            "action": action_to_dict(row),
            "events": [action_event_to_dict(event) for event in events],
        }


async def create_send_approved_lead_gen_draft_action(
    *,
    batch_item_id: str,
    subject: str,
    body: str,
    requested_by: str = "operator",
    approved_by: str = "operator",
    composer_experiment_key: str | None = None,
    composer_variant_key: str | None = None,
    skill_path: str | None = None,
    skill_sha256: str | None = None,
) -> dict[str, Any]:
    await ensure_agent_tables()
    draft_subject = _sanitize_email_copy(subject)
    draft_body = _sanitize_email_copy(body)
    if not draft_subject:
        raise ValueError("draft_subject_empty")
    if not draft_body:
        raise ValueError("draft_body_empty")
    action_id = _new_id("action")
    input_json = {
        "batch_item_id": batch_item_id,
        "subject": draft_subject,
        "body": draft_body,
        "subject_sha256": _sha256(draft_subject),
        "body_sha256": _sha256(draft_body),
        "composer_experiment_key": composer_experiment_key,
        "composer_variant_key": composer_variant_key,
        "skill_path": skill_path,
        "skill_sha256": skill_sha256,
        "approval": {
            "approved_by": approved_by or "operator",
            "approved_at": _utcnow().isoformat(),
            "subject_sha256": _sha256(draft_subject),
            "body_sha256": _sha256(draft_body),
        },
    }
    async with AsyncSessionLocal() as session:
        action = AgentActionRow(
            id=action_id,
            action_type=SEND_APPROVED_LEAD_GEN_DRAFT,
            status="approved",
            risk_level="high",
            requested_by=(requested_by or "operator")[:128],
            approved_by=(approved_by or "operator")[:128],
            entity_type="lead_gen_batch_item",
            entity_id=batch_item_id,
            input_json=input_json,
        )
        session.add(action)
        await session.flush()
        await _record_action_event(
            session,
            action_id=action_id,
            event_type="action_approved",
            actor=approved_by or requested_by or "operator",
            message="Approved exact lead-gen draft for execution.",
            input_json={
                "batch_item_id": batch_item_id,
                "subject_sha256": input_json["subject_sha256"],
                "body_sha256": input_json["body_sha256"],
            },
        )
        await session.commit()
        await session.refresh(action)
        result = action_to_dict(action)
    await safe_record_product_trace(
        actor_type="user" if (approved_by or "operator") == "operator" else "agent",
        actor_id=approved_by or requested_by or "operator",
        event_type="action_approved",
        surface="actions",
        entity_type="agent_action",
        entity_id=action_id,
        input_json={
            "action_type": SEND_APPROVED_LEAD_GEN_DRAFT,
            "batch_item_id": batch_item_id,
        },
        output_json={"status": result["status"]},
        context_json={
            "subject_sha256": input_json["subject_sha256"],
            "body_sha256": input_json["body_sha256"],
        },
    )
    return result


async def create_send_email_action(
    *,
    to: str,
    subject: str,
    body: str,
    mode: str = "test",
    requested_by: str = "operator",
    approved_by: str | None = "operator",
    from_addr: str | None = None,
    contact_id: str | None = None,
    batch_item_id: str | None = None,
    pif_id: str | None = None,
    firm_name: str | None = None,
    composer_experiment_key: str | None = None,
    composer_variant_key: str | None = None,
    skill_path: str | None = None,
    skill_sha256: str | None = None,
) -> dict[str, Any]:
    await ensure_agent_tables()
    email_mode = (mode or "test").strip().lower()
    recipient = to.strip().lower()
    draft_subject = _sanitize_email_copy(subject)
    draft_body = _sanitize_email_copy(body)
    if email_mode not in {"test", "lead_gen"}:
        raise ValueError("email_mode_not_supported")
    if not recipient or "@" not in recipient:
        raise ValueError("recipient_email_invalid")
    if not draft_subject:
        raise ValueError("draft_subject_empty")
    if not draft_body:
        raise ValueError("draft_body_empty")
    action_id = _new_id("action")
    approved_actor = (approved_by or "").strip()
    approval_json = None
    if approved_actor:
        approval_json = {
            "approved_by": approved_actor,
            "approved_at": _utcnow().isoformat(),
            "recipient": recipient,
            "subject_sha256": _sha256(draft_subject),
            "body_sha256": _sha256(draft_body),
        }
    input_json = {
        "to": recipient,
        "subject": draft_subject,
        "body": draft_body,
        "mode": email_mode,
        "from_addr": (from_addr or "").strip() or None,
        "contact_id": (contact_id or "").strip() or None,
        "batch_item_id": (batch_item_id or "").strip() or None,
        "pif_id": (pif_id or "").strip() or None,
        "firm_name": (firm_name or "").strip() or None,
        "composer_experiment_key": composer_experiment_key,
        "composer_variant_key": composer_variant_key,
        "skill_path": skill_path,
        "skill_sha256": skill_sha256,
        "subject_sha256": _sha256(draft_subject),
        "body_sha256": _sha256(draft_body),
        "test_email": email_mode == "test",
        "approval": approval_json,
    }
    entity_type = "test_email" if email_mode == "test" else "lead_gen_email"
    entity_id = recipient if email_mode == "test" else (batch_item_id or contact_id or recipient)
    async with AsyncSessionLocal() as session:
        action = AgentActionRow(
            id=action_id,
            action_type=SEND_EMAIL,
            status="approved" if approved_actor else "waiting_for_approval",
            risk_level="high",
            requested_by=(requested_by or "operator")[:128],
            approved_by=approved_actor[:128] or None,
            entity_type=entity_type,
            entity_id=entity_id,
            input_json=input_json,
        )
        session.add(action)
        await session.flush()
        await _record_action_event(
            session,
            action_id=action_id,
            event_type="action_approved" if approved_actor else "action_created",
            actor=approved_actor or requested_by or "operator",
            message=(
                f"Approved exact {email_mode} email for execution."
                if approved_actor
                else f"Created {email_mode} email action awaiting approval."
            ),
            input_json={
                "mode": email_mode,
                "to": recipient,
                "contact_id": input_json["contact_id"],
                "batch_item_id": input_json["batch_item_id"],
                "subject_sha256": input_json["subject_sha256"],
                "body_sha256": input_json["body_sha256"],
            },
        )
        await session.commit()
        await session.refresh(action)
        result = action_to_dict(action)
    await safe_record_product_trace(
        actor_type="user" if (approved_actor or "operator") == "operator" else "agent",
        actor_id=approved_actor or requested_by or "operator",
        event_type="action_approved" if approved_actor else "action_created",
        surface="actions",
        entity_type="agent_action",
        entity_id=action_id,
        input_json={
            "action_type": SEND_EMAIL,
            "mode": email_mode,
            "to": recipient,
            "contact_id": input_json["contact_id"],
            "batch_item_id": input_json["batch_item_id"],
        },
        output_json={"status": result["status"]},
        context_json={
            "subject_sha256": input_json["subject_sha256"],
            "body_sha256": input_json["body_sha256"],
        },
    )
    return result


async def create_send_test_email_action(
    *,
    to: str,
    subject: str,
    body: str,
    requested_by: str = "operator",
    approved_by: str = "operator",
    from_addr: str | None = None,
) -> dict[str, Any]:
    return await create_send_email_action(
        to=to,
        subject=subject,
        body=body,
        mode="test",
        requested_by=requested_by,
        approved_by=approved_by,
        from_addr=from_addr,
    )


async def check_action_policy(action_id: str, *, actor: str = "operator") -> dict[str, Any]:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        action = await session.get(AgentActionRow, action_id)
        if not action:
            raise ValueError("action_not_found")
        result = await _check_action_policy_in_session(session, action)
        action.policy_result_json = result
        await _record_action_event(
            session,
            action_id=action.id,
            event_type="action_policy_checked",
            actor=actor,
            message=result["reason"],
            output_json=result,
        )
        await session.commit()
    await safe_record_product_trace(
        actor_type="user" if actor == "operator" else "agent",
        actor_id=actor,
        event_type="action_policy_checked",
        surface="actions",
        entity_type="agent_action",
        entity_id=action_id,
        output_json=result,
    )
    return result


async def _check_action_policy_in_session(session, action: AgentActionRow) -> dict[str, Any]:
    if action.action_type in {SEND_EMAIL, SEND_TEST_EMAIL}:
        return await _check_send_email_policy_in_session(session, action)
    if action.action_type != SEND_APPROVED_LEAD_GEN_DRAFT:
        return {"allowed": False, "reason": "unsupported_action_type", "checks": []}
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    payload = dict(action.input_json or {})
    approval = dict(payload.get("approval") or {})
    subject = _sanitize_email_copy(str(payload.get("subject") or ""))
    body = _sanitize_email_copy(str(payload.get("body") or ""))
    batch_item_id = str(payload.get("batch_item_id") or action.entity_id or "").strip()

    add("status_allows_execution", action.status in {"approved", "queued"}, action.status)
    add("human_approval_present", bool(action.approved_by and approval.get("approved_by")), str(action.approved_by or ""))
    add("subject_present", bool(subject.strip()), "")
    add("body_present", bool(body.strip()), "")
    add("subject_hash_matches_approval", _sha256(subject) == approval.get("subject_sha256"), "")
    add("body_hash_matches_approval", _sha256(body) == approval.get("body_sha256"), "")
    add("zoho_api_configured", bool(os.getenv("ZOHO_MAIL_REFRESH_TOKEN", "").strip()), "")

    item = await session.get(LeadGenBatchItemRow, batch_item_id) if batch_item_id else None
    add("batch_item_exists", item is not None, batch_item_id)
    if item:
        add("batch_item_not_already_started", item.approval_status != "started", item.approval_status)
        contact = await session.get(FirmContactRow, item.contact_id)
        add("contact_email_present", bool(contact and contact.email), getattr(contact, "email", "") if contact else "")
    else:
        contact = None
    existing_success = (await session.execute(
        select(AgentActionRow).where(
            AgentActionRow.id != action.id,
            AgentActionRow.action_type == SEND_APPROVED_LEAD_GEN_DRAFT,
            AgentActionRow.entity_type == "lead_gen_batch_item",
            AgentActionRow.entity_id == batch_item_id,
            AgentActionRow.status == "succeeded",
        ).limit(1)
    )).scalar_one_or_none()
    add("no_prior_successful_action_for_item", existing_success is None, existing_success.id if existing_success else "")

    allowed = all(check["passed"] for check in checks)
    failed = [check for check in checks if not check["passed"]]
    return {
        "allowed": allowed,
        "reason": "allowed" if allowed else str(failed[0]["name"]),
        "checks": checks,
        "risk_level": action.risk_level,
        "requires_human_approval": True,
        "action_type": action.action_type,
        "contact_email": getattr(contact, "email", "") if contact else "",
    }


async def _check_send_email_policy_in_session(session, action: AgentActionRow) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    payload = dict(action.input_json or {})
    approval = dict(payload.get("approval") or {})
    recipient = str(payload.get("to") or action.entity_id or "").strip().lower()
    subject = _sanitize_email_copy(str(payload.get("subject") or ""))
    body = _sanitize_email_copy(str(payload.get("body") or ""))
    mode = str(payload.get("mode") or ("test" if action.action_type == SEND_TEST_EMAIL else "")).strip().lower()

    transport_configured = bool(
        os.getenv("ZOHO_MAIL_REFRESH_TOKEN", "").strip()
        or os.getenv("SMTP_HOST", "").strip()
        or os.getenv("RESEND_API_KEY", "").strip()
    )

    add("status_allows_execution", action.status in {"approved", "queued"}, action.status)
    add("human_approval_present", bool(action.approved_by and approval.get("approved_by")), str(action.approved_by or ""))
    add("email_mode_supported", mode in {"test", "lead_gen"}, mode)
    if mode == "test":
        add("marked_as_test_email", bool(payload.get("test_email") is True), "")
    add("recipient_present", bool(recipient and "@" in recipient), recipient)
    add("recipient_matches_approval", recipient == str(approval.get("recipient") or "").strip().lower(), "")
    add("subject_present", bool(subject.strip()), "")
    add("body_present", bool(body.strip()), "")
    add("subject_hash_matches_approval", _sha256(subject) == approval.get("subject_sha256"), "")
    add("body_hash_matches_approval", _sha256(body) == approval.get("body_sha256"), "")
    add("email_transport_configured", transport_configured, "")

    contact = None
    batch_item = None
    if mode == "test":
        existing_success = (await session.execute(
            select(AgentActionRow).where(
                AgentActionRow.id != action.id,
                AgentActionRow.action_type.in_([SEND_EMAIL, SEND_TEST_EMAIL]),
                AgentActionRow.entity_type == "test_email",
                AgentActionRow.entity_id == recipient,
                AgentActionRow.status == "succeeded",
            ).limit(1)
        )).scalar_one_or_none()
        add("no_prior_successful_test_action_for_recipient", existing_success is None, existing_success.id if existing_success else "")
    if mode == "lead_gen":
        contact_id = str(payload.get("contact_id") or "").strip()
        batch_item_id = str(payload.get("batch_item_id") or "").strip()
        if contact_id:
            contact = await session.get(FirmContactRow, contact_id)
        if batch_item_id:
            batch_item = await session.get(LeadGenBatchItemRow, batch_item_id)
            if batch_item and not contact:
                contact = await session.get(FirmContactRow, batch_item.contact_id)
        add("lead_gen_contact_exists", contact is not None, contact_id)
        add("lead_gen_contact_email_usable", bool(contact and has_usable_email(contact.email)), getattr(contact, "email", "") if contact else "")
        add(
            "recipient_matches_contact",
            bool(contact and (contact.email or "").strip().lower() == recipient),
            getattr(contact, "email", "") if contact else "",
        )
        add("batch_item_exists", bool(batch_item_id and batch_item), batch_item_id)
        if batch_item:
            add("batch_item_not_already_started", batch_item.approval_status != "started", batch_item.approval_status)
            suppressions = (batch_item.reason_json or {}).get("suppressions") or []
            add("not_suppressed_by_selection", len(suppressions) == 0, ", ".join(str(x) for x in suppressions))
        add("consult_link_present", "getpossibleminds.com/consult" in body.lower(), "")
        add("zoho_api_configured", bool(os.getenv("ZOHO_MAIL_REFRESH_TOKEN", "").strip()), "")
        try:
            policy = await ensure_default_policy()
            budget = daily_send_budget_from_policy(policy)
            add("daily_budget_available", budget >= 1, str(budget))
        except Exception as exc:
            add("daily_budget_available", False, f"{type(exc).__name__}: {str(exc)[:120]}")
        existing_item_success = None
        if batch_item_id:
            existing_item_success = (await session.execute(
                select(AgentActionRow).where(
                    AgentActionRow.id != action.id,
                    AgentActionRow.action_type == SEND_EMAIL,
                    AgentActionRow.entity_type == "lead_gen_email",
                    AgentActionRow.entity_id == batch_item_id,
                    AgentActionRow.status == "succeeded",
                ).limit(1)
            )).scalar_one_or_none()
        add("no_prior_successful_lead_gen_action_for_item", existing_item_success is None, existing_item_success.id if existing_item_success else "")
        existing_recipient_success = (await session.execute(
            select(AgentActionRow).where(
                AgentActionRow.id != action.id,
                AgentActionRow.action_type == SEND_EMAIL,
                AgentActionRow.entity_type == "lead_gen_email",
                AgentActionRow.status == "succeeded",
                AgentActionRow.input_json["to"].as_string() == recipient,
            ).limit(1)
        )).scalar_one_or_none()
        add("no_prior_successful_lead_gen_action_for_recipient", existing_recipient_success is None, existing_recipient_success.id if existing_recipient_success else "")

    allowed = all(check["passed"] for check in checks)
    failed = [check for check in checks if not check["passed"]]
    return {
        "allowed": allowed,
        "reason": "allowed" if allowed else str(failed[0]["name"]),
        "checks": checks,
        "risk_level": action.risk_level,
        "requires_human_approval": True,
        "action_type": action.action_type,
        "mode": mode,
        "recipient_email": recipient,
        "contact_id": getattr(contact, "id", None) if contact else None,
        "batch_item_id": getattr(batch_item, "id", None) if batch_item else None,
    }


async def execute_action(action_id: str, *, actor: str = "operator") -> dict[str, Any]:
    await ensure_agent_tables()
    policy = await check_action_policy(action_id, actor=actor)
    if not policy["allowed"]:
        return {
            "action": (await get_action(action_id) or {}).get("action"),
            "policy": policy,
            "executed": False,
        }

    async with AsyncSessionLocal() as session:
        action = await session.get(AgentActionRow, action_id)
        if not action:
            raise ValueError("action_not_found")
        action.status = "running"
        action.started_at = _utcnow()
        await _record_action_event(
            session,
            action_id=action.id,
            event_type="action_started",
            actor=actor,
            message="Action executor started.",
        )
        await session.commit()
        payload = dict(action.input_json or {})

    await safe_record_product_trace(
        actor_type="user" if actor == "operator" else "agent",
        actor_id=actor,
        event_type="action_started",
        surface="actions",
        entity_type="agent_action",
        entity_id=action_id,
        input_json={"action_type": str(payload.get("action_type") or policy.get("action_type") or "")},
    )

    try:
        if policy.get("action_type") in {SEND_EMAIL, SEND_TEST_EMAIL}:
            result = await _execute_send_email(payload)
        else:
            result = await send_batch_item_draft(
                batch_item_id=str(payload.get("batch_item_id") or ""),
                subject=str(payload.get("subject") or ""),
                body=str(payload.get("body") or ""),
                sent_by=actor,
                composer_experiment_key=payload.get("composer_experiment_key"),
                composer_variant_key=payload.get("composer_variant_key"),
                skill_path=payload.get("skill_path"),
                skill_sha256=payload.get("skill_sha256"),
            )
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            action = await session.get(AgentActionRow, action_id)
            if action:
                action.status = "failed"
                action.error = f"{type(exc).__name__}: {str(exc)[:500]}"
                action.completed_at = _utcnow()
                action.execution_result_json = {"error": action.error}
                await _record_action_event(
                    session,
                    action_id=action.id,
                    event_type="action_failed",
                    actor=actor,
                    message=action.error,
                    output_json=action.execution_result_json,
                )
                await session.commit()
        await safe_record_product_trace(
            actor_type="user" if actor == "operator" else "agent",
            actor_id=actor,
            event_type="action_failed",
            surface="actions",
            entity_type="agent_action",
            entity_id=action_id,
            output_json={"error": f"{type(exc).__name__}: {str(exc)[:500]}"},
        )
        raise

    async with AsyncSessionLocal() as session:
        action = await session.get(AgentActionRow, action_id)
        if action:
            action.status = "succeeded"
            action.error = None
            action.completed_at = _utcnow()
            action.execution_result_json = result
            await _record_action_event(
                session,
                action_id=action.id,
                event_type="action_succeeded",
                actor=actor,
                message="Action completed.",
                output_json=result,
            )
            await session.commit()
    await safe_record_product_trace(
        actor_type="user" if actor == "operator" else "agent",
        actor_id=actor,
        event_type="action_succeeded",
        surface="actions",
        entity_type="agent_action",
        entity_id=action_id,
        output_json=result,
    )
    return {
        "action": (await get_action(action_id) or {}).get("action"),
        "policy": policy,
        "executed": True,
        "result": result,
    }


async def execute_approved_lead_gen_email_actions(
    *,
    limit: int = 1,
    actor: str = "master-agent",
) -> dict[str, Any]:
    """Execute approved lead-gen email actions through the durable policy gate.

    This is the narrow autonomous send path for the master agent. It never
    creates email content, changes recipients, or bypasses approval; it only
    drains exact approved `send_email mode=lead_gen` actions.
    """
    await ensure_agent_tables()
    safe_limit = max(1, min(int(limit), 25))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentActionRow)
            .where(
                AgentActionRow.action_type == SEND_EMAIL,
                AgentActionRow.status == "approved",
                AgentActionRow.entity_type == "lead_gen_email",
                AgentActionRow.input_json["mode"].as_string() == "lead_gen",
            )
            .order_by(AgentActionRow.created_at.asc(), AgentActionRow.id.asc())
            .limit(safe_limit)
        )).scalars().all()
        action_ids = [row.id for row in rows]

    executions: list[dict[str, Any]] = []
    for action_id in action_ids:
        executions.append(await execute_action(action_id, actor=actor))

    await safe_record_product_trace(
        actor_type="agent" if actor != "operator" else "user",
        actor_id=actor,
        event_type="approved_lead_gen_email_actions_executed",
        surface="agents",
        entity_type="agent_action",
        input_json={"limit": safe_limit, "candidate_action_ids": action_ids},
        output_json={
            "attempted": len(executions),
            "executed": sum(1 for row in executions if row.get("executed")),
            "action_ids": action_ids,
        },
    )
    return {
        "limit": safe_limit,
        "candidate_action_ids": action_ids,
        "attempted": len(executions),
        "executed": sum(1 for row in executions if row.get("executed")),
        "results": executions,
    }


async def _execute_send_email(payload: dict[str, Any]) -> dict[str, Any]:
    subject = _sanitize_email_copy(str(payload.get("subject") or ""))
    body = _sanitize_email_copy(str(payload.get("body") or ""))
    recipient = str(payload.get("to") or "").strip().lower()
    from_addr = str(payload.get("from_addr") or "").strip() or None
    mode = str(payload.get("mode") or "test").strip().lower()
    contact_id = str(payload.get("contact_id") or "").strip()
    batch_item_id = str(payload.get("batch_item_id") or "").strip()
    recipient_name = "Pranav Modi" if recipient == "pranav.modi@gmail.com" else None
    pif_id = str(payload.get("pif_id") or "").strip() or None
    if mode == "lead_gen" and contact_id:
        async with AsyncSessionLocal() as session:
            contact = await session.get(FirmContactRow, contact_id)
            if contact:
                recipient_name = contact.full_name or recipient_name
                pif_id = contact.pif_id or pif_id
    msg_id = _send_email(
        subject,
        body,
        to=recipient,
        from_addr=from_addr,
        message_type=f"possible_os_action_{mode}",
        recipient_name=recipient_name,
        pif_id=pif_id,
        transport="zoho_api" if mode == "lead_gen" else None,
    )
    email_log: EmailLogRow | None = None
    async with AsyncSessionLocal() as session:
        email_log = (await session.execute(
            select(EmailLogRow)
            .where(
                EmailLogRow.recipient_email == recipient,
                EmailLogRow.message_type == f"possible_os_action_{mode}",
                EmailLogRow.message_id == msg_id,
            )
            .order_by(desc(EmailLogRow.sent_at))
            .limit(1)
        )).scalar_one_or_none()
        if email_log is None:
            email_log = (await session.execute(
                select(EmailLogRow)
                .where(
                    EmailLogRow.recipient_email == recipient,
                    EmailLogRow.message_type == f"possible_os_action_{mode}",
                    EmailLogRow.subject == subject,
                )
                .order_by(desc(EmailLogRow.sent_at))
                .limit(1)
            )).scalar_one_or_none()
        email_log_data = _email_log_snapshot(email_log)
    if mode == "lead_gen" and batch_item_id:
        async with AsyncSessionLocal() as session:
            item = await session.get(LeadGenBatchItemRow, batch_item_id)
            if item:
                item.approval_status = "started"
                reason = dict(item.reason_json or {})
                approval = dict(payload.get("approval") or {})
                reason["last_sent_by"] = str(approval.get("approved_by") or "operator")
                reason["last_sent_at"] = email_log_data.get("sent_at") or _utcnow().isoformat()
                reason["last_sent_message_id"] = msg_id
                if email_log_data.get("email_log_id"):
                    reason["last_sent_email_log_id"] = email_log_data["email_log_id"]
                reason["last_sent_subject"] = subject
                reason["last_sent_mode"] = "lead_gen"
                reason["last_sent_transport"] = email_log_data.get("transport") or "zoho_api"
                reason["last_sent_status"] = email_log_data.get("status") or "sent"
                for key in (
                    "composer_experiment_key",
                    "composer_variant_key",
                    "skill_path",
                    "skill_sha256",
                ):
                    if payload.get(key):
                        reason[f"last_sent_{key}"] = payload.get(key)
                item.reason_json = reason
                await session.commit()
    sent_at = email_log_data.get("sent_at") or _utcnow().isoformat()
    return {
        "action_type": SEND_EMAIL,
        "mode": mode,
        "sent_to": recipient,
        "sent_subject": subject,
        "sent_message_id": msg_id,
        "sent_at": sent_at,
        "message_type": f"possible_os_action_{mode}",
        "transport": email_log_data.get("transport"),
        "email_log_id": email_log_data.get("email_log_id"),
        "email_log_status": email_log_data.get("status"),
        "email_log": email_log_data,
        "subject_sha256": _sha256(subject),
        "body_sha256": _sha256(body),
        "contact_id": contact_id or None,
        "batch_item_id": batch_item_id or None,
    }


async def create_and_execute_send_approved_lead_gen_draft(
    *,
    batch_item_id: str,
    subject: str,
    body: str,
    requested_by: str = "operator",
    approved_by: str = "operator",
    composer_experiment_key: str | None = None,
    composer_variant_key: str | None = None,
    skill_path: str | None = None,
    skill_sha256: str | None = None,
) -> dict[str, Any]:
    action = await create_send_approved_lead_gen_draft_action(
        batch_item_id=batch_item_id,
        subject=subject,
        body=body,
        requested_by=requested_by,
        approved_by=approved_by,
        composer_experiment_key=composer_experiment_key,
        composer_variant_key=composer_variant_key,
        skill_path=skill_path,
        skill_sha256=skill_sha256,
    )
    return await execute_action(action["id"], actor=approved_by or requested_by or "operator")


async def create_and_execute_send_test_email(
    *,
    to: str,
    subject: str,
    body: str,
    requested_by: str = "operator",
    approved_by: str = "operator",
    from_addr: str | None = None,
) -> dict[str, Any]:
    action = await create_send_email_action(
        to=to,
        subject=subject,
        body=body,
        mode="test",
        requested_by=requested_by,
        approved_by=approved_by,
        from_addr=from_addr,
    )
    return await execute_action(action["id"], actor=approved_by or requested_by or "operator")
