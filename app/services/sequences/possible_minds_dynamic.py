"""Dynamic Possible Minds lead-gen strategy.

This template defines cadence/objectives only. The actual email is composed at
send time by the possible-minds-lead-email-composer skill.
"""
from __future__ import annotations

import os

from app.services.sequences.common import Ctx, RenderedStep


TEMPLATE_KEY = "possible_minds_dynamic"
LABEL = "Possible Minds dynamic composer"
DESCRIPTION = (
    "Skill-composed emails using firm context, prior sends/replies, consult "
    "learnings, optional blog links, and the required consult signature."
)

STEP_OBJECTIVES = {
    1: "Open with a relevant operational pain and a clear consult path.",
    2: "Bump without repeating the opener; reframe around evidence, a blog post, or a sharper operational angle.",
    3: "Close the loop with a low-pressure next step or ask for the right owner/referral.",
}

DEFAULT_STEPS_TOTAL = 3
DEFAULT_CADENCE_DAYS = [0, 3, 7]


def variant_for(*, pain_quote: str | None) -> str:
    return "dynamic"


def steps_total(variant: str) -> int:
    raw = (os.getenv("SEQUENCE_STEPS") or "").strip()
    if not raw:
        return DEFAULT_STEPS_TOTAL
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_STEPS_TOTAL


def _configured_cadence_days(total_steps: int) -> list[int]:
    raw = (os.getenv("SEQUENCE_CADENCE_DAYS") or "").strip()
    if raw:
        try:
            parsed = [int(part.strip()) for part in raw.split(",") if part.strip()]
            if parsed and parsed[0] == 0 and parsed == sorted(parsed):
                cadence = parsed
            else:
                cadence = DEFAULT_CADENCE_DAYS.copy()
        except ValueError:
            cadence = DEFAULT_CADENCE_DAYS.copy()
    else:
        cadence = DEFAULT_CADENCE_DAYS.copy()

    cadence = cadence[:total_steps]
    while len(cadence) < total_steps:
        cadence.append(cadence[-1] + 7 if cadence else 0)
    return cadence


def cadence_for(variant: str) -> list[int]:
    return _configured_cadence_days(steps_total(variant))


def objective_for(step_num: int) -> str:
    return STEP_OBJECTIVES.get(step_num, STEP_OBJECTIVES[3])


def render_step(step_num: int, variant: str, ctx: Ctx) -> RenderedStep:
    raise RuntimeError(
        "possible_minds_dynamic must be composed by lead_email_composer, "
        "not rendered from fixed copy"
    )
