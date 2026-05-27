"""Shared OpenClaw gateway client for narrow, auditable LLM calls."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx


logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_CONFIG_PATH = Path(os.getenv("OPENCLAW_CONFIG_PATH", "/root/.openclaw/openclaw.json"))

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)
_token_cache: Optional[str] = None
_skill_cache: dict[str, str] = {}


class LLMGatewayError(Exception):
    pass


@dataclass
class GatewayJSONResult:
    parsed: dict[str, Any]
    raw_response: str
    model: str


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


def extract_json(content: str) -> dict[str, Any]:
    raw = content.strip()
    if raw.startswith("```"):
        match = _JSON_FENCE_RE.search(raw)
        if match:
            raw = match.group(1).strip()
    if not raw.startswith("{"):
        first = raw.find("{")
        last = raw.rfind("}")
        if first >= 0 and last > first:
            raw = raw[first : last + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMGatewayError(f"gateway returned non-JSON: {e}; first 200 chars: {raw[:200]!r}") from e
    if not isinstance(parsed, dict):
        raise LLMGatewayError("gateway JSON root must be an object")
    return parsed


def require_fields(parsed: dict[str, Any], required: list[str]) -> None:
    missing = [field for field in required if field not in parsed]
    if missing:
        raise LLMGatewayError(f"gateway JSON missing required fields: {missing}")


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
) -> GatewayJSONResult:
    """Call OpenClaw gateway with SKILL.md as system prompt and parse JSON."""
    skill = load_skill(skill_path)
    model_id = model or os.getenv("OPENCLAW_DEFAULT_MODEL", "openclaw")
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

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {gateway_token()}",
                        "Content-Type": "application/json",
                    },
                    json=body,
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
                raise LLMGatewayError("gateway returned empty content")
            parsed = extract_json(content)
            require_fields(parsed, required_fields)
            return GatewayJSONResult(parsed=parsed, raw_response=content, model=model_id)
        except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError, LLMGatewayError) as e:
            last_error = e
            logger.warning("gateway skill call attempt %d failed: %s", attempt, e)
            if attempt < attempts:
                await asyncio.sleep(2 ** (attempt - 1))
    raise LLMGatewayError(f"gateway call failed after {attempts} attempts: {last_error}")
