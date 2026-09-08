"""Reusable client for Possible OS's dedicated Codex app-server.

The app-server process is deliberately external to the FastAPI process and to
OpenClaw.  This module provides the small, shared JSON-RPC adapter that any
Possible OS agent can use without learning the Codex wire protocol.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
import websockets


CODEX_APP_SERVER_URL = os.getenv(
    "CODEX_APP_SERVER_URL", "ws://127.0.0.1:4510"
).rstrip("/")
CODEX_APP_SERVER_MODEL = os.getenv("CODEX_APP_SERVER_MODEL", "gpt-5.6-luna")
CODEX_APP_SERVER_EFFORT = os.getenv("CODEX_APP_SERVER_EFFORT", "low")
CODEX_APP_SERVER_TIMEOUT_S = int(os.getenv("CODEX_APP_SERVER_TIMEOUT_S", "300"))
CODEX_APP_SERVER_CWD = os.getenv("CODEX_APP_SERVER_CWD", "/home/pranav/possibleos")
CODEX_APP_SERVER_MAX_MESSAGE_BYTES = int(
    os.getenv("CODEX_APP_SERVER_MAX_MESSAGE_BYTES", str(16 * 1024 * 1024))
)

_turn_lock = asyncio.Lock()
TurnObserver = Callable[[dict[str, Any]], Awaitable[None]]


class CodexAppServerError(RuntimeError):
    pass


@dataclass
class CodexTurnResult:
    text: str
    thread_id: str
    turn_id: str
    model: str
    usage: dict[str, Any]
    events: list[dict[str, Any]]
    latency: dict[str, float | None]


def _http_url(path: str) -> str:
    if CODEX_APP_SERVER_URL.startswith("wss://"):
        base = "https://" + CODEX_APP_SERVER_URL[len("wss://") :]
    elif CODEX_APP_SERVER_URL.startswith("ws://"):
        base = "http://" + CODEX_APP_SERVER_URL[len("ws://") :]
    else:
        raise CodexAppServerError("codex_app_server_url_must_use_ws_or_wss")
    return f"{base}{path}"


async def _send(ws: Any, message: dict[str, Any]) -> None:
    await ws.send(json.dumps(message, separators=(",", ":"), ensure_ascii=False))


async def _receive_for_id(
    ws: Any,
    request_id: int,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    while True:
        message = json.loads(await ws.recv())
        if message.get("id") == request_id and ("result" in message or "error" in message):
            if "error" in message:
                error = message.get("error") or {}
                raise CodexAppServerError(
                    f"codex_app_server_rpc_error:{error.get('code')}:{error.get('message')}"
                )
            return message.get("result") or {}
        events.append(message)


async def _initialize(ws: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    await _send(ws, {
        "method": "initialize",
        "id": 1,
        "params": {
            "clientInfo": {
                "name": "possibleos",
                "title": "Possible OS Codex Gateway",
                "version": "1.0.0",
            }
        },
    })
    initialized = await _receive_for_id(ws, 1, events)
    await _send(ws, {"method": "initialized", "params": {}})
    return initialized


def _usage_from_event(message: dict[str, Any]) -> dict[str, Any] | None:
    if message.get("method") != "thread/tokenUsage/updated":
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    token_usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
    last = token_usage.get("last") if isinstance(token_usage.get("last"), dict) else {}
    if not last:
        return None
    return {
        "input_tokens": int(last.get("inputTokens") or 0),
        "output_tokens": int(last.get("outputTokens") or 0),
        "total_tokens": int(last.get("totalTokens") or 0),
        "reasoning_output_tokens": int(last.get("reasoningOutputTokens") or 0),
        "input_tokens_details": {
            "cached_tokens": int(last.get("cachedInputTokens") or 0),
        },
    }


def _agent_text(message: dict[str, Any]) -> str | None:
    if message.get("method") != "item/completed":
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    item = params.get("item") if isinstance(params.get("item"), dict) else {}
    if item.get("type") != "agentMessage":
        return None
    return str(item.get("text") or "")


async def codex_app_server_status() -> dict[str, Any]:
    """Return a live readiness check without creating a model turn."""
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(_http_url("/readyz"))
        ready = response.status_code == 200
        error = None if ready else f"HTTP {response.status_code}"
    except Exception as exc:
        ready = False
        error = str(exc) or exc.__class__.__name__
    return {
        "provider": "codex",
        "ready": ready,
        "url": CODEX_APP_SERVER_URL,
        "model": CODEX_APP_SERVER_MODEL,
        "effort": CODEX_APP_SERVER_EFFORT,
        "independent_of_openclaw": True,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "error": error,
    }


async def list_codex_models() -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    started = time.monotonic()
    try:
        async with websockets.connect(
            CODEX_APP_SERVER_URL,
            open_timeout=5,
            max_size=CODEX_APP_SERVER_MAX_MESSAGE_BYTES,
        ) as ws:
            initialized = await _initialize(ws, events)
            await _send(ws, {
                "method": "model/list",
                "id": 2,
                "params": {"limit": 100, "includeHidden": True},
            })
            result = await _receive_for_id(ws, 2, events)
    except Exception as exc:
        if isinstance(exc, CodexAppServerError):
            raise
        raise CodexAppServerError(f"codex_app_server_unavailable:{exc}") from exc
    return {
        "models": result.get("data") or [],
        "next_cursor": result.get("nextCursor"),
        "server": initialized,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
    }


async def run_codex_turn(
    *,
    agent_id: str,
    prompt: str,
    instructions: str | None = None,
    thread_id: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    output_schema: dict[str, Any] | None = None,
    web_search: str = "disabled",
    timeout_s: int | None = None,
    observer: TurnObserver | None = None,
) -> CodexTurnResult:
    """Run one serialized turn through the dedicated Possible OS app-server.

    Serialization is an intentional first safety limit for this two-core host.
    Callers still receive queue wait separately from model execution latency.
    """
    selected_model = model or CODEX_APP_SERVER_MODEL
    selected_effort = effort or CODEX_APP_SERVER_EFFORT
    timeout = timeout_s or CODEX_APP_SERVER_TIMEOUT_S
    queued_at = time.monotonic()
    async with _turn_lock:
        lock_acquired = time.monotonic()
        events: list[dict[str, Any]] = []
        first_token_at: float | None = None
        usage: dict[str, Any] = {}
        final_text = ""
        turn_id = ""
        active_thread_id = thread_id or ""
        request_snapshot = {
            "agent_id": agent_id,
            "thread_id": thread_id,
            "model": selected_model,
            "effort": selected_effort,
            "web_search": web_search,
            "prompt": prompt,
            "has_instructions": bool(instructions),
            "output_schema": output_schema,
        }
        if observer:
            await observer({
                "phase": "started",
                "attempt": 1,
                "provider": "codex",
                "model": selected_model,
                "gateway_url": CODEX_APP_SERVER_URL,
                "request": request_snapshot,
            })
        started = time.monotonic()
        try:
            async with asyncio.timeout(timeout):
                async with websockets.connect(
                    CODEX_APP_SERVER_URL,
                    open_timeout=5,
                    max_size=CODEX_APP_SERVER_MAX_MESSAGE_BYTES,
                ) as ws:
                    connected_at = time.monotonic()
                    await _initialize(ws, events)
                    if thread_id:
                        await _send(ws, {
                            "method": "thread/resume",
                            "id": 2,
                            "params": {"threadId": thread_id, "model": selected_model},
                        })
                    else:
                        await _send(ws, {
                            "method": "thread/start",
                            "id": 2,
                            "params": {
                                "model": selected_model,
                                "cwd": CODEX_APP_SERVER_CWD,
                                "approvalPolicy": "never",
                                "sandbox": "read-only",
                                "baseInstructions": instructions,
                                "serviceName": f"possibleos:{agent_id}"[:64],
                                "threadSource": "appServer",
                                "config": {
                                    "web_search": web_search,
                                    "features": {"memory_tool": False},
                                },
                            },
                        })
                    thread_result = await _receive_for_id(ws, 2, events)
                    thread = thread_result.get("thread") if isinstance(thread_result.get("thread"), dict) else {}
                    active_thread_id = str(thread.get("id") or thread_id or "")
                    if not active_thread_id:
                        raise CodexAppServerError("codex_app_server_thread_id_missing")
                    turn_params: dict[str, Any] = {
                        "threadId": active_thread_id,
                        "input": [{"type": "text", "text": prompt}],
                        "model": selected_model,
                        "effort": selected_effort,
                        "approvalPolicy": "never",
                    }
                    if output_schema:
                        turn_params["outputSchema"] = output_schema
                    await _send(ws, {"method": "turn/start", "id": 3, "params": turn_params})
                    turn_result = await _receive_for_id(ws, 3, events)
                    initial_turn = turn_result.get("turn") if isinstance(turn_result.get("turn"), dict) else {}
                    turn_id = str(initial_turn.get("id") or "")
                    while True:
                        message = json.loads(await ws.recv())
                        events.append(message)
                        if message.get("method") == "item/agentMessage/delta" and first_token_at is None:
                            first_token_at = time.monotonic()
                        event_usage = _usage_from_event(message)
                        if event_usage is not None:
                            usage = event_usage
                        item_text = _agent_text(message)
                        if item_text is not None:
                            final_text = item_text
                        if message.get("method") != "turn/completed":
                            continue
                        params = message.get("params") if isinstance(message.get("params"), dict) else {}
                        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
                        if turn_id and str(turn.get("id") or "") != turn_id:
                            continue
                        turn_id = str(turn.get("id") or turn_id)
                        for item in turn.get("items") or []:
                            if isinstance(item, dict) and item.get("type") == "agentMessage":
                                final_text = str(item.get("text") or final_text)
                        if turn.get("status") != "completed":
                            raise CodexAppServerError(
                                f"codex_app_server_turn_{turn.get('status')}:{turn.get('error')}"
                            )
                        turn_duration_ms = turn.get("durationMs")
                        break
            completed = time.monotonic()
        except Exception as exc:
            if observer:
                await observer({
                    "phase": "failed",
                    "attempt": 1,
                    "provider": "codex",
                    "model": selected_model,
                    "status": "timed_out" if isinstance(exc, TimeoutError) else "failed",
                    "error": str(exc) or exc.__class__.__name__,
                    "will_retry": False,
                })
            if isinstance(exc, CodexAppServerError):
                raise
            if isinstance(exc, TimeoutError):
                raise CodexAppServerError("codex_app_server_turn_timeout") from exc
            raise CodexAppServerError(f"codex_app_server_turn_failed:{exc}") from exc

        latency = {
            "queue_wait_ms": round((lock_acquired - queued_at) * 1000, 1),
            "connect_ms": round((connected_at - started) * 1000, 1),
            "first_token_ms": (
                round((first_token_at - started) * 1000, 1)
                if first_token_at is not None else None
            ),
            "total_ms": round((completed - queued_at) * 1000, 1),
            "turn_duration_ms": float(turn_duration_ms) if turn_duration_ms is not None else None,
        }
        if observer:
            await observer({
                "phase": "completed",
                "attempt": 1,
                "provider": "codex",
                "model": selected_model,
                "thread_id": active_thread_id,
                "turn_id": turn_id,
                "http_status": 200,
                "raw_response": json.dumps({
                    "thread_id": active_thread_id,
                    "turn_id": turn_id,
                    "text": final_text,
                    "usage": usage,
                    "latency": latency,
                    "events": events,
                }, ensure_ascii=False),
                "usage": usage,
                "latency": latency,
            })
        return CodexTurnResult(
            text=final_text,
            thread_id=active_thread_id,
            turn_id=turn_id,
            model=selected_model,
            usage=usage,
            events=events,
            latency=latency,
        )
