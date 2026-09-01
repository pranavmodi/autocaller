"""Shared OpenClaw gateway client for narrow, auditable LLM calls."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx


logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_CONFIG_PATH = Path(os.getenv("OPENCLAW_CONFIG_PATH", "/root/.openclaw/openclaw.json"))

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)
_token_cache: Optional[str] = None
_skill_cache: dict[str, str] = {}

GatewayAttemptObserver = Callable[[dict[str, Any]], Awaitable[None]]


class LLMGatewayError(Exception):
    pass


class LLMGatewayResponseError(LLMGatewayError):
    """A gateway response that arrived but failed structured-output validation."""

    def __init__(
        self,
        message: str,
        *,
        raw_response: str,
        parsed_response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.parsed_response = parsed_response or {}


@dataclass
class GatewayJSONResult:
    parsed: dict[str, Any]
    raw_response: str
    model: str
    usage: dict[str, Any] | None = None


def prompt_cache_metrics(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize provider/OpenClaw prompt-cache usage for operator surfaces."""
    if not isinstance(usage, dict):
        return {
            "status": "unreported",
            "cached_tokens": None,
            "cache_write_tokens": None,
            "input_tokens": None,
            "hit_rate_percent": None,
        }

    def token_count(*values: Any) -> int | None:
        for value in values:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
        return None

    prompt_details = usage.get("prompt_tokens_details")
    input_details = usage.get("input_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    input_details = input_details if isinstance(input_details, dict) else {}
    cached_tokens = token_count(
        usage.get("cacheRead"),
        usage.get("cache_read"),
        usage.get("cache_read_input_tokens"),
        usage.get("cached_tokens"),
        prompt_details.get("cached_tokens"),
        input_details.get("cached_tokens"),
    )
    cache_write_tokens = token_count(
        usage.get("cacheWrite"),
        usage.get("cache_write"),
        usage.get("cache_creation_input_tokens"),
        prompt_details.get("cache_write_tokens"),
        input_details.get("cache_write_tokens"),
    )
    input_tokens = token_count(usage.get("prompt_tokens"), usage.get("input_tokens"))
    if cached_tokens is None and input_tokens is not None:
        cached_tokens = 0
    hit_rate = None
    if input_tokens and cached_tokens is not None:
        hit_rate = round((cached_tokens / input_tokens) * 100, 1)
    return {
        "status": (
            "hit" if cached_tokens and cached_tokens > 0
            else "miss" if cached_tokens == 0
            else "unreported"
        ),
        "cached_tokens": cached_tokens,
        "cache_write_tokens": cache_write_tokens,
        "input_tokens": input_tokens,
        "hit_rate_percent": hit_rate,
    }


def gateway_token() -> str:
    """Resolve OpenClaw gateway bearer token.

    Order: OPENCLAW_GATEWAY_TOKEN env, then gateway.auth.token in
    /root/.openclaw/openclaw.json. Cached after first read.
    """
    global _token_cache
    if _token_cache:
        return _token_cache
    env_token = os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip()
    if env_token:
        _token_cache = env_token
        return env_token
    try:
        with open(OPENCLAW_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError as e:
        raise LLMGatewayError(
            f"openclaw config not found at {OPENCLAW_CONFIG_PATH}; "
            "set OPENCLAW_GATEWAY_TOKEN"
        ) from e
    token = cfg.get("gateway", {}).get("auth", {}).get("token", "").strip()
    if not token:
        raise LLMGatewayError(
            f"No gateway.auth.token in {OPENCLAW_CONFIG_PATH}; "
            "set OPENCLAW_GATEWAY_TOKEN"
        )
    _token_cache = token
    return token


def load_skill(skill_path: str | Path) -> str:
    path = str(Path(skill_path))
    cached = _skill_cache.get(path)
    if cached:
        return cached
    try:
        with open(path, "r", encoding="utf-8") as f:
            skill = f.read()
    except FileNotFoundError as e:
        raise LLMGatewayError(f"SKILL.md not found at {path}") from e
    _skill_cache[path] = skill
    return skill


def clear_skill_cache() -> None:
    _skill_cache.clear()


def _balanced_json_objects(text: str):
    """Yield every top-level brace-balanced {...} substring, in order.

    Tolerates the gateway wrapping the real JSON in agent tool-chatter —
    including chatter that itself contains braces (e.g.
    `I tried { something } then: {"contains_phi": false}`), which is why we
    must try each candidate rather than the first brace span. Respects string
    literals and escapes so braces inside values don't miscount.
    """
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        escape = False
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i : j + 1]
                    break
        i += 1


def extract_json(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        match = _JSON_FENCE_RE.search(raw)
        if match:
            raw = match.group(1).strip()
    # Try the whole string first, then each balanced {...} candidate, returning
    # the first that parses to a dict. Handles leading/trailing agent chatter
    # (even chatter containing its own braces) appended to valid JSON.
    last_error: json.JSONDecodeError | None = None
    seen: set[str] = set()
    for candidate in (raw, *_balanced_json_objects(raw)):
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMGatewayError(
        f"gateway returned non-JSON: {last_error}; first 200 chars: {raw[:200]!r}"
    )


def require_fields(parsed: dict[str, Any], required: list[str]) -> None:
    missing = [field for field in required if field not in parsed]
    if missing:
        raise LLMGatewayError(f"gateway JSON missing required fields: {missing}")


def _schema_repair_body(
    original_body: dict[str, Any],
    *,
    raw_response: str,
    validation_error: str,
    required_fields: list[str],
) -> dict[str, Any]:
    """Build a bounded follow-up that repairs syntax/shape without re-reasoning."""
    repair_payload = {
        "kind": "gateway_schema_repair_v1",
        "instruction": (
            "Repair the previous assistant response only. Return exactly one complete valid "
            "JSON object with every required top-level field. Preserve the prior response's "
            "meaning and intended action. Do not claim a tool ran and do not perform a new "
            "reasoning step. Return JSON only."
        ),
        "required_top_level_fields": required_fields,
        "validation_error": validation_error,
        "invalid_response": raw_response[:20_000],
    }
    repaired = dict(original_body)
    original_messages = original_body.get("messages")
    system_message = (
        original_messages[0]
        if isinstance(original_messages, list) and original_messages
        else {"role": "system", "content": "Return valid JSON only."}
    )
    repaired["messages"] = [
        system_message,
        {"role": "user", "content": json.dumps(repair_payload, indent=2, ensure_ascii=False)},
    ]
    return repaired


async def call_skill_json(
    *,
    skill_path: str | Path,
    payload: dict[str, Any],
    required_fields: list[str],
    model: str | None = None,
    gateway_url: str | None = None,
    timeout_s: int | None = None,
    max_tokens: int | None = None,
    retries: int | None = None,
    gateway_user: str | None = None,
    prompt_cache_key: str | None = None,
    prompt_cache_retention: str | None = None,
    schema_repair_retries: int = 0,
    attempt_observer: GatewayAttemptObserver | None = None,
) -> GatewayJSONResult:
    """Call OpenClaw gateway with SKILL.md as system prompt and parse JSON."""
    skill = load_skill(skill_path)
    # Default to the lightweight memory-less proxy agent, never the main
    # `openclaw` agent — see CLAUDE.md "OpenClaw gateway: use the proxy agent".
    model_id = model or os.getenv("OPENCLAW_DEFAULT_MODEL", "openclaw/proxy")
    url = gateway_url or os.getenv("OPENCLAW_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    timeout = timeout_s or int(os.getenv("OPENCLAW_GATEWAY_TIMEOUT_S", "180"))
    token_limit = max_tokens or int(os.getenv("OPENCLAW_GATEWAY_MAX_TOKENS", "2000"))
    attempts = retries or int(os.getenv("OPENCLAW_GATEWAY_RETRIES", "3"))
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": skill},
            {"role": "user", "content": json.dumps(payload, indent=2, ensure_ascii=False)},
        ],
        "max_tokens": token_limit,
    }
    if gateway_user:
        body["user"] = gateway_user
    if prompt_cache_key:
        body["prompt_cache_key"] = prompt_cache_key
    if prompt_cache_retention:
        body["prompt_cache_retention"] = prompt_cache_retention

    repair_limit = max(0, int(schema_repair_retries))
    repairs_used = 0
    request_attempt = 0
    total_attempts = 0
    request_body = body
    last_error: Exception | None = None
    while True:
        request_attempt += 1
        total_attempts += 1
        if attempt_observer:
            try:
                await attempt_observer({
                    "phase": "started",
                    "attempt": total_attempts,
                    "model": model_id,
                    "gateway_url": url,
                    "request": request_body,
                })
            except Exception as observer_error:
                logger.warning("gateway attempt observer start failed: %s", observer_error)
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {gateway_token()}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
            if resp.status_code in (502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"gateway transient {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if not content:
                raise LLMGatewayResponseError(
                    "gateway returned empty content",
                    raw_response=content,
                )
            parsed: dict[str, Any] | None = None
            try:
                parsed = extract_json(content)
                require_fields(parsed, required_fields)
            except LLMGatewayError as validation_error:
                raise LLMGatewayResponseError(
                    str(validation_error),
                    raw_response=content,
                    parsed_response=parsed,
                ) from validation_error
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
            if attempt_observer:
                try:
                    await attempt_observer({
                        "phase": "completed",
                        "attempt": total_attempts,
                        "model": model_id,
                        "http_status": resp.status_code,
                        "raw_response": content,
                        "parsed_response": parsed,
                        "usage": usage or {},
                    })
                except Exception as observer_error:
                    logger.warning("gateway attempt observer completion failed: %s", observer_error)
            return GatewayJSONResult(parsed=parsed, raw_response=content, model=model_id, usage=usage)
        except LLMGatewayResponseError as e:
            last_error = e
            can_repair = repairs_used < repair_limit
            logger.warning(
                "gateway structured response attempt %d failed: %s",
                total_attempts,
                e,
            )
            if attempt_observer:
                try:
                    await attempt_observer({
                        "phase": "failed",
                        "attempt": total_attempts,
                        "model": model_id,
                        "status": "failed",
                        "http_status": resp.status_code,
                        "raw_response": e.raw_response,
                        "parsed_response": e.parsed_response,
                        "error": str(e) or e.__class__.__name__,
                        "will_retry": can_repair,
                    })
                except Exception as observer_error:
                    logger.warning("gateway attempt observer failure failed: %s", observer_error)
            if not can_repair:
                break
            repairs_used += 1
            request_body = _schema_repair_body(
                body,
                raw_response=e.raw_response,
                validation_error=str(e),
                required_fields=required_fields,
            )
            request_attempt = 0
        except (
            httpx.HTTPStatusError,
            httpx.ReadTimeout,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            LLMGatewayError,
        ) as e:
            last_error = e
            can_retry = request_attempt < attempts
            logger.warning("gateway skill call attempt %d failed: %s", total_attempts, e)
            if attempt_observer:
                try:
                    response = getattr(e, "response", None)
                    await attempt_observer({
                        "phase": "failed",
                        "attempt": total_attempts,
                        "model": model_id,
                        "status": "timed_out" if isinstance(e, httpx.ReadTimeout) else "failed",
                        "http_status": getattr(response, "status_code", None),
                        "raw_response": getattr(response, "text", "")[:20_000] if response is not None else "",
                        "error": str(e) or e.__class__.__name__,
                        "will_retry": can_retry,
                    })
                except Exception as observer_error:
                    logger.warning("gateway attempt observer failure failed: %s", observer_error)
            if not can_retry:
                break
            await asyncio.sleep(2 ** (request_attempt - 1))
    error_text = str(last_error).strip() if last_error is not None else ""
    if not error_text and last_error is not None:
        error_text = last_error.__class__.__name__
    raise LLMGatewayError(
        f"gateway call failed after {total_attempts} attempts: {error_text or 'unknown error'}"
    )
