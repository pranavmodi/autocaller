"""Structured gateway parsing, persistence, and repair behavior."""
import asyncio
import json

import pytest

from app.services import llm_gateway
from app.services.llm_gateway import LLMGatewayError, call_skill_json, extract_json


def test_trailing_agent_chatter_after_valid_json():
    out = extract_json('{"subject":"hi","body":"t"}\n\n⚠️ 🛠️ `read memory` (agent) failed')
    assert out == {"subject": "hi", "body": "t"}


def test_leading_chatter_containing_braces():
    # The real compose failure: chatter with its own { } before the JSON.
    out = extract_json('I tried { something } then:\n{"contains_phi": false, "reason": "ok"}')
    assert out == {"contains_phi": False, "reason": "ok"}


def test_code_fenced_json_with_trailing_text():
    assert extract_json('```json\n{"a":1}\n``` trailing') == {"a": 1}


def test_braces_and_escaped_quotes_inside_string_values():
    out = extract_json('{"subject":"x","body":"has } brace and \\" quote"}\n junk')
    assert out == {"subject": "x", "body": 'has } brace and " quote'}


def test_nested_objects_preserved():
    assert extract_json('pre {"a":{"n":"}"},"b":2} post') == {"a": {"n": "}"}, "b": 2}


def test_genuinely_non_json_raises():
    with pytest.raises(LLMGatewayError):
        extract_json("no json here at all")


def test_legacy_completions_url_is_only_used_to_find_rpc_gateway():
    assert llm_gateway._normalize_rpc_url(
        "http://127.0.0.1:18789/v1/chat/completions"
    ) == "ws://127.0.0.1:18789/"


def test_assistant_text_and_usage_reads_native_rpc_history_shape():
    text, usage = llm_gateway._assistant_text_and_usage({
        "messages": [
            {"role": "user", "content": "request"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": '{"answer":"ok"}'}],
                "usage": {"input": 10, "output": 5, "cacheRead": 8},
            },
        ]
    })
    assert text == '{"answer":"ok"}'
    assert usage == {"input": 10, "output": 5, "cacheRead": 8}


class _FakeAgentRPC:
    def __init__(self, responses=None, requests=None, tracker=None):
        self._responses = list(responses or ['{"answer":"ok"}'])
        self._requests = requests if requests is not None else []
        self._tracker = tracker

    async def __call__(self, **kwargs):
        self._requests.append(kwargs)
        if self._tracker is not None:
            self._tracker["active"] += 1
            self._tracker["max_active"] = max(
                self._tracker["max_active"], self._tracker["active"]
            )
            await asyncio.sleep(0.02)
            self._tracker["active"] -= 1
        return self._responses.pop(0), {"input_tokens": 10, "output_tokens": 5}, "ok"


class _FakeNativeRPCClient:
    def __init__(self):
        self.calls = []

    async def request(self, method, params, *, timeout_s):
        self.calls.append((method, params, timeout_s))
        if method == "agent":
            return {"runId": params["idempotencyKey"], "sessionKey": params["sessionKey"], "status": "accepted"}
        if method == "agent.wait":
            return {"runId": params["runId"], "status": "ok"}
        if method == "chat.history":
            return {"messages": [{
                "role": "assistant",
                "content": [{"type": "text", "text": '{"answer":"ok"}'}],
                "usage": {"input": 5, "output": 2},
            }]}
        if method == "sessions.delete":
            return {"ok": True}
        raise AssertionError(method)


@pytest.mark.asyncio
async def test_raw_model_rpc_puts_skill_in_message_and_disables_tools(monkeypatch):
    client = _FakeNativeRPCClient()
    monkeypatch.setattr(llm_gateway, "_rpc_client", lambda _url: client)
    request_body = {
        "messages": [
            {"role": "system", "content": "SKILL INSTRUCTIONS"},
            {"role": "user", "content": '{"work":"now"}'},
        ],
        "max_tokens": 100,
    }

    content, usage, status = await llm_gateway._run_agent_rpc(
        rpc_url="ws://example.test/",
        agent_id="neo",
        lane="possibleos-interactive",
        request_body=request_body,
        timeout_s=420,
        gateway_user=None,
        allow_tools=False,
    )

    agent_params = client.calls[0][1]
    assert agent_params["modelRun"] is True
    assert agent_params["promptMode"] == "none"
    assert "extraSystemPrompt" not in agent_params
    assert agent_params["message"].startswith("SKILL INSTRUCTIONS")
    assert 'INPUT\n{"work":"now"}' in agent_params["message"]
    assert client.calls[0][2] == 435
    assert client.calls[1][0] == "agent.wait" and client.calls[1][2] == 435
    assert content == '{"answer":"ok"}'
    assert usage == {"input": 5, "output": 2}
    assert status == "ok"


@pytest.mark.asyncio
async def test_rpc_accepts_terminal_agent_response_without_wait(monkeypatch):
    class TerminalClient(_FakeNativeRPCClient):
        async def request(self, method, params, *, timeout_s):
            self.calls.append((method, params, timeout_s))
            if method == "agent":
                return {
                    "runId": params["idempotencyKey"],
                    "sessionKey": params["sessionKey"],
                    "status": "ok",
                }
            if method == "chat.history":
                return {"messages": [{"role": "assistant", "content": '{"answer":"ok"}'}]}
            if method == "sessions.delete":
                return {"ok": True}
            raise AssertionError(method)

    client = TerminalClient()
    monkeypatch.setattr(llm_gateway, "_rpc_client", lambda _url: client)
    content, _usage, status = await llm_gateway._run_agent_rpc(
        rpc_url="ws://example.test/",
        agent_id="neo",
        lane="possibleos-interactive",
        request_body={"messages": [
            {"role": "system", "content": "SKILL"},
            {"role": "user", "content": "INPUT"},
        ]},
        timeout_s=120,
        gateway_user=None,
        allow_tools=False,
    )
    assert content == '{"answer":"ok"}' and status == "ok"
    assert [call[0] for call in client.calls] == ["agent", "chat.history", "sessions.delete"]


@pytest.mark.asyncio
async def test_rpc_aborts_and_deletes_when_agent_response_fails(monkeypatch):
    class FailedClient(_FakeNativeRPCClient):
        async def request(self, method, params, *, timeout_s):
            self.calls.append((method, params, timeout_s))
            if method == "agent":
                raise llm_gateway.LLMGatewayRPCError("agent timed out", code="TIMEOUT")
            if method in {"chat.abort", "sessions.delete"}:
                return {"ok": True}
            raise AssertionError(method)

    client = FailedClient()
    monkeypatch.setattr(llm_gateway, "_rpc_client", lambda _url: client)
    with pytest.raises(llm_gateway.LLMGatewayRPCError, match="agent timed out"):
        await llm_gateway._run_agent_rpc(
            rpc_url="ws://example.test/",
            agent_id="neo",
            lane="possibleos-interactive",
            request_body={"messages": [
                {"role": "system", "content": "SKILL"},
                {"role": "user", "content": "INPUT"},
            ]},
            timeout_s=120,
            gateway_user=None,
            allow_tools=False,
        )
    assert [call[0] for call in client.calls] == ["agent", "chat.abort", "sessions.delete"]


@pytest.mark.asyncio
async def test_rpc_retries_read_only_history_after_gateway_pressure(monkeypatch):
    class SlowHistoryClient(_FakeNativeRPCClient):
        def __init__(self):
            super().__init__()
            self.history_attempts = 0

        async def request(self, method, params, *, timeout_s):
            self.calls.append((method, params, timeout_s))
            if method == "agent":
                return {"runId": params["idempotencyKey"], "sessionKey": params["sessionKey"],
                        "status": "accepted"}
            if method == "agent.wait":
                return {"runId": params["runId"], "status": "ok"}
            if method == "chat.history":
                self.history_attempts += 1
                if self.history_attempts == 1:
                    raise llm_gateway.LLMGatewayRPCError(
                        "history timed out", code="TIMEOUT",
                    )
                return {"messages": [{"role": "assistant", "content": '{"answer":"ok"}'}]}
            if method == "sessions.delete":
                return {"ok": True}
            raise AssertionError(method)

    client = SlowHistoryClient()
    monkeypatch.setattr(llm_gateway, "_rpc_client", lambda _url: client)
    content, _usage, status = await llm_gateway._run_agent_rpc(
        rpc_url="ws://example.test/",
        agent_id="neo",
        lane="possibleos-interactive",
        request_body={"messages": [
            {"role": "system", "content": "SKILL"},
            {"role": "user", "content": "INPUT"},
        ]},
        timeout_s=120,
        gateway_user=None,
        allow_tools=False,
    )
    assert content == '{"answer":"ok"}' and status == "ok"
    assert [call[0] for call in client.calls] == [
        "agent", "agent.wait", "chat.history", "chat.history", "sessions.delete",
    ]
    assert client.calls[2][2] == client.calls[3][2] == 60


@pytest.mark.asyncio
async def test_native_tool_invocation_uses_rpc_without_agent_session(monkeypatch):
    client = _FakeNativeRPCClient()

    async def request(method, params, *, timeout_s):
        client.calls.append((method, params, timeout_s))
        return {"ok": True, "toolName": "web_search", "output": {"results": []}}

    client.request = request
    monkeypatch.setattr(llm_gateway, "_rpc_client", lambda _url: client)
    result = await llm_gateway.invoke_openclaw_tool(
        "web_search", {"objective": "Find Example", "search_queries": ["Example official"]},
    )
    assert result["ok"] is True
    assert client.calls[0][0] == "tools.invoke"
    assert client.calls[0][1]["name"] == "web_search"
    assert client.calls[0][1]["agentId"] == "main"


@pytest.mark.asyncio
async def test_gateway_serializes_concurrent_openclaw_requests(monkeypatch, tmp_path):
    tracker = {"active": 0, "max_active": 0}
    monkeypatch.setattr(
        llm_gateway,
        "_run_agent_rpc",
        _FakeAgentRPC(responses=['{"answer":"ok"}', '{"answer":"ok"}'], tracker=tracker),
    )
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("Return one JSON object.", encoding="utf-8")

    await asyncio.gather(*(
        call_skill_json(
            skill_path=skill_path,
            payload={"request": index},
            required_fields=["answer"],
            retries=1,
        )
        for index in range(2)
    ))

    assert tracker["max_active"] == 1


@pytest.mark.asyncio
async def test_gateway_allows_different_named_lanes_to_progress(monkeypatch, tmp_path):
    tracker = {"active": 0, "max_active": 0}
    monkeypatch.setattr(
        llm_gateway,
        "_run_agent_rpc",
        _FakeAgentRPC(responses=['{"answer":"ok"}', '{"answer":"ok"}'], tracker=tracker),
    )
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("Return one JSON object.", encoding="utf-8")

    await asyncio.gather(
        call_skill_json(
            skill_path=skill_path,
            payload={"request": "main"},
            required_fields=["answer"],
            model="openclaw/main",
            retries=1,
            lane="possibleos-interactive",
        ),
        call_skill_json(
            skill_path=skill_path,
            payload={"request": "neo"},
            required_fields=["answer"],
            model="openclaw/neo",
            retries=1,
            lane="possibleos-batch",
        ),
    )

    assert tracker["max_active"] == 2


@pytest.mark.asyncio
async def test_gateway_repairs_invalid_json_and_preserves_both_attempts(
    monkeypatch,
    tmp_path,
):
    invalid = (
        '{"step_name":"retrieve","summary":"found","reasoning":"evidence",'
        '"state_updates":{"candidate_shortlist":[]},"evidence_needed":["passage"]},'
        '"action":{"type":"tool_call","tool":"mission_control.get_passages",'
        '"arguments":{"chunk_ids":[1]}},"next_step":"review","is_complete":false}'
    )
    corrected = json.dumps({
        "step_name": "retrieve",
        "summary": "found",
        "reasoning": "evidence",
        "state_updates": {
            "candidate_shortlist": [],
            "evidence_needed": ["passage"],
        },
        "action": {
            "type": "tool_call",
            "tool": "mission_control.get_passages",
            "arguments": {"chunk_ids": [1]},
        },
        "next_step": "review",
        "is_complete": False,
    })
    responses = [invalid, corrected]
    requests = []
    monkeypatch.setattr(
        llm_gateway,
        "_run_agent_rpc",
        _FakeAgentRPC(responses, requests),
    )
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("Return one JSON object.", encoding="utf-8")
    events = []

    async def observe(event):
        events.append(event)

    required = [
        "step_name",
        "summary",
        "reasoning",
        "state_updates",
        "action",
        "next_step",
        "is_complete",
    ]
    result = await call_skill_json(
        skill_path=skill_path,
        payload={"context_layout": "continuation_v2"},
        required_fields=required,
        model="openclaw/main",
        retries=1,
        schema_repair_retries=1,
        attempt_observer=observe,
    )

    assert result.parsed == json.loads(corrected)
    assert [event["phase"] for event in events] == [
        "started",
        "failed",
        "started",
        "completed",
    ]
    assert events[1]["raw_response"] == invalid
    assert events[1]["parsed_response"]["step_name"] == "retrieve"
    assert events[1]["will_retry"] is True
    repair_payload = json.loads(requests[1]["request_body"]["messages"][1]["content"])
    assert repair_payload["kind"] == "gateway_schema_repair_v1"
    assert repair_payload["invalid_response"] == invalid
    assert repair_payload["required_top_level_fields"] == required


@pytest.mark.asyncio
async def test_gateway_fails_after_bounded_repair_and_keeps_raw_output(
    monkeypatch,
    tmp_path,
):
    invalid_responses = [
        '{"answer":"first malformed shape"}',
        '{"answer":"second malformed shape"}',
    ]
    requests = []
    monkeypatch.setattr(
        llm_gateway,
        "_run_agent_rpc",
        _FakeAgentRPC(invalid_responses, requests),
    )
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("Return one JSON object.", encoding="utf-8")
    events = []

    async def observe(event):
        events.append(event)

    with pytest.raises(LLMGatewayError, match="gateway call failed after 2 attempts"):
        await call_skill_json(
            skill_path=skill_path,
            payload={"work": "once"},
            required_fields=["answer", "is_complete"],
            retries=1,
            schema_repair_retries=1,
            attempt_observer=observe,
        )

    failures = [event for event in events if event["phase"] == "failed"]
    assert [event["raw_response"] for event in failures] == [
        '{"answer":"first malformed shape"}',
        '{"answer":"second malformed shape"}',
    ]
    assert failures[0]["will_retry"] is True
    assert failures[1]["will_retry"] is False
