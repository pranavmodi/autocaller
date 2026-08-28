"""Stateless, debug-first Lead Finder context and LLM step service."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal, async_engine
from app.db.models import (
    LeadFinderAttemptRow,
    LeadFinderRunRow,
    LeadFinderStepRow,
    LeadFinderToolCallRow,
)
from app.services.llm_gateway import call_skill_json, prompt_cache_metrics
from app.services.lead_finder_tools import (
    execute_lead_finder_tool,
    lead_finder_tool_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_DIR = Path(os.getenv("LEAD_FINDER_CONTEXT_DIR", REPO_ROOT / "docs/lead-finder-context"))
SKILL_PATH = Path(os.getenv("LEAD_FINDER_SKILL_PATH", REPO_ROOT / "app/skills/lead-finder/SKILL.md"))
MODEL = os.getenv("LEAD_FINDER_MODEL", "openclaw/main")
CONTEXT_FILES = ("company.md", "customer.md", "offer.md", "voice.md")
ACTIVE_STEP_STATUSES = {"queued", "running", "retrying"}
TERMINAL_STEP_STATUSES = {"completed", "failed", "interrupted"}
_tables_checked = False

JOB = {
    "name": "Lead Finder Agent",
    "objective": (
        "Find plausible prospective customers, research why they may be a fit, "
        "and recommend evidence-backed outreach angles to the user."
    ),
    "success_definition": (
        "A short ranked list of leads with observed evidence, explicit inferences, "
        "a suggested angle, uncertainty, and source links."
    ),
    "boundaries": [
        "Recommendation-only: never send outreach or mutate lead records.",
        "Never invent people, firms, facts, source evidence, or tool results.",
        "Keep observed facts separate from inference.",
        "In debug mode, perform exactly one reasoning transition per trigger and stop.",
        "Only lead_finder.add_researched_lead may mutate run-local results; never mutate CRM data.",
    ],
    "available_sources": [
        "Mission Control podcast transcripts through validated read-only tools",
        "Public web research after a named person is supported by transcript evidence",
    ],
    "future_sources": [],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_payload(name: str) -> dict[str, Any]:
    path = CONTEXT_DIR / name
    content = path.read_text(encoding="utf-8")
    return {
        "name": name,
        "path": str(path.relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def load_lead_finder_context() -> dict[str, Any]:
    """Load the authoritative baseline context used by every debug run."""
    return {
        "kind": "lead_finder_context_v1",
        "job": deepcopy(JOB),
        "user_direction": "",
        "baseline_context": {
            "loaded_at": _now(),
            "files": {name: _file_payload(name) for name in CONTEXT_FILES},
        },
        "agent_state": {
            "status": "ready",
            "completed_steps": 0,
            "next_step": "Assess the baseline context and the user's lead direction.",
            "working_state": {},
            "last_step": None,
        },
    }


def _merge_working_state(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(current)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_working_state(merged[key], value)
        else:
            merged[key] = value
    return merged


def _authoritative_context(context: dict[str, Any], user_direction: str) -> dict[str, Any]:
    """Keep browser working state, but reload job and baseline files server-side."""
    authoritative = load_lead_finder_context()
    supplied_state = context.get("agent_state") if isinstance(context, dict) else None
    if isinstance(supplied_state, dict):
        authoritative["agent_state"] = deepcopy(supplied_state)
    authoritative["user_direction"] = user_direction.strip()
    return authoritative


def _context_for_persisted_run(context: dict[str, Any], user_direction: str) -> dict[str, Any]:
    current = deepcopy(context)
    current["user_direction"] = user_direction.strip()
    return current


def _gateway_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "instruction": (
            "Perform exactly one debug step. Either reason or request exactly one available "
            "tool; never claim a requested tool has already run. Only add a result after its "
            "completed web-research tool call is present in context. Return the required "
            "JSON and stop."
        ),
        "available_tools": lead_finder_tool_catalog(),
        "context": context,
    }


def _cache_session_user(run_id: str | None) -> str | None:
    """Give one persisted run a stable OpenClaw session without exposing its id."""
    if not run_id:
        return None
    prompt_version = os.getenv("LEAD_FINDER_PROMPT_CACHE_KEY", "possible-os-lead-finder-v1")
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:24]
    prefix = "".join(char for char in prompt_version if char.isalnum() or char in "-_")[:32]
    return f"{prefix or 'lead-finder'}:{digest}"


def _normalized_action(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"type": "reason", "tool": None, "arguments": {}}
    action_type = str(value.get("type") or "reason")
    if action_type != "tool_call":
        return {"type": "reason", "tool": None, "arguments": {}}
    tool = value.get("tool")
    arguments = value.get("arguments")
    return {
        "type": "tool_call",
        "tool": str(tool or "")[:128],
        "arguments": arguments if isinstance(arguments, dict) else {},
    }


async def run_lead_finder_step(
    *,
    context: dict[str, Any],
    user_direction: str,
    reload_baseline: bool = True,
    run_id: str | None = None,
    attempt_observer: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run one Lead Finder reasoning or tool-request transition through OpenClaw."""
    current = (
        _authoritative_context(context, user_direction)
        if reload_baseline
        else _context_for_persisted_run(context, user_direction)
    )
    result = await call_skill_json(
        skill_path=SKILL_PATH,
        model=MODEL,
        payload=_gateway_payload(current),
        required_fields=[
            "step_name",
            "summary",
            "reasoning",
            "state_updates",
            "next_step",
            "is_complete",
            "action",
        ],
        max_tokens=int(os.getenv("LEAD_FINDER_MAX_TOKENS", "2000")),
        timeout_s=int(os.getenv("LEAD_FINDER_GATEWAY_TIMEOUT_S", "420")),
        retries=int(os.getenv("LEAD_FINDER_GATEWAY_RETRIES", "1")),
        gateway_user=_cache_session_user(run_id),
        attempt_observer=attempt_observer,
    )

    parsed = result.parsed
    updates = parsed.get("state_updates")
    if not isinstance(updates, dict):
        updates = {}
    action = _normalized_action(parsed.get("action"))
    prior_working_state = (
        current.get("agent_state", {}).get("working_state")
        if isinstance(current.get("agent_state"), dict)
        else {}
    )
    prior_working_state = prior_working_state if isinstance(prior_working_state, dict) else {}
    prior_tool_history = prior_working_state.get("tool_history")
    prior_tool_history = list(prior_tool_history) if isinstance(prior_tool_history, list) else []
    tool_execution: dict[str, Any] | None = None
    if action["type"] == "tool_call":
        execute = tool_executor
        if execute is None:
            async def execute(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                started_at = _now()
                try:
                    payload = await execute_lead_finder_tool(
                        tool_name,
                        arguments,
                        tool_history=prior_tool_history,
                    )
                    return {
                        "id": None,
                        "tool_name": tool_name,
                        "status": "completed",
                        "arguments": arguments,
                        "result": payload,
                        "error": None,
                        "started_at": started_at,
                        "completed_at": _now(),
                    }
                except Exception as exc:
                    return {
                        "id": None,
                        "tool_name": tool_name,
                        "status": "failed",
                        "arguments": arguments,
                        "result": {},
                        "error": str(exc),
                        "started_at": started_at,
                        "completed_at": _now(),
                    }
        tool_execution = await execute(action["tool"], action["arguments"])

    agent_state = current["agent_state"]
    completed_steps = int(agent_state.get("completed_steps") or 0) + 1
    # A tool result arrives after the model response, so it must be inspected on
    # a later debug click before the run can legitimately complete.
    is_complete = bool(parsed.get("is_complete")) and tool_execution is None
    transition = {
        "step_name": str(parsed.get("step_name") or "Lead Finder reasoning step")[:255],
        "summary": str(parsed.get("summary") or "")[:4000],
        "reasoning": str(parsed.get("reasoning") or "")[:8000],
        "state_updates": updates,
        "next_step": str(parsed.get("next_step") or "")[:1000],
        "is_complete": is_complete,
        "action": action,
        "tool_execution": tool_execution,
        "completed_at": _now(),
    }
    working_state = _merge_working_state(
        agent_state.get("working_state") if isinstance(agent_state.get("working_state"), dict) else {},
        updates,
    )
    if tool_execution:
        history = working_state.get("tool_history")
        history = list(history) if isinstance(history, list) else []
        working_state["tool_history"] = (history + [tool_execution])[-8:]
        lead = (
            tool_execution.get("result", {}).get("lead")
            if isinstance(tool_execution.get("result"), dict)
            else None
        )
        if (
            tool_execution.get("tool_name") == "lead_finder.add_researched_lead"
            and tool_execution.get("status") == "completed"
            and isinstance(lead, dict)
        ):
            found_leads = working_state.get("found_leads")
            found_leads = list(found_leads) if isinstance(found_leads, list) else []
            working_state["found_leads"] = (found_leads + [lead])[-100:]
    current["agent_state"] = {
        **agent_state,
        "status": "completed" if is_complete else "paused",
        "completed_steps": completed_steps,
        "next_step": None if is_complete else transition["next_step"],
        "working_state": working_state,
        "last_step": transition,
    }
    return {
        "context": current,
        "transition": transition,
        "gateway": {
            "used_llm": True,
            "model": result.model,
            "skill_path": str(SKILL_PATH.relative_to(REPO_ROOT)),
            "usage": result.usage or {},
            "prompt_cache": {
                **prompt_cache_metrics(result.usage),
                "session_scope": "run" if run_id else "stateless",
            },
            "raw_response": result.raw_response,
        },
    }


class LeadFinderNotFoundError(LookupError):
    pass


class LeadFinderRunBusyError(RuntimeError):
    pass


class LeadFinderRunStateError(RuntimeError):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [prefix or "root"]
    paths: list[str] = []
    for key in sorted(set(before) | set(after)):
        child = f"{prefix}.{key}" if prefix else key
        paths.extend(_changed_paths(before.get(key), after.get(key), child))
    return paths


async def ensure_lead_finder_tables() -> None:
    global _tables_checked
    if _tables_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(LeadFinderRunRow.__table__.create, checkfirst=True)
        await conn.run_sync(LeadFinderStepRow.__table__.create, checkfirst=True)
        await conn.run_sync(LeadFinderAttemptRow.__table__.create, checkfirst=True)
        await conn.run_sync(LeadFinderToolCallRow.__table__.create, checkfirst=True)
    _tables_checked = True


def _run_dict(row: LeadFinderRunRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "debug_mode": row.debug_mode,
        "user_direction": row.user_direction,
        "job": row.job_json or {},
        "baseline_context": row.baseline_context_json or {},
        "baseline_context_hash": row.baseline_context_hash,
        "current_context": row.current_context_json or {},
        "current_step": row.current_step,
        "next_step": row.next_step,
        "error": row.error,
        "restarted_from_run_id": row.restarted_from_run_id,
        "completed_at": _iso(row.completed_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _attempt_dict(row: LeadFinderAttemptRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_id": row.step_id,
        "attempt_number": row.attempt_number,
        "status": row.status,
        "model": row.model,
        "request": row.request_json or {},
        "response_raw": row.response_raw,
        "response_parsed": row.response_parsed_json or {},
        "usage": row.usage_json or {},
        "prompt_cache": prompt_cache_metrics(row.usage_json),
        "http_status": row.http_status,
        "error": row.error,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def _tool_call_dict(row: LeadFinderToolCallRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "step_id": row.step_id,
        "tool_name": row.tool_name,
        "status": row.status,
        "arguments": row.arguments_json or {},
        "result": row.result_json or {},
        "error": row.error,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def _step_dict(
    row: LeadFinderStepRow,
    attempts: list[LeadFinderAttemptRow] | None = None,
    tool_calls: list[LeadFinderToolCallRow] | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "step_number": row.step_number,
        "request_id": row.request_id,
        "status": row.status,
        "user_direction": row.user_direction,
        "context_before": row.context_before_json or {},
        "request": row.request_json or {},
        "response_parsed": row.response_parsed_json or {},
        "response_raw": row.response_raw,
        "context_after": row.context_after_json or {},
        "context_diff": row.context_diff_json or {},
        "model": row.model,
        "skill_path": row.skill_path,
        "usage": row.usage_json or {},
        "prompt_cache": prompt_cache_metrics(row.usage_json),
        "error": row.error,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "created_at": _iso(row.created_at),
        "attempts": [_attempt_dict(item) for item in (attempts or [])],
        "tool_calls": [_tool_call_dict(item) for item in (tool_calls or [])],
    }


def _build_lead_finder_run_row(
    *,
    user_direction: str = "",
    restarted_from_run_id: str | None = None,
) -> LeadFinderRunRow:
    baseline = load_lead_finder_context()
    baseline["user_direction"] = user_direction.strip()
    return LeadFinderRunRow(
        id=f"lfr_{uuid.uuid4().hex}",
        status="ready",
        debug_mode=True,
        user_direction=user_direction.strip(),
        job_json=deepcopy(baseline["job"]),
        baseline_context_json=deepcopy(baseline["baseline_context"]),
        baseline_context_hash=_stable_hash({
            "job": baseline["job"],
            "baseline_context": baseline["baseline_context"],
        }),
        current_context_json=baseline,
        current_step=0,
        next_step=baseline["agent_state"]["next_step"],
        restarted_from_run_id=restarted_from_run_id,
    )


async def create_lead_finder_run(
    *,
    user_direction: str = "",
    restarted_from_run_id: str | None = None,
) -> dict[str, Any]:
    await ensure_lead_finder_tables()
    row = _build_lead_finder_run_row(
        user_direction=user_direction,
        restarted_from_run_id=restarted_from_run_id,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return _run_dict(row)


async def reset_all_lead_finder_runs(*, user_direction: str = "") -> dict[str, Any]:
    """Delete all Lead Finder history and atomically create one fresh step-0 run."""
    await ensure_lead_finder_tables()
    row = _build_lead_finder_run_row(user_direction=user_direction)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            deleted = {
                "runs": int((await session.scalar(
                    select(func.count()).select_from(LeadFinderRunRow)
                )) or 0),
                "steps": int((await session.scalar(
                    select(func.count()).select_from(LeadFinderStepRow)
                )) or 0),
                "attempts": int((await session.scalar(
                    select(func.count()).select_from(LeadFinderAttemptRow)
                )) or 0),
                "tool_calls": int((await session.scalar(
                    select(func.count()).select_from(LeadFinderToolCallRow)
                )) or 0),
            }
            await session.execute(delete(LeadFinderRunRow))
            session.add(row)
        await session.refresh(row)
    return {"deleted": deleted, "run": _run_dict(row)}


async def list_lead_finder_runs(*, limit: int = 25) -> list[dict[str, Any]]:
    await ensure_lead_finder_tables()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(LeadFinderRunRow).order_by(desc(LeadFinderRunRow.created_at)).limit(limit)
            )
        ).scalars().all()
    return [_run_dict(row) for row in rows]


async def get_lead_finder_step(step_id: str) -> dict[str, Any] | None:
    await ensure_lead_finder_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(LeadFinderStepRow, step_id)
        if not row:
            return None
        attempts = (
            await session.execute(
                select(LeadFinderAttemptRow)
                .where(LeadFinderAttemptRow.step_id == step_id)
                .order_by(LeadFinderAttemptRow.attempt_number)
            )
        ).scalars().all()
        tool_calls = (
            await session.execute(
                select(LeadFinderToolCallRow)
                .where(LeadFinderToolCallRow.step_id == step_id)
                .order_by(LeadFinderToolCallRow.started_at)
            )
        ).scalars().all()
    return _step_dict(row, list(attempts), list(tool_calls))


async def get_lead_finder_run(run_id: str) -> dict[str, Any] | None:
    await ensure_lead_finder_tables()
    async with AsyncSessionLocal() as session:
        run = await session.get(LeadFinderRunRow, run_id)
        if not run:
            return None
        steps = (
            await session.execute(
                select(LeadFinderStepRow)
                .where(LeadFinderStepRow.run_id == run_id)
                .order_by(LeadFinderStepRow.step_number)
            )
        ).scalars().all()
        step_ids = [step.id for step in steps]
        attempts = []
        tool_calls = []
        if step_ids:
            attempts = (
                await session.execute(
                    select(LeadFinderAttemptRow)
                    .where(LeadFinderAttemptRow.step_id.in_(step_ids))
                    .order_by(LeadFinderAttemptRow.step_id, LeadFinderAttemptRow.attempt_number)
                )
            ).scalars().all()
            tool_calls = (
                await session.execute(
                    select(LeadFinderToolCallRow)
                    .where(LeadFinderToolCallRow.step_id.in_(step_ids))
                    .order_by(LeadFinderToolCallRow.step_id, LeadFinderToolCallRow.started_at)
                )
            ).scalars().all()
    by_step: dict[str, list[LeadFinderAttemptRow]] = {}
    for attempt in attempts:
        by_step.setdefault(attempt.step_id, []).append(attempt)
    tools_by_step: dict[str, list[LeadFinderToolCallRow]] = {}
    for tool_call in tool_calls:
        tools_by_step.setdefault(tool_call.step_id, []).append(tool_call)
    payload = _run_dict(run)
    payload["steps"] = [
        _step_dict(step, by_step.get(step.id, []), tools_by_step.get(step.id, []))
        for step in steps
    ]
    return payload


async def queue_lead_finder_step(
    *,
    run_id: str,
    request_id: str,
    user_direction: str,
) -> dict[str, Any]:
    await ensure_lead_finder_tables()
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(LeadFinderStepRow).where(LeadFinderStepRow.request_id == request_id)
            )
        ).scalar_one_or_none()
        if existing:
            if existing.run_id != run_id:
                raise LeadFinderRunStateError("request_id_already_used_for_another_run")
            payload = _step_dict(existing)
            payload["_created"] = False
            return payload

        run = (
            await session.execute(
                select(LeadFinderRunRow)
                .where(LeadFinderRunRow.id == run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if not run:
            raise LeadFinderNotFoundError("lead_finder_run_not_found")
        active = (
            await session.execute(
                select(LeadFinderStepRow).where(
                    LeadFinderStepRow.run_id == run_id,
                    LeadFinderStepRow.status.in_(ACTIVE_STEP_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if active:
            raise LeadFinderRunBusyError(active.id)
        if run.status in {"completed", "failed"}:
            raise LeadFinderRunStateError(f"run_is_{run.status}; restart_from_step_1")

        direction = user_direction.strip()
        before = _context_for_persisted_run(run.current_context_json or {}, direction)
        step = LeadFinderStepRow(
            id=f"lfs_{uuid.uuid4().hex}",
            run_id=run_id,
            step_number=run.current_step + 1,
            request_id=request_id,
            status="queued",
            user_direction=direction,
            context_before_json=before,
            request_json=_gateway_payload(before),
        )
        session.add(step)
        run.status = "queued"
        run.user_direction = direction
        run.current_context_json = before
        run.error = None
        run.updated_at = datetime.now(timezone.utc)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise LeadFinderRunBusyError("duplicate_step_request") from exc
    payload = _step_dict(step)
    payload["_created"] = True
    return payload


async def _attempt_observer(step_id: str, base_attempt: int, event: dict[str, Any]) -> None:
    number = base_attempt + int(event.get("attempt") or 1)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            step = await session.get(LeadFinderStepRow, step_id)
            if not step:
                return
            attempt = (
                await session.execute(
                    select(LeadFinderAttemptRow).where(
                        LeadFinderAttemptRow.step_id == step_id,
                        LeadFinderAttemptRow.attempt_number == number,
                    )
                )
            ).scalar_one_or_none()
            phase = str(event.get("phase") or "")
            if phase == "started":
                if not attempt:
                    attempt = LeadFinderAttemptRow(
                        step_id=step_id,
                        attempt_number=number,
                        status="running",
                        model=str(event.get("model") or MODEL),
                        request_json=event.get("request") if isinstance(event.get("request"), dict) else {},
                        started_at=now,
                    )
                    session.add(attempt)
                step.status = "retrying" if number > 1 else "running"
                step.model = str(event.get("model") or MODEL)
            elif attempt:
                attempt.status = "completed" if phase == "completed" else str(event.get("status") or "failed")
                attempt.response_raw = str(event.get("raw_response") or "")
                attempt.response_parsed_json = event.get("parsed_response") if isinstance(event.get("parsed_response"), dict) else {}
                attempt.usage_json = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                attempt.http_status = event.get("http_status") if isinstance(event.get("http_status"), int) else None
                attempt.error = str(event.get("error") or "") or None
                attempt.completed_at = now
                if phase == "failed" and event.get("will_retry"):
                    step.status = "retrying"


async def _execute_persisted_tool_call(
    step_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    tool_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist a tool call before execution and its complete result afterward."""
    row = LeadFinderToolCallRow(
        id=f"lft_{uuid.uuid4().hex}",
        step_id=step_id,
        tool_name=tool_name[:128],
        status="running",
        arguments_json=deepcopy(arguments),
        result_json={},
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    try:
        result = await execute_lead_finder_tool(
            tool_name,
            arguments,
            tool_history=tool_history,
        )
        status = "completed"
        error = None
    except Exception as exc:
        result = {}
        status = "failed"
        error = str(exc)[:4000]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            persisted = await session.get(LeadFinderToolCallRow, row.id)
            if not persisted:
                return {
                    "id": row.id,
                    "step_id": step_id,
                    "tool_name": tool_name,
                    "status": status,
                    "arguments": arguments,
                    "result": result,
                    "error": error,
                    "started_at": _iso(row.started_at),
                    "completed_at": _now(),
                }
            persisted.status = status
            persisted.result_json = result
            persisted.error = error
            persisted.completed_at = datetime.now(timezone.utc)
        await session.refresh(persisted)
        return _tool_call_dict(persisted)


async def execute_lead_finder_step(step_id: str) -> None:
    await ensure_lead_finder_tables()
    async with AsyncSessionLocal() as session:
        async with session.begin():
            step = (
                await session.execute(
                    select(LeadFinderStepRow)
                    .where(LeadFinderStepRow.id == step_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if not step or step.status not in {"queued", "interrupted"}:
                return
            run = await session.get(LeadFinderRunRow, step.run_id)
            if not run:
                return
            step.status = "running"
            step.started_at = datetime.now(timezone.utc)
            run.status = "running"
            run.updated_at = datetime.now(timezone.utc)
            base_attempt = int((await session.scalar(
                select(func.count()).select_from(LeadFinderAttemptRow).where(LeadFinderAttemptRow.step_id == step_id)
            )) or 0)
            before = deepcopy(step.context_before_json or {})
            direction = step.user_direction

    async def observe(event: dict[str, Any]) -> None:
        await _attempt_observer(step_id, base_attempt, event)

    async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        working_state = before.get("agent_state", {}).get("working_state", {})
        history = working_state.get("tool_history") if isinstance(working_state, dict) else []
        return await _execute_persisted_tool_call(
            step_id,
            tool_name,
            arguments,
            tool_history=list(history) if isinstance(history, list) else [],
        )

    try:
        result = await run_lead_finder_step(
            context=before,
            user_direction=direction,
            reload_baseline=False,
            run_id=step.run_id,
            attempt_observer=observe,
            tool_executor=execute_tool,
        )
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                step = await session.get(LeadFinderStepRow, step_id)
                if not step:
                    return
                run = await session.get(LeadFinderRunRow, step.run_id)
                step.status = "failed"
                step.error = str(exc)
                step.completed_at = datetime.now(timezone.utc)
                if run:
                    run.status = "failed"
                    run.error = str(exc)
                    run.updated_at = datetime.now(timezone.utc)
        return

    after = result["context"]
    transition = result["transition"]
    gateway = result["gateway"]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            step = await session.get(LeadFinderStepRow, step_id)
            if not step:
                return
            run = (
                await session.execute(
                    select(LeadFinderRunRow)
                    .where(LeadFinderRunRow.id == step.run_id)
                    .with_for_update()
                )
            ).scalar_one()
            step.status = "completed"
            step.response_parsed_json = transition
            step.response_raw = str(gateway.get("raw_response") or "")
            step.context_after_json = after
            step.context_diff_json = {"changed_paths": _changed_paths(before, after)}
            step.model = str(gateway.get("model") or MODEL)
            step.skill_path = str(gateway.get("skill_path") or "")
            step.usage_json = gateway.get("usage") if isinstance(gateway.get("usage"), dict) else {}
            step.completed_at = datetime.now(timezone.utc)
            step.error = None
            run.current_context_json = after
            run.current_step = step.step_number
            run.next_step = after.get("agent_state", {}).get("next_step")
            run.status = "completed" if transition.get("is_complete") else "paused"
            run.completed_at = datetime.now(timezone.utc) if transition.get("is_complete") else None
            run.error = None
            run.updated_at = datetime.now(timezone.utc)


async def restart_lead_finder_run(
    *,
    run_id: str,
    user_direction: str | None = None,
) -> dict[str, Any]:
    await ensure_lead_finder_tables()
    async with AsyncSessionLocal() as session:
        prior = await session.get(LeadFinderRunRow, run_id)
        if not prior:
            raise LeadFinderNotFoundError("lead_finder_run_not_found")
        direction = prior.user_direction if user_direction is None else user_direction.strip()
    return await create_lead_finder_run(
        user_direction=direction,
        restarted_from_run_id=run_id,
    )


async def recover_interrupted_lead_finder_steps() -> list[str]:
    """Requeue reasoning-only steps interrupted by a backend restart."""
    await ensure_lead_finder_tables()
    recovered: list[str] = []
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            steps = (
                await session.execute(
                    select(LeadFinderStepRow).where(
                        LeadFinderStepRow.status.in_({"queued", "running", "retrying"})
                    )
                )
            ).scalars().all()
            for step in steps:
                step.status = "queued"
                step.error = "Recovered after backend restart."
                attempts = (
                    await session.execute(
                        select(LeadFinderAttemptRow).where(
                            LeadFinderAttemptRow.step_id == step.id,
                            LeadFinderAttemptRow.status == "running",
                        )
                    )
                ).scalars().all()
                for attempt in attempts:
                    attempt.status = "interrupted"
                    attempt.error = "Backend restarted before the gateway response was persisted."
                    attempt.completed_at = now
                tool_calls = (
                    await session.execute(
                        select(LeadFinderToolCallRow).where(
                            LeadFinderToolCallRow.step_id == step.id,
                            LeadFinderToolCallRow.status == "running",
                        )
                    )
                ).scalars().all()
                for tool_call in tool_calls:
                    tool_call.status = "interrupted"
                    tool_call.error = "Backend restarted before the tool result was persisted."
                    tool_call.completed_at = now
                run = await session.get(LeadFinderRunRow, step.run_id)
                if run:
                    run.status = "queued"
                    run.error = None
                    run.updated_at = now
                recovered.append(step.id)
    return recovered
