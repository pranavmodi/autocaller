"""Product trace endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.product_traces import list_product_traces, record_product_trace


router = APIRouter(prefix="/api/traces", tags=["traces"])


class ProductTraceCreateRequest(BaseModel):
    trace_id: str | None = Field(None, max_length=64)
    session_id: str | None = Field(None, max_length=128)
    request_id: str | None = Field(None, max_length=64)
    actor_type: str = Field("user", max_length=32)
    actor_id: str | None = Field(None, max_length=128)
    event_type: str = Field(..., max_length=128)
    surface: str = Field("", max_length=128)
    entity_type: str | None = Field(None, max_length=128)
    entity_id: str | None = Field(None, max_length=128)
    parent_trace_id: str | None = Field(None, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("")
async def create_trace(payload: ProductTraceCreateRequest):
    trace = await record_product_trace(
        trace_id=payload.trace_id,
        session_id=payload.session_id,
        request_id=payload.request_id,
        actor_type=payload.actor_type,
        actor_id=payload.actor_id,
        event_type=payload.event_type,
        surface=payload.surface,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        parent_trace_id=payload.parent_trace_id,
        input_json=payload.input,
        output_json=payload.output,
        diff_json=payload.diff,
        context_json=payload.context,
        metadata_json=payload.metadata,
    )
    return {"trace": trace}


@router.get("")
async def traces(
    limit: int = 50,
    trace_id: str | None = None,
    session_id: str | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
):
    return {
        "traces": await list_product_traces(
            limit=limit,
            trace_id=trace_id,
            session_id=session_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
        ),
    }
