"""Versioned operational classification for source-backed PI firm reviews."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmReviewRow, PifFirmRow
from app.services.llm_gateway import call_skill_json


CLASSIFICATION_VERSION = "pi_reviews_v1"
SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/firm-review-classification/SKILL.md"
BATCH_SIZE = max(1, min(25, int(os.getenv("FIRM_REVIEW_CLASSIFICATION_BATCH_SIZE", "10"))))
CONCURRENCY = max(1, min(8, int(os.getenv("FIRM_REVIEW_CLASSIFICATION_CONCURRENCY", "1"))))

VOCABULARY: dict[str, set[str]] = {
    "overall_sentiment": {"positive", "negative", "mixed", "neutral"},
    "journey_stages": {
        "initial_contact", "intake", "case_evaluation", "signing_and_handoff",
        "medical_treatment", "case_management", "negotiation", "litigation",
        "settlement", "disbursement", "post_case", "unknown",
    },
    "praise_drivers": {
        "fast_initial_response", "frequent_updates", "easy_to_reach",
        "clear_explanations", "felt_cared_for", "staff_went_beyond_role",
        "smooth_process", "strong_outcome", "faster_than_expected",
        "transparent_fees", "effective_medical_coordination",
        "specific_employee_excellence",
    },
    "failure_modes": {
        "no_callback", "status_silence", "attorney_unreachable",
        "unclear_case_owner", "poor_handoff_after_signing",
        "repeated_document_requests", "staff_turnover", "unexpected_delay",
        "unexpected_fee_or_deduction", "settlement_expectation_mismatch",
        "medical_coordination_failure", "case_dropped_or_rejected",
        "payment_delay", "rude_or_dismissive_treatment",
        "promised_action_not_completed", "client_did_not_understand_process",
    },
    "staff_roles_mentioned": {
        "attorney", "case_manager", "paralegal", "intake_specialist",
        "receptionist", "medical_coordinator", "settlement_team",
        "firm_generally", "unknown",
    },
    "satisfaction": {"positive", "negative", "mixed", "neutral", "unknown"},
    "outcome_status": {
        "positive_outcome", "negative_outcome", "case_declined",
        "case_withdrawn", "settled", "went_to_trial", "still_open",
        "outcome_not_mentioned",
    },
    "actionability": {
        "directly_controllable", "partially_controllable", "mostly_external",
        "outcome_dependent", "unclear",
    },
    "operational_owners": {
        "intake", "case_management", "legal", "medical_coordination",
        "settlement", "finance", "leadership", "marketing_reputation",
    },
    "referral_intent": {"positive", "negative", "none", "unclear"},
    "information_density": {"high", "medium", "low"},
    "firsthand_signal": {"firsthand", "third_party", "unclear"},
    "source_quality": {
        "independent_review", "firm_curated_testimonial",
        "aggregator_republication", "unknown",
    },
}

THEMES = {
    "response_speed", "returned_calls", "proactive_updates",
    "attorney_accessibility", "case_manager_accessibility", "explanation",
    "expectation_setting", "empathy_and_respect", "professionalism",
    "staff_ownership", "internal_handoffs", "staff_continuity",
    "medical_coordination", "paperwork", "case_duration",
    "settlement_process", "settlement_amount", "fees_and_deductions",
    "payment_delivery", "language_accessibility", "technology_experience",
    "referral_willingness",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any, limit: int = 2_000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def review_id(source: dict[str, Any], review: dict[str, Any]) -> str:
    identity = "|".join([
        _clean(source.get("source"), 64).lower(),
        _clean(source.get("listing_url"), 1_000).lower().rstrip("/"),
        _clean(review.get("review_url"), 1_000).lower().rstrip("/"),
        _clean(review.get("reviewer_name"), 255).lower(),
        _clean(review.get("review_date"), 32),
        _clean(review.get("text"), 20_000).lower(),
    ])
    return f"review_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def ensure_review_ids(reviews_json: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(reviews_json) if isinstance(reviews_json, dict) else {}
    for source in data.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for review in source.get("reviews") or []:
            if isinstance(review, dict):
                review["review_id"] = review_id(source, review)
    return data


def _enum(value: Any, vocabulary: str, default: str) -> str:
    candidate = _clean(value, 64).lower()
    return candidate if candidate in VOCABULARY[vocabulary] else default


def _enum_list(value: Any, vocabulary: str) -> list[str]:
    values = value if isinstance(value, list) else []
    allowed = VOCABULARY[vocabulary]
    return list(dict.fromkeys(_clean(item, 64).lower() for item in values if _clean(item, 64).lower() in allowed))


def _string_list(value: Any, *, limit: int, item_limit: int, lower: bool = False) -> list[str]:
    values = value if isinstance(value, list) else []
    cleaned = [_clean(item, item_limit) for item in values]
    if lower:
        cleaned = [item.lower() for item in cleaned]
    return list(dict.fromkeys(item for item in cleaned if item))[:limit]


def normalize_classification(raw: Any, expected_review_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or _clean(raw.get("review_id"), 64) != expected_review_id:
        return None
    themes: list[dict[str, Any]] = []
    for item in raw.get("themes") if isinstance(raw.get("themes"), list) else []:
        if not isinstance(item, dict):
            continue
        theme = _clean(item.get("theme"), 64).lower()
        if theme not in THEMES:
            continue
        try:
            intensity = max(1, min(3, int(item.get("intensity") or 1)))
        except (TypeError, ValueError):
            intensity = 1
        themes.append({
            "theme": theme,
            "sentiment": _enum(item.get("sentiment"), "overall_sentiment", "neutral"),
            "intensity": intensity,
            "evidence": _clean(item.get("evidence"), 500) or None,
            "explicit_or_inferred": (
                "explicit" if _clean(item.get("explicit_or_inferred"), 32).lower() == "explicit" else "inferred"
            ),
        })
    try:
        sentiment_score = max(-1.0, min(1.0, float(raw.get("sentiment_score") or 0)))
    except (TypeError, ValueError):
        sentiment_score = 0.0
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "classification_version": CLASSIFICATION_VERSION,
        "classified_at": _utcnow().isoformat(),
        "overall_sentiment": _enum(raw.get("overall_sentiment"), "overall_sentiment", "neutral"),
        "sentiment_score": round(sentiment_score, 3),
        "language": _clean(raw.get("language"), 16).lower() or "unknown",
        "source_quality": _enum(raw.get("source_quality"), "source_quality", "unknown"),
        "journey_stages": _enum_list(raw.get("journey_stages"), "journey_stages") or ["unknown"],
        "case_types": _string_list(raw.get("case_types"), limit=10, item_limit=64, lower=True),
        "themes": themes,
        "praise_drivers": _enum_list(raw.get("praise_drivers"), "praise_drivers"),
        "failure_modes": _enum_list(raw.get("failure_modes"), "failure_modes"),
        "staff_roles_mentioned": _enum_list(raw.get("staff_roles_mentioned"), "staff_roles_mentioned"),
        "named_people": _string_list(raw.get("named_people"), limit=20, item_limit=255),
        "process_satisfaction": _enum(raw.get("process_satisfaction"), "satisfaction", "unknown"),
        "outcome_status": _enum(raw.get("outcome_status"), "outcome_status", "outcome_not_mentioned"),
        "outcome_satisfaction": _enum(raw.get("outcome_satisfaction"), "satisfaction", "unknown"),
        "actionability": _enum_list(raw.get("actionability"), "actionability") or ["unclear"],
        "operational_owners": _enum_list(raw.get("operational_owners"), "operational_owners"),
        "referral_intent": _enum(raw.get("referral_intent"), "referral_intent", "unclear"),
        "information_density": _enum(raw.get("information_density"), "information_density", "low"),
        "firsthand_signal": _enum(raw.get("firsthand_signal"), "firsthand_signal", "unclear"),
        "quality_flags": _string_list(raw.get("quality_flags"), limit=20, item_limit=64, lower=True),
        "summary": _clean(raw.get("summary"), 1_000) or None,
        "confidence": round(confidence, 3),
    }


def _review_inputs(data: dict[str, Any], *, force: bool) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for source in data.get("sources") or []:
        if not isinstance(source, dict):
            continue
        for review in source.get("reviews") or []:
            if not isinstance(review, dict):
                continue
            classification = review.get("classification")
            if not force and isinstance(classification, dict) and classification.get("classification_version") == CLASSIFICATION_VERSION:
                continue
            inputs.append({
                "review_id": review.get("review_id"),
                "source": source.get("source"),
                "listing_url": source.get("listing_url"),
                "reviewer_name": review.get("reviewer_name"),
                "rating": review.get("rating"),
                "review_date": review.get("review_date"),
                "text": review.get("text"),
            })
    return inputs


async def _classify_batch(firm_name: str, reviews: list[dict[str, Any]], semaphore: asyncio.Semaphore) -> list[dict[str, Any]]:
    batch_key = hashlib.sha256(
        "|".join(str(review.get("review_id") or "") for review in reviews).encode("utf-8")
    ).hexdigest()[:16]
    async with semaphore:
        result = await call_skill_json(
            skill_path=SKILL_PATH,
            payload={"firm_name": firm_name, "reviews": reviews},
            required_fields=["classifications"],
            model=os.getenv("FIRM_REVIEW_CLASSIFICATION_MODEL", "openclaw/main"),
            timeout_s=int(os.getenv("FIRM_REVIEW_CLASSIFICATION_TIMEOUT_S", "120")),
            max_tokens=int(os.getenv("FIRM_REVIEW_CLASSIFICATION_MAX_TOKENS", "8000")),
            retries=1,
            gateway_user=f"firm-review-classification:{batch_key}:{uuid.uuid4().hex[:8]}",
        )
    raw_rows = result.parsed.get("classifications")
    return [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []


async def classify_reviews_json(
    firm_name: str,
    reviews_json: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    data = ensure_review_ids(reviews_json)
    inputs = _review_inputs(data, force=force)
    if inputs:
        semaphore = asyncio.Semaphore(CONCURRENCY)
        batches = [inputs[index:index + BATCH_SIZE] for index in range(0, len(inputs), BATCH_SIZE)]
        batch_results = await asyncio.gather(*(
            _classify_batch(firm_name, batch, semaphore) for batch in batches
        ), return_exceptions=True)
        raw_batches = [result for result in batch_results if isinstance(result, list)]
        batch_errors = [str(result)[:500] for result in batch_results if isinstance(result, BaseException)]
        expected = {row["review_id"] for row in inputs}
        normalized: dict[str, dict[str, Any]] = {}
        for raw in (item for batch in raw_batches for item in batch):
            candidate_id = _clean(raw.get("review_id"), 64)
            if candidate_id not in expected:
                continue
            classification = normalize_classification(raw, candidate_id)
            if classification:
                normalized[candidate_id] = classification
        for source in data.get("sources") or []:
            for review in source.get("reviews") or []:
                candidate = normalized.get(review.get("review_id"))
                if candidate:
                    review["classification"] = candidate
        if batch_errors:
            data["classification_errors"] = batch_errors
        else:
            data.pop("classification_errors", None)

    all_reviews = [
        review
        for source in data.get("sources") or [] if isinstance(source, dict)
        for review in source.get("reviews") or [] if isinstance(review, dict)
    ]
    classified_count = sum(
        isinstance(review.get("classification"), dict)
        and review["classification"].get("classification_version") == CLASSIFICATION_VERSION
        for review in all_reviews
    )
    data.update({
        "classification_version": CLASSIFICATION_VERSION,
        "classification_status": "completed" if classified_count == len(all_reviews) else "partial",
        "classified_at": _utcnow().isoformat(),
        "classified_count": classified_count,
        "unclassified_count": len(all_reviews) - classified_count,
    })
    return data


async def backfill_review_classifications(*, force: bool = False) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FirmReviewRow, PifFirmRow.firm_name)
            .join(PifFirmRow, PifFirmRow.id == FirmReviewRow.pif_id)
            .where(FirmReviewRow.reviews_json["sources"].isnot(None))
            .order_by(FirmReviewRow.updated_at.asc())
        )).all()
    result = {"firms_total": len(rows), "firms_completed": 0, "reviews_classified": 0, "failures": []}
    for review_row, firm_name in rows:
        try:
            classified = review_row.reviews_json
            for attempt in range(2):
                classified = await classify_reviews_json(
                    str(firm_name or ""),
                    classified,
                    force=force and attempt == 0,
                )
                if classified.get("classification_status") == "completed":
                    break
            async with AsyncSessionLocal() as session:
                current = await session.get(FirmReviewRow, review_row.pif_id)
                if current is None:
                    continue
                current.reviews_json = classified
                current.updated_at = _utcnow()
                await session.commit()
            result["firms_completed"] += 1
            result["reviews_classified"] += int(classified.get("classified_count") or 0)
        except Exception as exc:
            result["failures"].append({"pif_id": review_row.pif_id, "firm_name": firm_name, "error": str(exc)[:500]})
    return result
