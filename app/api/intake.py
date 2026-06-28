"""Inbound PI intake API."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import Response

from app.services.inbound_intake import (
    get_intake_session,
    list_intake_sessions,
    prepare_telnyx_intake_call,
)


router = APIRouter(tags=["intake"])


def _public_base_url(request: Request) -> str:
    configured = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("APP_BASE_URL")
        or os.getenv("BASE_URL")
        or ""
    ).strip()
    if configured:
        return configured.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


@router.api_route("/api/telnyx/intake/inbound", methods=["GET", "POST"])
async def telnyx_intake_inbound(
    request: Request,
    From: Optional[str] = Form(None),
    To: Optional[str] = Form(None),
):
    """Dedicated Telnyx TeXML webhook for the after-hours intake product."""
    caller = From
    dialed = To
    if request.method == "GET":
        caller = caller or request.query_params.get("From") or request.query_params.get("from")
        dialed = dialed or request.query_params.get("To") or request.query_params.get("to")
    firm_name = request.query_params.get("firm") or os.getenv("INTAKE_FIRM_NAME", "")
    _, texml = await prepare_telnyx_intake_call(
        caller_number=caller,
        dialed_number=dialed,
        base_url=_public_base_url(request),
        firm_name=firm_name,
    )
    return Response(content=texml, media_type="application/xml")


@router.get("/api/intake/calls")
async def list_calls(limit: int = 20):
    return {"calls": await list_intake_sessions(limit=limit)}


@router.get("/api/intake/calls/{session_id}")
async def get_call(session_id: str):
    data = await get_intake_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="intake session not found")
    return data
