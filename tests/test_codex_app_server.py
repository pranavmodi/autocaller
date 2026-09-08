from app.services.codex_app_server import _agent_text, _usage_from_event


def test_codex_usage_event_maps_to_existing_provider_usage_shape():
    assert _usage_from_event({
        "method": "thread/tokenUsage/updated",
        "params": {
            "tokenUsage": {
                "last": {
                    "inputTokens": 120,
                    "cachedInputTokens": 80,
                    "outputTokens": 15,
                    "reasoningOutputTokens": 5,
                    "totalTokens": 135,
                }
            }
        },
    }) == {
        "input_tokens": 120,
        "output_tokens": 15,
        "total_tokens": 135,
        "reasoning_output_tokens": 5,
        "input_tokens_details": {"cached_tokens": 80},
    }


def test_codex_agent_message_uses_completed_item_as_authoritative_text():
    assert _agent_text({
        "method": "item/completed",
        "params": {"item": {"type": "agentMessage", "text": "done"}},
    }) == "done"
    assert _agent_text({"method": "item/completed", "params": {"item": {"type": "reasoning"}}}) is None
