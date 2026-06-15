"""extract_json must survive the gateway appending agent tool-chatter."""
import pytest

from app.services.llm_gateway import LLMGatewayError, extract_json


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
