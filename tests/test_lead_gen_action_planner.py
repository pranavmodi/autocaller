from app.services.lead_gen_action_planner import (
    CONTINUATION_ACTIONS,
    QUEUEABLE_ACTIONS,
    LeadGenActionCandidate,
)
from app.services.lead_gen_cybernetic import daily_send_budget_from_policy


def test_action_candidate_serializes_operator_decision_metadata():
    candidate = LeadGenActionCandidate(
        action_type="reply_to_inbound",
        contact_id="contact-1",
        pif_id="pif-1",
        firm_name="Example Law",
        contact_name="Nayeli",
        contact_email="nayeli@example.com",
        contact_title="COO",
        contact_source="pif_leadership",
        persona="active conversation",
        score=980,
        reason="Positive reply needs a thread response.",
        template_key="possible_minds_dynamic",
        source_type="inbound_email",
        source_id="inbound-1",
        sequence_id="seq-1",
        notification_id=12,
        priority_bucket="active_conversation",
        signals=["lead_email_reply", "positive_reply"],
        next_operator_action="open_operator_action_center_and_send_reply",
        score_breakdown={"persona:active": 980},
        selection_features={"email_quality": "direct_named_email"},
        selection_policy_version="contact-selection-v1",
    )

    payload = candidate.to_batch_reason(policy_version="lead-gen-v1")

    assert payload["action_type"] == "reply_to_inbound"
    assert payload["priority_bucket"] == "active_conversation"
    assert payload["notification_id"] == 12
    assert payload["next_operator_action"] == "open_operator_action_center_and_send_reply"
    assert payload["signals"] == ["lead_email_reply", "positive_reply"]
    assert payload["policy_version"] == "lead-gen-v1"
    assert payload["selection_policy_version"] == "contact-selection-v1"
    assert payload["score_breakdown"] == {"persona:active": 980}
    assert payload["selection_features"]["email_quality"] == "direct_named_email"


def test_reply_actions_are_continuations_but_not_batch_queueable():
    assert "reply_to_inbound" in CONTINUATION_ACTIONS
    assert "reply_to_inbound" not in QUEUEABLE_ACTIONS
    assert "first_touch" in QUEUEABLE_ACTIONS
    assert "follow_up" in QUEUEABLE_ACTIONS


def test_daily_send_budget_is_clamped_from_policy_weights():
    class Policy:
        weights_json = {"daily_send_budget": 500}

    assert daily_send_budget_from_policy(Policy()) == 200

    Policy.weights_json = {"daily_send_budget": 0}
    assert daily_send_budget_from_policy(Policy()) == 1

    Policy.weights_json = {}
    assert daily_send_budget_from_policy(Policy()) == 50
