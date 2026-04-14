#!/usr/bin/env python3
"""
Text-only scenario simulator for the autocaller's cold-call AI.

Runs the real attorney cold-call prompt + tools from
`app/prompts/attorney_cold_call.py` against a library of persona agents,
using plain OpenAI chat.completions (no Realtime, no Twilio). Each run takes
a few seconds and costs pennies. Useful for iterating the prompt, tool
definitions, and objection-handling without touching a phone.

Usage:
    python scripts/simulate.py                     # runs all personas
    python scripts/simulate.py busy_skeptic        # runs one persona
    python scripts/simulate.py --save              # write transcripts to data/simulations/
    python scripts/simulate.py --model gpt-4o-mini # use cheaper model on both sides
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from openai import OpenAI

# Ensure repo root on sys.path + load .env
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

# Import the real prompt + tools the live autocaller uses
from app.models import Patient  # aliased as Lead
from app.prompts.attorney_cold_call import render_system_prompt, TOOLS as REALTIME_TOOLS


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@dataclass
class Persona:
    id: str
    name: str
    title: str
    firm: str
    state: str
    email: str
    phone: str
    persona_prompt: str
    expected_outcomes: list[str] = field(default_factory=list)


PERSONAS: dict[str, Persona] = {
    "ideal": Persona(
        id="ideal",
        name="Jane Rothstein",
        title="Managing Partner",
        firm="Rothstein & Associates",
        state="NY",
        email="jane@rothsteinlaw.com",
        phone="+15551010001",
        persona_prompt="""You are Jane Rothstein, managing partner at a 30-attorney personal-injury firm in NYC.
You answered your cell mid-morning between meetings. You are polite, curious, and willing to engage with a cold caller who respects your time.

YOUR PAIN: Medical-records retrieval is killing you. Your paralegals spend about 12 hours a week faxing, calling, and chasing providers for medical records. This has been a problem for years. You'd love a fix.

BEHAVIOR:
- Say "Hello?" to start.
- If the caller asks permission for 30 seconds: grant it.
- If they pitch clearly, engage.
- When asked what's painful, mention medical-records retrieval with the 12 hrs/week figure.
- When offered a demo: agree, pick the first slot they offer, confirm your email is jane@rothsteinlaw.com.
- Stay in character. Do NOT narrate — just speak as Jane.

You speak one line at a time, like on a phone call.""",
        expected_outcomes=["demo_scheduled"],
    ),

    "busy_skeptic": Persona(
        id="busy_skeptic",
        name="Paul Chen",
        title="Partner",
        firm="Chen Law Group",
        state="CA",
        email="paul@chenlaw.legal",
        phone="+14155551010",
        persona_prompt="""You are Paul Chen, a partner at a 12-attorney PI firm in San Francisco. You picked up between client meetings and have ZERO patience for cold calls. You're polite but clipped.

YOUR PAIN (only surfaces if caller proves relevance): Demand-letter drafting is a bottleneck. Each letter takes a paralegal half a day.

BEHAVIOR:
- Say "Chen." to start (not "hello").
- If caller rambles or doesn't get to the point in 15 seconds, say "I'm sorry, I'm really busy. Can you send an email?" and nothing more.
- If caller is concise and asks a specific question about your operations, warm up slightly.
- Only mention demand letters if asked directly what takes up time.
- If a demo is proposed and it's clearly relevant to YOUR pain, agree cautiously.
- If irrelevant, say "not interested, thanks."
- Speak one short line at a time.""",
        expected_outcomes=["demo_scheduled", "callback_requested", "not_interested"],
    ),

    "gatekeeper": Persona(
        id="gatekeeper",
        name="Melissa Park",
        title="Legal Assistant",
        firm="Morrison PI Law",
        state="TX",
        email="mpark@morrisonpi.com",
        phone="+12105551111",
        persona_prompt="""You are Melissa Park, a legal assistant at Morrison PI Law. You answer the main line for the firm. The caller is looking for the attorney (one of the partners), but Melissa picked up.

BEHAVIOR:
- Say "Morrison PI Law, this is Melissa" to start.
- When caller asks for the attorney by name, explain you're the assistant and they're in court today.
- If caller asks for the best way to reach them or for an email, offer: "You can reach Attorney Morrison at jmorrison@morrisonpi.com. She usually checks email between cases."
- Do NOT pretend to be the attorney.
- If caller tries to pitch you, politely redirect: "I'd encourage you to email the attorney directly."
- If caller is respectful and asks who handles operational decisions, say "That would be Attorney Morrison — she's the managing partner."
- Stay warm but professional. Speak one line at a time.""",
        expected_outcomes=["gatekeeper_only"],
    ),
}


# ---------------------------------------------------------------------------
# Tool mocks (no real Cal.com, no real email)
# ---------------------------------------------------------------------------

def _mock_check_availability(args: dict) -> dict:
    # Return a stable set of slots so the persona can pick deterministically.
    return {
        "slots": [
            {"start_iso": "2026-04-16T15:00:00-04:00", "label": "Thursday April 16 at 3:00 PM"},
            {"start_iso": "2026-04-16T16:00:00-04:00", "label": "Thursday April 16 at 4:00 PM"},
            {"start_iso": "2026-04-17T14:00:00-04:00", "label": "Friday April 17 at 2:00 PM"},
        ],
        "timezone": "America/New_York",
    }


def _mock_book_demo(args: dict) -> dict:
    slot = args.get("slot_iso", "")
    email = args.get("invitee_email", "")
    if not slot or not email:
        return {"booked": False, "error": "missing_slot_or_email"}
    return {
        "booked": True,
        "booking_id": f"bkg_sim_{uuid.uuid4().hex[:8]}",
        "start_iso": slot,
        "meeting_url": "https://cal.com/sim/meeting-link",
    }


def _mock_mark_gatekeeper(args: dict) -> dict:
    return {"ok": True}


def _mock_send_followup_email(args: dict) -> dict:
    email = args.get("invitee_email", "")
    if not email:
        return {"sent": False, "error": "missing_email"}
    return {"sent": True}


def _handle_end_call(args: dict, state: dict) -> dict:
    state["end_call_invoked"] = True
    state["end_call_args"] = args
    return {"ended": True}


def dispatch_tool(name: str, args: dict, state: dict) -> dict:
    return {
        "check_availability": lambda a: _mock_check_availability(a),
        "book_demo":          lambda a: _mock_book_demo(a),
        "mark_gatekeeper":    lambda a: _mock_mark_gatekeeper(a),
        "send_followup_email":lambda a: _mock_send_followup_email(a),
        "end_call":           lambda a: _handle_end_call(a, state),
    }.get(name, lambda a: {"error": f"unknown_tool: {name}"})(args)


# ---------------------------------------------------------------------------
# Tool-schema conversion: Realtime -> chat.completions
# ---------------------------------------------------------------------------

def tools_for_chat_completions(realtime_tools: list[dict]) -> list[dict]:
    """Realtime tools are flat ({type, name, description, parameters});
    chat.completions nests them: {type: function, function: {name, ...}}."""
    converted = []
    for t in realtime_tools:
        if t.get("type") != "function":
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return converted


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    speaker: str            # "ai" | "persona" | "tool"
    text: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[dict] = None


@dataclass
class ScenarioResult:
    persona_id: str
    transcript: list[Turn]
    end_call_invoked: bool
    end_call_args: Optional[dict]
    expected_outcomes: list[str]
    actual_outcome: Optional[str]
    passed: bool
    duration_seconds: float


def run_scenario(
    persona: Persona,
    *,
    rep_name: str,
    rep_company: str,
    product_context: str,
    autocaller_model: str = "gpt-4o",
    persona_model: str = "gpt-4o-mini",
    max_turns: int = 40,
    client: Optional[OpenAI] = None,
    verbose: bool = True,
) -> ScenarioResult:
    cli = client or OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    started = time.time()

    # Build the Lead that the autocaller's prompt renders against.
    lead = Patient(
        patient_id=f"SIM-{persona.id}",
        name=persona.name,
        phone=persona.phone,
        firm_name=persona.firm,
        state=persona.state,
        email=persona.email,
        title=persona.title,
        practice_area="personal injury",
    )

    autocaller_system = render_system_prompt(
        lead=lead,
        rep_name=rep_name,
        rep_company=rep_company,
        product_context=product_context,
    )
    # Realtime prompt assumes audio; explicitly remind the text-mode model
    # that each message is one spoken turn on a phone call.
    autocaller_system += (
        "\n\n## Simulator mode\n"
        "You are in a text-based simulator of a phone call. Each of your "
        "messages is a single spoken turn. Keep each message under two "
        "sentences. Invoke tools as you normally would."
    )

    persona_system = persona.persona_prompt

    tools = tools_for_chat_completions(REALTIME_TOOLS)

    # Running histories
    ai_msgs: list[dict[str, Any]] = [{"role": "system", "content": autocaller_system}]
    persona_msgs: list[dict[str, Any]] = [{"role": "system", "content": persona_system}]

    transcript: list[Turn] = []
    state: dict[str, Any] = {"end_call_invoked": False, "end_call_args": None}

    # Persona speaks first (they picked up the phone).
    persona_msgs.append({"role": "user", "content": "(phone rings, you pick up)"})
    persona_resp = cli.chat.completions.create(
        model=persona_model,
        messages=persona_msgs,
        temperature=0.7,
    )
    persona_line = (persona_resp.choices[0].message.content or "").strip()
    persona_msgs.append({"role": "assistant", "content": persona_line})
    transcript.append(Turn(speaker="persona", text=persona_line))
    if verbose:
        print(f"\n\033[36m[persona] {persona_line}\033[0m")

    # Feed persona's opening to the autocaller as the caller's first audible line.
    ai_msgs.append({"role": "user", "content": persona_line})

    turns = 0
    while turns < max_turns and not state["end_call_invoked"]:
        turns += 1

        # Autocaller turn — may produce text AND/OR tool calls
        ai_resp = cli.chat.completions.create(
            model=autocaller_model,
            messages=ai_msgs,
            tools=tools,
            tool_choice="auto",
            temperature=0.4,
        )
        msg = ai_resp.choices[0].message
        ai_text = (msg.content or "").strip()
        tool_calls = msg.tool_calls or []

        # Store the assistant message in history
        stored: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            stored["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        ai_msgs.append(stored)

        # If AI said something, print + feed to persona
        if ai_text:
            transcript.append(Turn(speaker="ai", text=ai_text))
            if verbose:
                print(f"\033[33m[ai]      {ai_text}\033[0m")

        # Dispatch tool calls
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = dispatch_tool(tc.function.name, args, state)
            transcript.append(Turn(
                speaker="tool",
                text=f"{tc.function.name}({json.dumps(args)}) -> {json.dumps(result)}",
                tool_name=tc.function.name,
                tool_args=args,
                tool_result=result,
            ))
            if verbose:
                print(f"\033[35m[tool]    {tc.function.name}({json.dumps(args)}) -> {json.dumps(result)}\033[0m")
            ai_msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

        if state["end_call_invoked"]:
            break

        # If the AI said nothing AND didn't call a tool, nudge it once then break
        if not ai_text and not tool_calls:
            break

        # If the AI only called tools without speaking, loop back so it can produce a verbal turn now that it has tool results
        if tool_calls and not ai_text:
            continue

        # Persona turn
        persona_msgs.append({"role": "user", "content": ai_text or "(silence)"})
        persona_resp = cli.chat.completions.create(
            model=persona_model,
            messages=persona_msgs,
            temperature=0.7,
        )
        persona_line = (persona_resp.choices[0].message.content or "").strip()
        persona_msgs.append({"role": "assistant", "content": persona_line})
        transcript.append(Turn(speaker="persona", text=persona_line))
        if verbose:
            print(f"\033[36m[persona] {persona_line}\033[0m")
        ai_msgs.append({"role": "user", "content": persona_line})

    # Determine outcome
    actual = None
    if state["end_call_invoked"] and state["end_call_args"]:
        actual = state["end_call_args"].get("outcome") or state["end_call_args"].get("reason")
    passed = actual in (persona.expected_outcomes or [])

    return ScenarioResult(
        persona_id=persona.id,
        transcript=transcript,
        end_call_invoked=state["end_call_invoked"],
        end_call_args=state["end_call_args"],
        expected_outcomes=persona.expected_outcomes,
        actual_outcome=actual,
        passed=passed,
        duration_seconds=time.time() - started,
    )


# ---------------------------------------------------------------------------
# Persistence + summary
# ---------------------------------------------------------------------------

def save_result(result: ScenarioResult, root: Path) -> Path:
    run_id = f"{result.persona_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    out_dir = root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "transcript.txt").write_text(
        "\n".join(
            f"[{t.speaker:7s}] {t.text}" + (f"  (tool={t.tool_name})" if t.tool_name else "")
            for t in result.transcript
        ),
        encoding="utf-8",
    )
    (out_dir / "verdict.json").write_text(
        json.dumps({
            "persona_id": result.persona_id,
            "expected_outcomes": result.expected_outcomes,
            "actual_outcome": result.actual_outcome,
            "passed": result.passed,
            "end_call_invoked": result.end_call_invoked,
            "end_call_args": result.end_call_args,
            "duration_seconds": round(result.duration_seconds, 1),
        }, indent=2),
        encoding="utf-8",
    )
    return out_dir


def print_summary(results: list[ScenarioResult]) -> None:
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        mark = "\033[32mPASS\033[0m" if r.passed else "\033[31mFAIL\033[0m"
        print(
            f"{mark}  {r.persona_id:16s}  "
            f"expected={r.expected_outcomes}  "
            f"actual={r.actual_outcome or '(no end_call)'}  "
            f"({r.duration_seconds:.1f}s)"
        )
    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} passed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("persona", nargs="?", default=None,
                        help="Persona id (omit to run all)")
    parser.add_argument("--save", action="store_true",
                        help="Write transcripts + verdicts to data/simulations/")
    parser.add_argument("--autocaller-model", default="gpt-4o")
    parser.add_argument("--persona-model", default="gpt-4o-mini")
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.persona and args.persona not in PERSONAS:
        print(f"Unknown persona: {args.persona}")
        print(f"Available: {', '.join(PERSONAS.keys())}")
        return 2

    personas = [PERSONAS[args.persona]] if args.persona else list(PERSONAS.values())

    rep_name = os.getenv("SALES_REP_NAME", "Alex")
    rep_company = os.getenv("SALES_REP_COMPANY", "Possible Minds")
    product_context = os.getenv(
        "PRODUCT_CONTEXT",
        "We build custom software and AI tooling for PI firms — intake automation, "
        "medical-records retrieval, demand-letter drafting, lien processing.",
    )

    results: list[ScenarioResult] = []
    for p in personas:
        print(f"\n\033[1m▶ Running scenario: {p.id}  ({p.name}, {p.firm})\033[0m")
        print(f"   expected: {p.expected_outcomes}")
        result = run_scenario(
            persona=p,
            rep_name=rep_name,
            rep_company=rep_company,
            product_context=product_context,
            autocaller_model=args.autocaller_model,
            persona_model=args.persona_model,
            max_turns=args.max_turns,
            verbose=not args.quiet,
        )
        results.append(result)
        if args.save:
            out = save_result(result, ROOT / "data" / "simulations")
            print(f"\n   saved: {out}")

    print_summary(results)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
