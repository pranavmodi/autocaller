"""TypeSafe Jev classification for legal-degree job requirements."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select


TYPESAFE_SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
CLASSIFICATION_VERSION = "jev-legal-degree-v2"
OPTIONS = ("required", "not_required", "unclear")
LegalDegreeStatus = Literal["required", "not_required", "unclear"]


class LegalDegreeDecision(BaseModel):
    candidate_id: str
    status: LegalDegreeStatus
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]
    model: str
    usage: dict = Field(default_factory=dict)
    provider: str = "typesafe"


_CANDIDATE_PATTERN = re.compile(
    r"\b(attorney|lawyer|solicitor|barrister|litigation associate|legal editor|"
    r"j\.?\s*d\.?|juris doctor|law degree|ll\.?\s*b\.?|bar admission|"
    r"admitted to (?:the )?bar|licensed to practice law|licensed attorney)\b",
    re.IGNORECASE,
)


def _text(value, *, limit: int = 6000) -> str:
    if value is None:
        return ""
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True)
    return rendered[:limit]


def classification_input(posting: dict) -> dict[str, str]:
    return {
        key: _text(posting.get(key))
        for key in (
            "title", "description_summary", "responsibilities", "qualifications",
            "requirements", "required_qualifications", "minimum_qualifications",
            "role_category", "role_evidence",
        )
    }


def input_sha256(posting: dict) -> str:
    value = json.dumps(classification_input(posting), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def has_legal_credential_candidate(posting: dict) -> bool:
    """Cheaply narrow Jev work; this signal never makes the final decision."""
    return bool(_CANDIDATE_PATTERN.search(" ".join(classification_input(posting).values())))


def _request(postings: list[dict]) -> dict:
    jobs = [classification_input(posting) for posting in postings]
    criteria = {
        "required": {
            "label": "Required",
            "definition": (
                "The role is a practicing attorney/lawyer/counsel role, or the supplied listing explicitly "
                "requires a JD, Juris Doctor, LLB, law degree, bar admission, or license to practice law."
            ),
        },
        "not_required": {
            "label": "Not required",
            "definition": (
                "The supplied listing explicitly establishes that a law degree or attorney license is not required."
            ),
        },
        "unclear": {
            "label": "Unclear",
            "definition": (
                "The supplied facts do not establish whether a law degree or attorney license is mandatory. "
                "A preferred, beneficial, optional, or merely relevant legal background is not a requirement."
            ),
        },
    }
    rules = [
        "Judge only mandatory legal education or licensure for the role described in the supplied job facts.",
        "A practicing attorney, lawyer, or counsel role is required even when the qualifications omit the credential.",
        "Do not mark paralegal, legal assistant, legal operations, compliance, sales, or technology roles required unless the supplied facts make the legal credential mandatory.",
        "Do not treat preferred, optional, beneficial, or equivalent-experience language as required.",
        "If a law degree is only one option and a non-law credential or experience also satisfies the requirement, choose not_required.",
        "Choose unclear when the relevant qualifications are absent or ambiguous.",
        "Choose exactly one option.",
    ]
    return {
        "state": {"jobs": jobs},
        "model": os.getenv("JOB_LEGAL_DEGREE_TYPESAFE_MODEL", "jev-latest"),
        "questions": {
            f"job_{index}": {
                "type": "choice",
                "instructions": {
                    "task": f"Does only `jobs[{index}]` require a law degree or attorney license?",
                    "rules": rules,
                },
                "criteria": criteria,
            }
            for index in range(len(jobs))
        },
    }


def _parse(response: dict, identities: list[str]) -> list[LegalDegreeDecision]:
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("TypeSafe response is missing answers.")
    model = response.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("TypeSafe response is missing its model version.")
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    decisions = []
    option_ids = set(OPTIONS)
    for index, identity in enumerate(identities):
        answer = response["answers"].get(f"job_{index}")
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            raise ValueError(f"TypeSafe response is missing Choice answer job_{index}.")
        choice = answer.get("choice")
        probabilities = answer.get("probabilities")
        confidence = answer.get("confidence")
        if choice not in option_ids or not isinstance(probabilities, dict) or set(probabilities) != option_ids:
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid options.")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid confidence.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1 for value in probabilities.values()):
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid probabilities.")
        if abs(sum(probabilities.values()) - 1) > 0.02:
            raise ValueError(f"TypeSafe Choice answer job_{index} probabilities do not sum to one.")
        decisions.append(LegalDegreeDecision(
            candidate_id=identity,
            status=choice,
            confidence=float(confidence),
            probabilities={key: float(value) for key, value in probabilities.items()},
            model=model,
            usage=usage,
        ))
    return decisions


async def classify_postings(postings: list[dict]) -> list[LegalDegreeDecision]:
    if not postings:
        return []
    candidates = [(index, posting) for index, posting in enumerate(postings) if has_legal_credential_candidate(posting)]
    decisions: list[LegalDegreeDecision | None] = [None] * len(postings)
    for index, posting in enumerate(postings):
        if not has_legal_credential_candidate(posting):
            decisions[index] = LegalDegreeDecision(
                candidate_id=str(posting.get("candidate_id") or index), status="unclear", confidence=1,
                probabilities={"required": 0, "not_required": 0, "unclear": 1},
                model="legal-credential-prefilter-v1", provider="mechanical_prefilter",
            )
    if not candidates:
        return [decision for decision in decisions if decision is not None]
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured.")
    candidate_postings = [posting for _, posting in candidates]
    identities = [str(posting.get("candidate_id") or index) for index, posting in candidates]
    request = _request(candidate_postings)
    timeout_s = int(os.getenv("JOB_LEGAL_DEGREE_CLASSIFICATION_TIMEOUT_S", "120"))
    url = os.getenv("TYPESAFE_SYSTEM_ONE_URL", TYPESAFE_SYSTEM_ONE_URL)
    last_error = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                response = await client.post(url, headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }, json=request)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            response.raise_for_status()
            classified = _parse(response.json(), identities)
            for (index, _), decision in zip(candidates, classified):
                decisions[index] = decision
            return [decision for decision in decisions if decision is not None]
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            break
    raise RuntimeError("TypeSafe Jev legal-degree classification request failed.") from last_error


def apply_decision(posting: dict, decision: LegalDegreeDecision, *, classified_at: datetime | None = None) -> dict:
    result = dict(posting)
    observed_at = classified_at or datetime.now(timezone.utc)
    result["legal_degree_requirement"] = decision.status
    result["legal_degree_classification"] = {
        "state": "completed", "version": CLASSIFICATION_VERSION, "provider": decision.provider,
        "model": decision.model, "confidence": decision.confidence,
        "probabilities": decision.probabilities, "classified_at": observed_at.isoformat(),
        "input_sha256": input_sha256(posting),
    }
    return result


def apply_error(posting: dict, error: Exception, *, classified_at: datetime | None = None) -> dict:
    result = dict(posting)
    observed_at = classified_at or datetime.now(timezone.utc)
    result["legal_degree_requirement"] = "unclear"
    result["legal_degree_classification"] = {
        "state": "error", "version": CLASSIFICATION_VERSION, "provider": "typesafe",
        "model": None, "confidence": None, "probabilities": {},
        "classified_at": observed_at.isoformat(), "input_sha256": input_sha256(posting),
        "error": str(error)[:1000] or type(error).__name__,
    }
    return result


async def classify_extracted_postings(postings: list[dict]) -> tuple[list[dict], str | None]:
    if not postings:
        return [], None
    try:
        decisions = await classify_postings(postings)
    except Exception as exc:
        return [apply_error(posting, exc) for posting in postings], str(exc)[:1000]
    return [apply_decision(posting, decision) for posting, decision in zip(postings, decisions)], None


def current_classification(posting: dict) -> bool:
    classification = posting.get("legal_degree_classification")
    return bool(
        posting.get("legal_degree_requirement") in OPTIONS
        and isinstance(classification, dict)
        and classification.get("state") == "completed"
        and classification.get("version") == CLASSIFICATION_VERSION
        and classification.get("input_sha256") == input_sha256(posting)
    )


async def backfill_recent_postings(*, within_days: int = 14, batch_size: int = 20, limit: int | None = None, force: bool = False) -> dict:
    """Classify recent Leads postings and persist results without replacing other research."""
    from app.db import AsyncSessionLocal
    from app.db.models import PifFirmRow
    from app.services.career_job_store import same_job

    within_days = max(1, min(3650, int(within_days)))
    batch_size = max(1, min(50, int(batch_size)))
    cutoff = (date.today() - timedelta(days=within_days)).isoformat()
    async with AsyncSessionLocal() as session:
        firms = list((await session.scalars(select(PifFirmRow).order_by(PifFirmRow.id))).all())

    selected: list[tuple[str, dict]] = []
    for firm in firms:
        jobs = (firm.research_data or {}).get("job_postings") or {}
        for posting in jobs.get("postings") or []:
            if not isinstance(posting, dict) or str(posting.get("posted_date") or "") < cutoff:
                continue
            if not force and current_classification(posting):
                continue
            selected.append((firm.id, dict(posting)))
    if limit is not None:
        selected = selected[:max(0, int(limit))]

    summary = {"within_days": within_days, "cutoff": cutoff, "selected": len(selected), "processed": 0,
               "required": 0, "not_required": 0, "unclear": 0, "errors": []}
    for start in range(0, len(selected), batch_size):
        batch = selected[start:start + batch_size]
        inputs = [{**posting, "candidate_id": f"{firm_id}:{index}"} for index, (firm_id, posting) in enumerate(batch)]
        try:
            decisions = await classify_postings(inputs)
        except Exception as exc:
            summary["errors"].append({"count": len(batch), "error": str(exc)[:1000] or type(exc).__name__})
            continue
        by_firm: dict[str, list[tuple[dict, LegalDegreeDecision]]] = {}
        for (firm_id, posting), decision in zip(batch, decisions):
            by_firm.setdefault(firm_id, []).append((posting, decision))
        async with AsyncSessionLocal() as session:
            for firm_id, updates in by_firm.items():
                firm = await session.get(PifFirmRow, firm_id, with_for_update=True)
                if not firm:
                    continue
                data = dict(firm.research_data or {})
                jobs = dict(data.get("job_postings") or {})
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
