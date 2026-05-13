"""4-step email sequence: Precise opener → Yelp pain quote → 100hr/wk
proof → break-up. Mirrors the cold-call script's tone — peer voice,
permission before pitch, the 100hr figure as proof not headline.

Two variants share three of four steps:
  - `with_quote`     — uses the Yelp `client_communication` quote in step 2
  - `without_quote`  — drops step 2 entirely, runs as a 3-touch sequence
                       (cadence shifts: day 0, day 7, day 14)

Each step is a pure function of `Ctx` → `RenderedStep`. No DB
access, no I/O — that's the scheduler's job. Keeps the renderer
unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


TEMPLATE_KEY = "precise_pain_4step"

CADENCE_DAYS_WITH_QUOTE = [0, 4, 10, 17]      # 4 sends
CADENCE_DAYS_WITHOUT_QUOTE = [0, 7, 14]       # 3 sends, step 2 dropped
# Default for callers that don't yet know the variant — the scheduler
# overrides per-row from `email_sequences.variant`.
CADENCE_DAYS = CADENCE_DAYS_WITH_QUOTE


CONSULT_LINK = "getpossibleminds.com/consult"
WEBSITE_LINK = "getpossibleminds.com"
REP_TITLE = "Founder, Possible Minds"


def _signature(rep_name: str) -> str:
    """The signature block appended to every step. Keeps the rep's
    role + the two outbound links (website, free-consult) consistent
    across all four emails. Even step 1 — where the body itself
    intentionally avoids any pitch or CTA — surfaces the consult link
    here so it's available without being pushed."""
    return (
        f"— {rep_name}\n"
        f"{REP_TITLE}\n"
        f"{WEBSITE_LINK}\n"
        f"Free 30-min consult: {CONSULT_LINK}\n"
    )


@dataclass
class Ctx:
    """All the personalization a template ever sees. Fields that the
    renderer treats as optional (reviewer_name, review_date) can be
    None — the renderer adapts copy."""
    first_name: str
    firm_name: str
    rep_name: str
    pain_quote: Optional[str] = None
    reviewer_name: Optional[str] = None
    review_date: Optional[str] = None       # YYYY-MM-DD or human-readable, opaque to us


@dataclass
class RenderedStep:
    subject: str
    body: str
    message_type: str        # 'sequence_step_1' .. 'sequence_step_4'


# ---------------------------------------------------------------------------
# step renderers
# ---------------------------------------------------------------------------

def _step_1(ctx: Ctx) -> RenderedStep:
    body = (
        f"Hi {ctx.first_name},\n\n"
        f"{ctx.rep_name} from Possible Minds. We're the team behind the "
        f"automated email replies your firm's probably seen from Precise "
        f"Imaging — the status updates on imaging requests come from a "
        f"system we built for them.\n\n"
        f"I've been talking to PI firms that work with Precise, mostly to "
        f"learn what eats the most staff time on the intake and records "
        f"side.\n\n"
        f"Mind if I ask a few questions about how that runs at "
        f"{ctx.firm_name}? Genuinely just listening — not a pitch.\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject="Precise Imaging — quick check",
        body=body,
        message_type="sequence_step_1",
    )


def _step_2_with_quote(ctx: Ctx) -> RenderedStep:
    if not ctx.pain_quote:
        # Defensive: scheduler shouldn't dispatch step 2 without a
        # quote — the variant should be 'without_quote'. But never
        # fabricate; if we ever land here, fail loud.
        raise ValueError(
            "step_2_with_quote called with no pain_quote — variant mismatch."
        )

    if ctx.reviewer_name and ctx.review_date:
        attribution = f"{ctx.reviewer_name} wrote ({ctx.review_date}):"
        subject_who = ctx.reviewer_name
    elif ctx.reviewer_name:
        attribution = f"{ctx.reviewer_name} wrote:"
        subject_who = ctx.reviewer_name
    else:
        attribution = "A recent reviewer wrote:"
        subject_who = "a Yelp reviewer"

    body = (
        f"Hi {ctx.first_name} — circling back.\n\n"
        f"I went through {ctx.firm_name}'s Yelp recently. {attribution}\n\n"
        f"> \"{ctx.pain_quote}\"\n\n"
        f"The \"client called multiple times, never got an update\" pattern "
        f"is one of the most common things we hear from PI firms. It's also "
        f"one of the most fixable — it usually traces back to a case-manager "
        f"queue that no one's quite owning, not anyone being lazy.\n\n"
        f"The system we built for Precise reads each attorney-office email, "
        f"pulls the answer from their case management software, and replies "
        f"the same day. The PI-side equivalent — keeping clients informed "
        f"without your team spending the time — is the same shape of "
        f"problem.\n\n"
        f"If it's worth a 20-minute conversation, here's the link: "
        f"{CONSULT_LINK}. No pitch, just a real look at whether there's "
        f"something here.\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject=f"Saw {subject_who}'s review of {ctx.firm_name}",
        body=body,
        message_type="sequence_step_2",
    )


def _step_3(ctx: Ctx) -> RenderedStep:
    body = (
        f"{ctx.first_name},\n\n"
        f"One concrete data point, in case the Precise context is useful:\n\n"
        f"Precise's intake team was spending ~100 hours/week on email "
        f"triage — attorney offices asking for imaging status, scheduling, "
        f"results. We built a system that reads each email, pulls the "
        f"answer from their case management system, and replies. They "
        f"reviewed every reply for two weeks, then handed it the keys.\n\n"
        f"100 hours back. Same response quality. No headcount change.\n\n"
        f"The PI-side analog is \"client called for an update — here's the "
        f"status, sent.\" Same shape, different system, our team builds it "
        f"bespoke for each firm.\n\n"
        f"Two weeks of build, a 30-minute scoping call to see if it fits: "
        f"{CONSULT_LINK}.\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject="100 hours a week — what it actually looks like",
        body=body,
        message_type="sequence_step_3",
    )


def _step_4(ctx: Ctx) -> RenderedStep:
    body = (
        f"{ctx.first_name},\n\n"
        f"Last note from me — I don't want to keep landing in your inbox "
        f"uninvited.\n\n"
        f"If client communication or the records side is on your radar to "
        f"fix this year, the link's still there: {CONSULT_LINK}. If it's "
        f"not, no worries — I'll close the file and stop emailing.\n\n"
        f"Thanks for the time spent reading any of these.\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject="Closing the loop",
        body=body,
        message_type="sequence_step_4",
    )


# ---------------------------------------------------------------------------
# public dispatch
# ---------------------------------------------------------------------------

def render_step(step_num: int, variant: str, ctx: Ctx) -> RenderedStep:
    """Render the Nth step of the named variant. `step_num` is 1-indexed.

    `variant`:
      - 'with_quote'    → 4 steps: 1, 2, 3, 4
      - 'without_quote' → 3 steps: 1, 3, 4 (presented to the world as steps 1, 2, 3)

    The scheduler always passes `step_num` matching the operator-visible
    numbering (1..N), so the mapping happens here once.
    """
    if variant == "with_quote":
        if step_num == 1:
            return _step_1(ctx)
        if step_num == 2:
            return _step_2_with_quote(ctx)
        if step_num == 3:
            return _step_3(ctx)
        if step_num == 4:
            return _step_4(ctx)
    elif variant == "without_quote":
        if step_num == 1:
            return _step_1(ctx)
        if step_num == 2:
            return _step_3(ctx)
        if step_num == 3:
            return _step_4(ctx)
    raise ValueError(
        f"render_step: invalid step {step_num} for variant {variant!r}"
    )


def cadence_for(variant: str) -> list[int]:
    return (
        CADENCE_DAYS_WITH_QUOTE
        if variant == "with_quote"
        else CADENCE_DAYS_WITHOUT_QUOTE
    )


def steps_total(variant: str) -> int:
    return len(cadence_for(variant))
