"""Run-wide Lead Finder LLM provider selection and direct OpenAI reasoning."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI

from app.services.llm_gateway import require_fields


OPENAI_MODEL = os.getenv("LEAD_FINDER_OPENAI_MODEL", "gpt-5.6-luna")
OPENCLAW_MODEL = os.getenv("LEAD_FINDER_MODEL", "openclaw/main")
PROVIDERS = {"openai", "openclaw"}
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
                "type": {"type": "string", "enum": ["reason", "tool_call"]},
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

AttemptObserver = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class DirectReasoningResult:
    parsed: dict[str, Any]
    raw_response: str
    raw_provider_response: str
    model: str
    usage: dict[str, Any]
    response_id: str


def normalize_lead_finder_provider(value: str | None) -> str:
    provider = str(value or "openai").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("lead_finder_provider_must_be_openai_or_openclaw")
    return provider


def lead_finder_provider_model(provider: str) -> str:
    return (
        OPENAI_MODEL
        if normalize_lead_finder_provider(provider) == "openai"
        else OPENCLAW_MODEL
    )


def lead_finder_provider_status(provider: str) -> dict[str, Any]:
    selected = normalize_lead_finder_provider(provider)
    return {
        "provider": selected,
        "model": lead_finder_provider_model(selected),
        "configured": selected != "openai" or bool(
            os.getenv("LEAD_FINDER_OPENAI_API_KEY", "").strip()
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
