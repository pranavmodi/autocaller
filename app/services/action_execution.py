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
    FirmContactRow,
    LeadGenBatchItemRow,
)
from app.services.email_notification_service import _send_email
from app.services.lead_email_composer import _sanitize_email_copy
from app.services.lead_gen_cybernetic import send_batch_item_draft
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
        return [action_to_dict(row) for row in rows]


async def get_action(action_id: str) -> dict[str, Any] | None:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentActionRow, action_id)
        if not row:
            return None
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
    approved_by: str = "operator",
    from_addr: str | None = None,
) -> dict[str, Any]:
    await ensure_agent_tables()
    email_mode = (mode or "test").strip().lower()
    recipient = to.strip().lower()
    draft_subject = _sanitize_email_copy(subject)
    draft_body = _sanitize_email_copy(body)
    if email_mode not in {"test"}:
        raise ValueError("email_mode_not_supported")
    if not recipient or "@" not in recipient:
        raise ValueError("recipient_email_invalid")
    if not draft_subject:
        raise ValueError("draft_subject_empty")
    if not draft_body:
        raise ValueError("draft_body_empty")
    action_id = _new_id("action")
    input_json = {
        "to": recipient,
        "subject": draft_subject,
        "body": draft_body,
        "mode": email_mode,
        "from_addr": (from_addr or "").strip() or None,
        "subject_sha256": _sha256(draft_subject),
        "body_sha256": _sha256(draft_body),
        "test_email": email_mode == "test",
        "approval": {
            "approved_by": approved_by or "operator",
            "approved_at": _utcnow().isoformat(),
            "recipient": recipient,
            "subject_sha256": _sha256(draft_subject),
            "body_sha256": _sha256(draft_body),
        },
    }
    async with AsyncSessionLocal() as session:
        action = AgentActionRow(
            id=action_id,
            action_type=SEND_EMAIL,
            status="approved",
            risk_level="high",
            requested_by=(requested_by or "operator")[:128],
            approved_by=(approved_by or "operator")[:128],
            entity_type="test_email",
            entity_id=recipient,
            input_json=input_json,
        )
        session.add(action)
        await session.flush()
        await _record_action_event(
            session,
            action_id=action_id,
            event_type="action_approved",
            actor=approved_by or requested_by or "operator",
            message=f"Approved exact {email_mode} email for execution.",
            input_json={
                "mode": email_mode,
                "to": recipient,
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
            "action_type": SEND_EMAIL,
            "mode": email_mode,
            "to": recipient,
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
    add("email_mode_supported", mode in {"test"}, mode)
    if mode == "test":
        add("marked_as_test_email", bool(payload.get("test_email") is True), "")
    add("recipient_present", bool(recipient and "@" in recipient), recipient)
    add("recipient_matches_approval", recipient == str(approval.get("recipient") or "").strip().lower(), "")
    add("subject_present", bool(subject.strip()), "")
    add("body_present", bool(body.strip()), "")
    add("subject_hash_matches_approval", _sha256(subject) == approval.get("subject_sha256"), "")
    add("body_hash_matches_approval", _sha256(body) == approval.get("body_sha256"), "")
    add("email_transport_configured", transport_configured, "")

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


async def _execute_send_email(payload: dict[str, Any]) -> dict[str, Any]:
    subject = _sanitize_email_copy(str(payload.get("subject") or ""))
    body = _sanitize_email_copy(str(payload.get("body") or ""))
    recipient = str(payload.get("to") or "").strip().lower()
    from_addr = str(payload.get("from_addr") or "").strip() or None
    mode = str(payload.get("mode") or "test").strip().lower()
    msg_id = _send_email(
        subject,
        body,
        to=recipient,
        from_addr=from_addr,
        message_type=f"possible_os_action_{mode}",
        recipient_name="Pranav Modi" if recipient == "pranav.modi@gmail.com" else None,
    )
    return {
        "action_type": SEND_EMAIL,
        "mode": mode,
        "sent_to": recipient,
        "sent_subject": subject,
        "sent_message_id": msg_id,
        "sent_at": _utcnow().isoformat(),
        "message_type": f"possible_os_action_{mode}",
        "subject_sha256": _sha256(subject),
        "body_sha256": _sha256(body),
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
