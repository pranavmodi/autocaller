from app.services.action_execution import _terminal_policy_block_reason


def test_terminal_policy_block_reason_detects_duplicate_send_failures():
    policy = {
        "reason": "batch_item_not_already_started",
        "checks": [
            {"name": "daily_budget_available", "passed": True},
            {"name": "no_prior_successful_lead_gen_action_for_item", "passed": False},
        ],
    }

    assert _terminal_policy_block_reason(policy) == "batch_item_not_already_started"


def test_terminal_policy_block_reason_ignores_retryable_failures():
    policy = {
        "reason": "daily_budget_available",
        "checks": [
            {"name": "daily_budget_available", "passed": False},
            {"name": "email_transport_configured", "passed": True},
        ],
    }

    assert _terminal_policy_block_reason(policy) == ""

