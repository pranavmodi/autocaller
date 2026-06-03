"""Possible OS master-agent task coordination and heartbeat."""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal, async_engine
from app.db.models import AgentReportRow, AgentTaskEventRow, AgentTaskRow, SystemSettingsRow
from app.services.product_traces import safe_record_product_trace


logger = logging.getLogger(__name__)

ACTIVE_TASK_STATUSES = {
    "queued",
    "accepted",
    "running",
    "waiting_on_tool",
    "waiting_on_user",
    "blocked",
    "stale",
}
STALE_CHECK_STATUSES = {
    "accepted",
    "running",
    "waiting_on_tool",
    "waiting_on_user",
}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}

_agent_tables_checked = False
_last_heartbeat_result: dict[str, Any] | None = None

DEFAULT_AGENT_CONFIG = {
    "heartbeat_enabled": True,
    "heartbeat_interval_seconds": 300,
}

RESEARCH_SCOUT_SOURCES = [
    {
        "url": "https://openai.com/news/rss.xml",
        "label": "OpenAI news RSS",
        "source_type": "rss",
        "why": "Discover recent OpenAI posts, including Codex/self-improvement material.",
    },
    {
        "url": "https://openai.com/index/building-self-improving-tax-agents-with-codex/",
        "label": "OpenAI self-improving tax agents with Codex",
        "source_type": "article",
        "why": "Direct reference for trace -> eval -> Codex improvement loop.",
    },
    {
        "url": "https://www.anthropic.com/engineering/multi-agent-research-system",
        "label": "Anthropic multi-agent research system",
        "source_type": "article",
        "why": "Reference for orchestrator-worker systems and subagent delegation.",
    },
    {
        "url": "https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents",
        "label": "Anthropic evals for AI agents",
        "source_type": "article",
        "why": "Reference for agent traces, outcomes, and eval harnesses.",
    },
    {
        "url": "https://code.claude.com/docs/en/best-practices",
        "label": "Claude Code best practices",
        "source_type": "docs",
        "why": "Reference for subagents, skills, context management, and verification.",
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _json_object(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_list(value: list[Any] | None) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _soul_context() -> dict[str, Any]:
    path = _repo_root() / "soul.md"
    if not path.exists():
        return {
            "soul_path": str(path),
            "loaded": False,
            "rule": "soul.md is protected constitutional context and must not be edited by heartbeat.",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "soul_path": str(path),
        "loaded": True,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": len(text),
        "rule": "soul.md is protected constitutional context and must not be edited by heartbeat.",
    }


def _env_heartbeat_enabled() -> bool:
    raw = os.getenv("MASTER_AGENT_HEARTBEAT_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_heartbeat_interval_seconds() -> int:
    raw = os.getenv("MASTER_AGENT_HEARTBEAT_SECONDS", "300").strip()
    try:
        return max(60, min(int(raw), 3600))
    except ValueError:
        return 300


def _normalize_agent_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    config = dict(DEFAULT_AGENT_CONFIG)
    config["heartbeat_enabled"] = _env_heartbeat_enabled()
    config["heartbeat_interval_seconds"] = _env_heartbeat_interval_seconds()
    if isinstance(raw, dict):
        if "heartbeat_enabled" in raw:
            config["heartbeat_enabled"] = bool(raw.get("heartbeat_enabled"))
        if "heartbeat_interval_seconds" in raw:
            try:
                config["heartbeat_interval_seconds"] = max(
                    60,
                    min(int(raw.get("heartbeat_interval_seconds")), 3600),
                )
            except (TypeError, ValueError):
                pass
    return config


def _default_settings_row() -> SystemSettingsRow:
    return SystemSettingsRow(
        id=1,
        business_hours={
            "start_time": "08:00",
            "end_time": "17:00",
            "enabled": False,
            "timezone": "America/New_York",
            "days_of_week": [0, 1, 2, 3, 4],
            "holidays": [],
        },
        queue_thresholds={
            "calls_waiting_threshold": 1,
            "holdtime_threshold_seconds": 30,
            "stable_polls_required": 3,
        },
        dispatcher_settings={},
        daily_report={},
        agent_config=_normalize_agent_config(None),
    )


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _compact_text(value: str, *, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", html.unescape(_strip_tags(value))).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _extract_title(body: str) -> str:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if title_match:
        return _compact_text(title_match.group(1), limit=180)
    item_match = re.search(r"<item\b.*?<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if item_match:
        return _compact_text(item_match.group(1), limit=180)
    return ""


def _extract_rss_items(body: str, *, limit: int = 8) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in re.findall(r"<item\b.*?</item>", body, flags=re.I | re.S)[:limit]:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", item, re.I | re.S)
        link_match = re.search(r"<link[^>]*>(.*?)</link>", item, re.I | re.S)
        pub_match = re.search(r"<pubDate[^>]*>(.*?)</pubDate>", item, re.I | re.S)
        description_match = re.search(r"<description[^>]*>(.*?)</description>", item, re.I | re.S)
        items.append({
            "title": _compact_text(title_match.group(1), limit=180) if title_match else "",
            "url": _compact_text(link_match.group(1), limit=500) if link_match else "",
            "published_at": _compact_text(pub_match.group(1), limit=120) if pub_match else "",
            "description": _compact_text(description_match.group(1), limit=240) if description_match else "",
        })
    return items


def _source_key_ideas(url: str, title: str) -> list[str]:
    text = f"{url} {title}".lower()
    if "self-improving-tax-agents" in text:
        return [
            "Use production traces and expert corrections as the raw material for improvement.",
            "Convert repeated failures into evals before changing code or prompts.",
            "Use bounded coding-agent tasks to implement the improvement and measure outcomes afterward.",
        ]
    if "multi-agent-research-system" in text:
        return [
            "Use an orchestrator-worker pattern: the master owns planning and synthesis, workers explore bounded branches.",
            "Give subagents clear objectives, source/tool guidance, and output formats.",
            "Use subagents when parallel exploration or context partitioning is worth the overhead.",
        ]
    if "demystifying-evals" in text:
        return [
            "Separate trace inspection from outcome measurement.",
            "Build eval cases that check the actual behavior the agent should improve.",
            "Use eval harnesses to prevent regressions when agent behavior changes.",
        ]
    if "claude.com/docs" in text or "best practices" in text:
        return [
            "Manage context deliberately and load only what the task needs.",
            "Use skills and subagents for repeated or specialized workflows.",
            "Give coding agents concrete verification commands and inspect their work.",
        ]
    return [
        "Monitor official source material for ideas that could improve Possible OS.",
    ]


def _possible_os_implications(source_results: list[dict[str, Any]]) -> list[str]:
    implications = [
        "Keep building the master-agent system in horizontal slices: first observe/report, then execute, then learn.",
        "Treat subagent reports as evidence, not final truth; the master agent owns acceptance and verification.",
        "Turn repeated corrections into findings, evals, and bounded Codex task packets.",
        "Use progressive disclosure: task packets should point to docs/skills/traces instead of loading everything.",
    ]
    if any(result.get("status_code") == 403 for result in source_results):
        implications.append(
            "When official pages block direct fetches, record source availability honestly and fall back to RSS or manual review."
        )
    return implications


async def _fetch_research_source(client: httpx.AsyncClient, source: dict[str, str]) -> dict[str, Any]:
    url = source["url"]
    result: dict[str, Any] = {
        **source,
        "status": "unknown",
        "status_code": None,
        "title": "",
        "excerpt": "",
        "items": [],
        "key_ideas": [],
    }
    try:
        response = await client.get(url, follow_redirects=True)
    except Exception as exc:
        result.update({
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })
        return result
    body = response.text or ""
    title = _extract_title(body)
    result.update({
        "status_code": response.status_code,
        "status": "fetched" if response.status_code < 400 else "unavailable",
        "title": title,
        "excerpt": _compact_text(body, limit=500),
        "items": _extract_rss_items(body) if source.get("source_type") == "rss" and response.status_code < 400 else [],
        "key_ideas": _source_key_ideas(url, title),
        "final_url": str(response.url),
    })
    if response.status_code >= 400:
        result["error"] = f"HTTP {response.status_code}"
    return result


def _render_research_note(task: dict[str, Any], source_results: list[dict[str, Any]]) -> str:
    now = _utcnow().isoformat()
    fetched = sum(1 for result in source_results if result.get("status") == "fetched")
    unavailable = [result for result in source_results if result.get("status") != "fetched"]
    implications = _possible_os_implications(source_results)
    lines = [
        "# ResearchScoutAgent Learning Note",
        "",
        f"Created at: {now}",
        f"Task: {task['id']} - {task['title']}",
        "",
        "## Summary",
        "",
        (
            f"ResearchScoutAgent checked {len(source_results)} official OpenAI, Anthropic, "
            f"and Claude Code sources. {fetched} were fetched successfully. "
            f"{len(unavailable)} were unavailable or blocked from direct backend fetch."
        ),
        "",
        "## Sources Checked",
        "",
    ]
    for result in source_results:
        lines.extend([
            f"### {result.get('label')}",
            "",
            f"- URL: {result.get('url')}",
            f"- Status: {result.get('status')} ({result.get('status_code')})",
            f"- Title: {result.get('title') or 'n/a'}",
            f"- Why checked: {result.get('why')}",
        ])
        if result.get("error"):
            lines.append(f"- Error: {result.get('error')}")
        if result.get("items"):
            lines.append("- Recent RSS items:")
            for item in result["items"][:5]:
                lines.append(f"  - {item.get('title')} - {item.get('url')}")
        lines.extend(["", "Key ideas:"])
        for idea in result.get("key_ideas") or []:
            lines.append(f"- {idea}")
        lines.append("")
    lines.extend([
        "## Possible OS Implications",
        "",
    ])
    for implication in implications:
        lines.append(f"- {implication}")
    lines.extend([
        "",
        "## Recommended Next Actions",
        "",
        "- Keep the ResearchScout loop proposal-only until the finding/eval path is connected.",
        "- Add a finding generator that converts this report into a reviewed improvement finding.",
        "- Add a daily schedule for ResearchScoutAgent after the runner proves useful manually.",
        "- Skillify this workflow once the source list and report format stabilize.",
        "",
    ])
    return "\n".join(lines)


def _write_research_note(task: dict[str, Any], source_results: list[dict[str, Any]]) -> str:
    notes_dir = _repo_root() / "docs" / "learning-notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    date_part = _utcnow().strftime("%Y-%m-%d")
    path = notes_dir / f"{date_part}-research-scout-{task['id']}.md"
    path.write_text(_render_research_note(task, source_results), encoding="utf-8")
    return str(path.relative_to(_repo_root()))


def task_to_dict(row: AgentTaskRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "parent_task_id": row.parent_task_id,
        "assigned_agent": row.assigned_agent,
        "title": row.title,
        "objective": row.objective,
        "context": row.context_json or {},
        "allowed_tools": row.allowed_tools_json or [],
        "forbidden_actions": row.forbidden_actions_json or [],
        "expected_output_schema": row.expected_output_schema_json or {},
        "acceptance_criteria": row.acceptance_criteria_json or [],
        "verification_commands": row.verification_commands_json or [],
        "artifacts": row.artifacts_json or [],
        "risk_level": row.risk_level,
        "requires_human_approval": row.requires_human_approval,
        "status": row.status,
        "priority": row.priority,
        "heartbeat_interval_seconds": row.heartbeat_interval_seconds,
        "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
        "claimed_at": row.claimed_at.isoformat() if row.claimed_at else None,
        "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def event_to_dict(row: AgentTaskEventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "event_type": row.event_type,
        "message": row.message,
        "input": row.input_json or {},
        "output": row.output_json or {},
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def report_to_dict(row: AgentReportRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "status": row.status,
        "summary": row.summary,
        "key_findings": row.key_findings_json or [],
        "actions_taken": row.actions_taken_json or [],
        "artifacts": row.artifacts_json or [],
        "evidence": row.evidence_json or [],
        "verification": row.verification_json or [],
        "risks": row.risks_json or [],
        "open_questions": row.open_questions_json or [],
        "recommended_next_actions": row.recommended_next_actions_json or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def ensure_agent_tables() -> None:
    """Create agent tables on demand if Alembic has not been applied yet."""
    global _agent_tables_checked
    if _agent_tables_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(AgentTaskRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentTaskEventRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentReportRow.__table__.create, checkfirst=True)
    _agent_tables_checked = True


async def get_agent_config() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(SystemSettingsRow).where(SystemSettingsRow.id == 1)
        )).scalar_one_or_none()
        if row is None:
            return _normalize_agent_config(None)
        return _normalize_agent_config(getattr(row, "agent_config", None))


async def update_agent_config(
    *,
    heartbeat_enabled: bool | None = None,
    heartbeat_interval_seconds: int | None = None,
    actor: str = "operator",
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(SystemSettingsRow).where(SystemSettingsRow.id == 1)
        )).scalar_one_or_none()
        if row is None:
            row = _default_settings_row()
            session.add(row)
            await session.flush()
        current = _normalize_agent_config(getattr(row, "agent_config", None))
        before = dict(current)
        if heartbeat_enabled is not None:
            current["heartbeat_enabled"] = bool(heartbeat_enabled)
        if heartbeat_interval_seconds is not None:
            current["heartbeat_interval_seconds"] = max(
                60,
                min(int(heartbeat_interval_seconds), 3600),
            )
        row.agent_config = current
        await session.commit()
    await create_task_event(
        task_id=None,
        agent_id="master-agent",
        event_type="agent_config_updated",
        message="Master-agent configuration updated.",
        input_json={"before": before, "actor": actor},
        output_json=current,
    )
    await safe_record_product_trace(
        actor_type="user" if actor == "operator" else "agent",
        actor_id=actor,
        event_type="agent_config_updated",
        surface="agents",
        entity_type="master_agent",
        entity_id="config",
        input_json={"before": before},
        output_json=current,
    )
    return current


async def create_task_event(
    *,
    task_id: str | None,
    agent_id: str,
    event_type: str,
    message: str = "",
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        row = AgentTaskEventRow(
            task_id=task_id,
            agent_id=agent_id[:128],
            event_type=event_type[:64],
            message=message,
            input_json=_json_object(input_json),
            output_json=_json_object(output_json),
            metadata_json=_json_object(metadata_json),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return event_to_dict(row)


async def create_agent_task(
    *,
    assigned_agent: str,
    title: str,
    objective: str,
    parent_task_id: str | None = None,
    context: dict[str, Any] | None = None,
    allowed_tools: list[Any] | None = None,
    forbidden_actions: list[Any] | None = None,
    expected_output_schema: dict[str, Any] | None = None,
    acceptance_criteria: list[Any] | None = None,
    verification_commands: list[Any] | None = None,
    risk_level: str = "low",
    requires_human_approval: bool = False,
    priority: int = 50,
    heartbeat_interval_seconds: int = 300,
    deadline_at: str | None = None,
    created_by: str = "master-agent",
) -> dict[str, Any]:
    await ensure_agent_tables()
    task_id = _new_id("task")
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = AgentTaskRow(
            id=task_id,
            parent_task_id=parent_task_id,
            assigned_agent=assigned_agent[:128],
            title=title[:255],
            objective=objective,
            context_json=_json_object(context),
            allowed_tools_json=_json_list(allowed_tools),
            forbidden_actions_json=_json_list(forbidden_actions),
            expected_output_schema_json=_json_object(expected_output_schema),
            acceptance_criteria_json=_json_list(acceptance_criteria),
            verification_commands_json=_json_list(verification_commands),
            risk_level=(risk_level or "low")[:16],
            requires_human_approval=requires_human_approval,
            priority=max(0, min(int(priority), 1000)),
            heartbeat_interval_seconds=max(60, min(int(heartbeat_interval_seconds), 3600)),
            deadline_at=_parse_dt(deadline_at),
            created_by=created_by[:128] if created_by else None,
        )
        session.add(row)
        await session.flush()
        session.add(AgentTaskEventRow(
            task_id=task_id,
            agent_id="master-agent",
            event_type="task_created",
            message=f"Delegated to {assigned_agent}",
            input_json={
                "assigned_agent": assigned_agent,
                "title": title,
                "objective": objective,
                "created_at": now.isoformat(),
            },
            metadata_json={"created_by": created_by},
        ))
        await session.commit()
        await session.refresh(row)
        task = task_to_dict(row)
    await safe_record_product_trace(
        actor_type="agent",
        actor_id="master-agent",
        event_type="subagent_task_created",
        surface="agents",
        entity_type="agent_task",
        entity_id=task_id,
        input_json={"assigned_agent": assigned_agent, "title": title},
        output_json={"status": task["status"]},
        context_json={"soul": _soul_context()},
    )
    return task


async def create_research_scout_task(*, created_by: str = "operator") -> dict[str, Any]:
    return await create_agent_task(
        assigned_agent="ResearchScoutAgent",
        title="Scan OpenAI and Anthropic for self-improving agent ideas",
        objective=(
            "Check official OpenAI and Anthropic sources for recent ideas about "
            "self-improving agents, evals, traces, memory, subagents, and safe "
            "autonomous development. Produce a concise learning note and proposed "
            "Possible OS implications. Do not edit product code or send external messages."
        ),
        context={
            "source_scope": [
                "https://openai.com/index/",
                "https://www.anthropic.com/engineering",
                "https://code.claude.com/docs/",
            ],
            "write_notes_under": "docs/learning-notes/",
            "protected_constitution": "soul.md",
        },
        allowed_tools=["web_search", "web_fetch", "read_docs", "write_learning_note"],
        forbidden_actions=[
            "edit soul.md",
            "edit product code",
            "send email",
            "modify Front/Zoho/Gmail state",
            "mark task accepted",
        ],
        expected_output_schema={
            "summary": "string",
            "sources": ["url"],
            "key_ideas": ["string"],
            "possible_os_implications": ["string"],
            "recommended_next_actions": ["string"],
        },
        acceptance_criteria=[
            "Uses official OpenAI/Anthropic/Claude Code sources where available.",
            "Each substantive claim includes a URL.",
            "Creates proposals only; no code/product mutation.",
            "Connects ideas to Possible OS master-agent or learning-loop design.",
        ],
        verification_commands=[],
        risk_level="low",
        requires_human_approval=False,
        heartbeat_interval_seconds=300,
        created_by=created_by,
    )


async def list_agent_tasks(
    *,
    status: str | None = None,
    assigned_agent: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    limit = max(1, min(limit, 500))
    async with AsyncSessionLocal() as session:
        stmt = select(AgentTaskRow).order_by(
            AgentTaskRow.priority.desc(),
            AgentTaskRow.updated_at.desc(),
        ).limit(limit)
        if status and status != "all":
            stmt = stmt.where(AgentTaskRow.status == status)
        if assigned_agent:
            stmt = stmt.where(AgentTaskRow.assigned_agent == assigned_agent)
        rows = (await session.execute(stmt)).scalars().all()
        return [task_to_dict(row) for row in rows]


async def get_agent_task(task_id: str) -> dict[str, Any] | None:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentTaskRow, task_id)
        return task_to_dict(row) if row else None


async def list_agent_events(*, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    limit = max(1, min(limit, 500))
    async with AsyncSessionLocal() as session:
        stmt = select(AgentTaskEventRow).order_by(AgentTaskEventRow.created_at.desc()).limit(limit)
        if task_id:
            stmt = stmt.where(AgentTaskEventRow.task_id == task_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [event_to_dict(row) for row in rows]


async def list_agent_reports(*, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    limit = max(1, min(limit, 500))
    async with AsyncSessionLocal() as session:
        stmt = select(AgentReportRow).order_by(AgentReportRow.created_at.desc()).limit(limit)
        if task_id:
            stmt = stmt.where(AgentReportRow.task_id == task_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [report_to_dict(row) for row in rows]


async def claim_next_research_scout_task() -> dict[str, Any] | None:
    await ensure_agent_tables()
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(AgentTaskRow)
            .where(AgentTaskRow.assigned_agent == "ResearchScoutAgent")
            .where(AgentTaskRow.status == "queued")
            .order_by(AgentTaskRow.priority.desc(), AgentTaskRow.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()
        if not row:
            return None
        row.status = "running"
        row.claimed_at = now
        row.last_heartbeat_at = now
        row.updated_at = now
        session.add(AgentTaskEventRow(
            task_id=row.id,
            agent_id="ResearchScoutAgent",
            event_type="task_claimed",
            message="ResearchScoutAgent claimed queued official-source scan task.",
            output_json={"status": "running", "claimed_at": now.isoformat()},
        ))
        await session.commit()
        await session.refresh(row)
        task = task_to_dict(row)
    await safe_record_product_trace(
        actor_type="agent",
        actor_id="ResearchScoutAgent",
        event_type="subagent_task_claimed",
        surface="agents",
        entity_type="agent_task",
        entity_id=task["id"],
        output_json={"status": "running"},
    )
    return task


async def run_research_scout_task(task_id: str | None = None) -> dict[str, Any] | None:
    """Execute one safe ResearchScout task and report back.

    This runner is intentionally narrow: it fetches a fixed official-source list,
    writes a learning note, records task events, and creates a report. It does
    not edit product code, send external messages, or modify mailbox state.
    """
    await ensure_agent_tables()
    if task_id:
        task = await update_agent_task_status(
            task_id,
            status="running",
            message="ResearchScoutAgent manually started.",
            actor="ResearchScoutAgent",
        )
    else:
        task = await claim_next_research_scout_task()
    if not task:
        return None

    await record_agent_heartbeat(
        task["id"],
        agent_id="ResearchScoutAgent",
        message="Fetching official OpenAI, Anthropic, and Claude Code sources.",
        status="running",
        metadata={"source_count": len(RESEARCH_SCOUT_SOURCES)},
    )
    await safe_record_product_trace(
        actor_type="agent",
        actor_id="ResearchScoutAgent",
        event_type="research_scout_started",
        surface="agents",
        entity_type="agent_task",
        entity_id=task["id"],
        input_json={"sources": [source["url"] for source in RESEARCH_SCOUT_SOURCES]},
        context_json={"soul": _soul_context()},
    )

    try:
        async with httpx.AsyncClient(timeout=15.0, headers={
            "User-Agent": "PossibleOS-ResearchScout/0.1 (+https://getpossibleminds.com)",
        }) as client:
            source_results = await asyncio.gather(*[
                _fetch_research_source(client, source)
                for source in RESEARCH_SCOUT_SOURCES
            ])
        note_path = _write_research_note(task, list(source_results))
        implications = _possible_os_implications(list(source_results))
        fetched_count = sum(1 for result in source_results if result.get("status") == "fetched")
        report = await create_agent_report(
            task_id=task["id"],
            agent_id="ResearchScoutAgent",
            status="completed",
            summary=(
                f"Checked {len(source_results)} official sources; fetched {fetched_count}. "
                f"Wrote learning note to {note_path}."
            ),
            key_findings=implications,
            actions_taken=[
                "Fetched official source pages/RSS where reachable.",
                "Recorded unavailable blocked sources honestly.",
                "Wrote durable markdown learning note.",
            ],
            artifacts=[{"path": note_path, "kind": "learning_note"}],
            evidence=[
                {
                    "url": result.get("url"),
                    "status": result.get("status"),
                    "status_code": result.get("status_code"),
                    "title": result.get("title"),
                }
                for result in source_results
            ],
            verification=[
                "Learning note file exists.",
                "No product code, mailbox state, or soul.md edits were made by runner.",
            ],
            risks=[
                "OpenAI article pages may block direct backend fetches; RSS fallback is used for source discovery."
            ],
            open_questions=[
                "Should ResearchScoutAgent run daily automatically once report-to-finding conversion exists?"
            ],
            recommended_next_actions=[
                "Convert this report into a reviewable improvement finding.",
                "Add a SystemsHealthAgent/log observation slice for app logs and bug detection.",
                "Skillify the ResearchScout workflow after the source list stabilizes.",
            ],
        )
        async with AsyncSessionLocal() as session:
            row = await session.get(AgentTaskRow, task["id"])
            if row:
                row.artifacts_json = [{"path": note_path, "kind": "learning_note"}]
                row.updated_at = _utcnow()
                await session.commit()
        await safe_record_product_trace(
            actor_type="agent",
            actor_id="ResearchScoutAgent",
            event_type="research_scout_completed",
            surface="agents",
            entity_type="agent_task",
            entity_id=task["id"],
            output_json={"note_path": note_path, "report_id": report["id"]},
            metadata_json={"fetched_count": fetched_count, "source_count": len(source_results)},
        )
        return report
    except Exception as exc:
        logger.exception("ResearchScoutAgent failed task_id=%s", task["id"])
        await create_agent_report(
            task_id=task["id"],
            agent_id="ResearchScoutAgent",
            status="failed",
            summary=f"ResearchScoutAgent failed: {type(exc).__name__}: {exc}",
            risks=["Runner failed before producing a learning note."],
            recommended_next_actions=["Inspect backend logs and rerun the task after fixing the failure."],
        )
        await safe_record_product_trace(
            actor_type="agent",
            actor_id="ResearchScoutAgent",
            event_type="research_scout_failed",
            surface="agents",
            entity_type="agent_task",
            entity_id=task["id"],
            output_json={"error": f"{type(exc).__name__}: {exc}"},
        )
        return None


async def update_agent_task_status(
    task_id: str,
    *,
    status: str,
    message: str = "",
    actor: str = "master-agent",
) -> dict[str, Any] | None:
    await ensure_agent_tables()
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentTaskRow, task_id)
        if not row:
            return None
        row.status = status
        row.updated_at = now
        if status == "accepted" and row.claimed_at is None:
            row.claimed_at = now
        if status in TERMINAL_TASK_STATUSES:
            row.completed_at = now
        elif status != "completed":
            row.completed_at = None
        session.add(AgentTaskEventRow(
            task_id=task_id,
            agent_id=actor[:128],
            event_type="status_changed",
            message=message or f"Status set to {status}",
            output_json={"status": status},
        ))
        await session.commit()
        await session.refresh(row)
        task = task_to_dict(row)
    await safe_record_product_trace(
        actor_type="agent" if actor != "operator" else "user",
        actor_id=actor,
        event_type="subagent_task_status_changed",
        surface="agents",
        entity_type="agent_task",
        entity_id=task_id,
        output_json={"status": status},
        metadata_json={"message": message},
    )
    return task


async def record_agent_heartbeat(
    task_id: str,
    *,
    agent_id: str,
    message: str = "",
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    await ensure_agent_tables()
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentTaskRow, task_id)
        if not row:
            return None
        row.last_heartbeat_at = now
        if status:
            row.status = status
        row.updated_at = now
        event = AgentTaskEventRow(
            task_id=task_id,
            agent_id=agent_id[:128],
            event_type="heartbeat",
            message=message,
            output_json={"status": row.status, "last_heartbeat_at": now.isoformat()},
            metadata_json=_json_object(metadata),
        )
        session.add(event)
        await session.commit()
        await session.refresh(row)
        return task_to_dict(row)


async def create_agent_report(
    *,
    task_id: str | None,
    agent_id: str,
    status: str = "reported",
    summary: str = "",
    key_findings: list[Any] | None = None,
    actions_taken: list[Any] | None = None,
    artifacts: list[Any] | None = None,
    evidence: list[Any] | None = None,
    verification: list[Any] | None = None,
    risks: list[Any] | None = None,
    open_questions: list[Any] | None = None,
    recommended_next_actions: list[Any] | None = None,
) -> dict[str, Any]:
    await ensure_agent_tables()
    report_id = _new_id("report")
    async with AsyncSessionLocal() as session:
        task = await session.get(AgentTaskRow, task_id) if task_id else None
        row = AgentReportRow(
            id=report_id,
            task_id=task_id,
            agent_id=agent_id[:128],
            status=status[:32],
            summary=summary,
            key_findings_json=_json_list(key_findings),
            actions_taken_json=_json_list(actions_taken),
            artifacts_json=_json_list(artifacts),
            evidence_json=_json_list(evidence),
            verification_json=_json_list(verification),
            risks_json=_json_list(risks),
            open_questions_json=_json_list(open_questions),
            recommended_next_actions_json=_json_list(recommended_next_actions),
        )
        session.add(row)
        session.add(AgentTaskEventRow(
            task_id=task_id,
            agent_id=agent_id[:128],
            event_type="report_created",
            message=summary[:500],
            output_json={"report_id": report_id, "status": status},
        ))
        if task and status in TERMINAL_TASK_STATUSES:
            task.status = status
            task.completed_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        report = report_to_dict(row)
    await safe_record_product_trace(
        actor_type="agent",
        actor_id=agent_id,
        event_type="subagent_report_received",
        surface="agents",
        entity_type="agent_task",
        entity_id=task_id,
        output_json={"report_id": report_id, "status": status, "summary": summary},
    )
    return report


async def run_master_heartbeat(*, actor: str = "master-agent") -> dict[str, Any]:
    """Run one lightweight heartbeat tick.

    V1 does not execute external actions. It reads protected constitution
    metadata, records traces, checks subagent/task status, and marks stale
    running tasks.
    """
    global _last_heartbeat_result
    await ensure_agent_tables()
    agent_config = await get_agent_config()
    started_at = _utcnow()
    trace = await safe_record_product_trace(
        actor_type="agent",
        actor_id=actor,
        event_type="master_heartbeat_started",
        surface="agents",
        entity_type="master_agent",
        entity_id="heartbeat",
        context_json={"soul": _soul_context()},
        metadata_json={"started_at": started_at.isoformat()},
    )
    stale_ids: list[str] = []
    active_count = 0
    blocked_count = 0
    queued_count = 0
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentTaskRow).where(AgentTaskRow.status.in_(list(ACTIVE_TASK_STATUSES)))
        )).scalars().all()
        active_count = len(rows)
        blocked_count = sum(1 for row in rows if row.status == "blocked")
        queued_count = sum(1 for row in rows if row.status == "queued")
        now = _utcnow()
        for row in rows:
            if row.status not in STALE_CHECK_STATUSES:
                continue
            anchor = row.last_heartbeat_at or row.claimed_at or row.updated_at or row.created_at
            allowed_lag = timedelta(seconds=max(row.heartbeat_interval_seconds * 2, 600))
            if anchor and now - anchor > allowed_lag:
                row.status = "stale"
                row.updated_at = now
                stale_ids.append(row.id)
                session.add(AgentTaskEventRow(
                    task_id=row.id,
                    agent_id="master-agent",
                    event_type="task_marked_stale",
                    message="No heartbeat inside expected interval.",
                    input_json={
                        "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
                        "heartbeat_interval_seconds": row.heartbeat_interval_seconds,
                    },
                    output_json={"status": "stale"},
                ))
        session.add(AgentTaskEventRow(
            task_id=None,
            agent_id="master-agent",
            event_type="master_heartbeat_completed",
            message="Heartbeat checked active subagent tasks.",
            input_json={"started_at": started_at.isoformat()},
            output_json={
                "active_task_count": active_count,
                "queued_task_count": queued_count,
                "blocked_task_count": blocked_count,
                "stale_task_ids": stale_ids,
            },
            metadata_json={"trace_id": trace.get("trace_id") if trace else None},
        ))
        await session.commit()
    completed_at = _utcnow()
    result = {
        "status": "ok",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "active_task_count": active_count,
        "queued_task_count": queued_count,
        "blocked_task_count": blocked_count,
        "stale_task_ids": stale_ids,
        "heartbeat_enabled": agent_config["heartbeat_enabled"],
        "heartbeat_interval_seconds": agent_config["heartbeat_interval_seconds"],
        "soul": _soul_context(),
        "next_recommended_slice": (
            "Create and run ResearchScoutAgent against official OpenAI/Anthropic sources, "
            "then turn its report into a reviewable improvement finding."
        ),
    }
    _last_heartbeat_result = result
    await safe_record_product_trace(
        actor_type="agent",
        actor_id=actor,
        event_type="master_heartbeat_completed",
        surface="agents",
        entity_type="master_agent",
        entity_id="heartbeat",
        output_json=result,
        metadata_json={"duration_seconds": (completed_at - started_at).total_seconds()},
    )
    return result


def last_heartbeat_result() -> dict[str, Any] | None:
    return _last_heartbeat_result


async def master_heartbeat_loop(interval_seconds: int = 300) -> None:
    while True:
        try:
            config = await get_agent_config()
            if config["heartbeat_enabled"]:
                await run_master_heartbeat(actor="master-agent-heartbeat-loop")
            sleep_seconds = config["heartbeat_interval_seconds"]
        except Exception:
            logger.exception("master heartbeat failed")
            sleep_seconds = max(60, interval_seconds)
        await asyncio.sleep(max(60, sleep_seconds))


def heartbeat_enabled() -> bool:
    return _env_heartbeat_enabled()


def heartbeat_interval_seconds() -> int:
    return _env_heartbeat_interval_seconds()


def subagent_runner_enabled() -> bool:
    raw = os.getenv("MASTER_AGENT_SUBAGENT_RUNNER_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def subagent_runner_interval_seconds() -> int:
    raw = os.getenv("MASTER_AGENT_SUBAGENT_RUNNER_SECONDS", "60").strip()
    try:
        return max(30, int(raw))
    except ValueError:
        return 60


async def subagent_runner_loop(interval_seconds: int = 60) -> None:
    interval_seconds = max(30, interval_seconds)
    while True:
        try:
            await run_research_scout_task()
        except Exception:
            logger.exception("subagent runner loop failed")
        await asyncio.sleep(interval_seconds)
