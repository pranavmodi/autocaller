"""Attorney cold-call system prompt.

The prompt is discovery-first: the AI opens with a permission-based greeting,
uncovers the biggest operational pain at the firm, and — if there's fit —
books a demo via Cal.com. It is deliberately product-agnostic because the
calling company solves attorney pain with custom software/AI and the specific
offer depends on what pain the firm surfaces.

`render_system_prompt()` fills in the lead-specific and operator-specific
slots; the rendered string is sent as `session.update.instructions` to
OpenAI Realtime at connect time.
"""
from __future__ import annotations

from typing import Optional

from app.models import Patient  # Patient is aliased as Lead in models/patient.py


SYSTEM_PROMPT_TEMPLATE = """\
You are {rep_name}, a consultant from {rep_company}. You are cold-calling \
{lead_name}{title_clause} at {firm_name_clause}{state_clause}.

## Your goal
Have a short, respectful discovery conversation. Uncover the firm's biggest \
operational bottleneck. If there is a real fit, book a 20-minute intro demo \
via the scheduling tool. If not, end the call gracefully.

## Opening — say this verbatim
"Hi, is this {lead_first_name}? This is {rep_name} from {rep_company}. I \
know I'm catching you out of the blue — do you have thirty seconds for me \
to tell you why I called?"

## If they say yes (or don't hang up)
Pitch in one sentence: "We build custom software and AI tools for personal \
injury firms — things like automated case intake, medical-record retrieval, \
demand letter drafting, lien processing, and client communication. I'd \
rather not pitch blindly — what's the single most painful or repetitive \
workflow in your practice right now?"

## Discovery — listen for pain signals in these areas
- Case intake and lead conversion (missed calls, slow follow-up, low conversion rate)
- Medical records retrieval (delays, cost, manual faxing, provider friction)
- Lien processing and negotiation (time sink, manual spreadsheets, errors)
- Demand letter generation (days per letter, template drift, paralegal time)
- Docketing and deadlines (missed deadlines, manual calendaring)
- Client communication (repeat status calls, update requests)
- Billing, time tracking, trust accounting
- Hiring, training, paralegal throughput

Ask ONE quantifying follow-up: "Roughly how many hours a week does that eat?" \
or "What's that costing the firm — missed cases, overtime, both?" You are \
not trying to close. You are trying to learn and qualify.

## When you have a real pain + decision-maker
Propose the demo: "That's exactly the kind of thing we've built tooling for. \
Can I grab 20 minutes with you this week? I'll walk you through how we'd \
tackle {{their pain area}} specifically." Then call `check_availability` \
with the lead's timezone and read back the top two or three slots. Once \
they pick, confirm the email on file and call `book_demo`. Read back the \
confirmed time after the tool returns.

## If you reach a gatekeeper (receptionist, paralegal, not the attorney)
Be warm. Ask who handles operational decisions and the best way to reach \
them — name, direct line, or email. Call `mark_gatekeeper` with whatever \
you got. End politely: "Thanks — I'll reach out directly." Then call \
`end_call` with outcome `gatekeeper_only`.

## If they're not interested or the timing is bad
Ask permission to send a one-pager. If yes, call `send_followup_email`. \
Thank them, call `end_call` with outcome `not_interested` (or `callback_requested` \
with a `callback_requested_at` if they asked for a specific time).

## If you hit voicemail or an answering machine
Do NOT leave a message. Silently call `end_call` with outcome `voicemail`.

## If you reached the wrong person
Apologize briefly: "Sorry, I was looking for {lead_name}. I'll update our \
records." Call `end_call` with outcome `wrong_number`.

## Hard rules
- Never lie. Never claim prior contact, prior emails, or a mutual connection \
  you don't have.
- If asked to be removed from the list: acknowledge, confirm, call `end_call` \
  with `not_interested` and `is_decision_maker=false` only if that's true.
- Keep turns under 2 sentences unless asked for detail. Let them talk.
- Do NOT give legal advice. Do NOT discuss specific cases or confidential \
  matters. Refer those questions to an attorney.
- Respect if they say they're busy — pivot to callback or follow-up email.

## Tone
- Conversational, low-pressure, curious.
- You are a human consultant having a peer conversation, not a pitch machine.
- Humor and warmth where natural; never saccharine.
- Short sentences. Allow pauses. Never interrupt.

## Product context from the operator
{product_context}
"""


def _default_timezone_for_state(state: Optional[str]) -> str:
    """Rough state-to-timezone map for the AI's scheduling prompts.

    Only the most common mappings — for edge cases (AZ no DST, IN split,
    etc.) we accept slight fuzziness; the operator can override via
    CALCOM_DEFAULT_TIMEZONE.
    """
    if not state:
        return "America/New_York"
    s = state.strip().upper()
    eastern = {"CT", "DC", "DE", "FL", "GA", "MA", "MD", "ME", "MI", "NC", "NH",
               "NJ", "NY", "OH", "PA", "RI", "SC", "VA", "VT", "WV", "IN", "KY"}
    central = {"AL", "AR", "IA", "IL", "KS", "LA", "MN", "MO", "MS", "ND", "NE",
               "OK", "SD", "TN", "TX", "WI"}
    mountain = {"AZ", "CO", "ID", "MT", "NM", "UT", "WY"}
    pacific = {"CA", "NV", "OR", "WA"}
    alaska = {"AK"}
    hawaii = {"HI"}
    if s in eastern:
        return "America/New_York"
    if s in central:
        return "America/Chicago"
    if s in mountain:
        return "America/Denver"
    if s in pacific:
        return "America/Los_Angeles"
    if s in alaska:
        return "America/Anchorage"
    if s in hawaii:
        return "Pacific/Honolulu"
    return "America/New_York"


def render_system_prompt(
    lead: Patient,
    *,
    rep_name: str,
    rep_company: str,
    product_context: str = "",
) -> str:
    """Fill in the template with lead + operator context.

    Caller must supply rep_name / rep_company. product_context is optional
    free-form text pulled from SystemSettings.sales_context.
    """
    lead_name = (lead.name or "").strip() or "there"
    lead_first_name = lead_name.split()[0] if lead_name else "there"
    title_clause = f", {lead.title}" if lead.title else ""
    firm_name_clause = lead.firm_name or "your firm"
    state_clause = f" in {lead.state}" if lead.state else ""

    return SYSTEM_PROMPT_TEMPLATE.format(
        rep_name=rep_name or "a consultant",
        rep_company=rep_company or "our firm",
        lead_name=lead_name,
        lead_first_name=lead_first_name,
        title_clause=title_clause,
        firm_name_clause=firm_name_clause,
        state_clause=state_clause,
        product_context=(product_context or "").strip() or "(none provided)",
    )


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI Realtime function definitions)
# ---------------------------------------------------------------------------
#
# These are passed as `session.tools` in session.update. The realtime service
# receives a `response.function_call_arguments.done` event and dispatches to
# the call orchestrator, which handles each of these.

TOOLS: list[dict] = [
    {
        "type": "function",
        "name": "check_availability",
        "description": (
            "Fetch upcoming demo slots from the scheduling calendar. Call this "
            "after the lead has agreed to book a demo. Returns up to 5 slot "
            "options in the lead's local timezone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Search window, in days from now. Default 7.",
                    "default": 7,
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "book_demo",
        "description": (
            "Book a demo slot on the calendar for the lead. The lead must have "
            "agreed on a specific slot (from check_availability) and provided "
            "or confirmed their email. After a successful booking, confirm the "
            "time to the lead and then call end_call with outcome='demo_scheduled'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_iso": {
                    "type": "string",
                    "description": "ISO 8601 start time of the chosen slot (from check_availability).",
                },
                "invitee_email": {
                    "type": "string",
                    "description": "Lead's email address for the calendar invite.",
                },
                "pain_point_summary": {
                    "type": "string",
                    "description": (
                        "One-sentence summary of the biggest pain the lead "
                        "surfaced — used as booking metadata and post-call notes."
                    ),
                },
            },
            "required": ["slot_iso", "invitee_email", "pain_point_summary"],
        },
    },
    {
        "type": "function",
        "name": "mark_gatekeeper",
        "description": (
            "Record that the person on the line is a gatekeeper, not the "
            "decision maker. Capture any contact info they gave for the right "
            "person. Does NOT end the call — call end_call separately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "best_contact_name": {"type": "string"},
                "best_contact_email": {"type": "string"},
                "best_contact_phone": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "send_followup_email",
        "description": (
            "Send a short follow-up email with a one-pager to the lead. Use "
            "when they're not ready to book today but willing to read a "
            "summary. Requires a valid email address."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "invitee_email": {
                    "type": "string",
                    "description": "Lead's email address.",
                },
                "message_type": {
                    "type": "string",
                    "enum": ["one_pager", "case_study", "custom"],
                    "default": "one_pager",
                },
                "custom_note": {
                    "type": "string",
                    "description": "Optional 1-2 sentence note tailored to their pain.",
                },
            },
            "required": ["invitee_email"],
        },
    },
    {
        "type": "function",
        "name": "end_call",
        "description": (
            "End the call and record the outcome. Always speak a brief "
            "sign-off BEFORE calling this tool — it disconnects immediately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": [
                        "demo_scheduled",
                        "not_interested",
                        "gatekeeper_only",
                        "callback_requested",
                        "voicemail",
                        "wrong_number",
                        "completed",
                    ],
                },
                "pain_point_summary": {"type": "string"},
                "interest_level": {
                    "type": "integer",
                    "description": "1-5, where 1=not at all, 5=very interested.",
                    "minimum": 1,
                    "maximum": 5,
                },
                "is_decision_maker": {"type": "boolean"},
                "callback_requested_at": {
                    "type": "string",
                    "description": "Free-form time the lead requested (e.g. 'tomorrow 3pm PT').",
                },
            },
            "required": ["outcome"],
        },
    },
]
