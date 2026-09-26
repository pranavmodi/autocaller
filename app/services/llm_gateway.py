"""Shared OpenClaw gateway client for narrow, auditable LLM calls."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit, urlunsplit
from weakref import WeakKeyDictionary

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State


logger = logging.getLogger(__name__)

DEFAULT_GATEWAY_RPC_URL = "ws://127.0.0.1:18789"
DEFAULT_INTERACTIVE_LANE = "possibleos-interactive"
DEFAULT_BATCH_LANE = "possibleos-batch"
OPENCLAW_CONFIG_PATH = Path(os.getenv("OPENCLAW_CONFIG_PATH", "/root/.openclaw/openclaw.json"))

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.MULTILINE)
_token_cache: Optional[str] = None
_skill_cache: dict[str, str] = {}
# OpenClaw lanes, not agent ids, are the concurrency boundary. Mirror each named
# server lane with a one-at-a-time client gate so the per-run timeout starts only
# after this process reaches the head of its lane. Different lanes remain able
# to make progress concurrently.
_openclaw_request_gates: WeakKeyDictionary = WeakKeyDictionary()
_openclaw_rpc_clients: WeakKeyDictionary = WeakKeyDictionary()


def _request_gate(lane: str) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    gates = _openclaw_request_gates.setdefault(loop, {})
    return gates.setdefault(lane, asyncio.Semaphore(1))

GatewayAttemptObserver = Callable[[dict[str, Any]], Awaitable[None]]


class LLMGatewayError(Exception):
    pass


class LLMGatewayRPCError(LLMGatewayError):
    """A native OpenClaw gateway RPC or transport failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool = False,
        retry_after_ms: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms


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


@dataclass
class _PendingRPCRequest:
    future: asyncio.Future[Any]
    method: str


def interactive_lane() -> str:
    return os.getenv("OPENCLAW_RPC_INTERACTIVE_LANE", DEFAULT_INTERACTIVE_LANE).strip() or DEFAULT_INTERACTIVE_LANE


def batch_lane() -> str:
    return os.getenv("OPENCLAW_RPC_BATCH_LANE", DEFAULT_BATCH_LANE).strip() or DEFAULT_BATCH_LANE


def _normalize_rpc_url(value: str | None) -> str:
    """Return a gateway WebSocket URL, accepting the retired HTTP endpoint."""
    raw = (value or "").strip() or DEFAULT_GATEWAY_RPC_URL
    parts = urlsplit(raw)
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
    if scheme not in {"ws", "wss"}:
        raise LLMGatewayError(f"invalid OpenClaw RPC URL scheme: {parts.scheme or '<missing>'}")
    path = parts.path.rstrip("/")
    if path.endswith("/v1/chat/completions"):
        path = path[: -len("/v1/chat/completions")]
    return urlunsplit((scheme, parts.netloc, path or "/", parts.query, ""))


def _gateway_rpc_url(override: str | None = None) -> str:
    if override:
        return _normalize_rpc_url(override)
    configured = os.getenv("OPENCLAW_GATEWAY_RPC_URL", "").strip()
    if configured:
        return _normalize_rpc_url(configured)
    # Keep the old variable as an input-only compatibility bridge. Requests no
    # longer use its /v1/chat/completions endpoint.
    return _normalize_rpc_url(os.getenv("OPENCLAW_GATEWAY_URL", DEFAULT_GATEWAY_RPC_URL))


class OpenClawRPCClient:
    """Small multiplexed client for OpenClaw's native WebSocket RPC protocol."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self._token = token
        self._ws: ClientConnection | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, _PendingRPCRequest] = {}
        self._closed = False

    def _is_connected(self) -> bool:
        return (
            not self._closed
            and self._ws is not None
            and self._ws.state is State.OPEN
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    async def _connect(self) -> None:
        if self._is_connected():
            return
        async with self._connect_lock:
            if self._is_connected():
                return
            if self._closed:
                raise LLMGatewayRPCError("OpenClaw RPC client is closed")
            await self._discard_connection()
            ws: ClientConnection | None = None
            try:
                connect_timeout = max(
                    10.0,
                    float(os.getenv("OPENCLAW_RPC_CONNECT_TIMEOUT_S", "30")),
                )
                ws = await connect(
                    self.url,
                    open_timeout=connect_timeout,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                )
                challenge = json.loads(await asyncio.wait_for(ws.recv(), timeout=connect_timeout))
                if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
                    raise LLMGatewayRPCError("OpenClaw RPC connect challenge was not received")
                nonce = str((challenge.get("payload") or {}).get("nonce") or "").strip()
                if not nonce:
                    raise LLMGatewayRPCError("OpenClaw RPC connect challenge had no nonce")
                connect_id = uuid.uuid4().hex
                await ws.send(json.dumps({
                    "type": "req",
                    "id": connect_id,
                    "method": "connect",
                    "params": {
                        "minProtocol": 4,
                        "maxProtocol": 4,
                        "client": {
                            "id": "gateway-client",
                            "displayName": "Possible OS",
                            "version": "1",
                            "platform": "linux",
                            "mode": "backend",
                        },
                        "role": "operator",
                        "scopes": ["operator.read", "operator.write", "operator.admin"],
                        "caps": [],
                        "commands": [],
                        "permissions": {},
                        "auth": {"token": self._token},
                        "locale": "en-US",
                        "userAgent": "possibleos/1 native-rpc",
                    },
                }))
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=connect_timeout))
                    if frame.get("type") != "res" or frame.get("id") != connect_id:
                        continue
                    if not frame.get("ok"):
                        error = frame.get("error") or {}
                        raise LLMGatewayRPCError(
                            str(error.get("message") or "OpenClaw RPC connect failed"),
                            code=str(error.get("code") or "") or None,
                            retryable=bool(error.get("retryable")),
                        )
                    break
                self._ws = ws
                self._reader_task = asyncio.create_task(
                    self._reader_loop(ws),
                    name="possibleos-openclaw-rpc-reader",
                )
            except Exception:
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                raise

    async def _reader_loop(self, ws: ClientConnection) -> None:
        failure: Exception | None = None
        try:
            async for raw in ws:
                try:
                    frame = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    logger.warning("OpenClaw RPC returned an invalid frame")
                    continue
                if frame.get("type") != "res":
                    continue
                request_id = str(frame.get("id") or "")
                pending = self._pending.pop(request_id, None)
                if pending is None or pending.future.done():
                    continue
                if frame.get("ok"):
                    pending.future.set_result(frame.get("payload"))
                    continue
                error = frame.get("error") or {}
                pending.future.set_exception(LLMGatewayRPCError(
                    str(error.get("message") or f"OpenClaw RPC {pending.method} failed"),
                    code=str(error.get("code") or "") or None,
                    retryable=bool(error.get("retryable")),
                    retry_after_ms=(
                        int(error["retryAfterMs"])
                        if isinstance(error.get("retryAfterMs"), (int, float))
                        else None
                    ),
                ))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = exc
        finally:
            if self._ws is ws:
                self._ws = None
            message = "OpenClaw RPC connection closed"
            if failure and not isinstance(failure, ConnectionClosed):
                message = f"{message}: {failure}"
            error = LLMGatewayRPCError(message, code="CONNECTION_CLOSED", retryable=True)
            for request_id, pending in list(self._pending.items()):
                self._pending.pop(request_id, None)
                if not pending.future.done():
                    pending.future.set_exception(error)

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_s: float,
    ) -> Any:
        """Make one RPC request, reconnecting once before a response is seen."""
        last_error: Exception | None = None
        for connection_attempt in range(2):
            try:
                await self._connect()
                if self._ws is None:
                    raise LLMGatewayRPCError("OpenClaw RPC connection is unavailable", retryable=True)
                request_id = uuid.uuid4().hex
                future = asyncio.get_running_loop().create_future()
                self._pending[request_id] = _PendingRPCRequest(future=future, method=method)
                frame = {"type": "req", "id": request_id, "method": method, "params": params}
                try:
                    async with self._send_lock:
                        if self._ws is None:
                            raise LLMGatewayRPCError("OpenClaw RPC connection closed", retryable=True)
                        await self._ws.send(json.dumps(frame, ensure_ascii=False))
                except Exception:
                    self._pending.pop(request_id, None)
                    if not future.done():
                        future.cancel()
                    raise
                try:
                    return await asyncio.wait_for(asyncio.shield(future), timeout=max(1.0, timeout_s))
                except TimeoutError as exc:
                    self._pending.pop(request_id, None)
                    if not future.done():
                        future.cancel()
                    raise LLMGatewayRPCError(
                        f"OpenClaw RPC {method} timed out after {timeout_s:.0f}s",
                        code="TIMEOUT",
                    ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                retryable = isinstance(exc, (ConnectionClosed, OSError, TimeoutError)) or (
                    isinstance(exc, LLMGatewayRPCError) and exc.retryable
                )
                if connection_attempt == 0 and retryable:
                    await self._discard_connection()
                    continue
                if isinstance(exc, LLMGatewayError):
                    raise
                raise LLMGatewayRPCError(
                    f"OpenClaw RPC {method} failed: {exc}",
                    retryable=retryable,
                ) from exc
        raise LLMGatewayRPCError(f"OpenClaw RPC {method} failed: {last_error}")

    async def _discard_connection(self) -> None:
        ws, reader = self._ws, self._reader_task
        self._ws = None
        self._reader_task = None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def close(self) -> None:
        self._closed = True
        await self._discard_connection()


def _rpc_client(url: str) -> OpenClawRPCClient:
    loop = asyncio.get_running_loop()
    clients = _openclaw_rpc_clients.setdefault(loop, {})
    return clients.setdefault(url, OpenClawRPCClient(url, gateway_token()))


async def close_gateway_rpc_clients() -> None:
    """Close RPC sockets owned by the current event loop."""
    loop = asyncio.get_running_loop()
    clients = _openclaw_rpc_clients.pop(loop, {})
    await asyncio.gather(*(client.close() for client in clients.values()), return_exceptions=True)


async def invoke_openclaw_tool(
    name: str,
    args: dict[str, Any],
    *,
    agent_id: str = "main",
    timeout_s: int = 90,
) -> dict[str, Any]:
    """Invoke one native OpenClaw tool without starting an agent session."""
    url = _gateway_rpc_url()
    client = _rpc_client(url)
    async with _request_gate("possibleos-tools"):
        response = await client.request(
            "tools.invoke",
            {
                "name": name,
                "args": args,
                "agentId": agent_id,
                "idempotencyKey": f"possibleos-tool-{uuid.uuid4().hex}",
            },
            timeout_s=max(1, timeout_s),
        )
    if not isinstance(response, dict):
        raise LLMGatewayRPCError(f"OpenClaw tool {name} returned an invalid response")
    if not response.get("ok"):
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        raise LLMGatewayRPCError(
            str(error.get("message") or f"OpenClaw tool {name} failed"),
            code=str(error.get("code") or "") or None,
        )
    return response


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
    input_tokens = token_count(
        usage.get("prompt_tokens"),
        usage.get("input_tokens"),
        usage.get("input"),
    )
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


def _agent_id(model_id: str) -> str:
    value = model_id.strip()
    # Older campaign rows stored the OpenAI-compatible model name `openclaw`,
    # which meant the gateway's default agent. Preserve that meaning under RPC.
    if value == "openclaw":
        return "main"
    if value.startswith("openclaw/"):
        value = value.split("/", 1)[1]
    if not value or "/" in value:
        raise LLMGatewayError(
            f"native OpenClaw RPC requires an openclaw/<agent> model, got {model_id!r}"
        )
    return value


def _assistant_text_and_usage(history: Any) -> tuple[str, dict[str, Any] | None]:
    messages = history.get("messages") if isinstance(history, dict) else None
    if not isinstance(messages, list):
        raise LLMGatewayRPCError("OpenClaw chat.history returned no messages")
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        text_parts: list[str] = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                    value = part.get("text")
                    if isinstance(value, str):
                        text_parts.append(value)
        direct_text = message.get("text")
        if not text_parts and isinstance(direct_text, str):
            text_parts.append(direct_text)
        text = "\n".join(part for part in text_parts if part).strip()
        if not text:
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            usage = None
        return text, usage
    raise LLMGatewayRPCError("OpenClaw completed without an assistant response")


async def _best_effort_rpc(
    client: OpenClawRPCClient,
    method: str,
    params: dict[str, Any],
    *,
    timeout_s: float = 10,
) -> None:
    try:
        await client.request(method, params, timeout_s=timeout_s)
    except Exception as exc:
        logger.debug("OpenClaw RPC cleanup %s failed: %s", method, exc)


async def _run_agent_rpc(
    *,
    rpc_url: str,
    agent_id: str,
    lane: str,
    request_body: dict[str, Any],
    timeout_s: int,
    gateway_user: str | None,
    allow_tools: bool,
) -> tuple[str, dict[str, Any] | None, str]:
    """Run one isolated native RPC agent turn and return its assistant text."""
    messages = request_body.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise LLMGatewayError("gateway request is missing system or user content")
    system_prompt = str(messages[0].get("content") or "")
    user_message = str(messages[-1].get("content") or "")
    token_limit = request_body.get("max_tokens")
    output_instruction = (
        "\n\nReturn exactly one valid JSON object and no surrounding commentary."
        + (
            f" Keep the response below approximately {int(token_limit)} tokens."
            if isinstance(token_limit, int) and token_limit > 0
            else ""
        )
    )
    rpc_message = user_message
    if not allow_tools:
        # Raw model runs intentionally skip OpenClaw's assembled system prompt,
        # including extraSystemPrompt. Put the stable skill first so it remains
        # authoritative and provider prompt caches can still reuse the prefix.
        rpc_message = f"{system_prompt}{output_instruction}\n\nINPUT\n{user_message}"
    client = _rpc_client(rpc_url)
    idempotency_key = f"possibleos-{uuid.uuid4().hex}"
    session_key = f"agent:{agent_id}:possibleos:{uuid.uuid4().hex}"
    label = re.sub(r"[^A-Za-z0-9._:-]+", "-", gateway_user or "possibleos")[:80]
    accepted: dict[str, Any] | None = None
    dispatched = False
    terminal = False
    history_retrieved = False
    run_id = idempotency_key
    try:
        # Some deployed OpenClaw builds return the `agent` response only when
        # the run completes, despite the protocol documenting an immediate
        # accepted acknowledgement. Never give that first response a shorter
        # budget than the run itself or leave a live run behind on timeout.
        accept_timeout_s = min(
            float(os.getenv("OPENCLAW_RPC_ACCEPT_TIMEOUT_S", str(timeout_s + 15))),
            max(10, timeout_s + 15),
        )
        dispatched = True
        response = await client.request(
            "agent",
            {
                "message": rpc_message,
                "agentId": agent_id,
                "sessionKey": session_key,
                "timeout": max(1, int(math.ceil(timeout_s))),
                "lane": lane,
                "modelRun": not allow_tools,
                "promptMode": "minimal" if allow_tools else "none",
                **(
                    {"extraSystemPrompt": system_prompt + output_instruction}
                    if allow_tools
                    else {}
                ),
                "bootstrapContextMode": "lightweight",
                "cleanupBundleMcpOnRunEnd": True,
                "disableMessageTool": True,
                "deliver": False,
                "idempotencyKey": idempotency_key,
                "label": label or "possibleos",
            },
            timeout_s=accept_timeout_s,
        )
        if not isinstance(response, dict):
            raise LLMGatewayRPCError("OpenClaw agent RPC returned an invalid acknowledgement")
        accepted = response
        run_id = str(response.get("runId") or idempotency_key)
        session_key = str(response.get("sessionKey") or session_key)
        response_status = str(response.get("status") or "")
        if response_status not in {"accepted", "in_flight", "ok"}:
            raise LLMGatewayRPCError(
                f"OpenClaw agent RPC was not accepted: {response.get('status') or 'unknown'}"
            )
        waited = response if response_status == "ok" else await client.request(
                "agent.wait",
                {"runId": run_id, "timeoutMs": max(1_000, int(timeout_s * 1_000))},
                timeout_s=timeout_s + 15,
            )
        status = str(waited.get("status") or "") if isinstance(waited, dict) else ""
        if status != "ok":
            if status == "timeout":
                await _best_effort_rpc(
                    client,
                    "chat.abort",
                    {"sessionKey": session_key, "runId": run_id},
                )
            detail = waited.get("error") or waited.get("stopReason") if isinstance(waited, dict) else None
            raise LLMGatewayRPCError(
                f"OpenClaw agent run ended with {status or 'unknown status'}"
                + (f": {detail}" if detail else ""),
                code=status.upper() if status else None,
                retryable=status in {"timeout", "error"},
            )
        terminal = True
        history = None
        history_timeout_s = min(120.0, max(60.0, timeout_s / 4))
        for history_attempt in range(2):
            try:
                history = await client.request(
                    "chat.history",
                    {"sessionKey": session_key, "agentId": agent_id, "limit": 8,
                     "maxChars": 100_000},
                    timeout_s=history_timeout_s,
                )
                break
            except LLMGatewayRPCError as exc:
                if exc.code != "TIMEOUT" or history_attempt == 1:
                    raise
        history_retrieved = True
        content, usage = _assistant_text_and_usage(history)
        return content, usage, status
    except asyncio.CancelledError:
        if dispatched:
            try:
                await asyncio.shield(_best_effort_rpc(
                    client,
                    "chat.abort",
                    {"sessionKey": session_key, "runId": run_id},
                ))
            except asyncio.CancelledError:
                pass
        raise
    except Exception:
        if dispatched and not terminal:
            await _best_effort_rpc(
                client,
                "chat.abort",
                {"sessionKey": session_key, "runId": run_id},
            )
        raise
    finally:
        if dispatched and (history_retrieved or not terminal):
            try:
                await asyncio.shield(_best_effort_rpc(
                    client,
                    "sessions.delete",
                    {"key": session_key, "agentId": agent_id, "deleteTranscript": True},
                ))
            except asyncio.CancelledError:
                pass


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
    lane: str | None = None,
    allow_tools: bool = True,
) -> GatewayJSONResult:
    """Run a structured OpenClaw turn through native RPC and parse its JSON."""
    skill = load_skill(skill_path)
    model_id = model or os.getenv("OPENCLAW_DEFAULT_MODEL", "openclaw/main")
    agent_id = _agent_id(model_id)
    url = _gateway_rpc_url(gateway_url)
    lane_id = (lane or interactive_lane()).strip()
    if not lane_id:
        raise LLMGatewayError("OpenClaw RPC lane cannot be blank")
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
                    "transport": "openclaw_rpc",
                    "lane": lane_id,
                    "request": request_body,
                })
            except Exception as observer_error:
                logger.warning("gateway attempt observer start failed: %s", observer_error)
        try:
            async with _request_gate(lane_id):
                content, usage, rpc_status = await _run_agent_rpc(
                    rpc_url=url,
                    agent_id=agent_id,
                    lane=lane_id,
                    request_body=request_body,
                    timeout_s=timeout,
                    gateway_user=gateway_user,
                    allow_tools=allow_tools,
                )
            content = content.strip()
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
            if attempt_observer:
                try:
                    await attempt_observer({
                        "phase": "completed",
                        "attempt": total_attempts,
                        "model": model_id,
                        "transport": "openclaw_rpc",
                        "lane": lane_id,
                        "rpc_status": rpc_status,
                        "http_status": None,
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
                        "transport": "openclaw_rpc",
                        "lane": lane_id,
                        "rpc_status": "ok",
                        "http_status": None,
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
                        "transport": "openclaw_rpc",
                        "lane": lane_id,
                        "status": "timed_out" if getattr(e, "code", None) == "TIMEOUT" else "failed",
                        "rpc_status": getattr(e, "code", None),
                        "http_status": None,
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
