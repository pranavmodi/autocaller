"""AI-legible product traces for user and system actions."""
from __future__ import annotations

import contextvars
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.db.models import ProductTraceRow


logger = logging.getLogger(__name__)

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None,
)
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None,
)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def current_request_id() -> str | None:
    return request_id_var.get()


def current_trace_id() -> str | None:
    return trace_id_var.get()


def _json_object(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def trace_to_dict(row: ProductTraceRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "trace_id": row.trace_id,
        "session_id": row.session_id,
        "request_id": row.request_id,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "event_type": row.event_type,
        "surface": row.surface,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "parent_trace_id": row.parent_trace_id,
        "input": row.input_json or {},
        "output": row.output_json or {},
        "diff": row.diff_json or {},
        "context": row.context_json or {},
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create_product_trace(
    session: AsyncSession,
    *,
    actor_type: str,
    event_type: str,
    trace_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    actor_id: str | None = None,
    surface: str = "",
    entity_type: str | None = None,
    entity_id: str | None = None,
    parent_trace_id: str | None = None,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    diff_json: dict[str, Any] | None = None,
    context_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> ProductTraceRow:
    row = ProductTraceRow(
        trace_id=(trace_id or current_trace_id() or new_trace_id())[:64],
        session_id=(session_id or "")[:128] or None,
        request_id=(request_id or current_request_id() or "")[:64] or None,
        actor_type=(actor_type or "system")[:32],
        actor_id=(actor_id or "")[:128] or None,
        event_type=(event_type or "unknown")[:128],
        surface=(surface or "")[:128],
        entity_type=(entity_type or "")[:128] or None,
        entity_id=(entity_id or "")[:128] or None,
        parent_trace_id=(parent_trace_id or "")[:64] or None,
        input_json=_json_object(input_json),
        output_json=_json_object(output_json),
        diff_json=_json_object(diff_json),
        context_json=_json_object(context_json),
        metadata_json=_json_object(metadata_json),
    )
    session.add(row)
    await session.flush()
    return row


async def record_product_trace(**kwargs: Any) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = await create_product_trace(session, **kwargs)
        await session.commit()
        await session.refresh(row)
        return trace_to_dict(row)


async def safe_record_product_trace(**kwargs: Any) -> dict[str, Any] | None:
    try:
        return await record_product_trace(**kwargs)
    except Exception:
        logger.exception("failed to record product trace event_type=%s", kwargs.get("event_type"))
        return None


async def list_product_traces(
    *,
    limit: int = 50,
    trace_id: str | None = None,
    session_id: str | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    async with AsyncSessionLocal() as session:
        stmt = select(ProductTraceRow).order_by(ProductTraceRow.created_at.desc()).limit(limit)
        if trace_id:
            stmt = stmt.where(ProductTraceRow.trace_id == trace_id)
        if session_id:
            stmt = stmt.where(ProductTraceRow.session_id == session_id)
        if event_type:
            stmt = stmt.where(ProductTraceRow.event_type == event_type)
        if entity_type:
            stmt = stmt.where(ProductTraceRow.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(ProductTraceRow.entity_id == entity_id)
        rows = list((await session.execute(stmt)).scalars().all())
    return [trace_to_dict(row) for row in rows]


def iso_now() -> str:
    return datetime.utcnow().isoformat() + "Z"
