"""Structured gateway parsing, persistence, and repair behavior."""
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


class _FakeGatewayResponse:
    status_code = 200

    def __init__(self, content: str):
        self._payload = {
            "choices": [{"message": {"content": content}}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeGatewayClient:
    def __init__(self, responses, requests):
        self._responses = responses
        self._requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, url, *, headers, json):
        self._requests.append({"url": url, "headers": headers, "json": json})
        return self._responses.pop(0)


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
    responses = [_FakeGatewayResponse(invalid), _FakeGatewayResponse(corrected)]
    requests = []
    monkeypatch.setattr(
        llm_gateway.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeGatewayClient(responses, requests),
    )
    monkeypatch.setattr(llm_gateway, "gateway_token", lambda: "test-token")
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
    repair_payload = json.loads(requests[1]["json"]["messages"][1]["content"])
    assert repair_payload["kind"] == "gateway_schema_repair_v1"
    assert repair_payload["invalid_response"] == invalid
    assert repair_payload["required_top_level_fields"] == required


@pytest.mark.asyncio
async def test_gateway_fails_after_bounded_repair_and_keeps_raw_output(
    monkeypatch,
    tmp_path,
):
    invalid_responses = [
        _FakeGatewayResponse('{"answer":"first malformed shape"}'),
        _FakeGatewayResponse('{"answer":"second malformed shape"}'),
    ]
    requests = []
    monkeypatch.setattr(
        llm_gateway.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeGatewayClient(invalid_responses, requests),
    )
    monkeypatch.setattr(llm_gateway, "gateway_token", lambda: "test-token")
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
