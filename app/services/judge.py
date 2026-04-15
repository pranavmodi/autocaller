"""Post-call LLM reviewer.

One pass over each completed call's transcript produces:
  (a) Judge scores — call quality on 6 rubric dimensions (see Phase A of
      docs/SELF_IMPROVEMENT.md)
  (b) GTM disposition — one of 15 categories (see docs/DISPOSITIONS.md)
      plus follow-up action, owner, due date, signal flags, captured
      contacts, DNC reason, etc.

Default model: gpt-4o-mini. Cost ~$0.02-0.03 per call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("JUDGE_MODEL", "gpt-4o-mini")

# Full list of allowed disposition labels (keep in sync with docs/DISPOSITIONS.md)
DISPOSITIONS = [
    "meeting_booked",
    "hot_lead_no_booking",
    "warm_interest",
    "qualifying_signal_no_commitment",
    "not_now_try_later",
    "budget_cycle_gate",
    "wrong_target_path_captured",
    "dead_end_at_firm",
    "not_interested_polite",
    "competing_solution_satisfied",
    "do_not_recontact",
    "bad_data",
    "no_conversation",
    "technical_failure",
    "needs_human_review",
]

FOLLOW_UP_ACTIONS = [
    "confirm_demo",
    "call_back_next_day",
    "call_back_scheduled",
    "email_case_study",
    "add_to_nurture",
    "research_dm",
    "mark_dnc",
    "mark_bad_number",
    "discard",
    "human_review",
    "standard_retry",
]

FOLLOW_UP_OWNERS = ["autocaller", "sales_human", "none"]
DM_REACHABILITIES = ["reached", "path_captured", "path_unclear", "no_path"]


JUDGE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "call_review",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                # Judge dimensions
                "opening_quality": {"type": "integer", "minimum": 0, "maximum": 10},
                "discovery_quality": {"type": "integer", "minimum": 0, "maximum": 10},
                "tool_use_correctness": {"type": "integer", "minimum": 0, "maximum": 10},
                "objection_handling": {"type": "integer", "minimum": 0, "maximum": 10},
                "closing_quality": {"type": "integer", "minimum": 0, "maximum": 10},
                "overall": {"type": "integer", "minimum": 0, "maximum": 10},
                "missed_opportunities": {"type": "array", "items": {"type": "string"}},
                "ai_errors": {"type": "array", "items": {"type": "string"}},
                "recommended_prompt_edits": {"type": "array", "items": {"type": "string"}},

                # GTM disposition
                "gtm_disposition": {"type": "string", "enum": DISPOSITIONS},
                "follow_up_action": {"type": "string", "enum": FOLLOW_UP_ACTIONS},
                "follow_up_when": {
                    "type": ["string", "null"],
                    "description": "ISO-8601 timestamp of when to take the follow-up action, or null for terminal dispositions.",
                },
                "follow_up_owner": {"type": "string", "enum": FOLLOW_UP_OWNERS},
                "follow_up_note": {
                    "type": "string",
                    "description": "One or two sentences the human/agent should know before the next touch.",
                },
                "call_summary": {
                    "type": "string",
                    "description": "One-sentence summary of what actually happened on the call.",
                },
                "signal_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Free-form tags like 'hostile', 'friendly', 'busy', 'decisive', 'evasive', 'confused', 'authoritative'.",
                },
                "pain_points_discussed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Canonical pain categories surfaced, e.g. medical_records_retrieval, demand_letters, intake_volume, lien_processing.",
                },
                "objections_raised": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "objection": {"type": "string"},
                            "ai_response_quality": {"type": "integer", "minimum": 0, "maximum": 10},
                        },
                        "required": ["objection", "ai_response_quality"],
                    },
                },
                "captured_contacts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": ["string", "null"]},
                            "title": {"type": ["string", "null"]},
                            "email": {"type": ["string", "null"]},
                            "phone": {"type": ["string", "null"]},
                        },
                        "required": ["name", "title", "email", "phone"],
                    },
                },
                "dm_reachability": {"type": "string", "enum": DM_REACHABILITIES},
                "dnc_reason": {
                    "type": ["string", "null"],
                    "description": "Populated only when gtm_disposition='do_not_recontact'. Cite the transcript moment that triggered it.",
                },
            },
            "required": [
                "opening_quality", "discovery_quality", "tool_use_correctness",
                "objection_handling", "closing_quality", "overall",
                "missed_opportunities", "ai_errors", "recommended_prompt_edits",
                "gtm_disposition", "follow_up_action", "follow_up_when",
                "follow_up_owner", "follow_up_note", "call_summary",
                "signal_flags", "pain_points_discussed", "objections_raised",
                "captured_contacts", "dm_reachability", "dnc_reason",
            ],
        },
    },
}


SYSTEM_PROMPT = """You are a quality reviewer and GTM (go-to-market) analyst \
for an outbound cold-calling AI agent that targets US personal-injury law \
firms to book discovery meetings for Possible Minds (custom software + AI \
for PI firms).

Your job is to review one completed call and produce:
1. Judge scores on six dimensions (0-10 each).
2. A GTM disposition that tells a sales specialist EXACTLY what to do next.

The transcript may be in English OR Spanish (some leads are marked
language=es in the DB — the AI opened with "¿Bueno?" and ran the Spanish
prompt). Your ANALYSIS and all JSON fields MUST be in English regardless.
Judge both languages on equal terms — same rubric, same bar.

Be rigorous. Favor precision over generosity. Cite the transcript when \
recommending prompt edits or flagging DNC.

## Judge rubric
- opening_quality: permission-based, concise, honest; no dead-air; no lies.
- discovery_quality: asked ONE quantifying follow-up; didn't barrel into pitch.
- tool_use_correctness: right tool at right time; never promised a booking \
  that didn't actually succeed.
- objection_handling: sensible responses; never invented features/references.
- closing_quality: graceful exit on both yes and no; captured capture fields.
- overall: would you let this AI represent your company?

## GTM disposition (pick exactly one — see DISPOSITIONS.md style)
  meeting_booked, hot_lead_no_booking, warm_interest,
  qualifying_signal_no_commitment, not_now_try_later, budget_cycle_gate,
  wrong_target_path_captured, dead_end_at_firm, not_interested_polite,
  competing_solution_satisfied, do_not_recontact, bad_data, no_conversation,
  technical_failure, needs_human_review

## Follow-up rules
- meeting_booked → confirm_demo (owner: autocaller)
- hot_lead_no_booking → call_back_next_day (owner: autocaller)
- warm_interest → email_case_study + add_to_nurture (owner: sales_human for email)
- do_not_recontact → mark_dnc (owner: none), follow_up_when = null
- bad_data → mark_bad_number (owner: none), follow_up_when = null
- no_conversation / technical_failure → standard_retry
- needs_human_review → human_review

## Hard constraints
- If the lead asked to be removed, gtm_disposition MUST be do_not_recontact and dnc_reason must cite it.
- follow_up_when is null ONLY for terminal dispositions (do_not_recontact, bad_data, needs_human_review).
- captured_contacts: include ONLY people actually named on the call. Normalize phones to E.164, emails to lowercase. Never invent.
- Do not hallucinate pain points; if none were surfaced, return [].

Return ONLY the structured JSON — no prose."""


@dataclass
class CallReview:
    # Judge
    opening_quality: int
    discovery_quality: int
    tool_use_correctness: int
    objection_handling: int
    closing_quality: int
    overall: int
    missed_opportunities: list[str]
    ai_errors: list[str]
    recommended_prompt_edits: list[str]

    # GTM
    gtm_disposition: str
    follow_up_action: str
    follow_up_when: Optional[str]
    follow_up_owner: str
    follow_up_note: str
    call_summary: str
    signal_flags: list[str]
    pain_points_discussed: list[str]
    objections_raised: list[dict]
    captured_contacts: list[dict]
    dm_reachability: str
    dnc_reason: Optional[str]


def _compact_transcript(transcript: list[dict]) -> str:
    lines = []
    for t in transcript or []:
        speaker = t.get("speaker", "?")
        text = (t.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines) or "(no transcript)"


async def review_call(
    call_row,  # CallLogRow
    *,
    client: Optional[AsyncOpenAI] = None,
    model: str = DEFAULT_MODEL,
) -> CallReview:
    """Run the reviewer on a single call_log row. Returns structured result."""
    cli = client or AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    payload = {
        "lead": {
            "name": call_row.patient_name,
            "firm_name": call_row.firm_name,
            "state": call_row.lead_state,
            "phone": call_row.phone,
        },
        "call": {
            "started_at": call_row.started_at.isoformat() if call_row.started_at else None,
            "ended_at": call_row.ended_at.isoformat() if call_row.ended_at else None,
            "duration_seconds": call_row.duration_seconds,
            "outcome_declared_by_ai": call_row.outcome,
            "call_status": call_row.call_status,
            "call_disposition": call_row.call_disposition,
            "was_gatekeeper": call_row.was_gatekeeper,
            "is_decision_maker_declared": call_row.is_decision_maker,
            "mock_mode": call_row.mock_mode,
            "error_code": call_row.error_code,
            "error_message": call_row.error_message,
        },
        "transcript": _compact_transcript(call_row.transcript or []),
        "system_prompt_used": (call_row.prompt_text or "")[:4000],
    }

    resp = await cli.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format=JUDGE_SCHEMA,
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)

    return CallReview(
        opening_quality=int(data["opening_quality"]),
        discovery_quality=int(data["discovery_quality"]),
        tool_use_correctness=int(data["tool_use_correctness"]),
        objection_handling=int(data["objection_handling"]),
        closing_quality=int(data["closing_quality"]),
        overall=int(data["overall"]),
        missed_opportunities=list(data["missed_opportunities"] or []),
        ai_errors=list(data["ai_errors"] or []),
        recommended_prompt_edits=list(data["recommended_prompt_edits"] or []),
        gtm_disposition=str(data["gtm_disposition"]),
        follow_up_action=str(data["follow_up_action"]),
        follow_up_when=data.get("follow_up_when"),
        follow_up_owner=str(data["follow_up_owner"]),
        follow_up_note=str(data["follow_up_note"] or ""),
        call_summary=str(data["call_summary"] or ""),
        signal_flags=list(data.get("signal_flags") or []),
        pain_points_discussed=list(data.get("pain_points_discussed") or []),
        objections_raised=list(data.get("objections_raised") or []),
        captured_contacts=list(data.get("captured_contacts") or []),
        dm_reachability=str(data["dm_reachability"]),
        dnc_reason=data.get("dnc_reason"),
    )


async def persist_review(call_id: str, review: CallReview) -> None:
    """Write a review to call_logs."""
    from sqlalchemy import update
    from app.db import AsyncSessionLocal
    from app.db.models import CallLogRow

    follow_up_when = None
    if review.follow_up_when:
        try:
            follow_up_when = datetime.fromisoformat(review.follow_up_when)
        except ValueError:
            logger.warning("Bad follow_up_when from judge: %r", review.follow_up_when)

    scores = {
        "opening_quality": review.opening_quality,
        "discovery_quality": review.discovery_quality,
        "tool_use_correctness": review.tool_use_correctness,
        "objection_handling": review.objection_handling,
        "closing_quality": review.closing_quality,
        "overall": review.overall,
    }
    notes = {
        "missed_opportunities": review.missed_opportunities,
        "ai_errors": review.ai_errors,
        "recommended_prompt_edits": review.recommended_prompt_edits,
    }

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(CallLogRow).where(CallLogRow.call_id == call_id).values(
                judge_score=review.overall,
                judge_scores=scores,
                judge_notes=notes,
                judged_at=datetime.now(timezone.utc),
                gtm_disposition=review.gtm_disposition,
                follow_up_action=review.follow_up_action,
                follow_up_when=follow_up_when,
                follow_up_owner=review.follow_up_owner,
                follow_up_note=review.follow_up_note or None,
                call_summary=review.call_summary or None,
                signal_flags=review.signal_flags,
                pain_points_discussed=review.pain_points_discussed,
                objections_raised=review.objections_raised,
                captured_contacts=review.captured_contacts,
                dm_reachability=review.dm_reachability,
                dnc_reason=review.dnc_reason,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def _pick_pending(limit: int = 5):
    from sqlalchemy import select
    from app.db import AsyncSessionLocal
    from app.db.models import CallLogRow

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow)
            .where(CallLogRow.ended_at.is_not(None))
            .where(CallLogRow.judged_at.is_(None))
            .order_by(CallLogRow.ended_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def judge_loop(interval_seconds: int = 60):
    """Background task: every N seconds, pick unjudged calls and score them."""
    logger.info("Judge loop started (interval=%ds)", interval_seconds)
    client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    while True:
        try:
            rows = await _pick_pending(limit=5)
            for row in rows:
                try:
                    review = await review_call(row, client=client)
                    await persist_review(row.call_id, review)
                    logger.info("Judged call %s: overall=%s disposition=%s",
                                row.call_id[:10], review.overall, review.gtm_disposition)
                except Exception as e:
                    logger.warning("Judge failed on %s: %s", row.call_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Judge loop tick failed: %s", e)
        await asyncio.sleep(interval_seconds)
