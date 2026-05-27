"""Classify lead-generation feedback into structured outcomes."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.llm_gateway import call_skill_json


DEFAULT_SKILL_PATH = (
    Path(__file__).resolve().parents[2]
    / ".claude/skills/lead-feedback-classifier/SKILL.md"
)
SKILL_PATH = Path(os.getenv("LEAD_FEEDBACK_SKILL_PATH", str(DEFAULT_SKILL_PATH)))
MODEL = os.getenv("LEAD_FEEDBACK_MODEL", "openclaw")

OUTCOMES = {
    "booked_qualified_conversation",
    "positive_reply",
    "referral",
    "wrong_person",
    "not_interested",
    "do_not_contact",
    "bounce",
    "opened_or_clicked",
    "neutral",
    "needs_human_review",
}

NEXT_ACTIONS = {
    "confirm_booking",
    "human_reply",
    "ask_for_referral_contact",
    "find_better_contact",
    "continue_sequence",
    "pause_sequence",
    "mark_do_not_contact",
    "suppress_email",
    "no_action",
    "needs_human_review",
}


@dataclass
class FeedbackClassification:
    outcome: str
    confidence: int
    next_action: str
    reasoning: str
    signals: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    model: str = MODEL
    raw_response: str = ""


def _clamp_confidence(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(parsed, 100))


def validate_classification(parsed: dict[str, Any]) -> FeedbackClassification:
    outcome = str(parsed.get("outcome") or "needs_human_review")
    next_action = str(parsed.get("next_action") or "needs_human_review")
    if outcome not in OUTCOMES:
        outcome = "needs_human_review"
    if next_action not in NEXT_ACTIONS:
        next_action = "needs_human_review"
    signals_raw = parsed.get("signals") or []
    signals = [str(s) for s in signals_raw if str(s).strip()] if isinstance(signals_raw, list) else []
    return FeedbackClassification(
        outcome=outcome,
        confidence=_clamp_confidence(parsed.get("confidence")),
        next_action=next_action,
        reasoning=str(parsed.get("reasoning") or ""),
        signals=signals[:12],
        requires_human_review=bool(parsed.get("requires_human_review")),
    )


async def classify_feedback_event(
    *,
    event_type: str,
    raw_event: dict[str, Any],
    contact: dict[str, Any] | None = None,
    firm: dict[str, Any] | None = None,
    sequence: dict[str, Any] | None = None,
    target_metric: str = "booked_qualified_conversations",
    model: str | None = None,
) -> FeedbackClassification:
    payload = {
        "event_type": event_type,
        "raw_event": raw_event,
        "contact": contact or {},
        "firm": firm or {},
        "sequence": sequence or {},
        "target_metric": target_metric,
    }
    result = await call_skill_json(
        skill_path=SKILL_PATH,
        payload=payload,
        required_fields=[
            "outcome",
            "confidence",
            "next_action",
            "reasoning",
            "signals",
            "requires_human_review",
        ],
        model=model or MODEL,
        max_tokens=int(os.getenv("LEAD_FEEDBACK_MAX_TOKENS", "1200")),
    )
    classified = validate_classification(result.parsed)
    classified.model = result.model
    classified.raw_response = result.raw_response
    return classified
