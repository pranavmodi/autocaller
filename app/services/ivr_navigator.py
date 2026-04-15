"""IVR (phone-tree) navigator.

When the voicemail-signal pre-filter fires, this service decides whether
we're actually on a voicemail or a navigable menu, and — if it's a menu —
picks a digit, presses it via Twilio DTMF, waits for the next prompt, and
repeats until we reach a human, hit a dead-end, or run out of time.

Uses gpt-4o-mini with JSON-mode for all classification + picking decisions
(cheap, <300ms per call). Everything is logged to CallLog.ivr_menu_log so
we can review afterwards what worked and what didn't.

Safety rails:
  - Never claim to be a client / attorney / patient (menu options that
    require an identity claim are blacklisted — we skip them and try the
    next-best option).
  - Hard caps: 3 menu hops, 60 s wall-clock.
  - Loop detection: if the same menu transcript comes back twice, give up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from openai import AsyncOpenAI


logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("IVR_NAV_MODEL", "gpt-4o-mini")

# Max menu hops + total wall-clock budget for navigation.
MAX_HOPS = 3
MAX_NAVIGATION_SECONDS = 60.0
# How long to wait after pressing a digit before re-reading the transcript.
POST_DTMF_LISTEN_SECONDS = 3.5

# Outcome values stamped onto CallLog.ivr_outcome.
OUTCOME_REACHED_HUMAN = "reached_human"
OUTCOME_DEAD_END = "dead_end"
OUTCOME_TIMED_OUT = "timed_out"
OUTCOME_SKIPPED = "skipped"
OUTCOME_NOT_IVR = "not_ivr"


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = (
    "You are analysing audio transcript from the start of a US business "
    "phone call. Classify what the other side is. Output JSON only:\n"
    '  {"kind": "human"|"ivr_menu"|"voicemail"|"ambiguous", '
    '   "confidence": 0.0-1.0, "reason": "<short>"}\n\n'
    "Definitions:\n"
    "- human: a live person speaking informally (e.g. 'Hello?', 'Law office of X, this is Y').\n"
    "- ivr_menu: a scripted prompt offering NUMBERED OPTIONS to navigate "
    "(e.g. 'press 1 for new clients, press 2 for existing'). This is NAVIGABLE.\n"
    "- voicemail: an answering machine / voicemail greeting that asks to leave a message. "
    "Not navigable.\n"
    "- ambiguous: cannot tell yet (too little audio, music, etc.).\n\n"
    "Key distinction: if you hear 'press N' / 'dial N' / 'for X, press N', it's ivr_menu. "
    "If you hear 'leave a message' / 'record after the tone' / 'mailbox is full', it's voicemail."
)


_PARSE_AND_PICK_SYSTEM = (
    "You are navigating a US business phone tree on behalf of a cold-call sales agent. "
    "The goal is to reach a HUMAN EMPLOYEE (receptionist, attorney, operator) so the "
    "sales agent can pitch them. You are calling a personal-injury law firm.\n\n"
    "You will be given the transcript of the current menu prompt plus the prior "
    "digits already pressed in this call. Parse the options, then pick the single "
    "best digit to press.\n\n"
    "HARD RULES (non-negotiable):\n"
    "- NEVER pick an option that requires claiming to be a client, patient, "
    "existing customer, or attorney on record. E.g. 'press 1 if you're an existing "
    "client' — DO NOT PRESS 1.\n"
    "- NEVER pick 'emergency' / 'urgent' / '911' options.\n"
    "- Prefer: 'operator', 'receptionist', 'front desk', 'main', 'other', "
    "'speak to someone', 'attorney intake', 'general', or a named person.\n"
    "- If no option reaches a generic human, prefer a 'new clients' or 'new inquiries' "
    "path (that's us — we're initiating a new contact).\n"
    "- If all visible options require an identity claim or are dead-ends, pick '0' "
    "with rationale 'default to operator' — pressing 0 routes to an operator on "
    "most systems.\n\n"
    'Output strict JSON with this exact shape:\n'
    '{"parsed_menu": [{"digit": "1", "label": "...", '
    '"identity_claim_required": true, '
    '"route_type": "operator|new_client|existing_client|billing|legal|emergency|other"}], '
    '"chosen_digit": "N", "rationale": "..."}'
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class NavigationStep:
    """One hop in the menu tree."""
    step: int
    transcript_snippet: str
    kind: str              # "ivr_menu" | "voicemail" | "human" | "ambiguous"
    parsed_menu: list = field(default_factory=list)
    chosen_digit: Optional[str] = None
    rationale: str = ""
    result: str = ""       # "pressed" | "reached_human" | "dead_end" | "voicemail" | "loop_detected" | "error"

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "transcript_snippet": self.transcript_snippet,
            "kind": self.kind,
            "parsed_menu": self.parsed_menu,
            "chosen_digit": self.chosen_digit,
            "rationale": self.rationale,
            "result": self.result,
        }


@dataclass
class NavigationResult:
    """Outcome of the navigator."""
    outcome: str                       # one of the OUTCOME_* constants
    steps: list[NavigationStep] = field(default_factory=list)

    def to_log(self) -> list[dict]:
        return [s.to_dict() for s in self.steps]


# ---------------------------------------------------------------------------
# Navigator
# ---------------------------------------------------------------------------

class IVRNavigator:
    def __init__(
        self,
        *,
        client: Optional[AsyncOpenAI] = None,
        model: str = DEFAULT_MODEL,
    ):
        api_key = os.getenv("OPENAI_API_KEY", "")
        self._client = client or AsyncOpenAI(api_key=api_key)
        self._model = model

    async def classify(self, transcript: str) -> dict:
        """Return {"kind", "confidence", "reason"}."""
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _CLASSIFY_PROMPT},
                    {"role": "user", "content": transcript or "(silence)"},
                ],
                temperature=0.0,
                max_tokens=150,
            )
            raw = resp.choices[0].message.content or "{}"
            return json.loads(raw)
        except Exception as e:
            logger.warning("IVR classify failed: %s", e)
            return {"kind": "ambiguous", "confidence": 0.0, "reason": f"llm_error: {e}"}

    async def parse_and_pick(
        self,
        menu_transcript: str,
        prior_choices: list[str],
    ) -> dict:
        """Return {"parsed_menu", "chosen_digit", "rationale"}."""
        user_payload = (
            f"Prior digits pressed this call (avoid circular paths): "
            f"{', '.join(prior_choices) if prior_choices else '(none)'}\n\n"
            f"Current menu transcript:\n---\n{menu_transcript or '(empty)'}\n---"
        )
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _PARSE_AND_PICK_SYSTEM},
                    {"role": "user", "content": user_payload},
                ],
                temperature=0.0,
                max_tokens=600,
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            # Sanity-clamp chosen_digit to a single char in [0-9*#]
            digit = str(data.get("chosen_digit") or "0").strip()[:1]
            if digit not in "0123456789*#":
                digit = "0"
            data["chosen_digit"] = digit
            if not isinstance(data.get("parsed_menu"), list):
                data["parsed_menu"] = []
            data["rationale"] = str(data.get("rationale") or "")[:300]
            return data
        except Exception as e:
            logger.warning("IVR parse_and_pick failed: %s", e)
            return {
                "parsed_menu": [],
                "chosen_digit": "0",
                "rationale": f"llm_error_fallback_to_operator: {e}",
            }

    async def navigate(
        self,
        *,
        get_recent_transcript: Callable[[], str],
        send_dtmf: Callable[[str], Awaitable[None]],
        mute_ai_audio: Callable[[], None],
        unmute_ai_audio: Callable[[], None],
        initial_transcript: str = "",
        on_note: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> NavigationResult:
        """Run the full navigation loop.

        Args:
          get_recent_transcript: returns the latest N seconds of caller-side
            transcript as one string. Called between DTMFs.
          send_dtmf: sends a single digit over Twilio Media Stream.
          mute_ai_audio / unmute_ai_audio: silences the AI's audio output
            during navigation so the phone tree doesn't hear our pitch.
          initial_transcript: whatever triggered IVR detection (pre-filter
            match). Used for the first classify() call.
        """
        result = NavigationResult(outcome=OUTCOME_SKIPPED)
        started = time.monotonic()

        async def _note(msg: str) -> None:
            if on_note is not None:
                try:
                    await on_note(msg)
                except Exception:
                    pass

        # Mute the AI for the duration of navigation.
        try:
            mute_ai_audio()
            await _note("Navigator: muted AI audio, starting menu analysis.")
        except Exception:
            pass

        try:
            prior_choices: list[str] = []
            seen_menus: list[str] = []

            # Step 0: classify the initial prompt.
            current_transcript = (initial_transcript or get_recent_transcript() or "").strip()
            classified = await self.classify(current_transcript)
            await _note(
                f"Classified first prompt as '{classified.get('kind','?')}' "
                f"({int((classified.get('confidence') or 0)*100)}% conf): "
                f"{str(classified.get('reason',''))[:140]}"
            )
            step = NavigationStep(
                step=0,
                transcript_snippet=current_transcript[-600:],
                kind=str(classified.get("kind", "ambiguous")),
                rationale=f"classify: {classified.get('reason', '')}",
            )
            result.steps.append(step)

            if step.kind == "human":
                result.outcome = OUTCOME_NOT_IVR
                step.result = "reached_human"
                return result
            if step.kind == "voicemail":
                result.outcome = OUTCOME_NOT_IVR  # handled by existing voicemail path
                step.result = "voicemail"
                return result
            if step.kind not in ("ivr_menu", "ambiguous"):
                result.outcome = OUTCOME_SKIPPED
                step.result = "skipped"
                return result

            # Enter navigation loop.
            for hop in range(1, MAX_HOPS + 1):
                if time.monotonic() - started > MAX_NAVIGATION_SECONDS:
                    result.outcome = OUTCOME_TIMED_OUT
                    if result.steps:
                        result.steps[-1].result = "timed_out"
                    return result

                menu_transcript = current_transcript
                # Loop detection: same menu text twice in a row → dead end.
                menu_key = menu_transcript.strip().lower()[-400:]
                if menu_key in seen_menus:
                    result.outcome = OUTCOME_DEAD_END
                    if result.steps:
                        result.steps[-1].result = "loop_detected"
                    return result
                seen_menus.append(menu_key)

                pick = await self.parse_and_pick(menu_transcript, prior_choices)
                digit = pick["chosen_digit"]

                hop_step = NavigationStep(
                    step=hop,
                    transcript_snippet=menu_transcript[-600:],
                    kind="ivr_menu",
                    parsed_menu=pick.get("parsed_menu", []),
                    chosen_digit=digit,
                    rationale=pick.get("rationale", ""),
                )
                result.steps.append(hop_step)

                # Announce decision before pressing so it shows up in order
                # with the post-press outcome in the transcript.
                await _note(
                    f"Decision hop {hop}: press {digit} — {pick.get('rationale','')}"
                )

                try:
                    await send_dtmf(digit)
                    prior_choices.append(digit)
                    hop_step.result = "pressed"
                except Exception as e:
                    hop_step.result = f"error: {type(e).__name__}: {e}"
                    await _note(f"DTMF send failed: {e}")
                    result.outcome = OUTCOME_DEAD_END
                    return result

                # Wait for the next prompt to land on the transcript.
                await asyncio.sleep(POST_DTMF_LISTEN_SECONDS)
                current_transcript = (get_recent_transcript() or "").strip()

                # Re-classify. If it's a human now, we're done.
                classified = await self.classify(current_transcript)
                kind = str(classified.get("kind", "ambiguous"))
                await _note(
                    f"After pressing {digit}: classified '{kind}' "
                    f"({int((classified.get('confidence') or 0)*100)}% conf)"
                )
                if kind == "human":
                    result.outcome = OUTCOME_REACHED_HUMAN
                    hop_step.result = "reached_human"
                    return result
                if kind == "voicemail":
                    result.outcome = OUTCOME_DEAD_END
                    hop_step.result = "hit_voicemail"
                    return result
                # else: likely another menu (or ambiguous) — loop again.

            # Hit hop cap without reaching human.
            result.outcome = OUTCOME_DEAD_END
            if result.steps:
                result.steps[-1].result = "hop_cap_reached"
            return result

        except Exception as e:
            logger.exception("IVR navigate unexpected error")
            result.outcome = OUTCOME_DEAD_END
            if result.steps:
                result.steps[-1].result = f"error: {type(e).__name__}: {e}"
            return result
        finally:
            # Always unmute when leaving (caller may still wish to talk).
            try:
                unmute_ai_audio()
            except Exception:
                pass


_singleton: Optional[IVRNavigator] = None


def get_ivr_navigator() -> IVRNavigator:
    global _singleton
    if _singleton is None:
        _singleton = IVRNavigator()
    return _singleton
