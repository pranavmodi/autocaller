"""Master-agent and subagent coordination endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.master_agent import (
    create_agent_report,
    create_agent_task,
    create_research_scout_task,
    create_systems_health_agent_task,
    get_agent_config,
    get_agent_task,
    get_last_heartbeat_result,
    list_agent_capabilities,
    list_agent_events,
    list_agent_reports,
    list_agent_tasks,
    list_master_goals,
    record_agent_heartbeat,
    run_research_scout_task,
    run_systems_health_task,
    run_master_heartbeat,
    refresh_agent_capabilities,
    set_master_goal,
    update_agent_config,
    update_agent_task_status,
)


router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentTaskCreateRequest(BaseModel):
    assigned_agent: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)
    objective: str = Field(..., min_length=1)
    parent_task_id: str | None = Field(None, max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[Any] = Field(default_factory=list)
    forbidden_actions: list[Any] = Field(default_factory=list)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: list[Any] = Field(default_factory=list)
    verification_commands: list[Any] = Field(default_factory=list)
    risk_level: str = Field("low", max_length=16)
    requires_human_approval: bool = False
    priority: int = Field(50, ge=0, le=1000)
    heartbeat_interval_seconds: int = Field(300, ge=60, le=3600)
    deadline_at: str | None = None
    created_by: str = Field("operator", max_length=128)


class AgentTaskStatusRequest(BaseModel):
    status: str = Field(..., max_length=32)
    message: str = ""
    actor: str = Field("operator", max_length=128)


class AgentHeartbeatRequest(BaseModel):
    agent_id: str = Field(..., max_length=128)
    message: str = ""
    status: str | None = Field(None, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentReportRequest(BaseModel):
    agent_id: str = Field(..., max_length=128)
    status: str = Field("reported", max_length=32)
    summary: str = ""
    key_findings: list[Any] = Field(default_factory=list)
    actions_taken: list[Any] = Field(default_factory=list)
    artifacts: list[Any] = Field(default_factory=list)
    evidence: list[Any] = Field(default_factory=list)
    verification: list[Any] = Field(default_factory=list)
    risks: list[Any] = Field(default_factory=list)
    open_questions: list[Any] = Field(default_factory=list)
    recommended_next_actions: list[Any] = Field(default_factory=list)


class AgentConfigRequest(BaseModel):
    heartbeat_enabled: bool | None = None
    heartbeat_interval_seconds: int | None = Field(None, ge=60, le=3600)
    actor: str = Field("operator", max_length=128)


class MasterGoalSetRequest(BaseModel):
    goal: str = Field(..., min_length=1)
    why: str = ""
    next_actions: list[Any] = Field(default_factory=list)
    success_metric: str = ""
    time_horizon: str = "manual operating slice"
    confidence: str = Field("high", max_length=32)
    created_by: str = Field("operator", max_length=128)
    expires_hours: int = Field(24, ge=1, le=168)


@router.get("/status")
async def agents_status():
    config = await get_agent_config()
    return {
        "heartbeat_enabled": config["heartbeat_enabled"],
        "heartbeat_interval_seconds": config["heartbeat_interval_seconds"],
        "last_heartbeat": await get_last_heartbeat_result(),
    }


@router.patch("/config")
async def patch_agent_config(req: AgentConfigRequest):
    return {
        "config": await update_agent_config(
            heartbeat_enabled=req.heartbeat_enabled,
            heartbeat_interval_seconds=req.heartbeat_interval_seconds,
            actor=req.actor,
        ),
    }


@router.post("/heartbeat/run")
async def run_heartbeat():
    return {"heartbeat": await run_master_heartbeat(actor="operator")}


@router.get("/tasks")
async def tasks(
    status: str | None = Query(None),
    assigned_agent: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {
        "tasks": await list_agent_tasks(
            status=status,
            assigned_agent=assigned_agent,
            limit=limit,
        ),
    }


@router.post("/tasks")
async def post_task(req: AgentTaskCreateRequest):
    return {"task": await create_agent_task(**req.model_dump())}


@router.post("/tasks/research-scout")
async def post_research_scout_task(created_by: str = "operator"):
    return {"task": await create_research_scout_task(created_by=created_by)}


@router.post("/tasks/systems-health")
async def post_systems_health_task(created_by: str = "operator"):
    return {"task": await create_systems_health_agent_task(created_by=created_by)}


@router.post("/tasks/research-scout/run")
async def run_research_scout(task_id: str | None = None):
    return {"report": await run_research_scout_task(task_id=task_id)}


@router.post("/tasks/systems-health/run")
async def run_systems_health(task_id: str | None = None):
    return {"report": await run_systems_health_task(task_id=task_id)}


@router.get("/capabilities")
async def capabilities(limit: int = Query(100, ge=1, le=500)):
    return {"capabilities": await list_agent_capabilities(limit=limit)}


@router.post("/capabilities/refresh")
async def refresh_capabilities(probe: bool = Query(True)):
    return {"capabilities": await refresh_agent_capabilities(probe=probe, actor="operator")}


@router.get("/goals")
async def goals(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    return {"goals": await list_master_goals(status=status, limit=limit)}


@router.post("/goals/set")
async def set_goal(req: MasterGoalSetRequest):
    try:
        return {"goal": await set_master_goal(**req.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/tasks/{task_id}")
async def task(task_id: str):
    found = await get_agent_task(task_id)
    if not found:
        raise HTTPException(status_code=404, detail="agent_task_not_found")
    return {
        "task": found,
        "events": await list_agent_events(task_id=task_id, limit=100),
        "reports": await list_agent_reports(task_id=task_id, limit=100),
    }


@router.patch("/tasks/{task_id}/status")
async def patch_task_status(task_id: str, req: AgentTaskStatusRequest):
    updated = await update_agent_task_status(
        task_id,
        status=req.status,
        message=req.message,
        actor=req.actor,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="agent_task_not_found")
    return {"task": updated}


@router.post("/tasks/{task_id}/heartbeat")
async def post_task_heartbeat(task_id: str, req: AgentHeartbeatRequest):
    updated = await record_agent_heartbeat(
        task_id,
        agent_id=req.agent_id,
        message=req.message,
        status=req.status,
        metadata=req.metadata,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="agent_task_not_found")
    return {"task": updated}


@router.post("/tasks/{task_id}/reports")
async def post_task_report(task_id: str, req: AgentReportRequest):
    return {
        "report": await create_agent_report(
            task_id=task_id,
            **req.model_dump(),
        ),
    }


@router.get("/events")
async def events(
    task_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {"events": await list_agent_events(task_id=task_id, limit=limit)}


@router.get("/reports")
async def reports(
    task_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return {"reports": await list_agent_reports(task_id=task_id, limit=limit)}
