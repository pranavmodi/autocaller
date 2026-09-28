"""Cheap TypeSafe Jev judgments used inside the website-application loop.

Jev owns narrow semantic choices over already supplied state. It does not
generate browser actions, answers, evidence quotes, or application text.
"""
from __future__ import annotations

import asyncio
import json
import os

import httpx


TYPESAFE_SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
NONE_PROFILE = "no_saved_answer"
ACTION_SUPPORT_OPTIONS = ("supported", "unsupported", "unclear")
ACTION_EFFECT_OPTIONS = ("input", "navigation", "advance", "read", "submit", "blocked")
CONFIRMATION_OPTIONS = ("confirmed", "not_confirmed", "unclear")


def _number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"TypeSafe {label} is invalid.")
    return float(value)


def _choice(response: dict, question_id: str, options: set[str]) -> dict:
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("TypeSafe response is missing answers.")
    answer = response["answers"].get(question_id)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError(f"TypeSafe response is missing Choice answer {question_id}.")
    choice = answer.get("choice")
    probabilities = answer.get("probabilities")
    if choice not in options or not isinstance(probabilities, dict) or set(probabilities) != options:
        raise ValueError(f"TypeSafe Choice answer {question_id} has invalid options.")
    confidence = _number(answer.get("confidence"), f"confidence for {question_id}")
    parsed = {key: _number(value, f"probability for {question_id}.{key}")
              for key, value in probabilities.items()}
    if abs(sum(parsed.values()) - 1) > 0.02:
        raise ValueError(f"TypeSafe probabilities for {question_id} do not sum to one.")
    return {"choice": choice, "confidence": confidence, "probabilities": parsed}


async def _system_one(state: dict, questions: dict) -> dict:
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured.")
    request = {
        "state": state,
        "model": os.getenv("JOB_BROWSER_TYPESAFE_MODEL",
                           os.getenv("JOB_AGENT_TYPESAFE_MODEL", DEFAULT_MODEL)),
        "questions": questions,
    }
    # Jev is the latency optimization. If it is unavailable, return quickly to
    # the configured controller instead of turning the fast path into a delay.
    timeout_s = float(os.getenv("JOB_BROWSER_TYPESAFE_TIMEOUT_S", "8"))
    url = os.getenv("TYPESAFE_SYSTEM_ONE_URL", TYPESAFE_SYSTEM_ONE_URL)
    last_error = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                response = await client.post(url, headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }, json=request)
            if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                await asyncio.sleep(0.5)
                continue
            response.raise_for_status()
            result = response.json()
            if not isinstance(result.get("model"), str) or not result["model"]:
                raise ValueError("TypeSafe response is missing its model version.")
            return result
        except json.JSONDecodeError as exc:
            last_error = exc
        except ValueError:
            raise
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_error = exc
        if attempt == 0:
            await asyncio.sleep(0.5)
    raise RuntimeError("TypeSafe Jev browser judgment is temporarily unavailable.") from last_error


def _metadata(response: dict, **details) -> dict:
    return {
        "provider": "typesafe",
        "model": response["model"],
        "usage": response.get("usage") if isinstance(response.get("usage"), dict) else {},
        **details,
    }


async def audit_action(state: dict, proposed_action: dict,
                       *, mailbox_result_available: bool = False) -> tuple[dict | None, dict]:
    """Return an allowed audit, or None so the richer controller can review it.

    Jev handles the common supported path. Unsupported, unclear, or low-
    confidence proposals fall through to the existing generative auditor so it
    can explain a correction without weakening the safety boundary.
    """
    relevant_state = {
        "job": {key: state.get("posting", {}).get(key) for key in (
            "firm_name", "title", "location", "description_summary",
            "responsibilities", "qualifications", "employment_type")},
        "resume": str(state.get("resume", {}).get("text") or "")[:14_000],
        "preferences": state.get("preferences", {}),
        "saved_profile": state.get("saved_profile", []),
        "operator_answers": state.get("answers", []),
        "page": state.get("snapshot"),
        "proposed_action": proposed_action,
        "mailbox_result_available": mailbox_result_available,
        "submission_authorized": bool(state.get("authorized_at")),
        "submission_started": bool(state.get("submit_started_at")),
    }
    response = await _system_one(relevant_state, {
        "action_support": {
            "type": "choice",
            "instructions": {
                "task": "Is `proposed_action` supported by the supplied application state?",
                "rules": [
                    "Treat truthful form input supported by the resume, saved profile, operator answers, or explicit preferences as supported.",
                    "Treat ordinary navigation, resume upload, and read-only mailbox search as supported when their target is visible and relevant.",
                    "Treat a submission as supported only when authorized and no unresolved contradiction is visible.",
                    "Treat invented identity, credentials, legal status, work authorization, employment facts, or unsupported biographical claims as unsupported.",
                    "Treat missing evidence or an ambiguous consequential claim as unclear.",
                ],
            },
            "criteria": {
                "supported": {"label": "Supported", "definition": "The action is truthful, relevant, and supported by supplied state."},
                "unsupported": {"label": "Unsupported", "definition": "The action conflicts with or invents a consequential fact."},
                "unclear": {"label": "Unclear", "definition": "The supplied state is insufficient to audit the action safely."},
            },
        },
        "action_effect": {
            "type": "choice",
            "instructions": {
                "task": "What is the actual primary effect of `proposed_action` on the visible application?",
                "rules": [
                    "Classify what the control does, not the wording of the action summary.",
                    "Choose input for filling, selecting, checking, uploading, or a click that only changes a field.",
                    "Choose navigation for opening a different URL or page, advance for moving to another form step, read for read-only mailbox access, and submit only for a final or verification submission.",
                    "Choose blocked when the effect cannot be established from the supplied control and page state.",
                ],
            },
            "criteria": {
                "input": {"label": "Form input", "definition": "Changes a field without advancing or submitting."},
                "navigation": {"label": "Navigation", "definition": "Opens another page or URL."},
                "advance": {"label": "Advance", "definition": "Moves to a later form step without final submission."},
                "read": {"label": "Read", "definition": "Reads scoped information without changing it."},
                "submit": {"label": "Submit", "definition": "Submits the application or a required verification form."},
                "blocked": {"label": "Blocked", "definition": "The effect is unavailable or cannot be established."},
            },
        },
    })
    support = _choice(response, "action_support", set(ACTION_SUPPORT_OPTIONS))
    effect = _choice(response, "action_effect", set(ACTION_EFFECT_OPTIONS))
    minimum = float(os.getenv("JOB_BROWSER_JEV_MIN_CONFIDENCE", "0.70"))
    metadata = _metadata(response, support=support, effect=effect, minimum_confidence=minimum)
    if (support["choice"] != "supported" or support["confidence"] < minimum
            or effect["choice"] == "blocked" or effect["confidence"] < minimum):
        return None, metadata
    return {
        "allowed": True,
        "effect": effect["choice"],
        "reason": "Jev found the proposed action supported by the saved application facts.",
        "recovery": "none",
        "repair_hint": "",
    }, metadata


async def resolve_profile_question(state: dict, question: str) -> tuple[dict | None, dict]:
    """Choose one existing answer verbatim, or defer to the richer controller."""
    profile = list(state.get("saved_profile", []))[:40]
    if not profile:
        return None, {}
    option_ids = [f"answer_{index}" for index in range(len(profile))]
    criteria = {
        option_id: {
            "label": item.get("question") or f"Saved answer {index + 1}",
            "definition": json.dumps({
                "answer": item.get("answer"), "scope": item.get("scope"),
                "scope_value": item.get("scope_value"), "context": item.get("context"),
            }, ensure_ascii=True)[:6000],
        }
        for index, (option_id, item) in enumerate(zip(option_ids, profile, strict=True))
    }
    criteria[NONE_PROFILE] = {
        "label": "No saved answer applies",
        "definition": "None of the saved answers truthfully and specifically answers the current question in this job context.",
    }
    response = await _system_one({
        "question": question,
        "job": {key: state.get("posting", {}).get(key) for key in (
            "firm_name", "title", "location", "employment_type", "work_arrangement")},
        "saved_answers": [{"option": option_id, **item}
                          for option_id, item in zip(option_ids, profile, strict=True)],
    }, {
        "saved_answer": {
            "type": "choice",
            "instructions": {
                "task": "Which saved answer, if any, truthfully answers `question` for this job?",
                "rules": [
                    "Respect each answer's scope, scope value, original question, and context.",
                    "Choose no_saved_answer when location, country, company, role, authorization, compensation, or other context differs materially.",
                    "Do not combine answers and do not infer a new answer.",
                ],
            },
            "criteria": criteria,
        },
    })
    selected = _choice(response, "saved_answer", set(criteria))
    minimum = float(os.getenv("JOB_BROWSER_PROFILE_JEV_MIN_CONFIDENCE", "0.72"))
    metadata = _metadata(response, selection=selected, minimum_confidence=minimum)
    if selected["choice"] == NONE_PROFILE or selected["confidence"] < minimum:
        return None, metadata
    index = option_ids.index(selected["choice"])
    item = profile[index]
    answer = str(item.get("answer") or "")
    if not answer:
        return None, metadata
    return {
        "answer": answer,
        "missing_question": "",
        "citations": [{"id": item["id"], "quote": answer}],
        "reason": "Jev selected the saved answer that best matches this question and job context.",
    }, metadata


async def verify_confirmation(state: dict, evidence: str) -> tuple[dict | None, dict]:
    """Verify an exact visible receipt with Jev, deferring uncertain cases."""
    response = await _system_one({
        "job": {key: state.get("posting", {}).get(key) for key in
                ("firm_name", "title", "location")},
        "visible_page": state.get("snapshot"),
        "exact_visible_evidence": evidence,
        "submission_started": bool(state.get("submit_started_at")),
    }, {
        "submission_confirmation": {
            "type": "choice",
            "instructions": {
                "task": "Does the exact visible evidence prove that this specific job application was submitted successfully?",
                "rules": [
                    "Require an employer or ATS receipt for the application, not a generic page heading, button, draft state, sign-in screen, or invitation to submit.",
                    "Use the job and surrounding visible page to disambiguate the evidence.",
                    "Choose unclear when the text could describe a different action or application.",
                ],
            },
            "criteria": {
                "confirmed": {"label": "Confirmed", "definition": "The page clearly confirms successful submission of this job application."},
                "not_confirmed": {"label": "Not confirmed", "definition": "The page does not confirm a successful application submission."},
                "unclear": {"label": "Unclear", "definition": "The evidence is ambiguous or lacks enough context."},
            },
        },
    })
    decision = _choice(response, "submission_confirmation", set(CONFIRMATION_OPTIONS))
    minimum = float(os.getenv("JOB_BROWSER_CONFIRMATION_JEV_MIN_CONFIDENCE", "0.75"))
    metadata = _metadata(response, confirmation=decision, minimum_confidence=minimum)
    if decision["confidence"] < minimum or decision["choice"] == "unclear":
        return None, metadata
    return {
        "confirmed": decision["choice"] == "confirmed",
        "reason": ("Jev found that the exact visible receipt confirms this application."
                   if decision["choice"] == "confirmed" else
                   "Jev found that the visible text does not confirm this application."),
    }, metadata
