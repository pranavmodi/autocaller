"""Lead Finder debug-context and single-step LLM endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.lead_finder import (
    LeadFinderNotFoundError,
    LeadFinderRunBusyError,
    LeadFinderRunStateError,
    LeadFinderSessionNotFoundError,
    LeadFinderSessionStateError,
    create_lead_finder_run,
    execute_lead_finder_step,
    get_lead_finder_llm_session,
    get_lead_finder_run,
    get_lead_finder_step,
    list_lead_finder_runs,
    load_lead_finder_context,
    queue_lead_finder_step,
    reset_all_lead_finder_runs,
    restart_lead_finder_run,
    run_lead_finder_step,
    start_lead_finder_auto_run,
    stop_lead_finder_auto_run,
)
from app.services.llm_gateway import LLMGatewayError
from app.services.lead_finder_tools import (
    LeadFinderToolError,
    execute_lead_finder_tool,
    lead_finder_tool_catalog,
)


router = APIRouter(prefix="/api/lead-finder", tags=["lead-finder"])


class LeadFinderStepRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    user_direction: str = Field(default="", max_length=10_000)


class LeadFinderRunCreateRequest(BaseModel):
    user_direction: str = Field(default="", max_length=10_000)


class LeadFinderRunStepRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=64)
    user_direction: str = Field(default="", max_length=10_000)


class LeadFinderRestartRequest(BaseModel):
    user_direction: str | None = Field(default=None, max_length=10_000)


class LeadFinderAutoRunRequest(BaseModel):
    user_direction: str | None = Field(default=None, max_length=10_000)
    max_steps: int = Field(default=25, ge=1, le=100)


class LeadFinderToolExecuteRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/context")
async def lead_finder_context():
    try:
        return {"context": load_lead_finder_context()}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"lead_finder_context_unavailable: {exc}") from exc


@router.get("/tools")
async def lead_finder_tools():
    return {"tools": lead_finder_tool_catalog()}


@router.post("/tools/execute")
async def execute_tool(req: LeadFinderToolExecuteRequest):
    try:
        result = await execute_lead_finder_tool(req.tool, req.arguments)
    except LeadFinderToolError as exc:
        detail = str(exc)
        upstream_failure = detail.startswith(("mission_control_", "web_research_"))
        status_code = 502 if upstream_failure else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {"tool": req.tool, "arguments": req.arguments, "result": result}


@router.post("/step")
async def lead_finder_step(req: LeadFinderStepRequest):
    try:
        return await run_lead_finder_step(
            context=req.context,
            user_direction=req.user_direction,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"lead_finder_context_unavailable: {exc}") from exc
    except LLMGatewayError as exc:
        raise HTTPException(status_code=502, detail=f"openclaw_gateway_error: {exc}") from exc


@router.get("/runs")
async def lead_finder_runs(limit: int = Query(25, ge=1, le=100)):
    return {"runs": await list_lead_finder_runs(limit=limit)}


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(req: LeadFinderRunCreateRequest):
    return {"run": await create_lead_finder_run(user_direction=req.user_direction)}


@router.post("/runs/reset-all", status_code=status.HTTP_201_CREATED)
async def reset_all_runs(req: LeadFinderRunCreateRequest):
    return await reset_all_lead_finder_runs(user_direction=req.user_direction)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = await get_lead_finder_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="lead_finder_run_not_found")
    return {"run": run}


@router.post("/runs/{run_id}/auto-run", status_code=status.HTTP_202_ACCEPTED)
async def start_auto_run(
    run_id: str,
    req: LeadFinderAutoRunRequest,
    background_tasks: BackgroundTasks,
):
    try:
        result = await start_lead_finder_auto_run(
            run_id=run_id,
            user_direction=req.user_direction,
            max_steps=req.max_steps,
        )
    except LeadFinderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LeadFinderRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    created = bool(result.pop("_created", False))
    step = result.get("step") or {}
    if created and step.get("id"):
        background_tasks.add_task(execute_lead_finder_step, step["id"])
    return result


@router.post("/runs/{run_id}/auto-run/stop")
async def stop_auto_run(run_id: str):
    try:
        run = await stop_lead_finder_auto_run(run_id=run_id)
    except LeadFinderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run": run}


@router.get("/runs/{run_id}/llm-session")
async def get_llm_session(run_id: str):
    try:
        return {"session": await get_lead_finder_llm_session(run_id)}
    except (LeadFinderNotFoundError, LeadFinderSessionNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LeadFinderSessionStateError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/runs/{run_id}/steps", status_code=status.HTTP_202_ACCEPTED)
async def create_run_step(
    run_id: str,
    req: LeadFinderRunStepRequest,
    background_tasks: BackgroundTasks,
):
    try:
        step = await queue_lead_finder_step(
            run_id=run_id,
            request_id=req.request_id,
            user_direction=req.user_direction,
        )
    except LeadFinderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LeadFinderRunBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "lead_finder_run_busy", "active_step_id": str(exc)},
        ) from exc
    except LeadFinderRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    created = bool(step.pop("_created", False))
    if created:
        background_tasks.add_task(execute_lead_finder_step, step["id"])
    return {"step": step}


@router.get("/steps/{step_id}")
async def get_step(step_id: str):
    step = await get_lead_finder_step(step_id)
    if not step:
        raise HTTPException(status_code=404, detail="lead_finder_step_not_found")
    return {"step": step}


@router.post("/runs/{run_id}/restart", status_code=status.HTTP_201_CREATED)
async def restart_run(run_id: str, req: LeadFinderRestartRequest):
    try:
        run = await restart_lead_finder_run(
            run_id=run_id,
            user_direction=req.user_direction,
        )
    except LeadFinderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run": run}
