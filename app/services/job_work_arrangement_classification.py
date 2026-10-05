"""Resolve conflicting remote, hybrid, and onsite job evidence with TypeSafe Jev."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select


TYPESAFE_SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
CLASSIFICATION_VERSION = "jev-work-arrangement-v1"
OPTIONS = ("remote", "hybrid", "onsite", "unclear")
WorkArrangement = Literal["remote", "hybrid", "onsite", "unclear"]


class WorkArrangementDecision(BaseModel):
    candidate_id: str
    status: WorkArrangement
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]
    model: str
    usage: dict = Field(default_factory=dict)


def _text(value, *, limit: int = 6000) -> str:
    if value is None:
        return ""
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True)
    return rendered[:limit]


def classification_input(posting: dict) -> dict[str, str]:
    return {
        key: _text(posting.get(key))
        for key in (
            "title", "location", "remote_eligibility", "description_summary",
            "responsibilities", "qualifications", "work_arrangement", "remote_scope",
        )
    }


def input_sha256(posting: dict) -> str:
    value = json.dumps(classification_input(posting), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def has_conflicting_evidence(posting: dict) -> bool:
    text = " ".join(classification_input(posting).values())
    has_remote = bool(re.search(r"\b(remote|work from home|work from anywhere)\b", text, re.I))
    has_hybrid_or_onsite = bool(re.search(r"\b(hybrid|on[- ]?site|in[- ]?office)\b", text, re.I))
    has_negation = bool(re.search(r"\b(no|not)\s+(?:a\s+)?(?:remote|hybrid)|\bremote\s+(?:work\s+)?(?:is\s+)?not\b", text, re.I))
    return (has_remote and has_hybrid_or_onsite) or has_negation


def _request(postings: list[dict]) -> dict:
    jobs = [classification_input(posting) for posting in postings]
    criteria = {
        "remote": {"label": "Remote", "definition": "The role can be performed fully remotely as an ordinary option without recurring in-person attendance."},
        "hybrid": {"label": "Hybrid", "definition": "The role requires or ordinarily combines recurring remote work with recurring in-person or office attendance."},
        "onsite": {"label": "Onsite", "definition": "The role is in-person and the supplied facts exclude remote and hybrid work."},
        "unclear": {"label": "Unclear", "definition": "The supplied facts are insufficient or genuinely conflict about whether the role is remote, hybrid, or onsite."},
    }
    rules = [
        "Judge the actual work arrangement offered for only the supplied role.",
        "A fixed schedule with some work-from-home days and some office days is hybrid, not remote.",
        "If fully remote is independently available and hybrid or office work is merely an alternative, choose remote.",
        "If the listing says remote or hybrid work is not available, choose onsite.",
        "Do not infer remote work from flexible scheduling or a distributed company.",
        "Choose exactly one option.",
    ]
    return {
        "state": {"jobs": jobs},
        "model": os.getenv("JOB_WORK_ARRANGEMENT_TYPESAFE_MODEL", "jev-latest"),
        "questions": {
            f"job_{index}": {
                "type": "choice",
                "instructions": {"task": f"What work arrangement is established for only `jobs[{index}]`?", "rules": rules},
                "criteria": criteria,
            }
            for index in range(len(jobs))
        },
    }


def _parse(response: dict, identities: list[str]) -> list[WorkArrangementDecision]:
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("TypeSafe response is missing answers.")
    model = response.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("TypeSafe response is missing its model version.")
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    decisions = []
    for index, identity in enumerate(identities):
        answer = response["answers"].get(f"job_{index}")
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            raise ValueError(f"TypeSafe response is missing Choice answer job_{index}.")
        choice, probabilities, confidence = answer.get("choice"), answer.get("probabilities"), answer.get("confidence")
        if choice not in OPTIONS or not isinstance(probabilities, dict) or set(probabilities) != set(OPTIONS):
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid options.")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid confidence.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1 for value in probabilities.values()):
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid probabilities.")
        decisions.append(WorkArrangementDecision(
            candidate_id=identity, status=choice, confidence=float(confidence),
            probabilities={key: float(value) for key, value in probabilities.items()}, model=model, usage=usage,
        ))
    return decisions


async def classify_postings(postings: list[dict]) -> list[WorkArrangementDecision]:
    if not postings:
        return []
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured.")
    identities = [str(posting.get("candidate_id") or index) for index, posting in enumerate(postings)]
    request = _request(postings)
    url = os.getenv("TYPESAFE_SYSTEM_ONE_URL", TYPESAFE_SYSTEM_ONE_URL)
    timeout_s = int(os.getenv("JOB_WORK_ARRANGEMENT_CLASSIFICATION_TIMEOUT_S", "120"))
    last_error = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                response = await client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=request)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            response.raise_for_status()
            return _parse(response.json(), identities)
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            break
    raise RuntimeError("TypeSafe Jev work-arrangement classification request failed.") from last_error


def apply_decision(posting: dict, decision: WorkArrangementDecision) -> dict:
    result = dict(posting)
    result["work_arrangement"] = decision.status
    if decision.status in {"hybrid", "onsite"}:
        result.update(remote_scope="not_remote", global_remote=False, global_remote_evidence=[])
    elif decision.status == "unclear":
        result.update(remote_scope="unclear", global_remote=False, global_remote_evidence=[])
    result["global_remote_confidence"] = decision.probabilities.get(decision.status, decision.confidence)
    result["work_arrangement_classification"] = {
        "state": "completed", "version": CLASSIFICATION_VERSION, "provider": "typesafe",
        "model": decision.model, "confidence": decision.confidence,
        "probabilities": decision.probabilities, "classified_at": datetime.now(timezone.utc).isoformat(),
        "input_sha256": input_sha256(posting),
    }
    return result


async def classify_conflicts(postings: list[dict]) -> tuple[list[dict], str | None]:
    candidates = [(index, posting) for index, posting in enumerate(postings) if has_conflicting_evidence(posting)]
    if not candidates:
        return postings, None
    try:
        decisions = await classify_postings([{**posting, "candidate_id": str(index)} for index, posting in candidates])
    except Exception as exc:
        return postings, str(exc)[:1000]
    result = [dict(posting) for posting in postings]
    for (index, _), decision in zip(candidates, decisions):
        result[index] = apply_decision(result[index], decision)
    return result, None


async def backfill_conflicts(*, batch_size: int = 20) -> dict:
    from app.db import AsyncSessionLocal
    from app.db.models import PifFirmRow
    from app.services.career_job_store import same_job

    batch_size = max(1, min(50, int(batch_size)))
    async with AsyncSessionLocal() as session:
        firms = list((await session.scalars(select(PifFirmRow).order_by(PifFirmRow.id))).all())
    selected = [(firm.id, dict(posting)) for firm in firms for posting in (((firm.research_data or {}).get("job_postings") or {}).get("postings") or []) if isinstance(posting, dict) and has_conflicting_evidence(posting)]
    summary = {"selected": len(selected), "processed": 0, "remote": 0, "hybrid": 0, "onsite": 0, "unclear": 0, "errors": []}
    for start in range(0, len(selected), batch_size):
        batch = selected[start:start + batch_size]
        try:
            decisions = await classify_postings([{**posting, "candidate_id": f"{firm_id}:{index}"} for index, (firm_id, posting) in enumerate(batch)])
        except Exception as exc:
            summary["errors"].append({"count": len(batch), "error": str(exc)[:1000] or type(exc).__name__})
            continue
        by_firm: dict[str, list[tuple[dict, WorkArrangementDecision]]] = {}
        for (firm_id, posting), decision in zip(batch, decisions):
            by_firm.setdefault(firm_id, []).append((posting, decision))
        async with AsyncSessionLocal() as session:
            for firm_id, updates in by_firm.items():
                firm = await session.get(PifFirmRow, firm_id, with_for_update=True)
                if not firm:
                    continue
                data, jobs = dict(firm.research_data or {}), dict((firm.research_data or {}).get("job_postings") or {})
                postings = [dict(item) for item in jobs.get("postings") or [] if isinstance(item, dict)]
                for original, decision in updates:
                    index = next((i for i, item in enumerate(postings) if same_job(item, original)), None)
                    if index is None:
                        continue
                    postings[index] = apply_decision(postings[index], decision)
                    summary["processed"] += 1
                    summary[decision.status] += 1
                jobs["postings"] = postings
                data["job_postings"] = jobs
                firm.research_data = data
            await session.commit()
    summary["remaining"] = summary["selected"] - summary["processed"]
    return summary
