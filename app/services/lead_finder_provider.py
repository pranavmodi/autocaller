"""Run-wide Lead Finder LLM provider selection and direct OpenAI reasoning."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.services.codex_app_server import (
    CODEX_APP_SERVER_MODEL,
    run_codex_turn,
)
from app.services.llm_gateway import LLMGatewayError, require_fields


OPENAI_MODEL = os.getenv("LEAD_FINDER_OPENAI_MODEL", "gpt-5.6-luna")
OPENCLAW_MODEL = os.getenv("LEAD_FINDER_MODEL", "openclaw/main")
PROVIDERS = {"openai", "openclaw", "codex"}
RESPONSES_URL = "https://api.openai.com/v1/responses"
REQUIRED_REASONING_FIELDS = [
    "step_name",
    "summary",
    "reasoning",
    "state_updates",
    "action",
    "next_step",
    "is_complete",
]

# state_updates deliberately remains flexible because the debug reasoner grows
# evidence-specific state. The surrounding transition and action contract is
# still mechanically constrained by the Responses API JSON Schema formatter.
REASONING_SCHEMA = {
    "type": "object",
    "properties": {
        "step_name": {"type": "string"},
        "summary": {"type": "string"},
        "reasoning": {"type": "string"},
        "state_updates": {"type": "object", "additionalProperties": True},
        "action": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["reason", "pause", "tool_call"]},
                "tool": {"type": ["string", "null"]},
                "arguments": {"type": "object", "additionalProperties": True},
            },
            "required": ["type", "tool", "arguments"],
            "additionalProperties": False,
        },
        "next_step": {"type": "string"},
        "is_complete": {"type": "boolean"},
    },
    "required": REQUIRED_REASONING_FIELDS,
    "additionalProperties": False,
}

_CODEX_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "person_name": {"type": "string"},
        "organization": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]},
        "status": {"type": "string"},
        "confidence": {"type": ["string", "null"]},
        "primary_angle": {"type": ["string", "null"]},
        "research_tool_call_id": {"type": ["string", "null"]},
        "transcript_chunk_ids": {"type": "array", "items": {"type": "integer"}},
        "transcript_episode": {"type": ["string", "null"]},
        "evidence_notes": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "person_name",
        "organization",
        "role",
        "status",
        "confidence",
        "primary_angle",
        "research_tool_call_id",
        "transcript_chunk_ids",
        "transcript_episode",
        "evidence_notes",
        "caveats",
    ],
    "additionalProperties": False,
}

_CODEX_MISSION_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "integer"},
        "episode_title": {"type": "string"},
        "excerpt": {"type": ["string", "null"]},
    },
    "required": ["chunk_id", "episode_title", "excerpt"],
    "additionalProperties": False,
}

_CODEX_ACTION_ARGUMENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": ["string", "null"]},
        "mode": {
            "type": ["string", "null"],
            "enum": ["keyword", "semantic", "hybrid", None],
        },
        "limit": {"type": ["integer", "null"]},
        "show_ids": {"type": "array", "items": {"type": "integer"}},
        "published_after": {"type": ["string", "null"]},
        "published_before": {"type": ["string", "null"]},
        "chunk_ids": {"type": "array", "items": {"type": "integer"}},
        "person_name": {"type": ["string", "null"]},
        "organization": {"type": ["string", "null"]},
        "role": {"type": ["string", "null"]},
        "research_focus": {"type": ["string", "null"]},
        "mission_control_evidence": {
            "type": "array",
            "items": _CODEX_MISSION_EVIDENCE_SCHEMA,
        },
        "research_tool_call_id": {"type": ["string", "null"]},
        "selected_angle_indexes": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "notes": {"type": ["string", "null"]},
    },
    "required": [
        "query",
        "mode",
        "limit",
        "show_ids",
        "published_after",
        "published_before",
        "chunk_ids",
        "person_name",
        "organization",
        "role",
        "research_focus",
        "mission_control_evidence",
        "research_tool_call_id",
        "selected_angle_indexes",
        "notes",
    ],
    "additionalProperties": False,
}

# Codex app-server applies strict structured output. Keep every object closed
# and versioned so malformed JSON-inside-a-string cannot pass outer validation.
CODEX_REASONING_SCHEMA = {
    **REASONING_SCHEMA,
    "properties": {
        **REASONING_SCHEMA["properties"],
        "state_updates": {
            "type": "object",
            "properties": {
                "targeting_criteria": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "assumptions": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "evidence_needed": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "search_plan": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "candidate_queue": {
                    "type": ["array", "null"],
                    "items": _CODEX_CANDIDATE_SCHEMA,
                },
            },
            "required": [
                "targeting_criteria",
                "assumptions",
                "evidence_needed",
                "search_plan",
                "candidate_queue",
            ],
            "additionalProperties": False,
        },
        "action": {
            **REASONING_SCHEMA["properties"]["action"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["reason", "pause", "tool_call"],
                },
                "tool": {
                    "type": ["string", "null"],
                    "enum": [
                        None,
                        "mission_control.search",
                        "mission_control.get_passages",
                        "mission_control.index_status",
                        "web.research_person",
                        "lead_finder.add_researched_lead",
                    ],
                },
                "arguments": _CODEX_ACTION_ARGUMENTS_SCHEMA,
            },
        },
    },
}

_CODEX_TOOL_ARGUMENT_KEYS = {
    "mission_control.search": {
        "query", "mode", "limit", "show_ids", "published_after", "published_before",
    },
    "mission_control.get_passages": {"chunk_ids"},
    "mission_control.index_status": set(),
    "web.research_person": {
        "person_name", "organization", "role", "research_focus",
        "mission_control_evidence",
    },
    "lead_finder.add_researched_lead": {
        "research_tool_call_id", "selected_angle_indexes", "notes",
    },
}

AttemptObserver = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class DirectReasoningResult:
    parsed: dict[str, Any]
    raw_response: str
    raw_provider_response: str
    model: str
    usage: dict[str, Any]
    response_id: str
    thread_id: str | None = None


class CodexReasoningValidationError(RuntimeError):
    """A completed Codex turn whose structured payload is unusable."""

    def __init__(
        self,
        code: str,
        *,
        parsed_response: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        message = code if not detail else f"{code}:{detail}"
        super().__init__(message)
        self.code = code
        self.parsed_response = parsed_response or {}


def normalize_lead_finder_provider(value: str | None) -> str:
    provider = str(value or "openai").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("lead_finder_provider_must_be_openai_openclaw_or_codex")
    return provider


def lead_finder_provider_model(provider: str) -> str:
    selected = normalize_lead_finder_provider(provider)
    if selected == "openai":
        return OPENAI_MODEL
    if selected == "codex":
        return CODEX_APP_SERVER_MODEL
    return OPENCLAW_MODEL


def lead_finder_provider_status(provider: str) -> dict[str, Any]:
    selected = normalize_lead_finder_provider(provider)
    return {
        "provider": selected,
        "model": lead_finder_provider_model(selected),
        "configured": (
            bool(os.getenv("LEAD_FINDER_OPENAI_API_KEY", "").strip())
            if selected == "openai" else True
        ),
    }


async def _observe(
    observer: AttemptObserver | None,
    event: dict[str, Any],
) -> None:
    if observer:
        await observer(event)


async def call_openai_reasoning(
    *,
    skill_path: Path,
    payload: dict[str, Any],
    run_id: str | None,
    previous_response_id: str | None,
    prompt_cache_key: str | None,
    attempt_observer: AttemptObserver | None = None,
) -> DirectReasoningResult:
    """Run one structured Lead Finder reasoning transition via Responses API."""
    api_key = os.getenv("LEAD_FINDER_OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("direct_openai_api_key_not_configured")
    model = OPENAI_MODEL
    attempts = max(1, int(os.getenv("LEAD_FINDER_OPENAI_RETRIES", "1")))
    request: dict[str, Any] = {
        "model": model,
        "instructions": skill_path.read_text(encoding="utf-8"),
        "input": json.dumps(payload, indent=2, ensure_ascii=False),
        "max_output_tokens": int(os.getenv("LEAD_FINDER_MAX_TOKENS", "2000")),
        "store": True,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "lead_finder_reasoning_transition",
                "strict": False,
                "schema": REASONING_SCHEMA,
            }
        },
        "prompt_cache_retention": "24h",
    }
    if previous_response_id:
        request["previous_response_id"] = previous_response_id
    if prompt_cache_key:
        request["prompt_cache_key"] = prompt_cache_key
    if run_id:
        request["metadata"] = {"possibleos_run_id": run_id}

    timeout = int(os.getenv("LEAD_FINDER_OPENAI_TIMEOUT_S", "300"))
    last_error: Exception | None = None
    async with AsyncOpenAI(
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
    ) as client:
        for attempt in range(1, attempts + 1):
            await _observe(attempt_observer, {
                "phase": "started",
                "attempt": attempt,
                "model": model,
                "gateway_url": RESPONSES_URL,
                "request": request,
            })
            try:
                response = await client.responses.create(**request)
                if response.status != "completed" or not response.output_text:
                    detail = getattr(response, "incomplete_details", None)
                    raise RuntimeError(f"direct_openai_response_{response.status}:{detail}")
                try:
                    parsed = json.loads(response.output_text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("direct_openai_response_invalid_json") from exc
                if not isinstance(parsed, dict):
                    raise RuntimeError("direct_openai_response_not_an_object")
                require_fields(parsed, REQUIRED_REASONING_FIELDS)
                usage = response.usage.model_dump() if response.usage else {}
                raw_provider_response = response.model_dump_json()
                await _observe(attempt_observer, {
                    "phase": "completed",
                    "attempt": attempt,
                    "provider": "openai",
                    "model": response.model,
                    "response_id": response.id,
                    "http_status": 200,
                    "raw_response": raw_provider_response,
                    "parsed_response": parsed,
                    "usage": usage,
                })
                return DirectReasoningResult(
                    parsed=parsed,
                    raw_response=response.output_text,
                    raw_provider_response=raw_provider_response,
                    model=response.model,
                    usage=usage,
                    response_id=response.id,
                )
            except Exception as exc:
                last_error = exc
                await _observe(attempt_observer, {
                    "phase": "failed",
                    "attempt": attempt,
                    "model": model,
                    "status": "timed_out" if "timeout" in exc.__class__.__name__.lower() else "failed",
                    "error": str(exc) or exc.__class__.__name__,
                    "will_retry": attempt < attempts,
                })
                if attempt < attempts:
                    await asyncio.sleep(2 ** (attempt - 1))
    detail = str(last_error) if last_error else "unknown_error"
    raise RuntimeError(f"direct_openai_reasoning_failed:{detail}") from last_error


async def call_codex_reasoning(
    *,
    skill_path: Path,
    payload: dict[str, Any],
    run_id: str | None,
    thread_id: str | None,
    attempt_observer: AttemptObserver | None = None,
) -> DirectReasoningResult:
    """Run one structured transition through Possible OS's Codex app-server."""
    initial_prompt = (
        "Codex structured-output requirement: follow the supplied schema exactly. In "
        "state_updates, use null for a section that should remain unchanged. For each "
        "candidate, put transcript facts in evidence_notes and transcript_chunk_ids. "
        "In action.arguments, populate only the selected tool's fields meaningfully; "
        "use null or empty arrays for every unused required field.\n\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
    )

    def decode_response(text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CodexReasoningValidationError(
                "codex_app_server_response_invalid_json",
                detail=str(exc),
            ) from exc
        if not isinstance(parsed, dict):
            raise CodexReasoningValidationError(
                "codex_app_server_response_not_an_object"
            )

        encoded_updates = parsed.get("state_updates")
        if isinstance(encoded_updates, str):
            # Backward-compatible decoding for a turn produced under the prior
            # transport schema and then repaired after deployment.
            try:
                decoded_updates = json.loads(encoded_updates)
            except json.JSONDecodeError as exc:
                raise CodexReasoningValidationError(
                    "codex_app_server_state_updates_invalid_json",
                    parsed_response=parsed,
                    detail=str(exc),
                ) from exc
        elif isinstance(encoded_updates, dict):
            decoded_updates = encoded_updates
        else:
            raise CodexReasoningValidationError(
                "codex_app_server_state_updates_not_an_object",
                parsed_response=parsed,
            )
        if not isinstance(decoded_updates, dict):
            raise CodexReasoningValidationError(
                "codex_app_server_state_updates_not_an_object",
                parsed_response=parsed,
            )
        parsed["state_updates"] = {
            key: value for key, value in decoded_updates.items() if value is not None
        }

        action = parsed.get("action")
        if not isinstance(action, dict):
            raise CodexReasoningValidationError(
                "codex_app_server_action_not_an_object",
                parsed_response=parsed,
            )
        encoded_arguments = action.get("arguments")
        if isinstance(encoded_arguments, str):
            try:
                decoded_arguments = json.loads(encoded_arguments)
            except json.JSONDecodeError as exc:
                raise CodexReasoningValidationError(
                    "codex_app_server_action_arguments_invalid_json",
                    parsed_response=parsed,
                    detail=str(exc),
                ) from exc
        elif isinstance(encoded_arguments, dict):
            decoded_arguments = encoded_arguments
        else:
            raise CodexReasoningValidationError(
                "codex_app_server_action_arguments_not_an_object",
                parsed_response=parsed,
            )
        if not isinstance(decoded_arguments, dict):
            raise CodexReasoningValidationError(
                "codex_app_server_action_arguments_not_an_object",
                parsed_response=parsed,
            )
        allowed_keys = _CODEX_TOOL_ARGUMENT_KEYS.get(action.get("tool"), set())
        action["arguments"] = {
            key: value
            for key, value in decoded_arguments.items()
            if key in allowed_keys and value is not None
        }
        try:
            require_fields(parsed, REQUIRED_REASONING_FIELDS)
        except LLMGatewayError as exc:
            raise CodexReasoningValidationError(
                "codex_app_server_required_fields_invalid",
                parsed_response=parsed,
                detail=str(exc),
            ) from exc
        return parsed

    def provider_response(result: Any) -> str:
        return json.dumps({
            "thread_id": result.thread_id,
            "turn_id": result.turn_id,
            "text": result.text,
            "events": result.events,
            "latency": result.latency,
        }, ensure_ascii=False)

    async def offset_observer(offset: int, event: dict[str, Any]) -> None:
        if attempt_observer is None:
            return
        adjusted = dict(event)
        adjusted["attempt"] = offset + int(event.get("attempt") or 1)
        await attempt_observer(adjusted)

    repair_limit = max(
        0, int(os.getenv("LEAD_FINDER_CODEX_SCHEMA_REPAIR_RETRIES", "1"))
    )
    repairs_used = 0
    attempt_number = 1
    active_thread_id = thread_id
    prompt = initial_prompt
    while True:
        result = await run_codex_turn(
            agent_id="lead-finder",
            prompt=prompt,
            instructions=skill_path.read_text(encoding="utf-8"),
            thread_id=active_thread_id,
            model=CODEX_APP_SERVER_MODEL,
            effort=os.getenv("LEAD_FINDER_CODEX_EFFORT", "low"),
            output_schema=CODEX_REASONING_SCHEMA,
            web_search="disabled",
            timeout_s=int(os.getenv("LEAD_FINDER_CODEX_TIMEOUT_S", "300")),
            observer=(
                (lambda event, offset=attempt_number - 1: offset_observer(offset, event))
                if attempt_observer else None
            ),
        )
        try:
            parsed = decode_response(result.text)
        except CodexReasoningValidationError as exc:
            can_repair = repairs_used < repair_limit
            await _observe(attempt_observer, {
                "phase": "failed",
                "attempt": attempt_number,
                "provider": "codex",
                "model": result.model,
                "thread_id": result.thread_id,
                "http_status": 200,
                "raw_response": provider_response(result),
                "parsed_response": exc.parsed_response,
                "usage": {**result.usage, "latency": result.latency},
                "error": str(exc),
                "will_retry": can_repair,
            })
            if not can_repair:
                raise
            repairs_used += 1
            attempt_number += 1
            active_thread_id = result.thread_id
            prompt = (
                "Repair the immediately preceding assistant response only. Do not do new "
                "research or change the intended action. Return the complete response again "
                "under the same supplied structured-output schema. Use null for unchanged "
                "state sections and for unused scalar tool arguments; use empty arrays for "
                "unused array arguments.\n\n"
                f"Validation error: {exc}\n\n"
                "Invalid response:\n"
                f"{result.text[:20_000]}"
            )
            continue
        return DirectReasoningResult(
            parsed=parsed,
            raw_response=result.text,
            raw_provider_response=provider_response(result),
            model=result.model,
            usage={**result.usage, "latency": result.latency},
            response_id=result.turn_id,
            thread_id=result.thread_id,
        )
