"""Operator and agent API for the dedicated Possible OS Codex app-server."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.codex_app_server import (
    CodexAppServerError,
    codex_app_server_status,
    list_codex_models,
    run_codex_turn,
)


router = APIRouter(prefix="/api/codex-gateway", tags=["codex-gateway"])


class CodexTurnRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    prompt: str = Field(..., min_length=1, max_length=250_000)
    instructions: str | None = Field(default=None, max_length=250_000)
    thread_id: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    effort: Literal["minimal", "low", "medium", "high", "xhigh", "max", "ultra"] | None = None
    web_search: Literal["disabled", "cached", "indexed", "live"] = "disabled"
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int = Field(default=300, ge=10, le=900)


@router.get("/status")
async def get_codex_gateway_status():
    return await codex_app_server_status()


@router.get("/models")
async def get_codex_gateway_models():
    try:
        return await list_codex_models()
    except CodexAppServerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/turn")
async def create_codex_gateway_turn(req: CodexTurnRequest):
    try:
        result = await run_codex_turn(
            agent_id=req.agent_id,
            prompt=req.prompt,
            instructions=req.instructions,
            thread_id=req.thread_id,
            model=req.model,
            effort=req.effort,
            output_schema=req.output_schema,
            web_search=req.web_search,
            timeout_s=req.timeout_seconds,
        )
    except CodexAppServerError as exc:
        detail = str(exc)
        status_code = 504 if "timeout" in detail.lower() else 502
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {
        "provider": "codex",
        "model": result.model,
        "thread_id": result.thread_id,
        "turn_id": result.turn_id,
        "text": result.text,
        "usage": result.usage,
        "latency": result.latency,
        "events": result.events,
    }
