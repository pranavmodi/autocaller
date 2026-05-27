from app.services.lead_feedback_classifier import validate_classification
from datetime import datetime, timezone

from app.services.lead_gen_cybernetic import (
    _default_weights,
    parse_scheduled_start_at,
    staggered_due_at,
)
from app.services.llm_gateway import extract_json, require_fields


def test_gateway_extracts_json_from_fenced_response():
    parsed = extract_json('```json\n{"outcome": "positive_reply", "confidence": 90}\n```')

    assert parsed["outcome"] == "positive_reply"
    assert parsed["confidence"] == 90


def test_gateway_required_field_validation():
    require_fields({"a": 1, "b": 2}, ["a", "b"])


def test_feedback_classification_validation_clamps_and_sanitizes():
    result = validate_classification({
        "outcome": "made_up",
        "confidence": 500,
        "next_action": "no_action",
        "reasoning": "ambiguous",
        "signals": ["x", ""],
        "requires_human_review": True,
    })

    assert result.outcome == "needs_human_review"
    assert result.confidence == 100
    assert result.next_action == "no_action"
    assert result.signals == ["x"]
    assert result.requires_human_review


def test_default_policy_targets_booked_qualified_conversations():
    weights = _default_weights()

    assert weights["target_metric"] == "booked_qualified_conversations"
    assert weights["persona"]["founder_owner"] > weights["persona"]["partner"]


def test_staggered_due_at_spreads_batch_across_window():
    start = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)

    first = staggered_due_at(start_at=start, index=0, total=50, window_minutes=60)
    middle = staggered_due_at(start_at=start, index=24, total=50, window_minutes=60)
    last = staggered_due_at(start_at=start, index=49, total=50, window_minutes=60)

    assert first == start
    assert 29 * 60 < (middle - start).total_seconds() < 30 * 60
    assert (last - start).total_seconds() == 60 * 60


def test_parse_scheduled_start_at_interprets_naive_time_as_california():
    parsed = parse_scheduled_start_at(
        "2026-05-27T09:30",
        "America/Los_Angeles",
    )

    assert parsed.isoformat() == "2026-05-27T16:30:00+00:00"
