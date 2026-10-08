"""TypeSafe Jev relevance ranking for structured job-source listings."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone

import httpx

from app.services.job_search_source_adapters import SourceListing


TYPESAFE_SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
CLASSIFICATION_VERSION = "jev-job-source-relevance-v1"
OPTIONS = {"match", "possible", "unrelated"}


def _input_hash(listing: SourceListing, profile: object) -> str:
    value = {
        "listing": listing.compact(),
        "profile": {
            key: getattr(profile, key) for key in (
                "target_roles", "preferred_industries", "industry_mode",
                "location_preferences", "location_mode", "employment_type",
                "employment_mode", "exclusions", "additional_preferences",
            )
        },
        "version": CLASSIFICATION_VERSION,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()


def _request(listings: list[SourceListing], profile: object) -> dict:
    jobs = [{
        "title": item.title,
        "employer": item.employer_name,
        "location": item.location,
        "employment_type": item.employment_type,
        "description": item.description,
        "published_at": item.published_at,
    } for item in listings]
    search = {key: getattr(profile, key) for key in (
        "target_roles", "preferred_industries", "industry_mode",
        "location_preferences", "location_mode", "employment_type",
        "employment_mode", "exclusions", "additional_preferences",
    )}
    criteria = {
        "match": {
            "label": "Likely match",
            "definition": (
                "The supplied listing likely matches a configured target role and does not conflict with any "
                "criterion marked required. Preferred criteria improve fit but are not mandatory."
            ),
        },
        "possible": {
            "label": "Possible match or incomplete evidence",
            "definition": (
                "The listing may match a configured target role, but the supplied facts are incomplete, ambiguous, "
                "or require employer research before required criteria can be decided."
            ),
        },
        "unrelated": {
            "label": "Unrelated or clearly excluded",
            "definition": (
                "The primary responsibilities do not match a configured target role, or supplied facts clearly "
                "conflict with a required location, industry, employment, or exclusion rule."
            ),
        },
    }
    rules = [
        "Judge primary responsibilities, not isolated title words or incidental technology mentions.",
        "Do not invent employer industry, location eligibility, employment type, credentials, or responsibilities.",
        "Use possible when missing evidence prevents a safe match or exclusion.",
        "A preferred criterion cannot by itself exclude a role.",
        "Choose exactly one option for each supplied job.",
    ]
    return {
        "state": {"search": search, "jobs": jobs},
        "model": os.getenv("JOB_SEARCH_RELEVANCE_TYPESAFE_MODEL", "jev-latest"),
        "questions": {
            f"job_{index}": {
                "type": "choice",
                "instructions": {
                    "task": f"How relevant is only `jobs[{index}]` to `search`?",
                    "rules": rules,
                },
                "criteria": criteria,
            }
            for index in range(len(jobs))
        },
    }


def _parse(response: dict, listings: list[SourceListing], profile: object) -> list[SourceListing]:
    answers = response.get("answers") if isinstance(response, dict) else None
    model = response.get("model") if isinstance(response, dict) else None
    usage = response.get("usage") if isinstance(response, dict) and isinstance(response.get("usage"), dict) else {}
    if not isinstance(answers, dict) or not isinstance(model, str) or not model:
        raise ValueError("TypeSafe response is missing answers or model version.")
    classified_at = datetime.now(timezone.utc).isoformat()
    result = []
    for index, listing in enumerate(listings):
        answer = answers.get(f"job_{index}")
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            raise ValueError(f"TypeSafe response is missing Choice answer job_{index}.")
        choice = answer.get("choice")
        probabilities = answer.get("probabilities")
        confidence = answer.get("confidence")
        if choice not in OPTIONS or not isinstance(probabilities, dict) or set(probabilities) != OPTIONS:
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid options.")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid confidence.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1
               for value in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 0.02:
            raise ValueError(f"TypeSafe Choice answer job_{index} has invalid probabilities.")
        listing.relevance = {
            "state": "completed", "version": CLASSIFICATION_VERSION, "provider": "typesafe",
            "model": model, "choice": choice, "confidence": float(confidence),
            "probabilities": {key: float(value) for key, value in probabilities.items()},
            "classified_at": classified_at, "input_sha256": _input_hash(listing, profile), "usage": usage,
        }
        result.append(listing)
    return result


async def _classify_batch(listings: list[SourceListing], profile: object) -> list[SourceListing]:
    api_key = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured.")
    request = _request(listings, profile)
    timeout_s = int(os.getenv("JOB_SEARCH_RELEVANCE_TIMEOUT_S", "120"))
    url = os.getenv("TYPESAFE_SYSTEM_ONE_URL", TYPESAFE_SYSTEM_ONE_URL)
    last_error: Exception | None = None
    attempts = max(1, int(os.getenv("JOB_SEARCH_RELEVANCE_ATTEMPTS", "5")))
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
                response = await client.post(url, headers={
                    "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                }, json=request)
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                retry_after = response.headers.get("retry-after", "")
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = 0
                await asyncio.sleep(min(60, max(delay, 2 * (2**attempt))))
                continue
            response.raise_for_status()
            return _parse(response.json(), listings, profile)
        except (httpx.TransportError, httpx.HTTPStatusError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(min(60, 2 * (2**attempt)))
                continue
            break
    detail = str(last_error)[:500] if last_error else "unknown error"
    raise RuntimeError(f"TypeSafe Jev source-relevance classification failed: {detail}") from last_error


async def rank_source_listings(listings: list[SourceListing], profile: object,
                               *, max_selected: int) -> tuple[list[SourceListing], dict]:
    """Judge every normalized listing, then retain a high-recall ranked shortlist."""
    if not listings:
        return [], {"state": "completed", "version": CLASSIFICATION_VERSION, "checked": 0, "selected": 0}
    try:
        batch_size = int(os.getenv("JOB_SEARCH_RELEVANCE_BATCH_SIZE", "80"))
        concurrency = max(1, int(os.getenv("JOB_SEARCH_RELEVANCE_CONCURRENCY", "1")))
        semaphore = asyncio.Semaphore(concurrency)

        async def classify(batch: list[SourceListing]):
            async with semaphore:
                try:
                    return await _classify_batch(batch, profile), None
                except Exception as exc:
                    return [], str(exc)[:1000]

        outcomes = await asyncio.gather(*(
            classify(listings[start:start + batch_size])
            for start in range(0, len(listings), batch_size)
        ))
        classified = [item for rows, _error in outcomes for item in rows]
        errors = [error for _rows, error in outcomes if error]
        if not classified:
            raise RuntimeError(errors[0] if errors else "No relevance judgments were returned.")
        eligible = [item for item in classified if (
            item.relevance["choice"] in {"match", "possible"}
            or item.relevance["probabilities"]["match"] + item.relevance["probabilities"]["possible"] >= 0.35
        )]
        eligible.sort(key=lambda item: (
            item.relevance["probabilities"]["match"] + 0.5 * item.relevance["probabilities"]["possible"],
            item.published_at or "",
        ), reverse=True)
        selected = eligible[:max_selected]
        return selected, {
            "state": "partial" if errors else "completed", "version": CLASSIFICATION_VERSION,
            "model": classified[0].relevance["model"] if classified else None,
            "checked": len(classified), "eligible": len(eligible), "selected": len(selected),
            "failed_batches": len(errors), "errors": errors, "threshold": 0.35,
        }
    except Exception as exc:
        # The slower web-research path still runs. No string heuristic substitutes
        # for the missing semantic judgment.
        return [], {"state": "error", "version": CLASSIFICATION_VERSION,
                    "checked": 0, "selected": 0, "error": str(exc)[:1000]}
