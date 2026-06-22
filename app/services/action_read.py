"""Read-only durable action inspection for Possible OS agents."""
from __future__ import annotations

from typing import Any

from app.services.action_execution import get_action, list_actions
from app.services.product_traces import safe_record_product_trace


MAX_ACTIONS = 25


class ActionReadError(ValueError):
    """Raised when a read-only action inspection request is rejected."""


def _compact_text(value: Any, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _failed_policy_checks(policy: dict[str, Any]) -> list[dict[str, Any]]:
    checks = policy.get("checks") if isinstance(policy, dict) else []
    failed: list[dict[str, Any]] = []
    for check in checks if isinstance(checks, list) else []:
        if not isinstance(check, dict) or check.get("passed") is not False:
            continue
        failed.append({
            "name": str(check.get("name") or ""),
            "detail": str(check.get("detail") or ""),
        })
    return failed


def _related_action_ids_from_policy(policy: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for check in _failed_policy_checks(policy):
        detail = str(check.get("detail") or "").strip()
        if detail.startswith("action_") and detail not in ids:
            ids.append(detail)
    return ids


def _interpret_action(action: dict[str, Any]) -> dict[str, Any]:
    status = str(action.get("status") or "")
    policy = action.get("policy_result") if isinstance(action.get("policy_result"), dict) else {}
    execution = action.get("execution_result") if isinstance(action.get("execution_result"), dict) else {}
    failed_checks = _failed_policy_checks(policy)
    related_action_ids = _related_action_ids_from_policy(policy)

    if execution.get("blocked_by_policy") or status == "blocked":
        reason = str(execution.get("reason") or policy.get("reason") or action.get("error") or "policy_blocked")
        requires_user_help = reason in {
            "email_transport_configured",
            "zoho_api_configured",
            "lead_gen_transport_available",
            "daily_budget_available",
        }
        return {
            "feedback_type": "action_not_executable",
            "meaning": "The action did not execute because the policy gate blocked it.",
            "reason": reason,
            "failed_checks": failed_checks,
            "related_action_ids": related_action_ids,
            "recommended_interpretation": (
                "Treat this as stale duplicate work and do not retry."
                if related_action_ids else
                "Inspect the failed policy checks before deciding whether to retry, ask the user, or improve the system."
            ),
            "requires_user_help": requires_user_help,
        }
    if status == "succeeded":
        return {
            "feedback_type": "action_completed",
            "meaning": "The action completed successfully.",
            "reason": "succeeded",
            "failed_checks": [],
            "related_action_ids": related_action_ids,
            "recommended_interpretation": "Use this as evidence that the requested action path worked.",
            "requires_user_help": False,
        }
    if status == "failed":
        return {
            "feedback_type": "action_failed",
            "meaning": "The action was attempted and failed during execution.",
            "reason": str(action.get("error") or "execution_failed"),
            "failed_checks": failed_checks,
            "related_action_ids": related_action_ids,
            "recommended_interpretation": "Decide whether the failure is transient, needs user help, or should become an improvement finding.",
            "requires_user_help": False,
        }
    return {
        "feedback_type": f"action_{status or 'unknown'}",
        "meaning": "The action has not produced a terminal execution outcome yet.",
        "reason": status or "unknown",
        "failed_checks": failed_checks,
        "related_action_ids": related_action_ids,
        "recommended_interpretation": "Use the status and policy fields to decide the next safe step.",
        "requires_user_help": False,
    }


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    payload = action.get("input") if isinstance(action.get("input"), dict) else {}
    policy = action.get("policy_result") if isinstance(action.get("policy_result"), dict) else {}
    execution = action.get("execution_result") if isinstance(action.get("execution_result"), dict) else {}
    return {
        "id": action.get("id"),
        "action_type": action.get("action_type"),
        "status": action.get("status"),
        "risk_level": action.get("risk_level"),
        "requested_by": action.get("requested_by"),
        "approved_by": action.get("approved_by"),
        "entity_type": action.get("entity_type"),
        "entity_id": action.get("entity_id"),
        "created_at": action.get("created_at"),
        "started_at": action.get("started_at"),
        "completed_at": action.get("completed_at"),
        "input_summary": {
            "mode": payload.get("mode"),
            "to": payload.get("to"),
            "batch_item_id": payload.get("batch_item_id"),
            "contact_id": payload.get("contact_id"),
            "subject": _compact_text(payload.get("subject"), limit=220),
            "test_email": payload.get("test_email"),
            "subject_sha256": payload.get("subject_sha256"),
            "body_sha256": payload.get("body_sha256"),
            "composer_variant_key": payload.get("composer_variant_key"),
        },
        "policy_result": policy,
        "execution_result": execution,
        "error": action.get("error"),
        "trace_id": action.get("trace_id"),
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "event_type": event.get("event_type"),
        "actor": event.get("actor"),
        "message": _compact_text(event.get("message"), limit=300),
        "output": event.get("output") if isinstance(event.get("output"), dict) else {},
        "created_at": event.get("created_at"),
    }


async def read_action_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation") or "").strip()
    if operation == "get_action":
        action_id = str(payload.get("action_id") or "").strip()
        if not action_id:
            raise ActionReadError("action_id_required")
        detail = await get_action(action_id)
        if not detail:
            raise ActionReadError("action_not_found")
        action = _compact_action(detail.get("action") or {})
        events = [_compact_event(event) for event in (detail.get("events") or [])]
        interpretation = _interpret_action(action)
        return {
            "operation": "get_action",
            "action_id": action_id,
            "action": action,
            "events": events,
            "interpretation": interpretation,
            "summary": f"{action.get('status') or 'unknown'} {action.get('action_type') or 'action'} {action_id}",
            "truncated": False,
            "files_touched": [],
        }

    if operation == "list_recent":
        status = str(payload.get("status") or "").strip() or None
        action_type = str(payload.get("action_type") or "").strip() or None
        limit = max(1, min(int(payload.get("limit") or 10), MAX_ACTIONS))
        rows = await list_actions(status=status, action_type=action_type, limit=limit)
        actions = [_compact_action(row) for row in rows]
        return {
            "operation": "list_recent",
            "status": status,
            "action_type": action_type,
            "actions": actions,
            "count": len(actions),
            "summary": f"{len(actions)} recent action(s)",
            "truncated": len(actions) >= limit,
            "files_touched": [],
        }

    raise ActionReadError("unsupported_operation")


async def run_action_read(payload: dict[str, Any], *, actor: str = "master-agent") -> dict[str, Any]:
    try:
        result = await read_action_outcome(payload)
        await safe_record_product_trace(
            actor_type="agent" if actor == "master-agent" else "user",
            actor_id=actor,
            event_type="action_read_executed",
            surface="actions",
            entity_type="agent_action",
            entity_id=str(result.get("action_id") or result.get("operation") or "unknown"),
            input_json=payload,
            output_json={
                "operation": result.get("operation"),
                "summary": result.get("summary"),
                "count": result.get("count"),
                "interpretation": result.get("interpretation"),
            },
            metadata_json={"read_only": True},
        )
        return {"allowed": True, "result": result}
    except ActionReadError as exc:
        result = {
            "operation": str(payload.get("operation") or "unknown"),
            "error": str(exc),
            "summary": f"rejected: {exc}",
            "truncated": False,
            "files_touched": [],
        }
        await safe_record_product_trace(
            actor_type="agent" if actor == "master-agent" else "user",
            actor_id=actor,
            event_type="action_read_rejected",
            surface="actions",
            entity_type="agent_action",
            entity_id=str(payload.get("action_id") or payload.get("operation") or "unknown"),
            input_json=payload,
            output_json=result,
            metadata_json={"read_only": True},
        )
        return {"allowed": False, "result": result}
