"""Dynamic Possible Minds lead-gen strategy.

This template defines cadence/objectives only. The actual email is composed at
send time by the possible-minds-lead-email-composer skill.
"""
from __future__ import annotations

from app.services.sequences.common import Ctx, RenderedStep


TEMPLATE_KEY = "possible_minds_dynamic"
LABEL = "Possible Minds dynamic composer"
DESCRIPTION = (
    "Skill-composed emails using firm context, prior sends/replies, consult "
    "learnings, optional blog links, and the required consult signature."
)

STEP_OBJECTIVES = {
    1: "Open a relevant operational conversation based on the best inferred pain.",
    2: "Follow up without repeating the first email; reframe around evidence or a blog post.",
    3: "Try a different operational angle or ask for the right owner/referral.",
    4: "Close the loop respectfully and leave a clear consult path.",
}


def variant_for(*, pain_quote: str | None) -> str:
    return "dynamic"


def steps_total(variant: str) -> int:
    return 4


def cadence_for(variant: str) -> list[int]:
    return [0, 3, 7, 14]


def objective_for(step_num: int) -> str:
    return STEP_OBJECTIVES.get(step_num, STEP_OBJECTIVES[4])


def render_step(step_num: int, variant: str, ctx: Ctx) -> RenderedStep:
    raise RuntimeError(
        "possible_minds_dynamic must be composed by lead_email_composer, "
        "not rendered from fixed copy"
    )

