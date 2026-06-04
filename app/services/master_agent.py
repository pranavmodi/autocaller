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
from sqlalchemy import desc, select

from app.db import AsyncSessionLocal, async_engine
from app.db.models import (
    AgentCapabilityRow,
    AgentActionEventRow,
    AgentActionRow,
    AgentReportRow,
    AgentTaskEventRow,
    AgentTaskRow,
    MasterGoalRow,
    ProductTraceRow,
    SystemSettingsRow,
)
from app.services.llm_gateway import LLMGatewayError, call_skill_json
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

MASTER_STATUS_SKILL_PATH = Path(os.getenv(
    "MASTER_AGENT_STATUS_SKILL_PATH",
    str(Path(__file__).resolve().parents[2] / "app/skills/master-agent-status/SKILL.md"),
))
MASTER_STATUS_MODEL = os.getenv("MASTER_AGENT_STATUS_MODEL", "openclaw")
SOUL_COMPACT_PATH = Path(os.getenv(
    "MASTER_AGENT_COMPACT_SOUL_PATH",
    str(Path(__file__).resolve().parents[2] / "soul.compact.md"),
))

DEFAULT_AGENT_CONFIG = {
    "heartbeat_enabled": True,
    "heartbeat_interval_seconds": 300,
    "status_llm_enabled": True,
    "auto_delegate_next_slice_enabled": True,
}

SYSTEMS_HEALTH_AGENT_TITLE = "Add SystemsHealthAgent log observation and bug-fix delegation"
SUPPORTED_RUNNER_AGENTS = {"ResearchScoutAgent", "SystemsHealthAgent"}
MASTER_GOAL_TTL_SECONDS = 6 * 60 * 60
STALE_QUEUE_MIN_SECONDS = 30 * 60


CAPABILITY_DEFINITIONS = [
    {
        "name": "agents status",
        "capability_type": "cli",
        "source": "bin/autocaller agents status --json",
        "purpose": "Inspect master-agent heartbeat config and last heartbeat result.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/autocaller", "agents", "status", "--json"], "safe_probe": True},
    },
    {
        "name": "agents heartbeat",
        "capability_type": "cli",
        "source": "bin/autocaller agents heartbeat --json",
        "purpose": "Run one manual master-agent heartbeat.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/autocaller", "agents", "heartbeat", "--json"], "safe_probe": False},
    },
    {
        "name": "actions list",
        "capability_type": "cli",
        "source": "bin/autocaller actions list --json",
        "purpose": "Inspect durable Possible OS action execution records.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/autocaller", "actions", "list", "--json"], "safe_probe": True},
    },
    {
        "name": "actions policy-check",
        "capability_type": "cli",
        "source": "bin/autocaller actions policy-check <action_id> --json",
        "purpose": "Run reusable action policy checks without execution.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/autocaller", "actions", "policy-check", "<action_id>", "--json"], "safe_probe": False},
    },
    {
        "name": "actions execute",
        "capability_type": "cli",
        "source": "bin/autocaller actions execute <action_id> --json",
        "purpose": "Execute one policy-approved durable action through a narrow adapter.",
        "risk_level": "high",
        "requires_approval": True,
        "autonomous_allowed": False,
        "command_json": {"argv": ["bin/autocaller", "actions", "execute", "<action_id>", "--json"], "safe_probe": False},
    },
    {
        "name": "send approved lead-gen draft action",
        "capability_type": "cli",
        "source": "bin/autocaller actions send-approved-lead-gen-draft --item=<id> --subject=... --body=...",
        "purpose": "Create and optionally execute an exact approved lead-gen email draft action via Zoho-backed send path.",
        "risk_level": "high",
        "requires_approval": True,
        "autonomous_allowed": False,
        "command_json": {
            "argv": ["bin/autocaller", "actions", "send-approved-lead-gen-draft", "--item", "<batch_item_id>", "--subject", "<subject>", "--body", "<body>"],
            "safe_probe": False,
        },
    },
    {
        "name": "run research scout",
        "capability_type": "cli",
        "source": "bin/autocaller agents run-research-scout --json",
        "purpose": "Execute one queued ResearchScoutAgent task and write a learning report.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/autocaller", "agents", "run-research-scout", "--json"], "safe_probe": False},
    },
    {
        "name": "run systems health",
        "capability_type": "cli",
        "source": "bin/autocaller agents run-systems-health --json",
        "purpose": "Execute one queued SystemsHealthAgent read-only health observation task.",
        "risk_level": "medium",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/autocaller", "agents", "run-systems-health", "--json"], "safe_probe": False},
    },
    {
        "name": "backend health endpoint",
        "capability_type": "api",
        "source": "GET http://127.0.0.1:8099/health",
        "purpose": "Check whether the backend is responding.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"method": "GET", "url": "http://127.0.0.1:8099/health", "safe_probe": True},
    },
    {
        "name": "frontend service status",
        "capability_type": "system",
        "source": "systemctl is-active autocaller-frontend.service",
        "purpose": "Check whether the frontend systemd service is active.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["systemctl", "is-active", "autocaller-frontend.service"], "safe_probe": True},
    },
    {
        "name": "backend service status",
        "capability_type": "system",
        "source": "systemctl is-active autocaller-backend.service",
        "purpose": "Check whether the backend systemd service is active.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["systemctl", "is-active", "autocaller-backend.service"], "safe_probe": True},
    },
]

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


def _compact_soul_context() -> dict[str, Any]:
    path = SOUL_COMPACT_PATH
    if not path.exists():
        return {
            "soul_compact_path": str(path),
            "loaded": False,
            "rule": (
                "soul.compact.md should provide compact constitutional guidance "
                "for frequent master-agent LLM calls."
            ),
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "soul_compact_path": str(path),
        "loaded": True,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": len(text),
        "content": text,
        "rule": (
            "Use this compact soul as constitutional guidance. The full soul.md "
            "remains protected and must not be edited by heartbeat."
        ),
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
    raw_status_llm = os.getenv("MASTER_AGENT_STATUS_LLM_ENABLED", "true").strip().lower()
    config["status_llm_enabled"] = raw_status_llm in {"1", "true", "yes", "on"}
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
        if "status_llm_enabled" in raw:
            config["status_llm_enabled"] = bool(raw.get("status_llm_enabled"))
        if "auto_delegate_next_slice_enabled" in raw:
            config["auto_delegate_next_slice_enabled"] = bool(raw.get("auto_delegate_next_slice_enabled"))
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


def capability_to_dict(row: AgentCapabilityRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "capability_type": row.capability_type,
        "source": row.source,
        "purpose": row.purpose,
        "risk_level": row.risk_level,
        "requires_approval": row.requires_approval,
        "autonomous_allowed": row.autonomous_allowed,
        "command": row.command_json or {},
        "metadata": row.metadata_json or {},
        "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
        "last_status": row.last_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def goal_to_dict(row: MasterGoalRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "goal": row.goal,
        "why": row.why,
        "time_horizon": row.time_horizon,
        "success_metric": row.success_metric,
        "next_actions": row.next_actions_json or [],
        "source": row.source_json or {},
        "confidence": row.confidence,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def _short_task_snapshot(row: AgentTaskRow) -> dict[str, Any]:
    now = _utcnow()
    queued_age_seconds = None
    if row.status == "queued":
        anchor = row.created_at or row.updated_at
        if anchor:
            queued_age_seconds = max(0, int((now - anchor).total_seconds()))
    return {
        "id": row.id,
        "assigned_agent": row.assigned_agent,
        "title": row.title,
        "status": row.status,
        "priority": row.priority,
        "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "queued_age_seconds": queued_age_seconds,
        "runner_supported": row.assigned_agent in SUPPORTED_RUNNER_AGENTS,
    }


def _short_event_snapshot(row: AgentTaskEventRow) -> dict[str, Any]:
    output = row.output_json if isinstance(row.output_json, dict) else {}
    return {
        "id": row.id,
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "event_type": row.event_type,
        "message": row.message,
        "output_summary": {
            "status": output.get("status"),
            "active_task_count": output.get("active_task_count"),
            "queued_task_count": output.get("queued_task_count"),
            "blocked_task_count": output.get("blocked_task_count"),
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _queue_age_analysis(rows: list[AgentTaskRow]) -> dict[str, Any]:
    now = _utcnow()
    stale_queue_items: list[dict[str, Any]] = []
    blocked_capabilities: list[dict[str, Any]] = []
    for row in rows:
        if row.status != "queued":
            continue
        anchor = row.created_at or row.updated_at
        age_seconds = max(0, int((now - anchor).total_seconds())) if anchor else 0
        threshold_seconds = max(row.heartbeat_interval_seconds * 2, STALE_QUEUE_MIN_SECONDS)
        if age_seconds >= threshold_seconds:
            stale_queue_items.append({
                "task_id": row.id,
                "assigned_agent": row.assigned_agent,
                "title": row.title,
                "queued_age_seconds": age_seconds,
                "threshold_seconds": threshold_seconds,
                "runner_supported": row.assigned_agent in SUPPORTED_RUNNER_AGENTS,
            })
        if row.assigned_agent not in SUPPORTED_RUNNER_AGENTS:
            blocked_capabilities.append({
                "task_id": row.id,
                "assigned_agent": row.assigned_agent,
                "reason": "No runner is registered for this assigned_agent.",
            })
    return {
        "stale_queue_items": stale_queue_items,
        "blocked_capabilities": blocked_capabilities,
    }


def _heartbeat_history_summary(rows: list[AgentTaskEventRow]) -> dict[str, Any]:
    heartbeat_rows = [row for row in rows if row.event_type == "master_heartbeat_completed"]
    if not heartbeat_rows:
        return {"count": 0}
    newest = heartbeat_rows[0]
    oldest = heartbeat_rows[-1]
    repeated_states: dict[str, int] = {}
    for row in heartbeat_rows:
        message = (row.message or "").strip()
        if message:
            repeated_states[message] = repeated_states.get(message, 0) + 1
    top_repeated = sorted(repeated_states.items(), key=lambda item: item[1], reverse=True)[:3]
    return {
        "count": len(heartbeat_rows),
        "newest_at": newest.created_at.isoformat() if newest.created_at else None,
        "oldest_at": oldest.created_at.isoformat() if oldest.created_at else None,
        "repeated_state_summaries": [
            {"state": state, "count": count}
            for state, count in top_repeated
            if count > 1
        ],
        "note": "Prior heartbeat prose is summarized here to avoid feeding old status text back into the next LLM call.",
    }


def _capabilities_context(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": cap.get("name"),
            "capability_type": cap.get("capability_type"),
            "source": cap.get("source"),
            "purpose": cap.get("purpose"),
            "risk_level": cap.get("risk_level"),
            "requires_approval": cap.get("requires_approval"),
            "autonomous_allowed": cap.get("autonomous_allowed"),
            "last_status": cap.get("last_status"),
            "last_verified_at": cap.get("last_verified_at"),
        }
        for cap in capabilities[:25]
    ]


def _build_wake_context(
    *,
    started_at: datetime,
    actor: str,
    agent_config: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    recent_reports: list[dict[str, Any]],
    recent_events: list[dict[str, Any]],
    heartbeat_history: dict[str, Any],
    queue_analysis: dict[str, Any],
    capabilities: list[dict[str, Any]],
    active_goal: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "kind": "master_agent_wake_context_v1",
        "note": (
            "This is the complete context packet loaded by the heartbeat before "
            "the optional OpenClaw status-writing call."
        ),
        "actor": actor,
        "woke_at": started_at.isoformat(),
        "mission": {
            "state": "Build and operate Possible OS as a self-improving operating system for Possible Minds.",
            "goal": "Keep the system observable, delegate bounded work, report status clearly, and improve through traces, reports, evals, and approved code or skill changes.",
            "goal_source": "bootstrap mission in app/services/master_agent.py::_build_wake_context; future version should load durable master plans",
            "protected_context": "soul.md is read as constitutional context and must not be edited by heartbeat.",
        },
        "soul_compact": _compact_soul_context(),
        "active_goal": active_goal or {},
        "configuration": agent_config,
        "capabilities_today": _capabilities_context(capabilities),
        "current_tasks": active_tasks,
        "queue_analysis": queue_analysis,
        "recent_reports": recent_reports[:5],
        "recent_events": recent_events[:8],
        "recent_heartbeat_summary": heartbeat_history,
        "constraints": [
            "No automatic code edits from heartbeat.",
            "No email, mailbox, or external business action from heartbeat.",
            "No destructive git action without explicit human approval.",
            "Subagent reports are evidence, not final truth.",
        ],
        "next_recommended_slice": (
            "Add SystemsHealthAgent log observation and bug-fix delegation, then "
            "connect reports to reviewable improvement findings."
        ),
        "soul": _soul_context(),
    }


def _build_human_status(
    *,
    active_count: int,
    queued_count: int,
    blocked_count: int,
    stale_ids: list[str],
    queue_analysis: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    recent_reports: list[dict[str, Any]],
    active_goal: dict[str, Any] | None,
) -> dict[str, Any]:
    stale_queue_items = queue_analysis.get("stale_queue_items") or []
    blocked_capabilities = queue_analysis.get("blocked_capabilities") or []
    if stale_ids:
        state = f"I found {len(stale_ids)} stale task{'s' if len(stale_ids) != 1 else ''} that need attention."
    elif stale_queue_items:
        state = f"I found {len(stale_queue_items)} queued task{'s' if len(stale_queue_items) != 1 else ''} older than the queue-age threshold."
    elif blocked_capabilities:
        state = f"I found {len(blocked_capabilities)} task capability gap{'s' if len(blocked_capabilities) != 1 else ''}."
    elif blocked_count:
        state = f"I am watching {blocked_count} blocked task{'s' if blocked_count != 1 else ''}."
    elif queued_count:
        state = f"I have {queued_count} queued task{'s' if queued_count != 1 else ''} ready for a worker."
    elif active_count:
        state = f"I am monitoring {active_count} active task{'s' if active_count != 1 else ''}."
    else:
        state = "I am idle right now. No active, queued, blocked, or stale subagent tasks need intervention."

    if active_goal and active_goal.get("goal"):
        focus = str(active_goal.get("goal"))
    elif active_tasks:
        focus = active_tasks[0]["title"]
    elif recent_reports:
        focus = recent_reports[0].get("summary") or "Review the latest subagent report."
    else:
        focus = "Keep the master-agent loop healthy and prepare the next useful development slice."

    intent = [
        "Keep checking the task board on the configured heartbeat period.",
        "Surface stale, blocked, or newly reported work in the Agents UI.",
        "Use the next approved slice to add log observation and bug-fix delegation.",
    ]
    if queued_count:
        intent.insert(0, "Let the subagent runner claim queued work when its worker type is supported.")
    if stale_queue_items:
        intent.insert(0, "Escalate or run queued work that has exceeded the queue-age threshold.")
    if stale_ids:
        intent.insert(0, "Show the stale task IDs so an operator can decide whether to restart, cancel, or reassign them.")

    needs = (
        "Nothing required from Pranav right now."
        if not stale_ids and not blocked_count and not stale_queue_items and not blocked_capabilities
        else "Review the stale or blocked tasks and decide whether to unblock, cancel, or reassign them."
    )

    return {
        "state": state,
        "goal": (
            str(active_goal.get("goal"))
            if active_goal and active_goal.get("goal")
            else "Operate Possible OS as a self-improving system: observe work, delegate bounded tasks, report clearly, learn from evidence, and improve only through reviewable changes."
        ),
        "current_focus": focus,
        "intended_next_steps": (
            list(active_goal.get("next_actions") or [])
            if active_goal and active_goal.get("next_actions")
            else intent
        ),
        "needs_from_user": needs,
        "confidence": "High for task-board status. Limited for app health until SystemsHealthAgent gets log access.",
    }


def _normalize_status_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:5]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _validate_llm_human_status(parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    status = {
        "state": str(parsed.get("state") or fallback["state"]).strip(),
        "goal": str(parsed.get("goal") or fallback["goal"]).strip(),
        "current_focus": str(parsed.get("current_focus") or fallback["current_focus"]).strip(),
        "intended_next_steps": _normalize_status_list(parsed.get("intended_next_steps"))
        or list(fallback["intended_next_steps"]),
        "needs_from_user": str(parsed.get("needs_from_user") or fallback["needs_from_user"]).strip(),
        "confidence": str(parsed.get("confidence") or fallback["confidence"]).strip(),
        "reasoning": str(parsed.get("reasoning") or "").strip(),
    }
    for key in ("state", "goal", "current_focus", "needs_from_user", "confidence", "reasoning"):
        if len(status[key]) > 1200:
            status[key] = status[key][:1197].rstrip() + "..."
    return status


async def _compose_human_status_with_llm(
    *,
    wake_context: dict[str, Any],
    fallback_status: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "stable_context": {
            "compact_soul": _compact_soul_context(),
            "output_contract": {
                "required_fields": [
                    "state",
                    "goal",
                    "current_focus",
                    "intended_next_steps",
                    "needs_from_user",
                    "confidence",
                    "reasoning",
                ],
            },
        },
        "wake_context": wake_context,
        "fallback_status": fallback_status,
        "instructions": {
            "return_json_only": True,
            "do_not_execute_tools": True,
            "do_not_invent_external_observations": True,
        },
    }
    result = await call_skill_json(
        skill_path=MASTER_STATUS_SKILL_PATH,
        payload=payload,
        required_fields=[
            "state",
            "goal",
            "current_focus",
            "intended_next_steps",
            "needs_from_user",
            "confidence",
            "reasoning",
        ],
        model=MASTER_STATUS_MODEL,
        max_tokens=int(os.getenv("MASTER_AGENT_STATUS_MAX_TOKENS", "1200")),
        timeout_s=int(os.getenv("MASTER_AGENT_STATUS_TIMEOUT_S", "60")),
        retries=int(os.getenv("MASTER_AGENT_STATUS_RETRIES", "1")),
    )
    status = _validate_llm_human_status(result.parsed, fallback_status)
    metadata = {
        "used_llm": True,
        "model": result.model,
        "skill_path": str(MASTER_STATUS_SKILL_PATH),
        "raw_response": result.raw_response[:4000],
    }
    return status, metadata


async def ensure_agent_tables() -> None:
    """Create agent tables on demand if Alembic has not been applied yet."""
    global _agent_tables_checked
    if _agent_tables_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(AgentTaskRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentTaskEventRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentReportRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentActionRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentActionEventRow.__table__.create, checkfirst=True)
        await conn.run_sync(AgentCapabilityRow.__table__.create, checkfirst=True)
        await conn.run_sync(MasterGoalRow.__table__.create, checkfirst=True)
    _agent_tables_checked = True


async def _probe_capability(definition: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    command = definition.get("command_json") or {}
    if command.get("safe_probe") is False:
        return "declared", {"reason": "Capability is actionful; discovery does not execute it as a probe."}
    if command.get("method") == "GET" and command.get("url"):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(str(command["url"]))
            return (
                "ok" if response.status_code < 400 else "failed",
                {"status_code": response.status_code, "sample": _compact_text(response.text, limit=160)},
            )
        except Exception as exc:
            return "failed", {"error": f"{type(exc).__name__}: {exc}"}
    argv = command.get("argv")
    if isinstance(argv, list) and argv:
        try:
            proc = await asyncio.create_subprocess_exec(
                *[str(part) for part in argv],
                cwd=str(_repo_root()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
            status = "ok" if proc.returncode == 0 else "failed"
            return status, {
                "returncode": proc.returncode,
                "stdout_sample": _compact_text(stdout.decode("utf-8", errors="replace"), limit=240),
                "stderr_sample": _compact_text(stderr.decode("utf-8", errors="replace"), limit=240),
            }
        except Exception as exc:
            return "failed", {"error": f"{type(exc).__name__}: {exc}"}
    return "unknown", {"reason": "No safe probe is defined."}


async def refresh_agent_capabilities(*, probe: bool = True, actor: str = "operator") -> list[dict[str, Any]]:
    await ensure_agent_tables()
    now = _utcnow()
    refreshed: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        for definition in CAPABILITY_DEFINITIONS:
            status = "declared"
            metadata: dict[str, Any] = {"definition_version": 1}
            verified_at = None
            if probe:
                status, probe_metadata = await _probe_capability(definition)
                metadata.update({"probe": probe_metadata})
                verified_at = now
            existing = (await session.execute(
                select(AgentCapabilityRow)
                .where(AgentCapabilityRow.name == definition["name"])
                .where(AgentCapabilityRow.source == definition["source"])
                .limit(1)
            )).scalar_one_or_none()
            if existing is None:
                existing = AgentCapabilityRow(
                    id=_new_id("cap"),
                    name=definition["name"],
                    source=definition["source"],
                )
            existing.capability_type = definition["capability_type"]
            existing.purpose = definition["purpose"]
            existing.risk_level = definition["risk_level"]
            existing.requires_approval = bool(definition["requires_approval"])
            existing.autonomous_allowed = bool(definition["autonomous_allowed"])
            existing.command_json = definition.get("command_json") or {}
            existing.metadata_json = metadata
            existing.last_status = status
            existing.last_verified_at = verified_at
            existing.updated_at = now
            session.add(existing)
            refreshed.append(capability_to_dict(existing))
        await session.commit()
    await safe_record_product_trace(
        actor_type="agent" if actor != "operator" else "user",
        actor_id=actor,
        event_type="agent_capabilities_refreshed",
        surface="agents",
        entity_type="agent_capability",
        entity_id="registry",
        output_json={"count": len(refreshed), "probed": probe},
    )
    return await list_agent_capabilities(limit=100)


async def list_agent_capabilities(*, limit: int = 100) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentCapabilityRow)
            .order_by(AgentCapabilityRow.capability_type.asc(), AgentCapabilityRow.name.asc())
            .limit(max(1, min(limit, 500)))
        )).scalars().all()
        if not rows:
            return await refresh_agent_capabilities(probe=False, actor="master-agent")
        return [capability_to_dict(row) for row in rows]


async def synthesize_master_goal(
    *,
    actor: str,
    queue_analysis: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    recent_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    await ensure_agent_tables()
    stale_queue_items = queue_analysis.get("stale_queue_items") or []
    blocked_capabilities = queue_analysis.get("blocked_capabilities") or []
    systems_health_ready = any(
        task.get("assigned_agent") == "SystemsHealthAgent" and task.get("status") == "queued"
        for task in active_tasks
    )
    if stale_queue_items:
        goal = "Resolve stale queued agent work before expanding autonomy."
        why = "At least one queued task has exceeded the queue-age threshold, so the control loop needs escalation or execution."
        next_actions = [
            "Run supported queued work if a safe worker exists.",
            "Mark unsupported queued work blocked with the missing capability.",
            "Record the outcome as an agent report or task event.",
        ]
        success_metric = "No high-priority queued task remains beyond the stale queue threshold without a runner or explicit blocked state."
        confidence = "high"
    elif blocked_capabilities:
        goal = "Expose missing runner capabilities and ask for the smallest implementation slice."
        why = "A queued task names an agent that the current runner cannot execute."
        next_actions = [
            "Create a bounded worker implementation for the missing agent.",
            "Keep the task queued or blocked until the worker can report safely.",
        ]
        success_metric = "Every queued task is either supported by a runner or clearly marked blocked."
        confidence = "high"
    elif systems_health_ready:
        goal = "Run the read-only SystemsHealthAgent observation slice."
        why = "System health observation is the next missing sensory layer for Possible OS."
        next_actions = [
            "Claim the SystemsHealthAgent task.",
            "Inspect bounded read-only health sources.",
            "Create a health report with anomalies, risks, and recommended delegations.",
        ]
        success_metric = "A SystemsHealthAgent report exists with observed sources and no unauthorized mutations."
        confidence = "medium"
    elif recent_reports:
        goal = "Convert latest agent reports into reviewable improvement findings."
        why = "A report exists; the learning loop should not stop at an artifact."
        next_actions = [
            "Review the latest report evidence.",
            "Create improvement findings or todos where appropriate.",
            "Decide whether an eval or coding task packet is justified.",
        ]
        success_metric = "Each useful report produces an accepted finding, todo, eval, or explicit no-action decision."
        confidence = "medium"
    else:
        goal = "Maintain observability and discover the next highest-leverage operating gap."
        why = "No active queued work or recent report requires immediate action."
        next_actions = [
            "Refresh capabilities.",
            "Inspect recent traces and business workflow state.",
            "Delegate the smallest safe next slice.",
        ]
        success_metric = "A verified next action is selected from live state rather than a hardcoded mission."
        confidence = "low"

    active_capabilities = [
        cap.get("name")
        for cap in capabilities
        if cap.get("autonomous_allowed") and cap.get("last_status") in {"ok", "declared"}
    ][:10]
    now = _utcnow()
    row = MasterGoalRow(
        id=_new_id("goal"),
        status="active",
        goal=goal,
        why=why,
        time_horizon="current operating slice",
        success_metric=success_metric,
        next_actions_json=next_actions,
        source_json={
            "actor": actor,
            "stale_queue_items": stale_queue_items,
            "blocked_capabilities": blocked_capabilities,
            "active_task_count": len(active_tasks),
            "available_autonomous_capabilities": active_capabilities,
        },
        confidence=confidence,
        created_by=actor,
        expires_at=now + timedelta(seconds=MASTER_GOAL_TTL_SECONDS),
    )
    async with AsyncSessionLocal() as session:
        old_goals = (await session.execute(
            select(MasterGoalRow).where(MasterGoalRow.status == "active")
        )).scalars().all()
        for old in old_goals:
            old.status = "superseded"
            session.add(old)
        session.add(row)
        session.add(AgentTaskEventRow(
            task_id=None,
            agent_id="master-agent",
            event_type="master_goal_synthesized",
            message=goal,
            input_json=row.source_json,
            output_json={"goal_id": row.id, "goal": goal, "next_actions": next_actions},
            metadata_json={"confidence": confidence},
        ))
        await session.commit()
        await session.refresh(row)
        result = goal_to_dict(row)
    await safe_record_product_trace(
        actor_type="agent",
        actor_id=actor,
        event_type="master_goal_synthesized",
        surface="agents",
        entity_type="master_goal",
        entity_id=result["id"],
        output_json=result,
    )
    return result


async def list_master_goals(*, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        stmt = select(MasterGoalRow).order_by(MasterGoalRow.created_at.desc()).limit(max(1, min(limit, 100)))
        if status and status != "all":
            stmt = stmt.where(MasterGoalRow.status == status)
        rows = (await session.execute(stmt)).scalars().all()
        return [goal_to_dict(row) for row in rows]


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


def _systems_health_task_kwargs(*, created_by: str) -> dict[str, Any]:
    return {
        "assigned_agent": "SystemsHealthAgent",
        "title": SYSTEMS_HEALTH_AGENT_TITLE,
        "objective": (
            "Design and implement the first safe SystemsHealthAgent slice. The agent should "
            "observe Possible OS operational health through bounded read-only sources, summarize "
            "bugs or anomalies, redact secrets, and produce reviewable bug-fix delegation packets. "
            "This task must start with observation and reporting before any code-changing autonomy."
        ),
        "context": {
            "source_doc": "docs/MASTER_AGENT_LEARNING_SYSTEM.md",
            "trigger": "master heartbeat next recommended slice",
            "horizontal_slice": "observe/report first; execute/fix later after review",
            "candidate_log_sources": [
                "systemctl status autocaller-backend.service",
                "systemctl status autocaller-frontend.service",
                "journalctl -u autocaller-backend.service",
                "journalctl -u autocaller-frontend.service",
                "product_traces",
                "agent_task_events",
                "backend health endpoint",
                "frontend route health",
            ],
        },
        "allowed_tools": [
            "read_logs",
            "read_product_traces",
            "read_agent_events",
            "read_git_status",
            "run_validation_commands",
            "write_agent_report",
            "create_bug_finding",
            "create_coding_subagent_task_packet",
        ],
        "forbidden_actions": [
            "edit soul.md",
            "send email",
            "modify mailboxes",
            "modify Front/Zoho/Gmail state",
            "run destructive git commands",
            "restart services without explicit operator approval",
            "apply code changes without explicit operator approval",
            "force push",
        ],
        "expected_output_schema": {
            "summary": "string",
            "observed_sources": ["string"],
            "anomalies": ["string"],
            "bug_findings": ["object"],
            "recommended_delegations": ["object"],
            "validation_commands": ["string"],
            "risks": ["string"],
        },
        "acceptance_criteria": [
            "Defines bounded read-only log and health sources.",
            "Produces a human-readable health report before proposing any fix.",
            "Redacts secrets and avoids dumping raw logs into LLM context.",
            "Creates reviewable bug-fix delegation packets with exact evidence and validation commands.",
            "Does not edit code, restart services, or run destructive git commands without approval.",
        ],
        "verification_commands": [
            ".venv/bin/python -m py_compile app/services/master_agent.py app/api/agents.py app/cli.py",
            ".venv/bin/pytest tests/test_master_agent.py tests/test_product_traces.py -q",
            "cd frontend && npx tsc --noEmit",
        ],
        "risk_level": "medium",
        "requires_human_approval": True,
        "priority": 90,
        "heartbeat_interval_seconds": 300,
        "created_by": created_by,
    }


async def create_systems_health_agent_task(*, created_by: str = "operator") -> dict[str, Any]:
    return await create_agent_task(**_systems_health_task_kwargs(created_by=created_by))


async def maybe_auto_delegate_next_slice(*, actor: str) -> dict[str, Any] | None:
    """Create one safe next-slice task when the board is otherwise idle.

    This is delegation only. It does not run the worker or mutate app code.
    """
    await ensure_agent_tables()
    now = _utcnow()
    kwargs = _systems_health_task_kwargs(created_by="master-agent-heartbeat")
    task_id = _new_id("task")
    async with AsyncSessionLocal() as session:
        active_existing = (await session.execute(
            select(AgentTaskRow)
            .where(AgentTaskRow.status.in_(list(ACTIVE_TASK_STATUSES)))
            .limit(1)
        )).scalar_one_or_none()
        if active_existing:
            return None
        prior_systems_health = (await session.execute(
            select(AgentTaskRow)
            .where(AgentTaskRow.assigned_agent == "SystemsHealthAgent")
            .where(AgentTaskRow.title == SYSTEMS_HEALTH_AGENT_TITLE)
            .limit(1)
        )).scalar_one_or_none()
        if prior_systems_health:
            return None
        row = AgentTaskRow(
            id=task_id,
            assigned_agent=kwargs["assigned_agent"],
            title=kwargs["title"],
            objective=kwargs["objective"],
            context_json=kwargs["context"],
            allowed_tools_json=kwargs["allowed_tools"],
            forbidden_actions_json=kwargs["forbidden_actions"],
            expected_output_schema_json=kwargs["expected_output_schema"],
            acceptance_criteria_json=kwargs["acceptance_criteria"],
            verification_commands_json=kwargs["verification_commands"],
            risk_level=kwargs["risk_level"],
            requires_human_approval=kwargs["requires_human_approval"],
            priority=kwargs["priority"],
            heartbeat_interval_seconds=kwargs["heartbeat_interval_seconds"],
            created_by=kwargs["created_by"],
        )
        session.add(row)
        await session.flush()
        session.add(AgentTaskEventRow(
            task_id=task_id,
            agent_id="master-agent",
            event_type="task_created",
            message="Auto-delegated next safe slice to SystemsHealthAgent.",
            input_json={
                "reason": "task board was idle and next recommended slice was internal observation/delegation",
                "actor": actor,
                "created_at": now.isoformat(),
            },
            output_json={"status": "queued", "assigned_agent": "SystemsHealthAgent"},
            metadata_json={"auto_delegated": True},
        ))
        session.add(AgentTaskEventRow(
            task_id=None,
            agent_id="master-agent",
            event_type="next_slice_delegated",
            message="Created SystemsHealthAgent task from heartbeat next recommended slice.",
            input_json={"actor": actor, "started_at": now.isoformat()},
            output_json={"task_id": task_id, "status": "queued"},
            metadata_json={"requires_human_approval": True},
        ))
        await session.commit()
        await session.refresh(row)
        task = task_to_dict(row)
    await safe_record_product_trace(
        actor_type="agent",
        actor_id="master-agent",
        event_type="next_slice_delegated",
        surface="agents",
        entity_type="agent_task",
        entity_id=task_id,
        input_json={"actor": actor, "title": SYSTEMS_HEALTH_AGENT_TITLE},
        output_json={"status": "queued", "assigned_agent": "SystemsHealthAgent"},
        context_json={"reason": "idle board; internal observation slice"},
    )
    return task


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


def _redact_operational_text(value: str) -> str:
    patterns = [
        (re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(['\"=: ]+)([^\\s'\";,]+)"), r"\1\2[REDACTED]"),
        (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
        (re.compile(r"postgresql://[^\\s]+"), "postgresql://[REDACTED]"),
    ]
    redacted = value
    for pattern, replacement in patterns:
        redacted = pattern.sub(replacement, redacted)
    return redacted


async def _run_read_only_command(argv: list[str], *, timeout: float = 8.0, limit: int = 1200) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(_repo_root()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout_text = _redact_operational_text(stdout.decode("utf-8", errors="replace"))
        stderr_text = _redact_operational_text(stderr.decode("utf-8", errors="replace"))
        return {
            "argv": argv,
            "returncode": proc.returncode,
            "status": "ok" if proc.returncode == 0 else "failed",
            "stdout_sample": _compact_text(stdout_text, limit=limit),
            "stderr_sample": _compact_text(stderr_text, limit=limit),
        }
    except Exception as exc:
        return {
            "argv": argv,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _collect_systems_health_observations() -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    commands = [
        ["systemctl", "is-active", "autocaller-backend.service"],
        ["systemctl", "is-active", "autocaller-frontend.service"],
        ["systemctl", "status", "autocaller-backend.service", "--no-pager", "--lines=20"],
        ["systemctl", "status", "autocaller-frontend.service", "--no-pager", "--lines=20"],
        ["journalctl", "-u", "autocaller-backend.service", "--no-pager", "-n", "60"],
        ["journalctl", "-u", "autocaller-frontend.service", "--no-pager", "-n", "60"],
        ["git", "status", "--short"],
    ]
    for argv in commands:
        observations.append(await _run_read_only_command(argv))

    backend_health: dict[str, Any]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://127.0.0.1:8099/health")
        backend_health = {
            "source": "GET /health",
            "status": "ok" if response.status_code < 400 else "failed",
            "status_code": response.status_code,
            "body_sample": _compact_text(response.text, limit=240),
        }
    except Exception as exc:
        backend_health = {
            "source": "GET /health",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    async with AsyncSessionLocal() as session:
        recent_agent_events = (await session.execute(
            select(AgentTaskEventRow).order_by(AgentTaskEventRow.created_at.desc()).limit(10)
        )).scalars().all()
        recent_traces = (await session.execute(
            select(ProductTraceRow).order_by(ProductTraceRow.created_at.desc()).limit(10)
        )).scalars().all()

    event_summary = [
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "event_type": row.event_type,
            "message": _compact_text(row.message or "", limit=240),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in recent_agent_events
    ]
    trace_summary = [
        {
            "trace_id": row.trace_id,
            "event_type": row.event_type,
            "surface": row.surface,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in recent_traces
    ]

    anomalies: list[str] = []
    for observation in observations:
        argv = " ".join(observation.get("argv") or [])
        if observation.get("status") != "ok":
            anomalies.append(f"Command failed: {argv}")
        sample = f"{observation.get('stdout_sample', '')} {observation.get('stderr_sample', '')}".lower()
        if any(token in sample for token in ["traceback", "exception", "error", "failed"]):
            anomalies.append(f"Recent error-like log signal in: {argv}")
    if backend_health.get("status") != "ok":
        anomalies.append("Backend /health endpoint is not healthy.")

    return {
        "observed_sources": [
            "systemctl is-active/status for backend and frontend",
            "journalctl recent backend/frontend logs",
            "backend /health endpoint",
            "git status --short",
            "recent agent_task_events",
            "recent product_traces",
        ],
        "command_observations": observations,
        "backend_health": backend_health,
        "recent_agent_events": event_summary,
        "recent_product_traces": trace_summary,
        "anomalies": anomalies[:20],
    }


async def claim_next_systems_health_task() -> dict[str, Any] | None:
    await ensure_agent_tables()
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(AgentTaskRow)
            .where(AgentTaskRow.assigned_agent == "SystemsHealthAgent")
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
            agent_id="SystemsHealthAgent",
            event_type="task_claimed",
            message="SystemsHealthAgent claimed queued read-only health observation task.",
            output_json={"status": "running", "claimed_at": now.isoformat()},
        ))
        await session.commit()
        await session.refresh(row)
        return task_to_dict(row)


async def run_systems_health_task(task_id: str | None = None) -> dict[str, Any] | None:
    """Execute one read-only SystemsHealthAgent observation task."""
    await ensure_agent_tables()
    if task_id:
        task = await update_agent_task_status(
            task_id,
            status="running",
            message="SystemsHealthAgent manually started.",
            actor="SystemsHealthAgent",
        )
    else:
        task = await claim_next_systems_health_task()
    if not task:
        return None

    await record_agent_heartbeat(
        task["id"],
        agent_id="SystemsHealthAgent",
        message="Collecting bounded read-only service, log, trace, and git health observations.",
        status="running",
        metadata={"mode": "read_only"},
    )
    observations = await _collect_systems_health_observations()
    anomalies = observations["anomalies"]
    key_findings = anomalies or ["No obvious bounded health anomalies found in this read-only pass."]
    report = await create_agent_report(
        task_id=task["id"],
        agent_id="SystemsHealthAgent",
        status="completed",
        summary=(
            "Read-only systems health pass completed. "
            f"Observed {len(observations['observed_sources'])} source categories and found {len(anomalies)} anomaly note(s)."
        ),
        key_findings=key_findings,
        actions_taken=[
            "Read backend/frontend service state.",
            "Read bounded recent backend/frontend journals.",
            "Checked backend health endpoint.",
            "Read recent agent events and product traces.",
            "Redacted likely secrets from command samples.",
        ],
        artifacts=[],
        evidence=[observations],
        verification=[
            "No code edits were made by SystemsHealthAgent.",
            "No services were restarted by SystemsHealthAgent.",
            "No mailbox, email, call, or external business action was taken.",
        ],
        risks=[
            "Journal snippets are bounded and redacted, but should still be reviewed before sharing externally.",
            "This v1 health pass detects obvious signals only; it does not yet diagnose root cause automatically.",
        ],
        open_questions=[
            "Which anomaly types should automatically become improvement findings?",
            "Should the health pass run periodically after the report format stabilizes?",
        ],
        recommended_next_actions=[
            "Review anomalies in the report.",
            "Create a bounded coding task packet only for reproducible bugs with evidence.",
            "Add more specific checks for lead-gen, email sending, and frontend route health.",
        ],
    )
    await safe_record_product_trace(
        actor_type="agent",
        actor_id="SystemsHealthAgent",
        event_type="systems_health_completed",
        surface="agents",
        entity_type="agent_task",
        entity_id=task["id"],
        output_json={"report_id": report["id"], "anomaly_count": len(anomalies)},
    )
    return report


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
    auto_delegated_task: dict[str, Any] | None = None
    if agent_config.get("auto_delegate_next_slice_enabled", True):
        auto_delegated_task = await maybe_auto_delegate_next_slice(actor=actor)
    stale_ids: list[str] = []
    active_count = 0
    blocked_count = 0
    queued_count = 0
    active_task_snapshots: list[dict[str, Any]] = []
    recent_report_snapshots: list[dict[str, Any]] = []
    recent_event_snapshots: list[dict[str, Any]] = []
    heartbeat_history: dict[str, Any] = {}
    queue_analysis: dict[str, Any] = {}
    capabilities: list[dict[str, Any]] = []
    active_goal: dict[str, Any] | None = None
    human_status: dict[str, Any] = {}
    wake_context: dict[str, Any] = {}
    status_metadata: dict[str, Any] = {"used_llm": False}
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentTaskRow).where(AgentTaskRow.status.in_(list(ACTIVE_TASK_STATUSES)))
        )).scalars().all()
        active_count = len(rows)
        blocked_count = sum(1 for row in rows if row.status == "blocked")
        queued_count = sum(1 for row in rows if row.status == "queued")
        active_task_snapshots = [_short_task_snapshot(row) for row in rows[:20]]
        queue_analysis = _queue_age_analysis(list(rows))
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
        recent_report_rows = (await session.execute(
            select(AgentReportRow).order_by(AgentReportRow.created_at.desc()).limit(5)
        )).scalars().all()
        recent_event_rows = (await session.execute(
            select(AgentTaskEventRow).order_by(AgentTaskEventRow.created_at.desc()).limit(30)
        )).scalars().all()
        recent_report_snapshots = [report_to_dict(row) for row in recent_report_rows]
        heartbeat_history = _heartbeat_history_summary(list(recent_event_rows))
        recent_event_snapshots = [
            _short_event_snapshot(row)
            for row in recent_event_rows
            if row.event_type != "master_heartbeat_completed"
        ][:8]
        capabilities = await list_agent_capabilities(limit=100)
        active_goal = await synthesize_master_goal(
            actor=actor,
            queue_analysis=queue_analysis,
            active_tasks=active_task_snapshots,
            capabilities=capabilities,
            recent_reports=recent_report_snapshots,
        )
        fallback_status = _build_human_status(
            active_count=active_count,
            queued_count=queued_count,
            blocked_count=blocked_count,
            stale_ids=stale_ids,
            queue_analysis=queue_analysis,
            active_tasks=active_task_snapshots,
            recent_reports=recent_report_snapshots,
            active_goal=active_goal,
        )
        wake_context = _build_wake_context(
            started_at=started_at,
            actor=actor,
            agent_config=agent_config,
            active_tasks=active_task_snapshots,
            recent_reports=recent_report_snapshots,
            recent_events=recent_event_snapshots,
            heartbeat_history=heartbeat_history,
            queue_analysis=queue_analysis,
            capabilities=capabilities,
            active_goal=active_goal,
        )
        wake_context["auto_delegated_task"] = auto_delegated_task or {}
        if agent_config.get("status_llm_enabled", True):
            try:
                human_status, status_metadata = await _compose_human_status_with_llm(
                    wake_context=wake_context,
                    fallback_status=fallback_status,
                )
            except LLMGatewayError as exc:
                human_status = {
                    **fallback_status,
                    "reasoning": "OpenClaw gateway status call failed; using deterministic fallback.",
                }
                status_metadata = {
                    "used_llm": False,
                    "error": str(exc),
                    "skill_path": str(MASTER_STATUS_SKILL_PATH),
                    "model": MASTER_STATUS_MODEL,
                }
                logger.warning("master-agent status LLM call failed: %s", exc)
        else:
            human_status = {
                **fallback_status,
                "reasoning": "Status LLM is disabled in agent_config; using deterministic fallback.",
            }
            status_metadata = {"used_llm": False, "disabled": True}
        wake_context["llm_call"] = {
            "enabled": bool(agent_config.get("status_llm_enabled", True)),
            "model": MASTER_STATUS_MODEL,
            "skill_path": str(MASTER_STATUS_SKILL_PATH),
            "status": "succeeded" if status_metadata.get("used_llm") else "fallback",
        }
        session.add(AgentTaskEventRow(
            task_id=None,
            agent_id="master-agent",
            event_type="master_heartbeat_completed",
            message=human_status["state"],
            input_json=wake_context,
            output_json={
                "active_task_count": active_count,
                "queued_task_count": queued_count,
                "blocked_task_count": blocked_count,
                "stale_task_ids": stale_ids,
                "queue_analysis": queue_analysis,
                "human_status": human_status,
                "auto_delegated_task": auto_delegated_task or {},
                "active_goal": active_goal or {},
            },
            metadata_json={
                "trace_id": trace.get("trace_id") if trace else None,
                "status_llm": status_metadata,
            },
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
        "queue_analysis": queue_analysis,
        "heartbeat_enabled": agent_config["heartbeat_enabled"],
        "heartbeat_interval_seconds": agent_config["heartbeat_interval_seconds"],
        "human_status": human_status,
        "wake_context": wake_context,
        "status_llm": status_metadata,
        "auto_delegated_task": auto_delegated_task,
        "active_goal": active_goal,
        "soul": _soul_context(),
        "next_recommended_slice": (
            "Add SystemsHealthAgent log observation and bug-fix delegation, then "
            "connect reports to reviewable improvement findings."
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


async def get_last_heartbeat_result() -> dict[str, Any] | None:
    """Return the latest heartbeat packet, including persisted fallback after restarts."""
    if _last_heartbeat_result:
        return _last_heartbeat_result
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(ProductTraceRow)
            .where(
                ProductTraceRow.event_type == "master_heartbeat_completed",
                ProductTraceRow.surface == "agents",
                ProductTraceRow.entity_type == "master_agent",
                ProductTraceRow.entity_id == "heartbeat",
            )
            .order_by(desc(ProductTraceRow.created_at))
            .limit(1)
        )).scalar_one_or_none()
    if not row or not isinstance(row.output_json, dict):
        return None
    return row.output_json


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
            await run_systems_health_task()
        except Exception:
            logger.exception("subagent runner loop failed")
        await asyncio.sleep(interval_seconds)
