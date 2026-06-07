import pytest

from app.services.action_read import read_action_outcome


@pytest.mark.asyncio
async def test_action_read_interprets_duplicate_policy_block(monkeypatch):
    async def fake_get_action(action_id):
        return {
            "action": {
                "id": action_id,
                "action_type": "send_email",
                "status": "blocked",
                "risk_level": "high",
                "requested_by": "operator",
                "approved_by": "operator",
                "entity_type": "lead_gen_email",
                "entity_id": "batch_item_1",
                "input": {
                    "mode": "lead_gen",
                    "to": "doug@example.com",
                    "subject": "the Precise autoresponders",
                    "body": "long body omitted by compact action",
                    "batch_item_id": "batch_item_1",
                },
                "policy_result": {
                    "allowed": False,
                    "reason": "no_prior_successful_lead_gen_action_for_recipient",
                    "checks": [
                        {"name": "recipient_present", "passed": True, "detail": "doug@example.com"},
                        {
                            "name": "no_prior_successful_lead_gen_action_for_recipient",
                            "passed": False,
                            "detail": "action_prior_success",
                        },
                    ],
                },
                "execution_result": {
                    "executed": False,
                    "blocked_by_policy": True,
                    "reason": "no_prior_successful_lead_gen_action_for_recipient",
                },
                "error": "Policy blocked permanently: no_prior_successful_lead_gen_action_for_recipient",
            },
            "events": [
                {
                    "id": 1,
                    "event_type": "action_blocked_by_policy",
                    "actor": "master-agent",
                    "message": "Policy blocked permanently.",
                    "output": {},
                    "created_at": "2026-06-07T00:00:00+00:00",
                },
            ],
        }

    monkeypatch.setattr("app.services.action_read.get_action", fake_get_action)

    result = await read_action_outcome({
        "operation": "get_action",
        "action_id": "action_blocked",
    })

    assert result["action"]["input_summary"]["to"] == "doug@example.com"
    assert "body" not in result["action"]["input_summary"]
    assert result["interpretation"]["feedback_type"] == "action_not_executable"
    assert result["interpretation"]["related_action_ids"] == ["action_prior_success"]
    assert "stale duplicate" in result["interpretation"]["recommended_interpretation"]


@pytest.mark.asyncio
async def test_action_read_lists_recent_actions(monkeypatch):
    async def fake_list_actions(status=None, action_type=None, limit=100):
        assert status == "blocked"
        assert limit == 2
        return [
            {
                "id": "action_1",
                "action_type": "send_email",
                "status": "blocked",
                "input": {"to": "a@example.com"},
                "policy_result": {},
                "execution_result": {},
            },
        ]

    monkeypatch.setattr("app.services.action_read.list_actions", fake_list_actions)

    result = await read_action_outcome({
        "operation": "list_recent",
        "status": "blocked",
        "limit": 2,
    })

    assert result["count"] == 1
    assert result["actions"][0]["id"] == "action_1"
