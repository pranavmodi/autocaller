"""Background scheduler for explicitly approved durable email actions."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import AgentActionRow
from app.services.action_execution import (
    _record_action_event,
    execute_action,
)
from app.services.master_agent import ensure_agent_tables
from app.services.product_traces import safe_record_product_trace

logger = logging.getLogger(__name__)

EXPIRE_AFTER = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class ScheduledActionSchedulerState:
    running: bool = False
    last_tick_at: datetime | None = None
    last_error: str | None = None
    last_result: dict[str, Any] = field(default_factory=dict)


SCHEDULER_STATE = ScheduledActionSchedulerState()


def classify_scheduled_action_rows(
    rows: list[AgentActionRow],
    *,
    now: datetime,
) -> dict[str, list[str]]:
    """Split due rows into sendable due actions and stale expired actions."""
    cutoff = _as_utc(now) - EXPIRE_AFTER
    expired_ids: list[str] = []
    due_ids: list[str] = []
    for row in rows:
        if row.scheduled_for is None:
            continue
        scheduled_for = _as_utc(row.scheduled_for)
        if scheduled_for > _as_utc(now):
            continue
        if scheduled_for < cutoff:
            expired_ids.append(row.id)
        else:
            due_ids.append(row.id)
    return {"due_ids": due_ids, "expired_ids": expired_ids}


async def get_due_scheduled_action_candidates(
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> dict[str, list[str]]:
    await ensure_agent_tables()
    tick_now = _as_utc(now or _utcnow())
    safe_limit = max(1, min(int(limit), 100))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentActionRow)
            .where(
                AgentActionRow.status == "approved",
                AgentActionRow.scheduled_for.is_not(None),
                AgentActionRow.scheduled_for <= tick_now,
            )
            .order_by(AgentActionRow.scheduled_for.asc(), AgentActionRow.id.asc())
            .limit(safe_limit)
        )).scalars().all()
    return classify_scheduled_action_rows(list(rows), now=tick_now)


async def count_pending_scheduled_actions(*, now: datetime | None = None) -> int:
    await ensure_agent_tables()
    tick_now = _as_utc(now or _utcnow())
    async with AsyncSessionLocal() as session:
        return int((await session.execute(
            select(func.count())
            .select_from(AgentActionRow)
            .where(
                AgentActionRow.status == "approved",
                AgentActionRow.scheduled_for.is_not(None),
                AgentActionRow.scheduled_for >= tick_now,
            )
        )).scalar_one() or 0)


async def count_due_scheduled_actions(*, now: datetime | None = None) -> int:
    await ensure_agent_tables()
    tick_now = _as_utc(now or _utcnow())
    async with AsyncSessionLocal() as session:
        return int((await session.execute(
            select(func.count())
            .select_from(AgentActionRow)
            .where(
                AgentActionRow.status == "approved",
                AgentActionRow.scheduled_for.is_not(None),
                AgentActionRow.scheduled_for <= tick_now,
            )
        )).scalar_one() or 0)


async def expire_scheduled_action(action_id: str, *, actor: str, now: datetime | None = None) -> dict[str, Any]:
    await ensure_agent_tables()
    tick_now = _as_utc(now or _utcnow())
    async with AsyncSessionLocal() as session:
        action = await session.get(AgentActionRow, action_id)
        if not action:
            return {"id": action_id, "expired": False, "reason": "not_found"}
        if action.status != "approved" or not action.scheduled_for:
            return {"id": action_id, "expired": False, "reason": "not_pending_scheduled"}
        scheduled_for = _as_utc(action.scheduled_for)
        if scheduled_for >= tick_now - EXPIRE_AFTER:
            return {"id": action_id, "expired": False, "reason": "not_stale"}
        action.status = "expired"
        action.completed_at = tick_now
        action.error = "Scheduled action expired: scheduled_for is more than 24 hours in the past."
        action.execution_result_json = {
            "executed": False,
            "expired": True,
            "scheduled_for": scheduled_for.isoformat(),
            "expired_at": tick_now.isoformat(),
        }
        await _record_action_event(
            session,
            action_id=action.id,
            event_type="action_expired",
            actor=actor,
            message=action.error,
            output_json=action.execution_result_json,
        )
        await session.commit()

    await safe_record_product_trace(
        actor_type="agent",
        actor_id=actor,
        event_type="action_expired",
        surface="actions",
        entity_type="agent_action",
        entity_id=action_id,
        output_json={"scheduled_for": scheduled_for.isoformat()},
    )
    return {"id": action_id, "expired": True}


async def tick_scheduled_actions(
    *,
    limit: int = 25,
    actor: str = "action-scheduler",
    now: datetime | None = None,
) -> dict[str, Any]:
    tick_now = _as_utc(now or _utcnow())
    candidates = await get_due_scheduled_action_candidates(now=tick_now, limit=limit)
    expired_results: list[dict[str, Any]] = []
    execution_results: list[dict[str, Any]] = []

    for action_id in candidates["expired_ids"]:
        try:
            expired_results.append(await expire_scheduled_action(action_id, actor=actor, now=tick_now))
        except Exception as exc:
            logger.exception("scheduled action expiration failed for %s", action_id)
            expired_results.append({"id": action_id, "expired": False, "error": str(exc)})

    for action_id in candidates["due_ids"]:
        try:
            execution_results.append(await execute_action(action_id, actor=actor))
        except Exception as exc:
            logger.exception("scheduled action execution failed for %s", action_id)
            execution_results.append({"action": {"id": action_id}, "executed": False, "error": str(exc)})

    result = {
        "tick_at": tick_now.isoformat(),
        "due_action_ids": candidates["due_ids"],
        "expired_action_ids": candidates["expired_ids"],
        "executed": sum(1 for row in execution_results if row.get("executed")),
        "expired": sum(1 for row in expired_results if row.get("expired")),
        "results": execution_results,
        "expired_results": expired_results,
    }
    SCHEDULER_STATE.last_tick_at = tick_now
    SCHEDULER_STATE.last_result = result
    SCHEDULER_STATE.last_error = None
    return result


async def scheduler_status() -> dict[str, Any]:
    now = _utcnow()
    return {
        "running": SCHEDULER_STATE.running,
        "last_tick_at": SCHEDULER_STATE.last_tick_at.isoformat() if SCHEDULER_STATE.last_tick_at else None,
        "last_error": SCHEDULER_STATE.last_error,
        "last_result": SCHEDULER_STATE.last_result,
        "pending_count": await count_pending_scheduled_actions(now=now),
        "due_count": await count_due_scheduled_actions(now=now),
    }


async def scheduled_action_loop(interval_seconds: int = 30):
    """Background loop. Wired into app.main lifespan."""
    logger.info("scheduled_action_loop starting (interval=%ss)", interval_seconds)
    SCHEDULER_STATE.running = True
    try:
        while True:
            try:
                result = await tick_scheduled_actions()
                if result["executed"] or result["expired"]:
                    logger.info(
                        "scheduled actions tick: %d executed, %d expired",
                        result["executed"],
                        result["expired"],
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                SCHEDULER_STATE.last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                logger.exception("scheduled_action_loop tick raised")
            await asyncio.sleep(interval_seconds)
    finally:
        SCHEDULER_STATE.running = False
