"""Public data-return receiver and operator readout."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.services.data_returned import (
    build_data_returned_noop_script,
    get_data_returned_script as load_data_returned_script,
    list_data_returned,
    prune_data_returned,
    record_data_returned,
    save_data_returned_script,
    set_data_returned_script_enabled,
)


router = APIRouter(tags=["data-returned"])


class DataReturnedScriptUpdate(BaseModel):
    script: str = Field(min_length=1, max_length=100_000)


class DataReturnedScriptEnabledUpdate(BaseModel):
    enabled: bool

_HEADER_ALLOWLIST = {
    "content-type",
    "user-agent",
    "referer",
    "origin",
    "x-forwarded-for",
    "x-real-ip",
    "x-request-id",
}


def _safe_headers(request: Request) -> dict[str, str]:
    return {
        key.lower(): value[:2048]
        for key, value in request.headers.items()
        if key.lower() in _HEADER_ALLOWLIST
    }


def _callback_url(request: Request) -> str:
    public_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base:
        public_base = str(request.base_url).rstrip("/")
    return f"{public_base}/datareturned"


@router.post("/datareturned")
async def post_data_returned(request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, (dict, list)):
        raise HTTPException(status_code=422, detail="payload_must_be_json_object_or_array")

    source_ip = request.client.host if request.client else None
    event = await record_data_returned(
        payload=payload,
        headers=_safe_headers(request),
        source_ip=source_ip,
        user_agent=request.headers.get("user-agent"),
        content_type=request.headers.get("content-type"),
    )
    return {"status": "received", "event": event}


@router.get("/datareturned/script", response_class=PlainTextResponse)
async def get_data_returned_script(request: Request):
    stored = await load_data_returned_script(_callback_url(request))
    return PlainTextResponse(
        stored["script"]
        if stored["enabled"]
        else build_data_returned_noop_script(_callback_url(request)),
        media_type="text/x-shellscript",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="possibleos-datareturned.sh"',
        },
    )


@router.get("/api/datareturned/script")
async def get_data_returned_script_config(request: Request):
    return await load_data_returned_script(_callback_url(request))


@router.put("/api/datareturned/script")
async def put_data_returned_script(update: DataReturnedScriptUpdate):
    try:
        saved = await save_data_returned_script(update.script)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return saved


@router.put("/api/datareturned/script/enabled")
async def put_data_returned_script_enabled(
    update: DataReturnedScriptEnabledUpdate,
    request: Request,
):
    return await set_data_returned_script_enabled(
        enabled=update.enabled,
        callback_url=_callback_url(request),
    )


@router.get("/api/datareturned")
async def get_data_returned(limit: int = Query(100, ge=1, le=100)):
    events = await list_data_returned(limit=limit)
    return {"events": events, "total": len(events)}


@router.post("/api/datareturned/prune")
async def post_data_returned_prune():
    return await prune_data_returned()
