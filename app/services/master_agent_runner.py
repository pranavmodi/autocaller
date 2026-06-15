"""Bounded heartbeat tool runner for master-agent multi-step work."""
from __future__ import annotations

import inspect
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.services.action_read import run_action_read
from app.services.filesystem_read import run_filesystem_read
from app.services.llm_gateway import LLMGatewayError, call_skill_json
from app.services.master_agent import create_goal_continuation_report
from app.services.product_traces import current_trace_id, new_trace_id, safe_record_product_trace
from app.services.sandbox_write import run_sandbox_write


DecisionProvider = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
ToolExecutor = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]

DEFAULT_ALLOWED_TOOLS = ["filesystem_read", "action_read", "sandbox_write"]
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_MAX_RUNTIME_SECONDS = 90
DEFAULT_MAX_RESULT_BYTES = 50_000
DEFAULT_DOCUMENT_TARGET = "docs/agent-kb/system-model/master-agent.md"
RUNNER_SKILL_PATH = Path(os.getenv(
    "MASTER_AGENT_RUNNER_SKILL_PATH",
    str(Path(__file__).resolve().parents[2] / "app/skills/master-agent-runner/SKILL.md"),
))
RUNNER_MODEL = os.getenv("MASTER_AGENT_RUNNER_MODEL", "openclaw")
ALLOWED_DECISIONS = {"tool_call", "finish", "blocked"}
FILESYSTEM_OPERATION_KEYS = {
    "operation",
    "path",
    "pattern",
    "query",
    "glob",
    "limit",
    "start",
    "end",
    "start_line",
    "end_line",
    "max_bytes",
    "ref",
}
ACTION_READ_OPERATION_KEYS = {
    "operation",
    "action_id",
    "status",
    "action_type",
    "limit",
}
SANDBOX_WRITE_OPERATION_KEYS = {
    "operation",
    "path",
    "content",
    "recursive",
    "limit",
    "max_bytes",
}


class MasterAgentRunnerError(ValueError):
    """Raised when a runner decision violates the bounded tool contract."""


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _compact_text(value: Any, *, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _decision_provider_missing(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": "blocked",
        "reason": "No runner decision provider is configured yet.",
        "remaining_questions": [
            "Wire the OpenClaw gateway decision provider or pass a deterministic provider for tests.",
        ],
    }


async def _default_tool_executor(payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    tool = str(payload.get("tool") or "").strip()
    request = payload.get("request") if isinstance(payload.get("request"), dict) else payload
    if tool == "action_read":
        return await run_action_read(request, actor=actor)
    if tool == "sandbox_write":
        return await run_sandbox_write(request, actor=actor)
    return await run_filesystem_read(request, actor=actor)


def _validate_decision(decision: dict[str, Any], allowed_tools: list[str]) -> None:
    if not isinstance(decision, dict):
        raise MasterAgentRunnerError("decision_must_be_object")
    kind = str(decision.get("decision") or "").strip()
    if kind not in ALLOWED_DECISIONS:
        raise MasterAgentRunnerError("unsupported_decision")
    if kind == "tool_call":
        tool = str(decision.get("tool") or "").strip()
        if tool not in allowed_tools:
            raise MasterAgentRunnerError("tool_not_allowed")
        if not str(decision.get("operation") or "").strip():
            raise MasterAgentRunnerError("tool_operation_required")


def _filesystem_payload(decision: dict[str, Any], *, max_result_bytes: int) -> dict[str, Any]:
    payload = {
        key: decision[key]
        for key in FILESYSTEM_OPERATION_KEYS
        if key in decision and decision[key] is not None
    }
    payload["operation"] = str(payload.get("operation") or "").strip()
    payload["max_bytes"] = min(
        int(payload.get("max_bytes") or max_result_bytes),
        max_result_bytes,
    )
    return payload


def _action_read_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: decision[key]
        for key in ACTION_READ_OPERATION_KEYS
        if key in decision and decision[key] is not None
    }
    payload["operation"] = str(payload.get("operation") or "").strip()
    return payload


def _sandbox_write_payload(decision: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: decision[key]
        for key in SANDBOX_WRITE_OPERATION_KEYS
        if key in decision and decision[key] is not None
    }
    payload["operation"] = str(payload.get("operation") or "").strip()
    return payload


def _tool_payload(decision: dict[str, Any], *, max_result_bytes: int) -> dict[str, Any]:
    tool = str(decision.get("tool") or "").strip()
    if tool == "action_read":
        return _action_read_payload(decision)
    if tool == "sandbox_write":
        return _sandbox_write_payload(decision)
    return _filesystem_payload(decision, max_result_bytes=max_result_bytes)


def _step_summary(step: dict[str, Any]) -> dict[str, Any]:
    result = step.get("result") if isinstance(step.get("result"), dict) else {}
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    return {
        "step": step.get("step"),
        "decision": step.get("decision"),
        "tool": step.get("tool"),
        "operation": step.get("operation"),
        "iteration_trace_id": step.get("iteration_trace_id"),
        "iteration_trace_row_id": step.get("iteration_trace_row_id"),
        "allowed": result.get("allowed", step.get("allowed")),
        "result_summary": inner.get("summary") if isinstance(inner, dict) else "",
        "files_touched": inner.get("files_touched") if isinstance(inner, dict) else [],
        "truncated": bool(inner.get("truncated")) if isinstance(inner, dict) else False,
        "error": inner.get("error") if isinstance(inner, dict) else "",
    }


def _compact_tool_observation(step: dict[str, Any], *, limit: int = 8_000) -> dict[str, Any]:
    result = step.get("result") if isinstance(step.get("result"), dict) else {}
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    observation: dict[str, Any] = _step_summary(step)
    if not isinstance(inner, dict):
        return observation
    for key in (
        "path",
        "root",
        "query",
        "count",
        "returncode",
        "total_lines",
        "start_line",
        "end_line",
        "action_id",
        "status",
        "action_type",
        "sandbox_root",
        "before_bytes",
        "after_bytes",
        "bytes_written",
        "deleted_kind",
    ):
        if key in inner:
            observation[key] = inner[key]
    if isinstance(inner.get("action"), dict):
        observation["action"] = inner["action"]
    if isinstance(inner.get("interpretation"), dict):
        observation["interpretation"] = inner["interpretation"]
    if isinstance(inner.get("events"), list):
        observation["events"] = inner["events"][:20]
    if isinstance(inner.get("actions"), list):
        observation["actions"] = inner["actions"][:25]
    if isinstance(inner.get("matches"), list):
        observation["matches"] = inner["matches"][:20]
    if isinstance(inner.get("files"), list):
        observation["files"] = inner["files"][:100]
    if isinstance(inner.get("items"), list):
        observation["items"] = inner["items"][:100]
    if isinstance(inner.get("content"), str):
        observation["content"] = inner["content"][:limit]
        observation["content_truncated_for_runner"] = len(inner["content"]) > limit
    if isinstance(inner.get("output"), str):
        observation["output"] = inner["output"][:limit]
        observation["output_truncated_for_runner"] = len(inner["output"]) > limit
    return observation


def compact_previous_heartbeat_summary(tool_loop: dict[str, Any]) -> dict[str, Any]:
    steps = tool_loop.get("steps") if isinstance(tool_loop, dict) else []
    final_answer = tool_loop.get("final_answer") if isinstance(tool_loop, dict) else {}
    files: set[str] = set()
    for step in steps if isinstance(steps, list) else []:
        for path in step.get("files_touched") or []:
            files.add(str(path))
    return {
        "status": tool_loop.get("status"),
        "summary": _compact_text((final_answer or {}).get("summary") or tool_loop.get("status") or ""),
        "tool_calls_used": tool_loop.get("tool_calls_used", 0),
        "files_inspected": sorted(files),
        "learned": (final_answer or {}).get("facts_learned") or [],
        "next_continuation": (final_answer or {}).get("next_actions") or [],
        "blockers": (final_answer or {}).get("blockers") or [],
        "user_help_needed": (final_answer or {}).get("user_help_needed") or [],
    }


def _prior_goal_continuation(wake_context: dict[str, Any]) -> dict[str, Any]:
    volatile = wake_context.get("volatile_wake_state") if isinstance(wake_context, dict) else {}
    if not isinstance(volatile, dict):
        return {}
    state = volatile.get("goal_continuation_state")
    return state if isinstance(state, dict) else {}


def _merge_unique_strings(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        items = value if isinstance(value, list) else []
        for item in items:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def _valid_file_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.isdigit():
        return ""
    if "\x00" in text or text.startswith("/") or ".." in text.split("/"):
        return ""
    return text


def _merge_file_paths(*values: Any) -> list[str]:
    return _merge_unique_strings(*[
        [_valid_file_path(item) for item in (value if isinstance(value, list) else [])]
        for value in values
    ])


async def openclaw_runner_decision_provider(payload: dict[str, Any]) -> dict[str, Any]:
    result = await call_skill_json(
        skill_path=RUNNER_SKILL_PATH,
        payload=payload,
        required_fields=["decision"],
        model=RUNNER_MODEL,
        max_tokens=int(os.getenv("MASTER_AGENT_RUNNER_MAX_TOKENS", "2000")),
        prompt_cache_key=os.getenv("MASTER_AGENT_RUNNER_PROMPT_CACHE_KEY", "possible-os-master-agent-runner-v1"),
        prompt_cache_retention=os.getenv("MASTER_AGENT_PROMPT_CACHE_RETENTION", "24h"),
    )
    decision = result.parsed
    decision["_llm_metadata"] = {
        "used_llm": True,
        "model": result.model,
        "skill_path": str(RUNNER_SKILL_PATH),
        "usage": result.usage or {},
    }
    return decision


async def run_master_agent_tool_loop(
    *,
    wake_context: dict[str, Any],
    active_goal: dict[str, Any] | None,
    allowed_tools: list[str] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS,
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES,
    actor: str = "master-agent",
    decision_provider: DecisionProvider | None = None,
    tool_executor: ToolExecutor | None = None,
    persist_continuation: bool = True,
) -> dict[str, Any]:
    """Run a short observe-orient-act loop over approved read-only tools.

    The heartbeat owns scheduling. This runner owns the bounded work cycle. It
    never exposes shell. V1 tools are read-only filesystem inspection, durable
    action outcome inspection, and bounded sandbox file mutation.
    """
    allowed = allowed_tools or list(DEFAULT_ALLOWED_TOOLS)
    provider = decision_provider or _decision_provider_missing
    executor = tool_executor
    started = time.monotonic()
    steps: list[dict[str, Any]] = []
    iteration_debug_traces: list[dict[str, Any]] = []
    status = "completed"
    final_answer: dict[str, Any] = {}
    calls_used = 0

    for idx in range(1, max(1, min(max_iterations, DEFAULT_MAX_ITERATIONS)) + 1):
        if time.monotonic() - started > max_runtime_seconds:
            status = "budget_exhausted"
            final_answer = {
                "summary": "Tool runner stopped because runtime budget was exhausted.",
                "remaining_questions": ["Continue from the last completed tool step."],
            }
            break

        decision_payload = {
            "wake_context": wake_context,
            "active_goal": active_goal or {},
            "steps": [_step_summary(step) for step in steps],
            "observations": [_compact_tool_observation(step) for step in steps],
            "limits": {
                "max_iterations": max_iterations,
                "max_runtime_seconds": max_runtime_seconds,
                "max_result_bytes": max_result_bytes,
                "allowed_tools": allowed,
            },
        }
        try:
            decision = await _maybe_await(provider(decision_payload))
        except LLMGatewayError as exc:
            decision = {
                "decision": "blocked",
                "reason": f"Runner decision provider failed: {exc}",
                "remaining_questions": [
                    "Check the OpenClaw gateway and runner skill before retrying the tool loop.",
                ],
            }
        iteration_trace: dict[str, Any] | None = None
        try:
            _validate_decision(decision, allowed)
        except Exception as exc:
            iteration_trace = await safe_record_product_trace(
                trace_id=new_trace_id(),
                parent_trace_id=current_trace_id(),
                actor_type="agent",
                actor_id=actor,
                event_type="master_agent_runner_iteration",
                surface="agents",
                entity_type="master_agent_tool_loop",
                entity_id=(active_goal or {}).get("id") or "no-goal",
                input_json=decision_payload,
                output_json={
                    "step": idx,
                    "decision": decision,
                    "validation_error": str(exc),
                },
                metadata_json={
                    "step": idx,
                    "status": "invalid_decision",
                    "model": ((decision or {}).get("_llm_metadata") or {}).get("model"),
                    "usage": ((decision or {}).get("_llm_metadata") or {}).get("usage") or {},
                },
            )
            if iteration_trace:
                iteration_debug_traces.append({
                    "step": idx,
                    "trace_id": iteration_trace.get("trace_id"),
                    "trace_row_id": iteration_trace.get("id"),
                    "decision": decision.get("decision"),
                    "status": "invalid_decision",
                })
            raise
        kind = str(decision.get("decision"))

        if kind == "finish":
            iteration_trace = await safe_record_product_trace(
                trace_id=new_trace_id(),
                parent_trace_id=current_trace_id(),
                actor_type="agent",
                actor_id=actor,
                event_type="master_agent_runner_iteration",
                surface="agents",
                entity_type="master_agent_tool_loop",
                entity_id=(active_goal or {}).get("id") or "no-goal",
                input_json=decision_payload,
                output_json={"step": idx, "decision": decision},
                metadata_json={
                    "step": idx,
                    "status": "finish",
                    "model": ((decision or {}).get("_llm_metadata") or {}).get("model"),
                    "usage": ((decision or {}).get("_llm_metadata") or {}).get("usage") or {},
                },
            )
            if iteration_trace:
                iteration_debug_traces.append({
                    "step": idx,
                    "trace_id": iteration_trace.get("trace_id"),
                    "trace_row_id": iteration_trace.get("id"),
                    "decision": "finish",
                    "status": "finish",
                })
            final_answer = {
                "summary": str(decision.get("summary") or "Runner finished."),
                "facts_learned": decision.get("facts_learned") or decision.get("learned") or [],
                "remaining_questions": decision.get("remaining_questions") or [],
                "next_actions": decision.get("next_actions") or decision.get("next_continuation") or [],
                "recommended_document_updates": decision.get("recommended_document_updates") or [],
                "blockers": [],
                "user_help_needed": decision.get("user_help_needed") or [],
            }
            status = "completed"
            break

        if kind == "blocked":
            iteration_trace = await safe_record_product_trace(
                trace_id=new_trace_id(),
                parent_trace_id=current_trace_id(),
                actor_type="agent",
                actor_id=actor,
                event_type="master_agent_runner_iteration",
                surface="agents",
                entity_type="master_agent_tool_loop",
                entity_id=(active_goal or {}).get("id") or "no-goal",
                input_json=decision_payload,
                output_json={"step": idx, "decision": decision},
                metadata_json={
                    "step": idx,
                    "status": "blocked",
                    "model": ((decision or {}).get("_llm_metadata") or {}).get("model"),
                    "usage": ((decision or {}).get("_llm_metadata") or {}).get("usage") or {},
                },
            )
            if iteration_trace:
                iteration_debug_traces.append({
                    "step": idx,
                    "trace_id": iteration_trace.get("trace_id"),
                    "trace_row_id": iteration_trace.get("id"),
                    "decision": "blocked",
                    "status": "blocked",
                })
            final_answer = {
                "summary": str(decision.get("reason") or "Runner blocked."),
                "facts_learned": decision.get("facts_learned") or [],
                "remaining_questions": decision.get("remaining_questions") or [],
                "next_actions": decision.get("next_actions") or [],
                "blockers": [decision.get("reason") or "blocked"],
                "user_help_needed": decision.get("user_help_needed") or [],
            }
            status = "blocked"
            break

        tool = str(decision.get("tool") or "").strip()
        payload = _tool_payload(decision, max_result_bytes=max_result_bytes)
        tool_result = await _maybe_await(
            (
                executor(payload)
                if executor
                else _default_tool_executor({"tool": tool, "request": payload}, actor=actor)
            )
        )
        calls_used += 1
        inner = tool_result.get("result") if isinstance(tool_result, dict) else {}
        step = {
            "step": idx,
            "decision": "tool_call",
            "tool": tool,
            "operation": payload.get("operation"),
            "reason": decision.get("reason") or "",
            "request": payload,
            "allowed": bool((tool_result or {}).get("allowed")),
            "result": tool_result,
            "result_summary": inner.get("summary") if isinstance(inner, dict) else "",
            "files_touched": inner.get("files_touched") if isinstance(inner, dict) else [],
            "truncated": bool(inner.get("truncated")) if isinstance(inner, dict) else False,
        }
        iteration_trace = await safe_record_product_trace(
            trace_id=new_trace_id(),
            parent_trace_id=current_trace_id(),
            actor_type="agent",
            actor_id=actor,
            event_type="master_agent_runner_iteration",
            surface="agents",
            entity_type="master_agent_tool_loop",
            entity_id=(active_goal or {}).get("id") or "no-goal",
            input_json=decision_payload,
            output_json={
                "step": idx,
                "decision": decision,
                "request": payload,
                "tool_result": tool_result,
                "observation": _compact_tool_observation(step),
            },
            metadata_json={
                "step": idx,
                "status": "tool_call_completed",
                "tool": tool,
                "operation": payload.get("operation"),
                "model": ((decision or {}).get("_llm_metadata") or {}).get("model"),
                "usage": ((decision or {}).get("_llm_metadata") or {}).get("usage") or {},
            },
        )
        if iteration_trace:
            step["iteration_trace_id"] = iteration_trace.get("trace_id")
            step["iteration_trace_row_id"] = iteration_trace.get("id")
            iteration_debug_traces.append({
                "step": idx,
                "trace_id": iteration_trace.get("trace_id"),
                "trace_row_id": iteration_trace.get("id"),
                "decision": "tool_call",
                "tool": tool,
                "operation": payload.get("operation"),
                "status": "tool_call_completed",
            })
        steps.append(step)
        await safe_record_product_trace(
            actor_type="agent",
            actor_id=actor,
            event_type="master_agent_tool_call_completed",
            surface="agents",
            entity_type="master_agent_tool_loop",
            entity_id=(active_goal or {}).get("id") or "no-goal",
            input_json={"decision": decision, "request": payload},
            output_json=_step_summary(step),
        )
    else:
        status = "budget_exhausted"
        final_answer = {
            "summary": "Tool runner used all allowed iterations.",
            "facts_learned": [],
            "remaining_questions": ["Continue from the compact step summaries."],
            "next_actions": [],
            "blockers": [],
            "user_help_needed": [],
        }

    tool_loop = {
        "status": status,
        "tool_calls_used": calls_used,
        "tool_calls_limit": max_iterations,
        "runtime_seconds": round(time.monotonic() - started, 3),
        "steps": [_step_summary(step) for step in steps],
        "iteration_debug_traces": iteration_debug_traces,
        "final_answer": final_answer,
        "previous_heartbeat_summary": {},
    }
    tool_loop["previous_heartbeat_summary"] = compact_previous_heartbeat_summary(tool_loop)

    goal_id = str((active_goal or {}).get("id") or "")
    if persist_continuation and goal_id:
        prior_continuation = _prior_goal_continuation(wake_context)
        files_read = _merge_file_paths(
            prior_continuation.get("files_read"),
            tool_loop["previous_heartbeat_summary"].get("files_inspected"),
        )
        facts_learned = _merge_unique_strings(
            prior_continuation.get("facts_learned"),
            final_answer.get("facts_learned"),
        )
        remaining_questions = _merge_unique_strings(
            final_answer.get("remaining_questions"),
            prior_continuation.get("remaining_questions"),
        )
        continuation = await create_goal_continuation_report(
            goal_id=goal_id,
            goal=str((active_goal or {}).get("goal") or ""),
            status="blocked" if status == "blocked" else "in_progress",
            summary=str(final_answer.get("summary") or tool_loop["previous_heartbeat_summary"].get("summary") or ""),
            files_read=files_read,
            facts_learned=facts_learned,
            remaining_questions=remaining_questions,
            next_suggested_tool_call=(final_answer.get("next_actions") or [{}])[0]
            if isinstance((final_answer.get("next_actions") or [{}])[0], dict)
            else {},
            document_target=DEFAULT_DOCUMENT_TARGET,
            tool_loop=tool_loop,
            actor=actor,
        )
        tool_loop["goal_continuation_state"] = continuation.get("continuation_state") or {}
        tool_loop["continuation_report_id"] = (continuation.get("report") or {}).get("id")

    return tool_loop
