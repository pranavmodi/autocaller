"""TypeSafe Jev classification for a job's contract relationship.

The judgment is made once from extracted job facts and then stored with the
posting. Application preparation and list filters only read the saved result.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select


TYPESAFE_SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
CONTRACT_CLASSIFICATION_VERSION = "jev-contract-v1"
CONTRACT_OPTIONS = ("contract", "non_contract", "unknown")
ContractStatus = Literal["contract", "non_contract", "unknown"]


class ContractDecision(BaseModel):
    candidate_id: str
    status: ContractStatus
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]
    model: str
    usage: dict = Field(default_factory=dict)


def _text(value, *, limit: int = 6000) -> str:
    if value is None:
        return ""
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True)
    return rendered[:limit]


def contract_input(posting: dict) -> dict[str, str]:
    """Return only extracted job facts relevant to the engagement judgment."""
    return {
        key: _text(posting.get(key))
        for key in (
            "title",
            "employment_type",
            "description_summary",
            "responsibilities",
            "qualifications",
            "location",
            "work_arrangement",
            "role_evidence",
        )
    }


def contract_input_sha256(posting: dict) -> str:
    value = json.dumps(contract_input(posting), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _jev_request(postings: list[dict]) -> dict:
    jobs = [contract_input(posting) for posting in postings]
    criteria = {
        "contract": {
            "label": "Contract",
            "definition": (
                "The listing establishes a contractor, independent-contractor, freelance, consulting, "
                "temporary, fixed-term contract, 1099, or business-to-business engagement."
            ),
        },
        "non_contract": {
            "label": "Non-contract",
            "definition": (
                "The listing establishes a regular or permanent employee role, including an ordinary "
                "full-time or part-time employment relationship, rather than a contract engagement."
            ),
        },
        "unknown": {
            "label": "Unknown",
            "definition": (
                "The supplied job facts do not establish the engagement relationship, or the evidence "
                "is conflicting or too ambiguous to choose contract or non-contract."
            ),
        },
    }
    rules = [
        "Judge the work relationship described by the supplied job facts, not the employer, title, or industry alone.",
        "Do not infer contract status merely because a role is remote, project-based, hourly, or uses the word client.",
        "Treat an explicit temporary or fixed-term contract as contract and an explicit permanent employee role as non-contract.",
        "Choose unknown when the listing does not supply enough evidence.",
        "Choose exactly one option.",
    ]
    return {
        "state": {"jobs": jobs},
        "model": os.getenv("JOB_CONTRACT_TYPESAFE_MODEL", "jev-latest"),
        "questions": {
            f"job_{index}": {
                "type": "choice",
                "instructions": {
                    "task": f"What engagement type is established for only `jobs[{index}]`?",
                    "rules": rules,
                },
                "criteria": criteria,
            }
            for index in range(len(jobs))
        },
    }


def _parse_jev_decisions(response: dict, identities: list[str]) -> list[ContractDecision]:
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("TypeSafe response is missing answers.")
    model = response.get("model")
    if not isinstance(model, str) or not model:
        raise ValueError("TypeSafe response is missing its model version.")
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    option_ids = set(CONTRACT_OPTIONS)
    decisions = []
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
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 1
                for value in probabilities.values()
            )
            or abs(sum(probabilities.values()) - 1) > 0.02
        ):
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid probabilities.")
        decisions.append(ContractDecision(
            candidate_id=identity,
            status=choice,
            confidence=float(confidence),
            probabilities={key: float(value) for key, value in probabilities.items()},
            model=model,
            usage=usage,
        ))
    return decisions


async def classify_contract_postings(postings: list[dict]) -> list[ContractDecision]:
    """Classify a batch with one TypeSafe System One request."""
    if not postings:
        return []
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured.")
    identities = [str(posting.get("candidate_id") or index) for index, posting in enumerate(postings)]
    request = _jev_request(postings)
    timeout_s = int(os.getenv("JOB_CONTRACT_CLASSIFICATION_TIMEOUT_S", "120"))
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
            return _parse_jev_decisions(response.json(), identities)
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue
            break
    raise RuntimeError("TypeSafe Jev contract classification request failed.") from last_error


def apply_contract_decision(
    posting: dict,
    decision: ContractDecision,
    *,
    classified_at: datetime | None = None,
) -> dict:
    result = dict(posting)
    observed_at = classified_at or datetime.now(timezone.utc)
    result["contract_status"] = decision.status
    result["contract_classification"] = {
        "state": "completed",
        "version": CONTRACT_CLASSIFICATION_VERSION,
        "provider": "typesafe",
        "model": decision.model,
        "confidence": decision.confidence,
        "probabilities": decision.probabilities,
        "classified_at": observed_at.isoformat(),
        "input_sha256": contract_input_sha256(posting),
    }
    return result


def apply_contract_error(posting: dict, error: Exception, *, classified_at: datetime | None = None) -> dict:
    """Keep extraction usable while making a failed Jev call visible and retryable."""
    result = dict(posting)
    observed_at = classified_at or datetime.now(timezone.utc)
    result["contract_status"] = "unknown"
    result["contract_classification"] = {
        "state": "error",
        "version": CONTRACT_CLASSIFICATION_VERSION,
        "provider": "typesafe",
        "model": None,
        "confidence": None,
        "probabilities": {},
        "classified_at": observed_at.isoformat(),
        "input_sha256": contract_input_sha256(posting),
        "error": str(error)[:1000] or type(error).__name__,
    }
    return result


async def classify_extracted_postings(postings: list[dict]) -> tuple[list[dict], str | None]:
    """Attach one stored Jev judgment per freshly extracted posting."""
    if not postings:
        return [], None
    try:
        decisions = await classify_contract_postings(postings)
    except Exception as exc:
        return [apply_contract_error(posting, exc) for posting in postings], str(exc)[:1000]
    return [apply_contract_decision(posting, decision) for posting, decision in zip(postings, decisions)], None


def current_contract_classification(posting: dict) -> bool:
    classification = posting.get("contract_classification")
    return bool(
        posting.get("contract_status") in CONTRACT_OPTIONS
        and isinstance(classification, dict)
        and classification.get("state") == "completed"
        and classification.get("version") == CONTRACT_CLASSIFICATION_VERSION
    )


def _contract_fields(posting: dict) -> dict:
    return {
        "contract_status": posting.get("contract_status"),
        "contract_classification": posting.get("contract_classification"),
    }


async def _persist_backfill_batch(decisions: list[ContractDecision]) -> dict[str, int]:
    from app.db import AsyncSessionLocal
    from app.db.models import PifFirmRow
    from app.services.career_job_store import same_job
    from app.services.job_agent import JobAgentCandidate, JobAgentEvent, now

    result = {"updated": 0, "mirrors_updated": 0}
    by_id = {decision.candidate_id: decision for decision in decisions}
    async with AsyncSessionLocal() as session:
        rows = list((await session.scalars(
            select(JobAgentCandidate).where(JobAgentCandidate.id.in_(by_id)).with_for_update()
        )).all())
        firm_updates: dict[str, list[dict]] = {}
        for row in rows:
            decision = by_id[row.id]
            updated = apply_contract_decision(row.posting, decision)
            row.posting = updated
            row.updated_at = now()
            row.revision += 1
            result["updated"] += 1
            if updated.get("firm_id"):
                firm_updates.setdefault(str(updated["firm_id"]), []).append(updated)

        for firm_id, candidate_postings in firm_updates.items():
            firm = await session.get(PifFirmRow, firm_id, with_for_update=True)
            if not firm:
                continue
            data = dict(firm.research_data or {})
            jobs = dict(data.get("job_postings") or {})
            postings = [dict(posting) for posting in jobs.get("postings") or [] if isinstance(posting, dict)]
            changed = False
            for candidate_posting in candidate_postings:
                index = next((i for i, posting in enumerate(postings)
                              if same_job(posting, candidate_posting)), None)
                if index is None:
                    continue
                postings[index].update(_contract_fields(candidate_posting))
                result["mirrors_updated"] += 1
                changed = True
            if changed:
                jobs["postings"] = postings
                data["job_postings"] = jobs
                firm.research_data = data
                firm.updated_at = now()

        session.add(JobAgentEvent(
            kind="contract_status_backfill_batch",
            message=f"Classified {result['updated']} jobs by contract status with Jev",
            details={
                "version": CONTRACT_CLASSIFICATION_VERSION,
                "updated": result["updated"],
                "mirrors_updated": result["mirrors_updated"],
            },
        ))
        await session.commit()
    return result


async def backfill_existing_jobs(*, batch_size: int = 20, limit: int | None = None, force: bool = False) -> dict:
    """Resumably classify existing Job Agent rows and their firm-listing mirrors."""
    from app.db import AsyncSessionLocal
    from app.services.job_agent import JobAgentCandidate, JobAgentEvent

    batch_size = max(1, min(50, int(batch_size)))
    async with AsyncSessionLocal() as session:
        rows = list((await session.scalars(
            select(JobAgentCandidate).order_by(JobAgentCandidate.created_at, JobAgentCandidate.id)
        )).all())
    selected = [row for row in rows if force or not current_contract_classification(row.posting)]
    if limit is not None:
        selected = selected[:max(0, int(limit))]

    summary = {
        "version": CONTRACT_CLASSIFICATION_VERSION,
        "total_jobs": len(rows),
        "selected": len(selected),
        "processed": 0,
        "mirrors_updated": 0,
        "contract": 0,
        "non_contract": 0,
        "unknown": 0,
        "errors": [],
    }
    for start in range(0, len(selected), batch_size):
        batch_rows = selected[start:start + batch_size]
        inputs = [{**row.posting, "candidate_id": row.id} for row in batch_rows]
        try:
            decisions = await classify_contract_postings(inputs)
            persisted = await _persist_backfill_batch(decisions)
        except Exception as exc:
            summary["errors"].append({
                "candidate_ids": [row.id for row in batch_rows],
                "error": str(exc)[:1000] or type(exc).__name__,
            })
            continue
        summary["processed"] += persisted["updated"]
        summary["mirrors_updated"] += persisted["mirrors_updated"]
        for decision in decisions:
            summary[decision.status] += 1

    async with AsyncSessionLocal() as session:
        current_rows = list((await session.scalars(select(JobAgentCandidate))).all())
        summary["remaining"] = sum(
            not current_contract_classification(row.posting) for row in current_rows
        )
        session.add(JobAgentEvent(
            kind="contract_status_backfill_completed" if not summary["errors"] else "contract_status_backfill_partial",
            message=(
                f"Contract-status backfill classified {summary['processed']} jobs; "
                f"{summary['remaining']} remain"
            ),
            details=summary,
        ))
        await session.commit()
    return summary
