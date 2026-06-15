"""Possible OS master-agent task coordination and heartbeat."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
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
    EmailLogRow,
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
    "tool_runner_enabled": False,
    "tool_runner_max_iterations": 5,
    "tool_runner_max_runtime_seconds": 90,
    "tool_runner_persist_continuation": True,
    "auto_delegate_next_slice_enabled": True,
    "auto_execute_approved_lead_gen_email_enabled": False,
    "auto_execute_approved_lead_gen_email_limit": 1,
}

SYSTEMS_HEALTH_AGENT_TITLE = "Add SystemsHealthAgent log observation and bug-fix delegation"
SUPPORTED_RUNNER_AGENTS = {"ResearchScoutAgent", "SystemsHealthAgent"}
MASTER_GOAL_TTL_SECONDS = 6 * 60 * 60
STALE_QUEUE_MIN_SECONDS = 30 * 60
GOAL_CONTINUATION_AGENT_ID = "MasterAgentToolRunner"
GOAL_CONTINUATION_STATUS = "continuation"


CAPABILITY_DEFINITIONS = [
    {
        "name": "agents status",
        "capability_type": "cli",
        "source": "bin/possibleos agents status --json",
        "purpose": "Inspect master-agent heartbeat config and last heartbeat result.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/possibleos", "agents", "status", "--json"], "safe_probe": True},
    },
    {
        "name": "agents heartbeat",
        "capability_type": "cli",
        "source": "bin/possibleos agents heartbeat --json",
        "purpose": "Run one manual master-agent heartbeat.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/possibleos", "agents", "heartbeat", "--json"], "safe_probe": False},
    },
    {
        "name": "actions list",
        "capability_type": "cli",
        "source": "bin/possibleos actions list --json",
        "purpose": "Inspect durable Possible OS action execution records.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/possibleos", "actions", "list", "--json"], "safe_probe": True},
    },
    {
        "name": "action outcome inspection",
        "capability_type": "runner_tool",
        "source": "master-agent runner tool: action_read",
        "purpose": "Inspect durable action status, policy feedback, execution result, and event timeline without changing anything.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {
            "tool": "action_read",
            "operations": ["get_action", "list_recent"],
            "read_only": True,
        },
    },
    {
        "name": "agent sandbox file workspace",
        "capability_type": "runner_tool",
        "source": "master-agent runner tool: sandbox_write",
        "purpose": "Create, read, append, overwrite, list, and delete files inside the bounded agent sandbox only.",
        "risk_level": "medium",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {
            "tool": "sandbox_write",
            "operations": ["list", "read", "write", "append", "mkdir", "delete"],
            "sandbox_root": "data/agent-sandbox",
            "bounded_write": True,
        },
    },
    {
        "name": "actions policy-check",
        "capability_type": "cli",
        "source": "bin/possibleos actions policy-check <action_id> --json",
        "purpose": "Run reusable action policy checks without execution.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/possibleos", "actions", "policy-check", "<action_id>", "--json"], "safe_probe": False},
    },
    {
        "name": "actions execute",
        "capability_type": "cli",
        "source": "bin/possibleos actions execute <action_id> --json",
        "purpose": "Execute one policy-approved durable action through a narrow adapter.",
        "risk_level": "high",
        "requires_approval": True,
        "autonomous_allowed": False,
        "command_json": {"argv": ["bin/possibleos", "actions", "execute", "<action_id>", "--json"], "safe_probe": False},
    },
    {
        "name": "execute approved lead-gen email actions",
        "capability_type": "cli",
        "source": "bin/possibleos actions execute-approved-lead-gen --limit=1 --actor=master-agent --json",
        "purpose": "Execute exact approved lead-gen email actions through the durable action policy gate. Does not create or modify drafts.",
        "risk_level": "high",
        "requires_approval": True,
        "autonomous_allowed": True,
        "command_json": {
            "argv": ["bin/possibleos", "actions", "execute-approved-lead-gen", "--limit", "1", "--actor", "master-agent", "--json"],
            "safe_probe": False,
        },
    },
    {
        "name": "send approved lead-gen draft action",
        "capability_type": "cli",
        "source": "bin/possibleos actions send-approved-lead-gen-draft --item=<id> --subject=... --body=...",
        "purpose": "Create and optionally execute an exact approved lead-gen email draft action via Zoho-backed send path.",
        "risk_level": "high",
        "requires_approval": True,
        "autonomous_allowed": False,
        "command_json": {
            "argv": ["bin/possibleos", "actions", "send-approved-lead-gen-draft", "--item", "<batch_item_id>", "--subject", "<subject>", "--body", "<body>"],
            "safe_probe": False,
        },
    },
    {
        "name": "send email action",
        "capability_type": "cli",
        "source": "bin/possibleos actions send-email --mode=test|lead_gen --to=<email> --subject=... --body=...",
        "purpose": "Create and optionally execute an exact approved email through the durable action executor. Lead-gen mode requires contact/item metadata and human approval.",
        "risk_level": "high",
        "requires_approval": True,
        "autonomous_allowed": False,
        "command_json": {
            "argv": ["bin/possibleos", "actions", "send-email", "--mode", "test", "--to", "<email>", "--subject", "<subject>", "--body", "<body>"],
            "safe_probe": False,
        },
    },
    {
        "name": "lead-gen email agent slice",
        "capability_type": "cli",
        "source": "bin/possibleos lead-gen email-agent-slice --limit=3 --approval-ready",
        "purpose": "Select senior lead-gen contacts, collect bounded evidence, compose approval-ready drafts through the email composer skill, and create no-send durable lead_gen email actions.",
        "risk_level": "medium",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {
            "argv": ["bin/possibleos", "lead-gen", "email-agent-slice", "--limit", "3", "--approval-ready", "--json"],
            "safe_probe": False,
        },
    },
    {
        "name": "read-only filesystem inspection",
        "capability_type": "cli",
        "source": "bin/possibleos fs <list|read|search|git-status|git-diff|git-log|git-show> --json",
        "purpose": "Inspect code, docs, config, and git state inside the Possible OS repo without modifying files or running arbitrary shell.",
        "risk_level": "medium",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {
            "argv": ["bin/possibleos", "fs", "search", "_build_wake_context", "app/services", "--limit", "3", "--actor", "master-agent", "--json"],
            "safe_probe": True,
            "allowed_root": str(Path(__file__).resolve().parents[2]),
            "operations": ["list_files", "read_file", "search_text", "git_status", "git_diff", "git_log", "git_show"],
            "forbidden": ["writes", "deletes", "installs", "service_restarts", "network_calls", "arbitrary_shell"],
        },
    },
    {
        "name": "run research scout",
        "capability_type": "cli",
        "source": "bin/possibleos agents run-research-scout --json",
        "purpose": "Execute one queued ResearchScoutAgent task and write a learning report.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/possibleos", "agents", "run-research-scout", "--json"], "safe_probe": False},
    },
    {
        "name": "run systems health",
        "capability_type": "cli",
        "source": "bin/possibleos agents run-systems-health --json",
        "purpose": "Execute one queued SystemsHealthAgent read-only health observation task.",
        "risk_level": "medium",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["bin/possibleos", "agents", "run-systems-health", "--json"], "safe_probe": False},
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
        "source": "systemctl is-active possibleos-frontend.service",
        "purpose": "Check whether the frontend systemd service is active.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["systemctl", "is-active", "possibleos-frontend.service"], "safe_probe": True},
    },
    {
        "name": "backend service status",
        "capability_type": "system",
        "source": "systemctl is-active possibleos-backend.service",
        "purpose": "Check whether the backend systemd service is active.",
        "risk_level": "low",
        "requires_approval": False,
        "autonomous_allowed": True,
        "command_json": {"argv": ["systemctl", "is-active", "possibleos-backend.service"], "safe_probe": True},
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
        if "tool_runner_enabled" in raw:
            config["tool_runner_enabled"] = bool(raw.get("tool_runner_enabled"))
        if "tool_runner_max_iterations" in raw:
            try:
                config["tool_runner_max_iterations"] = max(
                    1,
                    min(int(raw.get("tool_runner_max_iterations")), 5),
                )
            except (TypeError, ValueError):
                pass
        if "tool_runner_max_runtime_seconds" in raw:
            try:
                config["tool_runner_max_runtime_seconds"] = max(
                    15,
                    min(int(raw.get("tool_runner_max_runtime_seconds")), 180),
                )
            except (TypeError, ValueError):
                pass
        if "tool_runner_persist_continuation" in raw:
            config["tool_runner_persist_continuation"] = bool(raw.get("tool_runner_persist_continuation"))
        if "auto_delegate_next_slice_enabled" in raw:
            config["auto_delegate_next_slice_enabled"] = bool(raw.get("auto_delegate_next_slice_enabled"))
        if "auto_execute_approved_lead_gen_email_enabled" in raw:
            config["auto_execute_approved_lead_gen_email_enabled"] = bool(
                raw.get("auto_execute_approved_lead_gen_email_enabled")
            )
        if "auto_execute_approved_lead_gen_email_limit" in raw:
            try:
                config["auto_execute_approved_lead_gen_email_limit"] = max(
                    1,
                    min(int(raw.get("auto_execute_approved_lead_gen_email_limit")), 25),
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


def _payload_size(value: Any) -> int:
    if value in (None, {}, []):
        return 0
    try:
        return len(json.dumps(value, default=str))
    except TypeError:
        return len(str(value))


def _event_activity_summary(row: AgentTaskEventRow) -> str:
    output = row.output_json or {}
    if row.event_type == "master_heartbeat_completed":
        human_status = output.get("human_status") if isinstance(output, dict) else None
        if isinstance(human_status, dict):
            state = human_status.get("state")
            if isinstance(state, str) and state.strip():
                return state.strip()
        return (
            f"active {output.get('active_task_count', 0)}, "
            f"queued {output.get('queued_task_count', 0)}, "
            f"blocked {output.get('blocked_task_count', 0)}"
        )
    if row.event_type == "task_created":
        input_json = row.input_json or {}
        title = input_json.get("title") if isinstance(input_json, dict) else None
        if isinstance(title, str) and title.strip():
            return title.strip()
    if row.event_type == "status_changed":
        status = output.get("status") if isinstance(output, dict) else None
        if isinstance(status, str) and status.strip():
            return f"status {status.strip()}"
    return row.message or row.event_type


def event_summary_to_dict(row: AgentTaskEventRow) -> dict[str, Any]:
    input_size = _payload_size(row.input_json)
    output_size = _payload_size(row.output_json)
    metadata_size = _payload_size(row.metadata_json)
    return {
        "id": row.id,
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "event_type": row.event_type,
        "message": row.message,
        "summary": _event_activity_summary(row),
        "has_payload": bool(input_size or output_size or metadata_size),
        "payload_size_bytes": input_size + output_size + metadata_size,
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


def continuation_state_from_report(report: dict[str, Any]) -> dict[str, Any]:
    evidence = report.get("evidence") if isinstance(report, dict) else []
    if not isinstance(evidence, list):
        return {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "goal_continuation_state":
            return item
    return {}


def _valid_continuation_file_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.isdigit():
        return ""
    if "\x00" in text or text.startswith("/") or ".." in text.split("/"):
        return ""
    return text


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


def _short_action_event_snapshot(row: AgentActionEventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "actor": row.actor,
        "message": _compact_text(row.message or "", limit=220),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _email_log_evidence_snapshot(row: EmailLogRow | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "email_log_id": row.id,
        "recipient_email": row.recipient_email,
        "recipient_name": row.recipient_name,
        "subject": row.subject,
        "message_type": row.message_type,
        "transport": row.transport,
        "message_id": row.message_id,
        "status": row.status,
        "error": row.error,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "pif_id": row.pif_id,
        "call_id": row.call_id,
    }


async def _enrich_action_email_log_evidence_for_snapshot(session, row: AgentActionRow) -> None:
    if row.action_type != "send_email" or row.status != "succeeded":
        return
    payload = row.input_json if isinstance(row.input_json, dict) else {}
    result = row.execution_result_json if isinstance(row.execution_result_json, dict) else {}
    if result.get("email_log_id"):
        return
    recipient = str(result.get("sent_to") or payload.get("to") or "").strip().lower()
    if not recipient:
        return
    subject = str(result.get("sent_subject") or payload.get("subject") or "").strip()
    msg_id = str(result.get("sent_message_id") or "").strip()
    email_log: EmailLogRow | None = None
    if msg_id:
        email_log = (await session.execute(
            select(EmailLogRow)
            .where(
                EmailLogRow.recipient_email == recipient,
                EmailLogRow.message_id == msg_id,
            )
            .order_by(desc(EmailLogRow.sent_at))
            .limit(1)
        )).scalar_one_or_none()
    if email_log is None and subject:
        email_log = (await session.execute(
            select(EmailLogRow)
            .where(
                EmailLogRow.recipient_email == recipient,
                EmailLogRow.subject == subject,
            )
            .order_by(desc(EmailLogRow.sent_at))
            .limit(1)
        )).scalar_one_or_none()
    email_log_data = _email_log_evidence_snapshot(email_log)
    if not email_log_data:
        return
    updated = dict(result)
    updated.update({
        "transport": email_log_data.get("transport"),
        "email_log_id": email_log_data.get("email_log_id"),
        "email_log_status": email_log_data.get("status"),
        "email_log": email_log_data,
    })
    if not updated.get("sent_at") and email_log_data.get("sent_at"):
        updated["sent_at"] = email_log_data["sent_at"]
    if not updated.get("sent_message_id") and email_log_data.get("message_id"):
        updated["sent_message_id"] = email_log_data["message_id"]
    row.execution_result_json = updated
    row.updated_at = _utcnow()
    session.add(AgentActionEventRow(
        action_id=row.id,
        event_type="action_email_log_evidence_linked",
        actor="system",
        message="Linked existing email log evidence to successful send action.",
        output_json=email_log_data,
        metadata_json={"source": "master_agent_recent_action_snapshot"},
    ))


def _short_action_snapshot(row: AgentActionRow, events: list[AgentActionEventRow]) -> dict[str, Any]:
    payload = row.input_json if isinstance(row.input_json, dict) else {}
    result = row.execution_result_json if isinstance(row.execution_result_json, dict) else {}
    policy = row.policy_result_json if isinstance(row.policy_result_json, dict) else {}
    failed_checks = [
        str(check.get("name") or "")
        for check in (policy.get("checks") or [])
        if isinstance(check, dict) and not check.get("passed")
    ][:5]
    return {
        "id": row.id,
        "action_type": row.action_type,
        "status": row.status,
        "risk_level": row.risk_level,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "input_summary": {
            "to": payload.get("to"),
            "batch_item_id": payload.get("batch_item_id"),
            "subject": _compact_text(str(payload.get("subject") or ""), limit=180),
            "test_email": payload.get("test_email"),
            "subject_sha256": payload.get("subject_sha256"),
            "body_sha256": payload.get("body_sha256"),
            "composer_variant_key": payload.get("composer_variant_key"),
        },
        "policy_summary": {
            "allowed": policy.get("allowed"),
            "reason": policy.get("reason"),
            "failed_checks": failed_checks,
        },
        "result_summary": {
            "sent_to": result.get("sent_to"),
            "sent_subject": _compact_text(str(result.get("sent_subject") or ""), limit=180),
            "sent_message_id": result.get("sent_message_id"),
            "sent_at": result.get("sent_at"),
            "message_type": result.get("message_type"),
            "transport": result.get("transport"),
            "email_log_id": result.get("email_log_id"),
            "email_log_status": result.get("email_log_status"),
        },
        "error": _compact_text(row.error or "", limit=260),
        "recent_events": [_short_action_event_snapshot(event) for event in events[:5]],
    }


async def _recent_action_snapshots(session, *, limit: int = 8) -> list[dict[str, Any]]:
    action_rows = (await session.execute(
        select(AgentActionRow).order_by(AgentActionRow.created_at.desc()).limit(limit)
    )).scalars().all()
    if not action_rows:
        return []
    changed = False
    for row in action_rows:
        before = row.execution_result_json if isinstance(row.execution_result_json, dict) else {}
        await _enrich_action_email_log_evidence_for_snapshot(session, row)
        after = row.execution_result_json if isinstance(row.execution_result_json, dict) else {}
        changed = changed or before.get("email_log_id") != after.get("email_log_id")
    if changed:
        await session.commit()
    action_ids = [row.id for row in action_rows]
    event_rows = (await session.execute(
        select(AgentActionEventRow)
        .where(AgentActionEventRow.action_id.in_(action_ids))
        .order_by(AgentActionEventRow.created_at.desc(), AgentActionEventRow.id.desc())
    )).scalars().all()
    events_by_action: dict[str, list[AgentActionEventRow]] = {action_id: [] for action_id in action_ids}
    for event in event_rows:
        events_by_action.setdefault(event.action_id, []).append(event)
    return [
        _short_action_snapshot(row, events_by_action.get(row.id, []))
        for row in action_rows
    ]


def _goal_evidence(active_goal: dict[str, Any] | None, recent_actions: list[dict[str, Any]]) -> dict[str, Any]:
    if not active_goal or not active_goal.get("goal"):
        return {}
    goal_text = str(active_goal.get("goal") or "").lower()
    success_metric = str(active_goal.get("success_metric") or "").lower()
    if "test email" not in f"{goal_text} {success_metric}":
        return {}
    for action in recent_actions:
        result = action.get("result_summary") or {}
        input_summary = action.get("input_summary") or {}
        is_test_email_action = (
            action.get("action_type") == "send_test_email"
            or (
                action.get("action_type") == "send_email"
                and bool(input_summary.get("test_email"))
            )
        )
        if (
            is_test_email_action
            and action.get("status") == "succeeded"
            and str(result.get("sent_to") or "").lower() == "pranav.modi@gmail.com"
        ):
            return {
                "status": "satisfied",
                "matched_action_id": action.get("id"),
                "matched_action_type": action.get("action_type"),
                "sent_to": result.get("sent_to"),
                "sent_message_id": result.get("sent_message_id"),
                "sent_at": result.get("sent_at"),
                "reason": "Recent durable action succeeded for the active test-email goal recipient.",
            }
    return {
        "status": "not_yet_satisfied",
        "reason": "No recent succeeded send_test_email action matched the active test-email goal.",
    }


def _action_is_relevant_to_goal(action: dict[str, Any], active_goal: dict[str, Any]) -> bool:
    goal_text = " ".join([
        str(active_goal.get("goal") or ""),
        str(active_goal.get("success_metric") or ""),
        " ".join(str(item) for item in (active_goal.get("next_actions") or [])[:5]),
    ]).lower()
    action_type = str(action.get("action_type") or "").lower()
    entity_type = str(action.get("entity_type") or "").lower()
    input_summary = action.get("input_summary") or {}
    result_summary = action.get("result_summary") or {}
    subject = " ".join([
        str(input_summary.get("subject") or ""),
        str(result_summary.get("sent_subject") or ""),
    ]).lower()
    if "test email" in goal_text:
        return bool(input_summary.get("test_email")) or "test" in action_type
    if "email" in goal_text or "send" in goal_text or "lead-gen" in goal_text or "lead gen" in goal_text:
        return "email" in action_type or "lead_gen" in entity_type
    if "health" in goal_text:
        return "health" in action_type or "health" in entity_type
    if subject and any(token for token in goal_text.split() if len(token) > 5 and token in subject):
        return True
    return False


def _objective_status_context(
    active_goal: dict[str, Any] | None,
    recent_actions: list[dict[str, Any]],
    active_tasks: list[dict[str, Any]],
    recent_reports: list[dict[str, Any]],
    *,
    queue_analysis: dict[str, Any] | None = None,
    goal_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not active_goal or not active_goal.get("goal"):
        return {
            "active_goal_id": None,
            "goal": "",
            "status": "missing_goal",
            "evidence": [{
                "type": "missing_goal",
                "summary": "No active or synthesized master goal is available for this heartbeat.",
            }],
            "remaining_work": ["Set or synthesize a current operating goal."],
            "next_best_action": "Create a bounded operating goal before deciding or delegating work.",
        }

    goal_evidence = goal_evidence or _goal_evidence(active_goal, recent_actions)
    remaining_work = [
        str(item).strip()
        for item in (active_goal.get("next_actions") or [])
        if str(item).strip()
    ]
    evidence: list[dict[str, Any]] = []
    status = "in_progress"
    next_best_action = remaining_work[0] if remaining_work else "Continue collecting evidence toward the active goal."

    if goal_evidence.get("status") == "satisfied":
        evidence.append({
            "type": "goal_satisfied",
            "summary": goal_evidence.get("reason") or "Recent durable evidence satisfies the active goal.",
            "action_id": goal_evidence.get("matched_action_id"),
            "sent_to": goal_evidence.get("sent_to"),
            "sent_message_id": goal_evidence.get("sent_message_id"),
            "sent_at": goal_evidence.get("sent_at"),
        })
        return {
            "active_goal_id": active_goal.get("id"),
            "goal": active_goal.get("goal") or "",
            "status": "satisfied",
            "evidence": evidence,
            "remaining_work": [],
            "next_best_action": "Close or supersede the satisfied goal, then select the next highest-leverage objective.",
        }

    waiting_tasks = [
        task for task in active_tasks
        if task.get("status") == "waiting_on_user"
    ]
    if waiting_tasks:
        status = "waiting_on_user"
        for task in waiting_tasks[:3]:
            evidence.append({
                "type": "task_waiting_on_user",
                "task_id": task.get("id"),
                "title": task.get("title"),
                "assigned_agent": task.get("assigned_agent"),
            })
        next_best_action = "Ask or answer the blocking question, then resume the related task."

    stale_tasks = [
        task for task in active_tasks
        if task.get("status") == "stale"
    ]
    stale_queue_items = []
    if isinstance(queue_analysis, dict):
        stale_queue_items = list(queue_analysis.get("stale_queue_items") or [])
    if status == "in_progress" and (stale_tasks or stale_queue_items):
        status = "stale"
        for task in stale_tasks[:3]:
            evidence.append({
                "type": "task_stale",
                "task_id": task.get("id"),
                "title": task.get("title"),
                "assigned_agent": task.get("assigned_agent"),
            })
        for item in stale_queue_items[:3]:
            evidence.append({
                "type": "queued_task_stale",
                "task_id": item.get("task_id"),
                "title": item.get("title"),
                "queued_age_seconds": item.get("queued_age_seconds"),
                "threshold_seconds": item.get("threshold_seconds"),
            })
        next_best_action = "Resolve stale queued or running work before expanding autonomy."

    failed_relevant_actions = [
        action for action in recent_actions
        if action.get("status") == "failed" and _action_is_relevant_to_goal(action, active_goal)
    ]
    if status == "in_progress" and failed_relevant_actions:
        status = "blocked"
        for action in failed_relevant_actions[:3]:
            evidence.append({
                "type": "failed_relevant_action",
                "action_id": action.get("id"),
                "action_type": action.get("action_type"),
                "entity_type": action.get("entity_type"),
                "entity_id": action.get("entity_id"),
                "error": action.get("error"),
            })
        next_best_action = "Inspect the failed relevant action and fix or replace the blocked execution path."

    if status == "in_progress":
        if goal_evidence:
            evidence.append({
                "type": "goal_evidence",
                "summary": goal_evidence.get("reason") or "No satisfying evidence found yet.",
                "status": goal_evidence.get("status") or "unknown",
            })
        else:
            evidence.append({
                "type": "no_satisfying_evidence",
                "summary": "No durable evidence yet shows the active objective is complete, blocked, stale, or waiting on the user.",
            })

    return {
        "active_goal_id": active_goal.get("id"),
        "goal": active_goal.get("goal") or "",
        "status": status,
        "evidence": evidence,
        "remaining_work": remaining_work,
        "next_best_action": next_best_action,
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


def _context_sha256(value: dict[str, Any]) -> str:
    payload = json_dumps_stable(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def json_dumps_stable(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prime_directives_context() -> list[str]:
    return [
        "Move fast toward the user's stated short-term and long-term goals, effectively and efficiently.",
        "Maintain and improve a good mental model of how the system works and how it can improve over short and long horizons.",
    ]


def _wake_decision_questions() -> list[str]:
    return [
        "What is the user's most important stated goal right now?",
        "What is the fastest safe next move toward it?",
        "What does the current system state say is blocking progress?",
        "What did we learn since the last wake?",
        "Should the system model, skill, code, eval, or plan be updated?",
        "What should be done now, delegated, postponed, or escalated to the user?",
    ]


def _stable_operating_doctrine_context() -> dict[str, Any]:
    return {
        "context_design": "Stable first, volatile last. Use cached context for identity, doctrine, schemas, capability definitions, and durable knowledge summaries.",
        "ooda_loop": ["observe", "orient", "decide", "act"],
        "learning_rule": "Separate raw evidence from interpreted objective status and durable knowledge.",
        "horizontal_slices": "Prefer the smallest end-to-end slice that creates observable value.",
        "approval_posture": {
            "ask_before": [
                "unapproved outbound email",
                "live calls",
                "destructive data changes",
                "billing or DNS changes",
                "modifying read-only inboxes",
                "editing soul.md",
            ],
            "safe_autonomy": [
                "read-only inspection",
                "status synthesis",
                "creating bounded subagent tasks",
                "executing already-approved lead-gen email actions when enabled",
            ],
        },
    }


def _stable_output_schema_context() -> dict[str, Any]:
    return {
        "human_status": {
            "required_fields": [
                "state",
                "goal",
                "current_focus",
                "intended_next_steps",
                "needs_from_user",
                "confidence",
                "reasoning",
            ],
            "style": "concise human employee status update for a founder-operator",
        }
    }


def _stable_capability_definitions(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cap in capabilities:
        rows.append({
            "name": cap.get("name"),
            "capability_type": cap.get("capability_type"),
            "source": cap.get("source"),
            "purpose": cap.get("purpose"),
            "risk_level": cap.get("risk_level"),
            "requires_approval": cap.get("requires_approval"),
            "autonomous_allowed": cap.get("autonomous_allowed"),
        })
    return sorted(rows, key=lambda row: str(row.get("name") or ""))


def _capabilities_state_context(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cap in capabilities:
        rows.append({
            "name": cap.get("name"),
            "last_status": cap.get("last_status"),
            "last_verified_at": cap.get("last_verified_at"),
        })
    return sorted(rows, key=lambda row: str(row.get("name") or ""))


def _stable_knowledge_summaries_stub() -> list[dict[str, Any]]:
    return [
        {
            "slug": "possible-os",
            "version": 1,
            "confidence": "medium",
            "summary": "Possible OS is the operating system for Possible Minds: observe work, act through approved paths, learn from traces and outcomes, and improve tools, skills, docs, UI, and code.",
        },
        {
            "slug": "lead-gen-loop",
            "version": 1,
            "confidence": "medium",
            "summary": "Lead gen loop: select senior contacts, compose drafts with the email skill, get user approval, send approved actions through policy gates, observe replies and outcomes, then improve targeting and composition.",
        },
        {
            "slug": "action-execution",
            "version": 1,
            "confidence": "medium",
            "summary": "Durable actions are policy-checked records. Approved lead-gen sends execute through the Zoho-backed email path and link to email_logs when available.",
        },
        {
            "slug": "master-agent-heartbeat",
            "version": 1,
            "confidence": "medium",
            "summary": "Heartbeat builds a wake context, optionally executes narrow enabled actions, writes a human status update through the gateway, records events and traces, and exposes input/output JSON in the Agents UI.",
        },
    ]


def _cached_static_context(capabilities: list[dict[str, Any]]) -> dict[str, Any]:
    context = {
        "prime_directives": _prime_directives_context(),
        "soul_compact": _compact_soul_context(),
        "stable_operating_doctrine": _stable_operating_doctrine_context(),
        "stable_output_schema": _stable_output_schema_context(),
        "stable_capability_definitions": _stable_capability_definitions(capabilities),
        "stable_knowledge_summaries": _stable_knowledge_summaries_stub(),
        "wake_decision_questions": _wake_decision_questions(),
    }
    context["cache_design"] = {
        "provider": "openai_codex_gateway",
        "rule": "Keep this object byte-stable across heartbeats whenever inputs do not change.",
        "hash": _context_sha256(context),
    }
    return context


def _goal_stack_context(active_goal: dict[str, Any] | None) -> dict[str, Any]:
    current = active_goal or {}
    return {
        "short_term": current,
        "medium_term": {
            "goal": "Build a cybernetic lead-generation loop with human approval, observable outcomes, and self-improving contact selection and email composition.",
            "source": "durable product direction",
        },
        "long_term": {
            "goal": "Build Possible OS as a self-improving operating system for Possible Minds.",
            "source": "prime operating mission",
        },
    }


def _current_state_context(
    *,
    agent_config: dict[str, Any],
    active_tasks: list[dict[str, Any]],
    queue_analysis: dict[str, Any],
    recent_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    approved_lead_gen_actions = [
        action for action in recent_actions
        if action.get("action_type") == "send_email"
        and action.get("status") == "approved"
        and action.get("entity_type") == "lead_gen_email"
    ]
    latest_sent = next(
        (
            action for action in recent_actions
            if action.get("status") == "succeeded"
            and (action.get("result_summary") or {}).get("sent_at")
        ),
        None,
    )
    return {
        "heartbeat_enabled": bool(agent_config.get("heartbeat_enabled")),
        "heartbeat_interval_seconds": agent_config.get("heartbeat_interval_seconds"),
        "tool_runner_enabled": bool(agent_config.get("tool_runner_enabled")),
        "tool_runner_max_iterations": agent_config.get("tool_runner_max_iterations"),
        "tool_runner_max_runtime_seconds": agent_config.get("tool_runner_max_runtime_seconds"),
        "tool_runner_persist_continuation": bool(agent_config.get("tool_runner_persist_continuation")),
        "auto_send_approved_lead_gen_enabled": bool(agent_config.get("auto_execute_approved_lead_gen_email_enabled")),
        "auto_send_approved_lead_gen_limit": agent_config.get("auto_execute_approved_lead_gen_email_limit"),
        "active_task_count": len(active_tasks),
        "queued_task_count": sum(1 for task in active_tasks if task.get("status") == "queued"),
        "blocked_task_count": sum(1 for task in active_tasks if task.get("status") == "blocked"),
        "approved_lead_gen_actions_in_recent_window": len(approved_lead_gen_actions),
        "latest_sent_action": latest_sent or {},
        "queue_analysis": queue_analysis,
    }


def _recent_evidence_context(recent_actions: list[dict[str, Any]], recent_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for action in recent_actions[:5]:
        result = action.get("result_summary") or {}
        if action.get("status") in {"succeeded", "failed"}:
            evidence.append({
                "type": f"action_{action.get('status')}",
                "action_id": action.get("id"),
                "action_type": action.get("action_type"),
                "recipient": result.get("sent_to") or (action.get("input_summary") or {}).get("to"),
                "sent_at": result.get("sent_at"),
                "email_log_id": result.get("email_log_id"),
                "status": action.get("status"),
            })
    for report in recent_reports[:3]:
        evidence.append({
            "type": "agent_report",
            "report_id": report.get("id"),
            "task_id": report.get("task_id"),
            "status": report.get("status"),
            "summary": _compact_text(str(report.get("summary") or ""), limit=220),
            "created_at": report.get("created_at"),
        })
    return evidence


def _volatile_wake_state(
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
    recent_actions: list[dict[str, Any]],
    goal_evidence: dict[str, Any],
    goal_continuation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    objective_status = _objective_status_context(
        active_goal,
        recent_actions,
        active_tasks,
        recent_reports,
        queue_analysis=queue_analysis,
        goal_evidence=goal_evidence,
    )
    return {
        "woke_at": started_at.isoformat(),
        "actor": actor,
        "goal_stack": _goal_stack_context(active_goal),
        "active_goal": active_goal or {},
        "objective_status": objective_status,
        "current_state": _current_state_context(
            agent_config=agent_config,
            active_tasks=active_tasks,
            queue_analysis=queue_analysis,
            recent_actions=recent_actions,
        ),
        "recent_evidence": _recent_evidence_context(recent_actions, recent_reports),
        "capabilities_state": _capabilities_state_context(capabilities),
        "configuration": agent_config,
        "current_tasks": active_tasks,
        "recent_actions": recent_actions,
        "goal_evidence": goal_evidence,
        "tool_runner": {
            "enabled": bool(agent_config.get("tool_runner_enabled")),
            "allowed_tools": ["filesystem_read", "action_read", "sandbox_write"],
            "sandbox_root": "data/agent-sandbox",
            "max_iterations": agent_config.get("tool_runner_max_iterations"),
            "max_runtime_seconds": agent_config.get("tool_runner_max_runtime_seconds"),
            "persist_continuation": bool(agent_config.get("tool_runner_persist_continuation")),
        },
        "goal_continuation_state": goal_continuation_state or {},
        "previous_heartbeat_summary": (
            (goal_continuation_state or {}).get("tool_loop", {}).get("previous_heartbeat_summary")
            if isinstance((goal_continuation_state or {}).get("tool_loop"), dict)
            else {}
        ),
        "queue_analysis": queue_analysis,
        "recent_reports": recent_reports[:5],
        "recent_events": recent_events[:8],
        "recent_heartbeat_summary": heartbeat_history,
    }


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
    recent_actions: list[dict[str, Any]],
    goal_continuation_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    goal_evidence = _goal_evidence(active_goal, recent_actions)
    cached_static_context = _cached_static_context(capabilities)
    volatile_wake_state = _volatile_wake_state(
        started_at=started_at,
        actor=actor,
        agent_config=agent_config,
        active_tasks=active_tasks,
        recent_reports=recent_reports,
        recent_events=recent_events,
        heartbeat_history=heartbeat_history,
        queue_analysis=queue_analysis,
        capabilities=capabilities,
        active_goal=active_goal,
        recent_actions=recent_actions,
        goal_evidence=goal_evidence,
        goal_continuation_state=goal_continuation_state,
    )
    return {
        "kind": "master_agent_wake_context_v2",
        "note": (
            "Prompt-cache-aware wake context: cached_static_context is stable and "
            "appears before volatile_wake_state."
        ),
        "cached_static_context": cached_static_context,
        "volatile_wake_state": volatile_wake_state,
        "cached_static_context_sha256": cached_static_context["cache_design"]["hash"],
        "prompt_cache": {
            "strategy": "stable_prefix_first",
            "provider": "openai_codex_gateway",
            "cache_key": os.getenv("MASTER_AGENT_PROMPT_CACHE_KEY", "possible-os-master-agent-v1"),
            "cache_retention": os.getenv("MASTER_AGENT_PROMPT_CACHE_RETENTION", "24h"),
        },
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


def _cached_tokens_from_usage(usage: dict[str, Any] | None) -> int | None:
    if not isinstance(usage, dict):
        return None
    candidates: list[Any] = [
        usage.get("cacheRead"),
        usage.get("cache_read"),
        usage.get("cached_tokens"),
    ]
    for key in ("prompt_tokens_details", "input_tokens_details"):
        details = usage.get(key)
        if isinstance(details, dict):
            candidates.append(details.get("cached_tokens"))
    for value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


async def _compose_human_status_with_llm(
    *,
    wake_context: dict[str, Any],
    fallback_status: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cached_context = wake_context.get("cached_static_context") if isinstance(wake_context.get("cached_static_context"), dict) else {}
    payload = {
        "stable_context": {
            "cached_static_context": cached_context,
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
        prompt_cache_key=(
            os.getenv("MASTER_AGENT_PROMPT_CACHE_KEY", "possible-os-master-agent-v1")
            if os.getenv("MASTER_AGENT_PROMPT_CACHE_PASSTHROUGH", "").strip().lower() in {"1", "true", "yes", "on"}
            else None
        ),
        prompt_cache_retention=(
            os.getenv("MASTER_AGENT_PROMPT_CACHE_RETENTION", "24h")
            if os.getenv("MASTER_AGENT_PROMPT_CACHE_PASSTHROUGH", "").strip().lower() in {"1", "true", "yes", "on"}
            else None
        ),
    )
    cached_tokens = _cached_tokens_from_usage(result.usage)
    status = _validate_llm_human_status(result.parsed, fallback_status)
    metadata = {
        "used_llm": True,
        "model": result.model,
        "skill_path": str(MASTER_STATUS_SKILL_PATH),
        "raw_response": result.raw_response[:4000],
        "usage": result.usage or {},
        "cached_tokens": cached_tokens,
        "prompt_cache": {
            "strategy": "stable_prefix_first",
            "cache_key": os.getenv("MASTER_AGENT_PROMPT_CACHE_KEY", "possible-os-master-agent-v1"),
            "passthrough_enabled": os.getenv("MASTER_AGENT_PROMPT_CACHE_PASSTHROUGH", "").strip().lower() in {"1", "true", "yes", "on"},
        },
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
    active_definition_keys = {
        (str(definition["name"]), str(definition["source"]))
        for definition in CAPABILITY_DEFINITIONS
    }
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
        existing_rows = (await session.execute(select(AgentCapabilityRow))).scalars().all()
        for row in existing_rows:
            if (row.name, row.source) in active_definition_keys:
                continue
            row.last_status = "deprecated"
            row.autonomous_allowed = False
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            row.metadata_json = {
                **metadata,
                "deprecated_at": now.isoformat(),
                "reason": "Capability definition is no longer present in CAPABILITY_DEFINITIONS.",
            }
            row.updated_at = now
            session.add(row)
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
            .where(AgentCapabilityRow.last_status != "deprecated")
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
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        active_rows = (await session.execute(
            select(MasterGoalRow).where(MasterGoalRow.status == "active").order_by(MasterGoalRow.created_at.desc())
        )).scalars().all()
        for existing in active_rows:
            source = existing.source_json or {}
            if source.get("manual") and (existing.expires_at is None or existing.expires_at > now):
                return goal_to_dict(existing)
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


async def set_master_goal(
    *,
    goal: str,
    why: str = "",
    next_actions: list[Any] | None = None,
    success_metric: str = "",
    time_horizon: str = "manual operating slice",
    confidence: str = "high",
    created_by: str = "operator",
    expires_hours: int = 24,
) -> dict[str, Any]:
    """Set a manual active goal that heartbeat respects until it expires or is superseded."""
    await ensure_agent_tables()
    cleaned_goal = goal.strip()
    if not cleaned_goal:
        raise ValueError("goal_required")
    now = _utcnow()
    row = MasterGoalRow(
        id=_new_id("goal"),
        status="active",
        goal=cleaned_goal,
        why=why.strip(),
        time_horizon=time_horizon.strip() or "manual operating slice",
        success_metric=success_metric.strip(),
        next_actions_json=_json_list(next_actions),
        source_json={
            "manual": True,
            "actor": created_by,
            "set_at": now.isoformat(),
        },
        confidence=confidence.strip() or "high",
        created_by=created_by[:128] if created_by else "operator",
        expires_at=now + timedelta(hours=max(1, min(int(expires_hours), 168))),
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
            event_type="master_goal_set",
            message=cleaned_goal,
            input_json={"actor": created_by, "manual": True},
            output_json={
                "goal_id": row.id,
                "goal": cleaned_goal,
                "next_actions": row.next_actions_json,
            },
            metadata_json={"confidence": row.confidence, "expires_hours": expires_hours},
        ))
        await session.commit()
        await session.refresh(row)
        result = goal_to_dict(row)
    await safe_record_product_trace(
        actor_type="user" if created_by == "operator" else "agent",
        actor_id=created_by,
        event_type="master_goal_set",
        surface="agents",
        entity_type="master_goal",
        entity_id=result["id"],
        input_json={"manual": True},
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
    tool_runner_enabled: bool | None = None,
    tool_runner_max_iterations: int | None = None,
    tool_runner_max_runtime_seconds: int | None = None,
    tool_runner_persist_continuation: bool | None = None,
    auto_execute_approved_lead_gen_email_enabled: bool | None = None,
    auto_execute_approved_lead_gen_email_limit: int | None = None,
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
        if tool_runner_enabled is not None:
            current["tool_runner_enabled"] = bool(tool_runner_enabled)
        if tool_runner_max_iterations is not None:
            current["tool_runner_max_iterations"] = max(
                1,
                min(int(tool_runner_max_iterations), 5),
            )
        if tool_runner_max_runtime_seconds is not None:
            current["tool_runner_max_runtime_seconds"] = max(
                15,
                min(int(tool_runner_max_runtime_seconds), 180),
            )
        if tool_runner_persist_continuation is not None:
            current["tool_runner_persist_continuation"] = bool(tool_runner_persist_continuation)
        if auto_execute_approved_lead_gen_email_enabled is not None:
            current["auto_execute_approved_lead_gen_email_enabled"] = bool(
                auto_execute_approved_lead_gen_email_enabled
            )
        if auto_execute_approved_lead_gen_email_limit is not None:
            current["auto_execute_approved_lead_gen_email_limit"] = max(
                1,
                min(int(auto_execute_approved_lead_gen_email_limit), 25),
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
                "systemctl status possibleos-backend.service",
                "systemctl status possibleos-frontend.service",
                "journalctl -u possibleos-backend.service",
                "journalctl -u possibleos-frontend.service",
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


async def get_agent_event(event_id: int) -> dict[str, Any] | None:
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentTaskEventRow, event_id)
        return event_to_dict(row) if row else None


async def list_agent_events(
    *,
    task_id: str | None = None,
    limit: int = 100,
    include_payload: bool = False,
) -> list[dict[str, Any]]:
    await ensure_agent_tables()
    limit = max(1, min(limit, 500))
    async with AsyncSessionLocal() as session:
        stmt = select(AgentTaskEventRow).order_by(AgentTaskEventRow.created_at.desc()).limit(limit)
        if task_id:
            stmt = stmt.where(AgentTaskEventRow.task_id == task_id)
        rows = (await session.execute(stmt)).scalars().all()
        serializer = event_to_dict if include_payload else event_summary_to_dict
        return [serializer(row) for row in rows]


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
        ["systemctl", "is-active", "possibleos-backend.service"],
        ["systemctl", "is-active", "possibleos-frontend.service"],
        ["systemctl", "status", "possibleos-backend.service", "--no-pager", "--lines=20"],
        ["systemctl", "status", "possibleos-frontend.service", "--no-pager", "--lines=20"],
        ["journalctl", "-u", "possibleos-backend.service", "--no-pager", "-n", "60"],
        ["journalctl", "-u", "possibleos-frontend.service", "--no-pager", "-n", "60"],
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


async def create_goal_continuation_report(
    *,
    goal_id: str,
    goal: str,
    status: str = "in_progress",
    summary: str = "",
    files_read: list[str] | None = None,
    facts_learned: list[Any] | None = None,
    remaining_questions: list[Any] | None = None,
    next_suggested_tool_call: dict[str, Any] | None = None,
    document_target: str = "docs/agent-kb/system-model/master-agent.md",
    tool_loop: dict[str, Any] | None = None,
    actor: str = GOAL_CONTINUATION_AGENT_ID,
) -> dict[str, Any]:
    """Persist a compact handoff note for future heartbeats.

    This intentionally reuses AgentReportRow so the slice avoids a new table
    until the continuation model proves it needs first-class indexing.
    """
    state = {
        "kind": "goal_continuation_state",
        "goal_id": goal_id,
        "goal": goal,
        "status": status,
        "summary": summary,
        "files_read": sorted({
            path for path in (_valid_continuation_file_path(item) for item in (files_read or []))
            if path
        }),
        "facts_learned": _json_list(facts_learned),
        "remaining_questions": _json_list(remaining_questions),
        "next_suggested_tool_call": _json_object(next_suggested_tool_call),
        "document_target": document_target,
        "tool_loop_summary": {
            "status": (tool_loop or {}).get("status"),
            "tool_calls_used": (tool_loop or {}).get("tool_calls_used"),
            "tool_calls_limit": (tool_loop or {}).get("tool_calls_limit"),
        },
        "updated_at": _utcnow().isoformat(),
    }
    report = await create_agent_report(
        task_id=None,
        agent_id=actor,
        status=GOAL_CONTINUATION_STATUS,
        summary=summary or f"Continuation state for goal {goal_id}",
        key_findings=state["facts_learned"],
        actions_taken=[{
            "type": "goal_continuation_saved",
            "files_read": state["files_read"],
            "tool_loop_status": state["tool_loop_summary"].get("status"),
        }],
        artifacts=[{
            "type": "document_target",
            "path": document_target,
        }],
        evidence=[state],
        verification=[
            "Continuation state was saved without modifying project files.",
            "Full tool-loop evidence remains in heartbeat output and product traces.",
        ],
        risks=[],
        open_questions=state["remaining_questions"],
        recommended_next_actions=[
            state["next_suggested_tool_call"]
            if state["next_suggested_tool_call"]
            else "Continue from this compact continuation state on the next heartbeat."
        ],
    )
    await safe_record_product_trace(
        actor_type="agent",
        actor_id=actor,
        event_type="goal_continuation_saved",
        surface="agents",
        entity_type="master_goal",
        entity_id=goal_id,
        output_json={
            "report_id": report.get("id"),
            "summary": state["summary"],
            "files_read": state["files_read"],
            "status": state["status"],
        },
    )
    return {"report": report, "continuation_state": state}


async def get_latest_goal_continuation_state(goal_id: str | None) -> dict[str, Any]:
    if not goal_id:
        return {}
    await ensure_agent_tables()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentReportRow)
            .where(AgentReportRow.agent_id == GOAL_CONTINUATION_AGENT_ID)
            .where(AgentReportRow.status == GOAL_CONTINUATION_STATUS)
            .order_by(AgentReportRow.created_at.desc())
            .limit(25)
        )).scalars().all()
    latest: dict[str, Any] = {}
    files_read: list[str] = []
    facts_learned: list[Any] = []
    remaining_questions: list[Any] = []
    seen_files: set[str] = set()
    seen_facts: set[str] = set()
    seen_questions: set[str] = set()
    for row in rows:
        report = report_to_dict(row)
        state = continuation_state_from_report(report)
        if state.get("goal_id") != goal_id:
            continue
        if not latest:
            latest = {
                "report_id": report.get("id"),
                "created_at": report.get("created_at"),
                **state,
            }
        for path in state.get("files_read") or []:
            text = _valid_continuation_file_path(path)
            if text and text not in seen_files:
                seen_files.add(text)
                files_read.append(text)
        for fact in state.get("facts_learned") or []:
            key = json.dumps(fact, sort_keys=True, default=str)
            if key not in seen_facts:
                seen_facts.add(key)
                facts_learned.append(fact)
        for question in state.get("remaining_questions") or []:
            key = json.dumps(question, sort_keys=True, default=str)
            if key not in seen_questions:
                seen_questions.add(key)
                remaining_questions.append(question)
    if latest:
        latest["files_read"] = sorted(files_read)
        latest["facts_learned"] = facts_learned
        latest["remaining_questions"] = remaining_questions
        latest["merged_report_count"] = len([
            row for row in rows
            if continuation_state_from_report(report_to_dict(row)).get("goal_id") == goal_id
        ])
        return latest
    return {}


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
    recent_action_snapshots: list[dict[str, Any]] = []
    heartbeat_history: dict[str, Any] = {}
    queue_analysis: dict[str, Any] = {}
    capabilities: list[dict[str, Any]] = []
    active_goal: dict[str, Any] | None = None
    human_status: dict[str, Any] = {}
    wake_context: dict[str, Any] = {}
    status_metadata: dict[str, Any] = {"used_llm": False}
    tool_loop: dict[str, Any] = {}
    tool_runner_metadata: dict[str, Any] = {"enabled": bool(agent_config.get("tool_runner_enabled"))}
    auto_executed_lead_gen_sends: dict[str, Any] = {}
    if agent_config.get("auto_execute_approved_lead_gen_email_enabled", False):
        from app.services.action_execution import execute_approved_lead_gen_email_actions

        auto_executed_lead_gen_sends = await execute_approved_lead_gen_email_actions(
            actor=actor,
            limit=int(agent_config.get("auto_execute_approved_lead_gen_email_limit") or 1),
        )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentTaskRow).where(AgentTaskRow.status.in_(list(ACTIVE_TASK_STATUSES)))
        )).scalars().all()
        active_count = len(rows)
        blocked_count = sum(1 for row in rows if row.status == "blocked")
        queued_count = sum(1 for row in rows if row.status == "queued")
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
        active_task_snapshots = [_short_task_snapshot(row) for row in rows[:20]]
        recent_report_rows = (await session.execute(
            select(AgentReportRow).order_by(AgentReportRow.created_at.desc()).limit(5)
        )).scalars().all()
        recent_event_rows = (await session.execute(
            select(AgentTaskEventRow).order_by(AgentTaskEventRow.created_at.desc()).limit(30)
        )).scalars().all()
        recent_report_snapshots = [report_to_dict(row) for row in recent_report_rows]
        recent_action_snapshots = await _recent_action_snapshots(session, limit=8)
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
        goal_continuation_state = await get_latest_goal_continuation_state(
            str((active_goal or {}).get("id") or "")
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
            recent_actions=recent_action_snapshots,
            goal_continuation_state=goal_continuation_state,
        )
        volatile_wake_state = wake_context.setdefault("volatile_wake_state", {})
        if isinstance(volatile_wake_state, dict):
            volatile_wake_state["auto_delegated_task"] = auto_delegated_task or {}
            volatile_wake_state["auto_executed_lead_gen_sends"] = auto_executed_lead_gen_sends or {}
        if agent_config.get("tool_runner_enabled", False) and active_goal:
            try:
                from app.services.master_agent_runner import (
                    openclaw_runner_decision_provider,
                    run_master_agent_tool_loop,
                )

                tool_loop = await run_master_agent_tool_loop(
                    wake_context=wake_context,
                    active_goal=active_goal,
                    max_iterations=int(agent_config.get("tool_runner_max_iterations") or 3),
                    max_runtime_seconds=int(agent_config.get("tool_runner_max_runtime_seconds") or 90),
                    actor=actor,
                    decision_provider=openclaw_runner_decision_provider,
                    persist_continuation=bool(agent_config.get("tool_runner_persist_continuation", True)),
                )
                tool_runner_metadata = {
                    "enabled": True,
                    "status": tool_loop.get("status"),
                    "tool_calls_used": tool_loop.get("tool_calls_used"),
                    "continuation_report_id": tool_loop.get("continuation_report_id"),
                }
            except Exception as exc:
                logger.exception("master-agent tool runner failed")
                tool_loop = {
                    "status": "failed",
                    "error": str(exc),
                    "tool_calls_used": 0,
                    "steps": [],
                    "final_answer": {
                        "summary": "Tool runner failed before completing a bounded loop.",
                        "blockers": [str(exc)],
                    },
                }
                tool_runner_metadata = {"enabled": True, "status": "failed", "error": str(exc)}
            if isinstance(volatile_wake_state, dict):
                volatile_wake_state["tool_loop"] = tool_loop
        elif isinstance(volatile_wake_state, dict):
            volatile_wake_state["tool_loop"] = {
                "status": "disabled" if not agent_config.get("tool_runner_enabled", False) else "no_active_goal",
                "tool_calls_used": 0,
                "steps": [],
            }
        objective_status = (
            volatile_wake_state.get("objective_status")
            if isinstance(volatile_wake_state.get("objective_status"), dict)
            else {}
        )
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
        if isinstance(volatile_wake_state, dict):
            volatile_wake_state["llm_call"] = {
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
                "objective_status": objective_status,
                "tool_loop": tool_loop,
                "auto_delegated_task": auto_delegated_task or {},
                "auto_executed_lead_gen_sends": auto_executed_lead_gen_sends or {},
                "active_goal": active_goal or {},
            },
            metadata_json={
                "trace_id": trace.get("trace_id") if trace else None,
                "status_llm": status_metadata,
                "tool_runner": tool_runner_metadata,
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
        "objective_status": objective_status,
        "tool_loop": tool_loop,
        "wake_context": wake_context,
        "status_llm": status_metadata,
        "tool_runner": tool_runner_metadata,
        "auto_delegated_task": auto_delegated_task,
        "auto_executed_lead_gen_sends": auto_executed_lead_gen_sends,
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
