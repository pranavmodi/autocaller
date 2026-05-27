"""3-step records workflow audit sequence for warm Precise-related PI firms."""
from __future__ import annotations

from app.services.sequences.common import Ctx, RenderedStep


TEMPLATE_KEY = "precise_records_audit"
LABEL = "Precise records audit"
DESCRIPTION = (
    "Records-only v1 sequence for founder/COO contacts at PI firms with a "
    "Precise relationship signal. Goal: book a qualified records workflow audit."
)

CADENCE_DAYS = [0, 5, 12]
VARIANT = "records_only"

CONSULT_LINK = "getpossibleminds.com/consult"
WEBSITE_LINK = "getpossibleminds.com"
REP_TITLE = "Founder, Possible Minds"


def _signature(rep_name: str) -> str:
    return (
        f"-- {rep_name}\n"
        f"{REP_TITLE}\n"
        f"{WEBSITE_LINK}\n"
    )


def _step_1(ctx: Ctx) -> RenderedStep:
    body = (
        f"Hi {ctx.first_name},\n\n"
        f"{ctx.rep_name} from Possible Minds. We're the team behind the "
        f"automated email replies and imaging-status updates your team may "
        f"have seen from Precise Imaging.\n\n"
        f"I'm reaching out to PI firms with a Precise connection to "
        f"understand where records requests, imaging updates, missing docs, "
        f"and follow-up loops still eat staff time.\n\n"
        f"Would it be worth a 20-minute records workflow audit for "
        f"{ctx.firm_name}, or is there someone else on your team who owns "
        f"that process?\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject="Precise Imaging -- quick records question",
        body=body,
        message_type="records_audit_step_1",
    )


def _step_2(ctx: Ctx) -> RenderedStep:
    body = (
        f"Hi {ctx.first_name} -- circling back.\n\n"
        f"The pattern I'm trying to understand is not a broad AI project. "
        f"It's the practical records loop: request goes out, status changes, "
        f"someone asks for an update, a document is missing, and staff have "
        f"to reconstruct context from email, case notes, and vendor portals.\n\n"
        f"We've seen that same shape on the medical-provider side with "
        f"Precise. The useful question for a PI firm is whether the records "
        f"workflow has enough repeatable signal to automate the follow-up "
        f"without losing human control.\n\n"
        f"Open to a short audit of that workflow for {ctx.firm_name}? If it "
        f"doesn't fit, we'll say so quickly.\n\n"
        f"{CONSULT_LINK}\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject="the records loop I mean",
        body=body,
        message_type="records_audit_step_2",
    )


def _step_3(ctx: Ctx) -> RenderedStep:
    body = (
        f"{ctx.first_name},\n\n"
        f"Last note from me. I don't want to keep landing in your inbox if "
        f"records follow-up is not a current bottleneck.\n\n"
        f"If it is, the audit is simple: map the records request/update loop, "
        f"identify where staff are re-checking the same context, and decide "
        f"whether one automation is worth testing.\n\n"
        f"Useful for {ctx.firm_name}, or should I close the loop here?\n\n"
        f"{CONSULT_LINK}\n\n"
        + _signature(ctx.rep_name)
    )
    return RenderedStep(
        subject="close the loop?",
        body=body,
        message_type="records_audit_step_3",
    )


def render_step(step_num: int, variant: str, ctx: Ctx) -> RenderedStep:
    if variant != VARIANT:
        raise ValueError(f"invalid variant for {TEMPLATE_KEY}: {variant!r}")
    if step_num == 1:
        return _step_1(ctx)
    if step_num == 2:
        return _step_2(ctx)
    if step_num == 3:
        return _step_3(ctx)
    raise ValueError(f"invalid step {step_num} for {TEMPLATE_KEY}")


def cadence_for(variant: str) -> list[int]:
    if variant != VARIANT:
        raise ValueError(f"invalid variant for {TEMPLATE_KEY}: {variant!r}")
    return CADENCE_DAYS


def steps_total(variant: str) -> int:
    return len(cadence_for(variant))


def variant_for(*, pain_quote: str | None = None) -> str:
    return VARIANT
