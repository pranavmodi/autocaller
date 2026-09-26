"""Firm research snapshots, LLM-validated change detection, and GTM ranking."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from openai import AsyncOpenAI
from sqlalchemy import exists, func, or_, select

from app.db import AsyncSessionLocal
from app.db.models import (
    FirmEvidenceRow,
    FirmResearchSnapshotRow,
    FirmResearchStateRow,
    FirmTriggerEventRow,
    FirmVendorRelationshipRow,
    PifFirmRow,
)
from app.services.pif_count_ranges import count_ranges_condition
from app.services.llm_gateway import LLMGatewayError, call_skill_json, prompt_cache_metrics


MODULE_PROFILE = "firm_profile"
MODULE_SITEMAP = "sitemap"
MODULE_JOBS = "job_postings"
MODULE_REVIEWS = "reviews"
RESEARCH_MODULES = (MODULE_PROFILE, MODULE_SITEMAP, MODULE_JOBS, MODULE_REVIEWS)

logger = logging.getLogger(__name__)
TRIGGER_DETECTOR_VERSION = "firm_trigger_llm_v2"
TRIGGER_DETECTOR_SKILL = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "firm-trigger-change-detection"
    / "SKILL.md"
)
TRIGGER_DECISIONS = {
    "confirmed_change",
    "newly_discovered_existing_fact",
    "same_entity_or_restatement",
    "source_coverage_change",
    "ambiguous",
    "not_gtm_relevant",
}
TRIGGER_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "decision": {"type": "string", "enum": sorted(TRIGGER_DECISIONS)},
                    "emit_trigger": {"type": "boolean"},
                    "event_type": {"type": ["string", "null"]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "source_date": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 3},
                    "reason": {"type": "string"},
                },
                "required": [
                    "candidate_id", "decision", "emit_trigger", "event_type", "title",
                    "summary", "source_date", "confidence", "score", "severity", "reason",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["decisions"],
    "additionalProperties": False,
}

EVENT_CONFIG: dict[str, tuple[str, int, int]] = {
    "ai_adoption_changed": ("technology", 84, 3),
    "ai_leadership_statement": ("technology", 72, 2),
    "vendor_added": ("technology", 82, 3),
    "vendor_removed": ("technology", 58, 2),
    "vendor_migration_detected": ("technology", 90, 3),
    "practice_area_added": ("business", 76, 3),
    "office_added": ("expansion", 72, 3),
    "leadership_added": ("team", 48, 1),
    "firm_size_changed": ("team", 44, 1),
    "sitemap_pages_added": ("website", 36, 1),
    "sitemap_pages_removed": ("website", 28, 1),
    "high_value_practice_page_added": ("business", 80, 3),
    "location_page_added": ("expansion", 67, 2),
    "intake_surface_added": ("intake", 73, 3),
    "job_posting_added": ("hiring", 54, 2),
    "intake_job_posted": ("hiring", 78, 3),
    "marketing_job_posted": ("hiring", 72, 3),
    "technology_job_posted": ("hiring", 80, 3),
    "operations_job_posted": ("hiring", 64, 2),
    "reviews_added": ("reputation", 34, 1),
    "negative_reviews_added": ("reputation", 74, 3),
    "review_pain_detected": ("reputation", 82, 3),
}

EVENT_MODULES = {
    **{event_type: MODULE_PROFILE for event_type in (
        "vendor_added", "vendor_removed", "vendor_migration_detected",
        "practice_area_added", "office_added", "leadership_added", "firm_size_changed",
        "ai_adoption_changed", "ai_leadership_statement",
    )},
    **{event_type: MODULE_SITEMAP for event_type in (
        "sitemap_pages_added", "sitemap_pages_removed", "high_value_practice_page_added",
        "location_page_added", "intake_surface_added",
    )},
    **{event_type: MODULE_JOBS for event_type in (
        "job_posting_added", "intake_job_posted", "marketing_job_posted",
        "technology_job_posted", "operations_job_posted",
    )},
    **{event_type: MODULE_REVIEWS for event_type in (
        "reviews_added", "negative_reviews_added", "review_pain_detected",
    )},
}

HIGH_VALUE_PRACTICE_TERMS = {
    "truck": "Truck accidents",
    "semi-truck": "Truck accidents",
    "tractor-trailer": "Truck accidents",
    "wrongful-death": "Wrongful death",
    "mass-tort": "Mass torts",
    "rideshare": "Rideshare accidents",
    "uber": "Rideshare accidents",
    "lyft": "Rideshare accidents",
    "catastrophic": "Catastrophic injury",
    "motorcycle": "Motorcycle accidents",
    "product-liability": "Product liability",
    "sexual-abuse": "Sexual abuse",
}
INTAKE_PATH_TERMS = (
    "free-case-evaluation", "case-evaluation", "free-consultation", "schedule-consultation",
    "book-consultation", "get-started", "contact-us", "chat-with-us",
)
LOCATION_PATH_TERMS = ("/locations/", "/location/", "/offices/", "/office/")

VENDOR_ALIASES = {
    "8am casepeer": ("casepeer", "8am CasePeer"),
    "case peer": ("casepeer", "CasePeer"),
    "casepeer": ("casepeer", "CasePeer"),
    "clio grow": ("clio", "Clio Grow"),
    "clio manage": ("clio", "Clio Manage"),
    "clio": ("clio", "Clio"),
    "lead docket": ("lead_docket", "Lead Docket"),
    "leaddocket": ("lead_docket", "Lead Docket"),
    "filevine": ("filevine", "Filevine"),
    "lawmatics": ("lawmatics", "Lawmatics"),
    "law ruler": ("law_ruler", "Law Ruler"),
    "lawruler": ("law_ruler", "Law Ruler"),
    "callrail": ("callrail", "CallRail"),
    "call rail": ("callrail", "CallRail"),
    "smartadvocate": ("smartadvocate", "SmartAdvocate"),
    "litify": ("litify", "Litify"),
    "captorra": ("captorra", "Captorra"),
    "ngage": ("ngage", "Ngage"),
    "vinesign": ("vinesign", "Vinesign"),
    "smith.ai": ("smith_ai", "Smith.ai"),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any, limit: int = 2_000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _clean(value, 255).casefold()).strip("_")


def _confidence(value: Any, default: float = 0.65) -> float:
    labels = {"high": 0.9, "medium": 0.7, "low": 0.45}
    if isinstance(value, str) and value.strip().lower() in labels:
        return labels[value.strip().lower()]
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> datetime | None:
    raw = _clean(value, 64).replace("Z", "+00:00")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{raw}T00:00:00+00:00")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _named_values(values: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in _as_list(values):
        if isinstance(raw, dict):
            text = _clean(raw.get("name") or raw.get("label") or raw.get("value"), 255)
        else:
            text = _clean(raw, 255)
        if text:
            result.setdefault(_key(text), text)
    return result


def _vendor_identity(name: Any, product: Any = None) -> tuple[str, str]:
    raw_name = _clean(name, 128)
    raw_product = _clean(product, 128)
    normalized = re.sub(r"[^a-z0-9.]+", " ", raw_name.casefold()).strip()
    if normalized in VENDOR_ALIASES:
        vendor, default_product = VENDOR_ALIASES[normalized]
        return vendor, raw_product or default_product
    vendor = _key(raw_name)
    return vendor, raw_product or raw_name


def normalize_vendor_snapshot(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize all supported vendor-stack shapes into stable relationships."""
    rows: list[dict[str, Any]] = []
    if isinstance(value, list):
        rows.extend(dict(item) for item in value if isinstance(item, dict))
    elif isinstance(value, dict):
        stack = dict(value)
        rows.extend(dict(item) for item in _as_list(stack.get("evidence")) if isinstance(item, dict))
        case_mgmt = stack.get("case_mgmt")
        if case_mgmt:
            rows.append({"vendor": case_mgmt, "source": "case_mgmt"})
        for vendor, detail in _as_dict(stack.get("other")).items():
            if isinstance(detail, str):
                row = {"vendor": detail, "source": vendor}
            else:
                row = dict(detail) if isinstance(detail, dict) else {}
                row.setdefault("vendor", vendor)
                row.setdefault("source", "other")
            rows.append(row)

    vendors: dict[str, dict[str, Any]] = {}
    for row in rows:
        vendor, product = _vendor_identity(row.get("vendor") or row.get("name"), row.get("product"))
        if not vendor:
            continue
        identity = f"{vendor}:{_key(product)}"
        evidence = {
            "source": _clean(row.get("source") or row.get("evidence_type"), 64) or None,
            "source_url": _clean(row.get("source_url") or row.get("url"), 2_000) or None,
            "published_at": _clean(row.get("published_at") or row.get("source_date"), 64) or None,
            "excerpt": _clean(row.get("evidence") or row.get("excerpt"), 1_000) or None,
            "confidence": _confidence(row.get("confidence")),
        }
        current = vendors.setdefault(identity, {
            "vendor": vendor,
            "product": product,
            "confidence": evidence["confidence"],
            "evidence": [],
        })
        current["confidence"] = max(float(current["confidence"]), float(evidence["confidence"]))
        if any(evidence.values()):
            current["evidence"].append(evidence)
    return vendors


def normalize_profile_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    leadership: dict[str, dict[str, Any]] = {}
    for person in _as_list(value.get("leadership")):
        if not isinstance(person, dict):
            continue
        name = _clean(person.get("name"), 255)
        if name:
            leadership[_key(name)] = {
                "name": name,
                "title": _clean(person.get("title"), 255) or None,
                "source_url": _source_url(person.get("source_url")),
            }
    sources = sorted({
        url for raw in [*_as_list(value.get("sources")), *_as_list(value.get("website_sources"))]
        if (url := _source_url(raw))
    })
    return {
        "practice_areas": _named_values(value.get("practice_areas")),
        "office_locations": _named_values(value.get("office_locations")),
        "leadership": leadership,
        "firm_size": _clean(value.get("firm_size"), 64) or None,
        "vendors": normalize_vendor_snapshot(value.get("vendor_stack")),
        "ai_adoption": normalize_ai_snapshot(value.get("ai_adoption")),
        "sources": sources,
    }


def normalize_ai_snapshot(value: Any) -> dict[str, Any]:
    posture = _as_dict(value)
    if not posture:
        return {}
    return {
        "adoption_stage": posture.get("adoption_stage", "unknown"),
        "leadership_stance": posture.get("leadership_stance", "unknown"),
        "statements": sorted(
            [item for item in _as_list(posture.get("statements")) if isinstance(item, dict)],
            key=_json_hash,
        ),
    }


def normalize_sitemap_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    urls = sorted({_clean(item, 2_000) for item in _as_list(value.get("urls")) if _clean(item, 2_000)})
    return {"urls": urls, "website": _clean(value.get("website"), 512) or None}


def _review_identity(source: dict[str, Any], review: dict[str, Any]) -> str:
    return _clean(review.get("review_id") or review.get("text_hash"), 128) or _json_hash({
        "source": source.get("source"),
        "listing_url": source.get("listing_url"),
        "reviewer": review.get("reviewer_name"),
        "date": review.get("review_date"),
        "text": review.get("text"),
    })


def normalize_reviews_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    reviews: dict[str, dict[str, Any]] = {}
    for source in _as_list(value.get("sources")):
        if not isinstance(source, dict):
            continue
        for review in _as_list(source.get("reviews")):
            if not isinstance(review, dict) or not _clean(review.get("text"), 20_000):
                continue
            classification = _as_dict(review.get("classification"))
            themes = [
                _clean(item.get("theme"), 64)
                for item in _as_list(classification.get("themes"))
                if isinstance(item, dict) and _clean(item.get("theme"), 64)
            ]
            review_id = _review_identity(source, review)
            reviews[review_id] = {
                "review_id": review_id,
                "source": _clean(source.get("source"), 64) or "other",
                "listing_url": _clean(source.get("listing_url"), 2_000) or None,
                "review_url": _clean(review.get("review_url"), 2_000) or None,
                "reviewer_name": _clean(review.get("reviewer_name"), 255) or None,
                "review_date": _clean(review.get("review_date"), 32) or None,
                "rating": review.get("rating"),
                "text": _clean(review.get("text"), 2_000),
                "sentiment": _clean(classification.get("overall_sentiment"), 32) or None,
                "themes": sorted(set(themes)),
                "failure_modes": sorted({_clean(item, 64) for item in _as_list(classification.get("failure_modes")) if _clean(item, 64)}),
                "confidence": _confidence(classification.get("confidence"), 0.6),
            }
    return {"reviews": reviews}


def _posting_identity(posting: dict[str, Any]) -> str:
    url = _clean(posting.get("source_url") or posting.get("url"), 2_000).lower().rstrip("/")
    if url:
        return _json_hash({"url": url})
    return _json_hash({
        "title": _clean(posting.get("title"), 255).casefold(),
        "date": posting.get("posted_date"),
        "location": _clean(posting.get("location"), 255).casefold(),
    })


def normalize_jobs_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    postings: dict[str, dict[str, Any]] = {}
    for posting in _as_list(value.get("postings")):
        if not isinstance(posting, dict) or not _clean(posting.get("title"), 255):
            continue
        posting_id = _posting_identity(posting)
        postings[posting_id] = {
            "posting_id": posting_id,
            "title": _clean(posting.get("title"), 255),
            "posted_date": _clean(posting.get("posted_date"), 32) or None,
            "source_url": _clean(posting.get("source_url") or posting.get("url"), 2_000) or None,
            "location": _clean(posting.get("location"), 255) or None,
            "role_category": _clean(posting.get("role_category"), 64) or "other",
            "trigger_tags": sorted({_clean(item, 64) for item in _as_list(posting.get("trigger_tags")) if _clean(item, 64)}),
            "technology_mentions": sorted({_clean(item, 128) for item in _as_list(posting.get("technology_mentions")) if _clean(item, 128)}),
            "gtm_relevance": _clean(posting.get("gtm_relevance"), 16) or "low",
            "classification_confidence": _confidence(posting.get("classification_confidence"), 0.6),
        }
    return {"postings": postings}


def normalize_snapshot(module: str, payload: dict[str, Any]) -> dict[str, Any]:
    if module == MODULE_PROFILE:
        return normalize_profile_snapshot(payload)
    if module == MODULE_SITEMAP:
        return normalize_sitemap_snapshot(payload)
    if module == MODULE_REVIEWS:
        return normalize_reviews_snapshot(payload)
    if module == MODULE_JOBS:
        return normalize_jobs_snapshot(payload)
    raise ValueError(f"unsupported_research_module:{module}")


def _event(
    event_type: str,
    title: str,
    *,
    summary: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    source_date: datetime | None = None,
    confidence: float = 0.75,
) -> dict[str, Any]:
    category, score, severity = EVENT_CONFIG[event_type]
    return {
        "event_type": event_type,
        "category": category,
        "title": title,
        "summary": summary,
        "old_value": old_value or {},
        "new_value": new_value or {},
        "evidence": evidence or [],
        "source_date": source_date,
        "confidence": confidence,
        "score": score,
        "severity": severity,
    }


def diff_profile_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    old_ai = _as_dict(previous.get("ai_adoption"))
    new_ai = _as_dict(current.get("ai_adoption"))
    if old_ai != new_ai and new_ai.get("statements"):
        events.append(_event(
            "ai_adoption_changed", "AI adoption or leadership position observed",
            summary="Source-backed AI observations require semantic and timing review.",
            old_value=old_ai, new_value=new_ai,
            evidence=[{
                "source": statement.get("source_type"),
                "source_url": statement.get("source_url"),
                "published_at": statement.get("published_at"),
                "excerpt": statement.get("quote") or statement.get("summary"),
            } for statement in new_ai["statements"]],
            confidence=0.7,
        ))
    profile_evidence = [
        {"source": "firm_research", "source_url": url, "confidence": 0.78}
        for url in _as_list(current.get("sources"))[:10]
    ]
    for key in sorted(set(_as_dict(current.get("practice_areas"))) - set(_as_dict(previous.get("practice_areas")))):
        value = current["practice_areas"][key]
        events.append(_event(
            "practice_area_added", f"New practice area: {value}",
            summary="The firm now presents this as a practice area.",
            new_value={"practice_area": value}, evidence=profile_evidence, confidence=0.82,
        ))
    for key in sorted(set(_as_dict(current.get("office_locations"))) - set(_as_dict(previous.get("office_locations")))):
        value = current["office_locations"][key]
        events.append(_event(
            "office_added", f"New office or market: {value}",
            summary="A new office location appeared in firm research.",
            new_value={"office": value}, evidence=profile_evidence, confidence=0.8,
        ))
    for key in sorted(set(_as_dict(current.get("leadership"))) - set(_as_dict(previous.get("leadership")))):
        person = current["leadership"][key]
        events.append(_event(
            "leadership_added", f"Leadership addition: {person['name']}",
            summary=person.get("title"), new_value=person,
            evidence=[{
                "source": "leadership_profile",
                "source_url": person.get("source_url"),
                "excerpt": " · ".join(filter(None, [person.get("name"), person.get("title")])),
                "confidence": 0.82,
            }] if person.get("source_url") else profile_evidence,
            confidence=0.72,
        ))
    old_size = previous.get("firm_size")
    new_size = current.get("firm_size")
    if old_size and new_size and old_size != new_size:
        events.append(_event(
            "firm_size_changed", f"Firm size changed to {new_size}",
            summary=f"Previously recorded as {old_size}.",
            old_value={"firm_size": old_size}, new_value={"firm_size": new_size},
            evidence=profile_evidence, confidence=0.7,
        ))
    return events


def _url_path(value: str) -> str:
    try:
        return urlparse(value).path.casefold()
    except ValueError:
        return value.casefold()


def diff_sitemap_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    old_urls = set(_as_list(previous.get("urls")))
    new_urls = set(_as_list(current.get("urls")))
    added = sorted(new_urls - old_urls)
    removed = sorted(old_urls - new_urls)
    events: list[dict[str, Any]] = []
    if added:
        evidence = [{"source": "sitemap", "source_url": url, "confidence": 0.96} for url in added[:20]]
        events.append(_event(
            "sitemap_pages_added", f"{len(added)} website page{'s' if len(added) != 1 else ''} added",
            summary="The sitemap contains URLs absent from the previous successful snapshot.",
            new_value={"urls": added[:100]}, evidence=evidence, confidence=0.96,
        ))
    if removed:
        evidence = [{"source": "previous_sitemap", "source_url": url, "confidence": 0.94} for url in removed[:20]]
        events.append(_event(
            "sitemap_pages_removed", f"{len(removed)} website page{'s' if len(removed) != 1 else ''} removed",
            summary="These URLs were absent from the current successful sitemap snapshot.",
            old_value={"urls": removed[:100]}, evidence=evidence, confidence=0.94,
        ))

    practices: dict[str, list[str]] = {}
    location_urls: list[str] = []
    intake_urls: list[str] = []
    for url in added:
        path = _url_path(url)
        for term, label in HIGH_VALUE_PRACTICE_TERMS.items():
            if term in path:
                practices.setdefault(label, []).append(url)
        if any(term in path for term in LOCATION_PATH_TERMS):
            location_urls.append(url)
        if any(term in path for term in INTAKE_PATH_TERMS):
            intake_urls.append(url)
    for label, urls in sorted(practices.items()):
        events.append(_event(
            "high_value_practice_page_added", f"New {label} pages",
            summary="The sitemap indicates a possible new or expanded high-value line of business.",
            new_value={"practice_area": label, "urls": urls[:20]},
            evidence=[{"source": "sitemap", "source_url": url, "confidence": 0.86} for url in urls[:20]],
            confidence=0.86,
        ))
    if location_urls:
        events.append(_event(
            "location_page_added", "New location pages detected",
            summary="The website added one or more office or location URLs.",
            new_value={"urls": location_urls[:20]},
            evidence=[{"source": "sitemap", "source_url": url, "confidence": 0.82} for url in location_urls[:20]],
            confidence=0.82,
        ))
    if intake_urls:
        events.append(_event(
            "intake_surface_added", "New intake or consultation page detected",
            summary="The website added a conversion-oriented contact or consultation URL.",
            new_value={"urls": intake_urls[:20]},
            evidence=[{"source": "sitemap", "source_url": url, "confidence": 0.82} for url in intake_urls[:20]],
            confidence=0.82,
        ))
    return events


def diff_job_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    previous_postings = _as_dict(previous.get("postings"))
    current_postings = _as_dict(current.get("postings"))
    events: list[dict[str, Any]] = []
    for posting_id in sorted(set(current_postings) - set(previous_postings)):
        posting = current_postings[posting_id]
        category = posting.get("role_category")
        event_type = {
            "intake_conversion": "intake_job_posted",
            "marketing_growth": "marketing_job_posted",
            "technology_data": "technology_job_posted",
            "firm_operations": "operations_job_posted",
            "case_operations": "operations_job_posted",
            "client_communication": "operations_job_posted",
        }.get(category, "job_posting_added")
        evidence = [{
            "source": "job_posting",
            "source_url": posting.get("source_url"),
            "published_at": posting.get("posted_date"),
            "excerpt": posting.get("title"),
            "confidence": posting.get("classification_confidence"),
        }]
        events.append(_event(
            event_type, f"New opening: {posting['title']}",
            summary=" · ".join(filter(None, [posting.get("role_category"), posting.get("location")])),
            new_value=posting, evidence=evidence,
            source_date=_parse_datetime(posting.get("posted_date")),
            confidence=float(posting.get("classification_confidence") or 0.65),
        ))
    return events


def diff_review_snapshots(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    reference_time: datetime | None = None,
) -> list[dict[str, Any]]:
    prior_reviews = _as_dict(previous.get("reviews"))
    current_reviews = _as_dict(current.get("reviews"))
    cutoff = (reference_time or _utcnow()) - timedelta(days=30)
    added = [
        current_reviews[key]
        for key in sorted(set(current_reviews) - set(prior_reviews))
        if (
            (published_at := _parse_datetime(current_reviews[key].get("review_date"))) is not None
            and published_at >= cutoff
        )
    ]
    if not added:
        return []
    evidence = [{
        "source": review.get("source"),
        "source_url": review.get("review_url") or review.get("listing_url"),
        "published_at": review.get("review_date"),
        "excerpt": review.get("text"),
        "confidence": review.get("confidence"),
    } for review in added[:20]]
    dated = [_parse_datetime(review.get("review_date")) for review in added]
    source_date = max((value for value in dated if value is not None), default=None)
    events = [_event(
        "reviews_added", f"{len(added)} new public review{'s' if len(added) != 1 else ''}",
        summary="New source-backed review text was collected since the previous snapshot.",
        new_value={"review_ids": [review["review_id"] for review in added]},
        evidence=evidence, source_date=source_date, confidence=0.94,
    )]
    negative = []
    pain_modes: set[str] = set()
    pain_themes: set[str] = set()
    for review in added:
        try:
            rating = float(review.get("rating"))
        except (TypeError, ValueError):
            rating = 0
        if (rating and rating <= 2) or review.get("sentiment") == "negative":
            negative.append(review)
        pain_modes.update(review.get("failure_modes") or [])
        if review.get("sentiment") == "negative":
            pain_themes.update(review.get("themes") or [])
    if negative:
        events.append(_event(
            "negative_reviews_added", f"{len(negative)} new negative review{'s' if len(negative) != 1 else ''}",
            summary="Recent public reviews contain negative client experiences.",
            new_value={"review_ids": [review["review_id"] for review in negative]},
            evidence=evidence, source_date=source_date, confidence=0.9,
        ))
    if pain_modes or pain_themes:
        labels = sorted(pain_modes or pain_themes)
        events.append(_event(
            "review_pain_detected", "Operational pain appeared in recent reviews",
            summary=", ".join(label.replace("_", " ") for label in labels[:6]),
            new_value={"failure_modes": sorted(pain_modes), "themes": sorted(pain_themes)},
            evidence=evidence, source_date=source_date, confidence=0.82,
        ))
    return events


def diff_snapshots(
    module: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    reference_time: datetime | None = None,
) -> list[dict[str, Any]]:
    if module == MODULE_PROFILE:
        return diff_profile_snapshots(previous, current)
    if module == MODULE_SITEMAP:
        return diff_sitemap_snapshots(previous, current)
    if module == MODULE_JOBS:
        return diff_job_snapshots(previous, current)
    if module == MODULE_REVIEWS:
        return diff_review_snapshots(previous, current, reference_time=reference_time)
    raise ValueError(f"unsupported_research_module:{module}")


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _compact_value(value: Any, *, list_limit: int = 20, string_limit: int = 800) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value[:string_limit]
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, list_limit=list_limit, string_limit=string_limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _compact_value(item, list_limit=list_limit, string_limit=string_limit)
            for item in value[:list_limit]
        ]
    return value


def _compact_candidate_for_llm(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate["candidate_id"],
        "proposed_event_type": candidate.get("event_type"),
        "proposed_title": _clean(candidate.get("title"), 255),
        "proposed_summary": _clean(candidate.get("summary"), 500) or None,
        "old_value": _compact_value(candidate.get("old_value") or {}, list_limit=30),
        "new_value": _compact_value(candidate.get("new_value") or {}, list_limit=30),
        "source_date": _json_safe(candidate.get("source_date")),
        "evidence": [
            {
                "source": _clean(item.get("source"), 64) or None,
                "source_url": _source_url(item.get("source_url")),
                "published_at": _clean(item.get("published_at"), 64) or None,
                "excerpt": _clean(item.get("excerpt"), 500) or None,
                "confidence": item.get("confidence"),
            }
            for item in _as_list(candidate.get("evidence"))[:6]
            if isinstance(item, dict)
        ],
    }


def _candidate_batches(
    candidates: list[dict[str, Any]],
    *,
    max_items: int,
    max_chars: int,
) -> list[list[dict[str, Any]]]:
    """Batch related decisions while bounding the serialized prompt contribution."""
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for candidate in candidates:
        compact = _compact_candidate_for_llm(candidate)
        candidate_chars = len(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        if current and (len(current) >= max_items or current_chars + candidate_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(candidate)
        current_chars += candidate_chars
    if current:
        batches.append(current)
    return batches


def _comparison_context(
    module: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Keep enough before/after context for semantic matching without huge prompts."""
    if module == MODULE_PROFILE:
        def compact_profile(profile: dict[str, Any]) -> dict[str, Any]:
            vendors = []
            for item in list(_as_dict(profile.get("vendors")).values())[:30]:
                if not isinstance(item, dict):
                    continue
                vendors.append({
                    "vendor": item.get("vendor"),
                    "product": item.get("product"),
                    "confidence": item.get("confidence"),
                    "evidence": _compact_value(item.get("evidence") or [], list_limit=2, string_limit=300),
                })
            return {
                "practice_areas": list(_as_dict(profile.get("practice_areas")).values())[:80],
                "office_locations": list(_as_dict(profile.get("office_locations")).values())[:40],
                "leadership": [
                    {
                        "name": item.get("name"),
                        "title": item.get("title"),
                        "source_url": item.get("source_url"),
                    }
                    for item in list(_as_dict(profile.get("leadership")).values())[:50]
                    if isinstance(item, dict)
                ],
                "firm_size": profile.get("firm_size"),
                "vendors": vendors,
                "ai_adoption": profile.get("ai_adoption") or {},
                "sources": _as_list(profile.get("sources"))[:15],
            }
        return {"previous": compact_profile(previous), "current": compact_profile(current)}

    if module == MODULE_SITEMAP:
        old_urls = set(_as_list(previous.get("urls")))
        new_urls = set(_as_list(current.get("urls")))
        return {
            "previous_url_count": len(old_urls),
            "current_url_count": len(new_urls),
            "added_urls": sorted(new_urls - old_urls)[:50],
            "removed_urls": sorted(old_urls - new_urls)[:50],
            "changes_truncated": len(old_urls ^ new_urls) > 100,
        }

    collection_key = "postings" if module == MODULE_JOBS else "reviews"
    before = _as_dict(previous.get(collection_key))
    after = _as_dict(current.get(collection_key))
    added_keys = sorted(set(after) - set(before))
    removed_keys = sorted(set(before) - set(after))
    return {
        "previous_count": len(before),
        "current_count": len(after),
        "added": [_compact_value(after[key], list_limit=10, string_limit=500) for key in added_keys[:30]],
        "removed": [_compact_value(before[key], list_limit=10, string_limit=500) for key in removed_keys[:30]],
        "prior_items_for_semantic_matching": [
            _compact_value(item, list_limit=10, string_limit=500)
            for item in list(before.values())[:30]
        ],
        "changes_truncated": len(added_keys) > 30 or len(removed_keys) > 30,
    }


def _candidate_specs(
    module: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    reference_time: datetime,
    vendor_specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    specs = diff_snapshots(module, previous, current, reference_time=reference_time)
    specs.extend(vendor_specs or [])
    candidates: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        candidate = dict(spec)
        candidate["candidate_id"] = f"cand_{index:03d}"
        candidates.append(candidate)
    return candidates


def _restore_pending_candidate(value: Any) -> dict[str, Any] | None:
    candidate = _as_dict(value)
    candidate_id = _clean(candidate.get("candidate_id"), 64)
    event_type = _clean(candidate.get("event_type"), 64)
    if not candidate_id or event_type not in EVENT_CONFIG:
        return None
    restored = dict(candidate)
    restored["candidate_id"] = candidate_id
    restored["event_type"] = event_type
    restored["source_date"] = _parse_datetime(candidate.get("source_date"))
    return restored


def _validate_trigger_decisions(
    parsed: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_decisions = parsed.get("decisions")
    if not isinstance(raw_decisions, list):
        raise LLMGatewayError("trigger detector decisions must be a list")
    expected = {str(item["candidate_id"]) for item in candidates}
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            raise LLMGatewayError("trigger detector decision must be an object")
        candidate_id = _clean(raw.get("candidate_id"), 64)
        if candidate_id not in expected or candidate_id in seen:
            raise LLMGatewayError(f"unexpected or duplicate trigger candidate: {candidate_id}")
        decision = _clean(raw.get("decision"), 64)
        if decision not in TRIGGER_DECISIONS:
            raise LLMGatewayError(f"unsupported trigger decision: {decision}")
        emit_trigger = raw.get("emit_trigger")
        if not isinstance(emit_trigger, bool):
            raise LLMGatewayError(f"emit_trigger must be boolean for {candidate_id}")
        if emit_trigger != (decision == "confirmed_change"):
            raise LLMGatewayError(f"trigger decision and emit_trigger disagree for {candidate_id}")
        event_type = _clean(raw.get("event_type"), 64) or None
        if emit_trigger and event_type not in EVENT_CONFIG:
            raise LLMGatewayError(f"unsupported emitted event type for {candidate_id}: {event_type}")
        if not emit_trigger and event_type is not None:
            raise LLMGatewayError(f"rejected trigger must not have event_type for {candidate_id}")
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence"))))
            score = max(0, min(100, int(raw.get("score"))))
            severity = max(1, min(3, int(raw.get("severity"))))
        except (TypeError, ValueError) as exc:
            raise LLMGatewayError(f"invalid trigger scoring for {candidate_id}") from exc
        if not emit_trigger and (score != 0 or severity != 1):
            raise LLMGatewayError(f"rejected trigger has nonzero scoring for {candidate_id}")
        source_date_raw = raw.get("source_date")
        source_date = _parse_datetime(source_date_raw)
        if source_date_raw and source_date is None:
            raise LLMGatewayError(f"invalid trigger source_date for {candidate_id}")
        decisions.append({
            "candidate_id": candidate_id,
            "decision": decision,
            "emit_trigger": emit_trigger,
            "event_type": event_type,
            "title": _clean(raw.get("title"), 255),
            "summary": _clean(raw.get("summary"), 4_000) or None,
            "source_date": source_date,
            "confidence": confidence,
            "score": score,
            "severity": severity,
            "reason": _clean(raw.get("reason"), 2_000),
        })
        seen.add(candidate_id)
    missing = expected - seen
    if missing:
        raise LLMGatewayError(f"trigger detector omitted candidates: {sorted(missing)}")
    return decisions


async def _call_trigger_detector(
    *,
    payload: dict[str, Any],
    batch_id: str,
) -> dict[str, Any]:
    provider = os.getenv("PIF_TRIGGER_LLM_PROVIDER", "openai").strip().lower() or "openai"
    if provider not in {"openai", "openclaw"}:
        raise LLMGatewayError("PIF_TRIGGER_LLM_PROVIDER must be openai or openclaw")
    if provider == "openclaw":
        model = os.getenv("PIF_TRIGGER_OPENCLAW_MODEL", "openclaw/main").strip() or "openclaw/main"
        result = await call_skill_json(
            skill_path=TRIGGER_DETECTOR_SKILL,
            payload=payload,
            required_fields=["decisions"],
            model=model,
            max_tokens=int(os.getenv("PIF_TRIGGER_LLM_MAX_TOKENS", "5000")),
            retries=int(os.getenv("PIF_TRIGGER_LLM_RETRIES", "3")),
            schema_repair_retries=1,
            gateway_user=f"possibleos-trigger-{batch_id}",
            prompt_cache_key=f"possibleos:{TRIGGER_DETECTOR_VERSION}",
            prompt_cache_retention="24h",
            lane=os.getenv("OPENCLAW_RPC_BATCH_LANE", "possibleos-batch"),
            allow_tools=False,
        )
        return {
            "parsed": result.parsed,
            "model": result.model,
            "usage": result.usage or {},
            "provider": "possibleos_openclaw",
        }

    api_key = (
        os.getenv("PIF_TRIGGER_OPENAI_API_KEY", "").strip()
        or os.getenv("LEAD_FINDER_OPENAI_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )
    if not api_key:
        raise LLMGatewayError("trigger detector OpenAI API key is not configured")
    model = (
        os.getenv("PIF_TRIGGER_OPENAI_MODEL", "").strip()
        or os.getenv("LEAD_FINDER_OPENAI_MODEL", "").strip()
        or "gpt-5.6-luna"
    )
    attempts = max(1, min(5, int(os.getenv("PIF_TRIGGER_LLM_RETRIES", "3"))))
    timeout = max(30, int(os.getenv("PIF_TRIGGER_OPENAI_TIMEOUT_S", "180")))
    last_error: Exception | None = None
    request = {
        "model": model,
        "instructions": TRIGGER_DETECTOR_SKILL.read_text(encoding="utf-8"),
        "input": json.dumps(payload, indent=2, ensure_ascii=False),
        "max_output_tokens": int(os.getenv("PIF_TRIGGER_LLM_MAX_TOKENS", "5000")),
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "firm_trigger_change_decisions",
                "strict": True,
                "schema": TRIGGER_DECISION_SCHEMA,
            }
        },
        "prompt_cache_key": f"possibleos:{TRIGGER_DETECTOR_VERSION}",
        "prompt_cache_retention": "24h",
        "metadata": {"possibleos_trigger_batch_id": batch_id},
    }
    async with AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0) as client:
        for attempt in range(1, attempts + 1):
            try:
                response = await client.responses.create(**request)
                if response.status != "completed" or not response.output_text:
                    detail = getattr(response, "incomplete_details", None)
                    raise LLMGatewayError(f"trigger detector response {response.status}: {detail}")
                parsed = json.loads(response.output_text)
                if not isinstance(parsed, dict):
                    raise LLMGatewayError("trigger detector returned a non-object")
                usage = response.usage.model_dump() if response.usage else {}
                return {
                    "parsed": parsed,
                    "model": response.model,
                    "usage": usage,
                    "provider": "openai_responses",
                }
            except Exception as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(2 ** (attempt - 1))
    raise LLMGatewayError(
        f"trigger detector OpenAI call failed after {attempts} attempts: "
        f"{_clean(last_error, 500) or last_error.__class__.__name__ if last_error else 'unknown error'}"
    )


async def evaluate_trigger_candidates(
    *,
    firm: dict[str, Any],
    module: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    candidates: list[dict[str, Any]],
    captured_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate related candidates in small batches; detector failures emit nothing."""
    if not candidates:
        return [], {
            "status": "not_needed",
            "version": TRIGGER_DETECTOR_VERSION,
            "candidate_count": 0,
            "calls": 0,
        }
    try:
        batch_size = max(1, min(50, int(os.getenv("PIF_TRIGGER_LLM_BATCH_SIZE", "24"))))
    except ValueError:
        batch_size = 24
    provider = os.getenv("PIF_TRIGGER_LLM_PROVIDER", "openai").strip().lower() or "openai"
    model = (
        os.getenv("PIF_TRIGGER_OPENAI_MODEL", "").strip()
        or os.getenv("LEAD_FINDER_OPENAI_MODEL", "").strip()
        or "gpt-5.6-luna"
    ) if provider == "openai" else (
        os.getenv("PIF_TRIGGER_OPENCLAW_MODEL", "openclaw/main").strip() or "openclaw/main"
    )
    context = _comparison_context(module, previous, current)
    accepted: list[dict[str, Any]] = []
    errors: list[str] = []
    decision_counts: dict[str, int] = {}
    outcomes: list[dict[str, Any]] = []
    usage_rows: list[dict[str, Any]] = []
    calls = 0

    try:
        max_batch_chars = max(8_000, min(80_000, int(os.getenv("PIF_TRIGGER_LLM_BATCH_CHARS", "24000"))))
    except ValueError:
        max_batch_chars = 24_000
    batches = _candidate_batches(candidates, max_items=batch_size, max_chars=max_batch_chars)

    for batch_index, batch in enumerate(batches, start=1):
        batch_id = uuid.uuid4().hex
        payload = {
            "task": "Decide whether each observed difference is a real, recent, GTM-relevant firm change.",
            "detector_version": TRIGGER_DETECTOR_VERSION,
            "captured_at": captured_at.isoformat(),
            "firm": firm,
            "module": module,
            "snapshot_context": context,
            "candidates": [_compact_candidate_for_llm(item) for item in batch],
        }
        calls += 1
        try:
            result = await _call_trigger_detector(payload=payload, batch_id=batch_id)
            decisions = _validate_trigger_decisions(result["parsed"], batch)
        except Exception as exc:
            error = _clean(exc, 500) or exc.__class__.__name__
            errors.append(f"batch {batch_index}: {error}")
            logger.warning(
                "trigger detector failed closed for firm=%s module=%s batch=%s: %s",
                firm.get("id"), module, batch_id, error,
            )
            continue

        usage = _as_dict(result.get("usage"))
        usage_rows.append(usage)
        candidates_by_id = {item["candidate_id"]: item for item in batch}
        for decision in decisions:
            decision_counts[decision["decision"]] = decision_counts.get(decision["decision"], 0) + 1
            decision_metadata = {
                "provider": result["provider"],
                "version": TRIGGER_DETECTOR_VERSION,
                "model": result["model"],
                "batch_id": batch_id,
                "batch_size": len(batch),
                "candidate_id": decision["candidate_id"],
                "decision": decision["decision"],
                "reason": decision["reason"],
                "usage": usage,
                "prompt_cache": prompt_cache_metrics(usage),
            }
            outcomes.append({
                "candidate_id": decision["candidate_id"],
                "decision": decision["decision"],
                "emit_trigger": decision["emit_trigger"],
                "event_type": decision["event_type"],
                "reason": decision["reason"],
                "confidence": decision["confidence"],
                "decision_metadata": decision_metadata,
            })
            if not decision["emit_trigger"]:
                continue
            candidate = dict(candidates_by_id[decision["candidate_id"]])
            event_type = str(decision["event_type"])
            category, default_score, default_severity = EVENT_CONFIG[event_type]
            candidate.update({
                "event_type": event_type,
                "category": category,
                "title": decision["title"] or candidate.get("title") or event_type.replace("_", " ").title(),
                "summary": decision["summary"],
                "source_date": decision["source_date"] or candidate.get("source_date"),
                "confidence": decision["confidence"],
                "score": decision["score"] if decision["score"] is not None else default_score,
                "severity": decision["severity"] if decision["severity"] is not None else default_severity,
                "decision_metadata": decision_metadata,
            })
            accepted.append(candidate)

    status = "completed" if not errors else ("failed" if len(errors) == calls else "partial")
    return accepted, {
        "status": status,
        "version": TRIGGER_DETECTOR_VERSION,
        "provider": provider,
        "model": model,
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "decision_counts": decision_counts,
        "calls": calls,
        "batch_size": batch_size,
        "max_batch_chars": max_batch_chars,
        "errors": errors,
        "usage": usage_rows,
        "outcomes": outcomes,
    }


def refresh_days_for(module: str, icp_tier: str | None) -> int:
    global_default = os.getenv("PIF_RESEARCH_MAINTENANCE_REFRESH_DAYS", "30")
    try:
        default = max(1, int(os.getenv(f"PIF_{module.upper()}_REFRESH_DAYS", global_default)))
    except (TypeError, ValueError):
        default = 30
    if str(icp_tier or "").upper() in {"A", "B"} and module in {MODULE_SITEMAP, MODULE_JOBS, MODULE_REVIEWS}:
        try:
            return max(1, int(os.getenv("PIF_HIGH_ICP_SIGNAL_REFRESH_DAYS", "7")))
        except (TypeError, ValueError):
            return 7
    return default


def _event_dedupe_key(pif_id: str, spec: dict[str, Any], detected_at: datetime) -> str:
    source_date = spec.get("source_date")
    time_key = source_date.isoformat() if isinstance(source_date, datetime) else detected_at.date().isoformat()
    return _json_hash({
        "pif_id": pif_id,
        "event_type": spec["event_type"],
        "new_value": spec.get("new_value") or {},
        "old_value": spec.get("old_value") or {},
        "time": time_key,
    })


def _source_url(value: Any) -> str | None:
    url = _clean(value, 2_000)
    return url if url.lower().startswith(("http://", "https://")) else None


def _has_direct_vendor_evidence(value: dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and _source_url(item.get("source_url"))
        for item in _as_list(value.get("evidence"))
    )


async def _store_event(session, pif_id: str, spec: dict[str, Any], detected_at: datetime) -> FirmTriggerEventRow | None:
    dedupe_key = _event_dedupe_key(pif_id, spec, detected_at)
    existing = (await session.execute(
        select(FirmTriggerEventRow).where(FirmTriggerEventRow.dedupe_key == dedupe_key)
    )).scalar_one_or_none()
    if existing is not None:
        return None
    event = FirmTriggerEventRow(
        id=uuid.uuid4().hex,
        pif_id=pif_id,
        event_type=spec["event_type"],
        category=spec["category"],
        title=_clean(spec["title"], 255),
        summary=_clean(spec.get("summary"), 4_000) or None,
        old_value=_as_dict(spec.get("old_value")),
        new_value=_as_dict(spec.get("new_value")),
        evidence_json=_as_list(spec.get("evidence")),
        decision_metadata=_as_dict(spec.get("decision_metadata")),
        source_date=spec.get("source_date"),
        detected_at=detected_at,
        expires_at=(spec.get("source_date") or detected_at) + timedelta(days=90),
        confidence=_confidence(spec.get("confidence")),
        severity=max(1, min(3, int(spec.get("severity") or 1))),
        score=max(0, min(100, int(spec.get("score") or 0))),
        dedupe_key=dedupe_key,
        active=True,
    )
    session.add(event)
    await session.flush()
    for evidence in _as_list(spec.get("evidence")):
        if not isinstance(evidence, dict):
            continue
        url = _source_url(evidence.get("source_url"))
        if not url:
            continue
        excerpt = _clean(evidence.get("excerpt"), 4_000)
        content_hash = _json_hash({"url": url.lower().rstrip("/"), "excerpt": excerpt})
        claim_key = _clean(
            spec.get("new_value", {}).get("vendor")
            or spec.get("new_value", {}).get("practice_area")
            or spec.get("title"),
            255,
        )
        row = (await session.execute(select(FirmEvidenceRow).where(
            FirmEvidenceRow.pif_id == pif_id,
            FirmEvidenceRow.claim_type == spec["event_type"],
            FirmEvidenceRow.claim_key == claim_key,
            FirmEvidenceRow.content_hash == content_hash,
        ))).scalar_one_or_none()
        if row is None:
            session.add(FirmEvidenceRow(
                id=uuid.uuid4().hex,
                pif_id=pif_id,
                event_id=event.id,
                claim_type=spec["event_type"],
                claim_key=claim_key,
                source_type=_clean(evidence.get("source"), 64) or None,
                source_url=url,
                source_published_at=_parse_datetime(evidence.get("published_at")),
                first_seen_at=detected_at,
                last_seen_at=detected_at,
                content_hash=content_hash,
                excerpt=excerpt or None,
                confidence=_confidence(evidence.get("confidence")),
                raw_json=evidence,
            ))
        else:
            row.last_seen_at = detected_at
            row.event_id = row.event_id or event.id
    return event


async def _update_vendor_relationships(
    session,
    *,
    pif_id: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    current_vendors = _as_dict(current.get("vendors"))
    previous_vendors = _as_dict((previous or {}).get("vendors"))
    relationships = list((await session.execute(
        select(FirmVendorRelationshipRow).where(FirmVendorRelationshipRow.pif_id == pif_id)
    )).scalars().all())
    indexed = {(row.vendor, _key(row.product)): row for row in relationships}
    events: list[dict[str, Any]] = []
    newly_added: list[dict[str, Any]] = []
    newly_removed: list[dict[str, Any]] = []
    newly_absent: list[dict[str, Any]] = []

    for identity, vendor_data in current_vendors.items():
        vendor = vendor_data["vendor"]
        product = vendor_data["product"]
        key = (vendor, _key(product))
        row = indexed.get(key)
        was_removed = row is not None and row.status == "removed"
        if row is None:
            row = FirmVendorRelationshipRow(
                id=uuid.uuid4().hex,
                pif_id=pif_id,
                vendor=vendor,
                product=product,
                status="active",
                first_seen_at=now,
                last_seen_at=now,
                absent_scans=0,
                confidence=_confidence(vendor_data.get("confidence")),
                evidence_json=_as_list(vendor_data.get("evidence")),
                updated_at=now,
            )
            session.add(row)
            indexed[key] = row
        else:
            row.status = "active"
            row.last_seen_at = now
            row.removed_at = None
            row.absent_scans = 0
            row.confidence = max(row.confidence, _confidence(vendor_data.get("confidence")))
            row.evidence_json = _as_list(vendor_data.get("evidence")) or row.evidence_json
            row.updated_at = now
        if (
            previous is not None
            and (identity not in previous_vendors or was_removed)
            and _has_direct_vendor_evidence(vendor_data)
        ):
            newly_added.append(vendor_data)
            published_dates = [
                parsed
                for item in _as_list(vendor_data.get("evidence"))
                if isinstance(item, dict)
                and (parsed := _parse_datetime(item.get("published_at"))) is not None
            ]
            events.append(_event(
                "vendor_added", f"Vendor first detected: {product}",
                summary="This vendor was absent from the previous successful firm snapshot.",
                new_value={"vendor": vendor, "product": product},
                evidence=_as_list(vendor_data.get("evidence")),
                source_date=max(published_dates, default=None),
                confidence=_confidence(vendor_data.get("confidence")),
            ))

    current_keys = {(data["vendor"], _key(data["product"])) for data in current_vendors.values()}
    for row in relationships:
        if (row.vendor, _key(row.product)) in current_keys or row.status == "removed":
            continue
        row.absent_scans += 1
        row.status = "removed" if row.absent_scans >= 2 else "suspected_removed"
        row.updated_at = now
        if row.absent_scans == 1 and any(
            isinstance(item, dict) and _source_url(item.get("source_url"))
            for item in _as_list(row.evidence_json)
        ):
            newly_absent.append({"vendor": row.vendor, "product": row.product})
        if row.status == "removed":
            row.removed_at = now
            removed = {"vendor": row.vendor, "product": row.product}
            if any(
                isinstance(item, dict) and _source_url(item.get("source_url"))
                for item in _as_list(row.evidence_json)
            ):
                newly_removed.append(removed)
                events.append(_event(
                    "vendor_removed", f"Vendor no longer detected: {row.product or row.vendor}",
                    summary="The vendor was absent from two consecutive successful snapshots.",
                    old_value=removed, evidence=_as_list(row.evidence_json), confidence=0.72,
                ))

    migration_departures = newly_absent or newly_removed
    if newly_added and migration_departures:
        migration_evidence = [
            item
            for vendor in newly_added
            for item in _as_list(vendor.get("evidence"))
            if isinstance(item, dict)
        ]
        events.append(_event(
            "vendor_migration_detected", "Possible vendor migration detected",
            summary="A vendor was added while another evidenced vendor became absent.",
            old_value={"vendors": migration_departures}, new_value={"vendors": [
                {"vendor": item["vendor"], "product": item["product"]} for item in newly_added
            ]}, evidence=migration_evidence, confidence=0.74,
        ))
    return events


async def record_research_snapshot(
    pif_id: str,
    module: str,
    payload: dict[str, Any],
    *,
    captured_at: datetime | None = None,
    emit_initial_events: bool = True,
) -> dict[str, Any]:
    """Persist a normalized snapshot and emit only LLM-confirmed changes."""
    if module not in RESEARCH_MODULES:
        raise ValueError(f"unsupported_research_module:{module}")
    now = captured_at or _utcnow()
    normalized = normalize_snapshot(module, payload)
    fingerprint = _json_hash(normalized)
    candidates: list[dict[str, Any]] = []
    next_due_at: datetime | None = None
    baseline_created = False
    changed = False
    firm_context: dict[str, Any] = {}

    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            raise ValueError("firm_not_found")
        firm_context = {
            "id": firm.id,
            "name": firm.firm_name,
            "website": firm.canonical_website or firm.website,
            "entity_type": firm.entity_type,
            "icp_tier": firm.icp_tier,
        }
        previous_row = (await session.execute(
            select(FirmResearchSnapshotRow)
            .where(
                FirmResearchSnapshotRow.pif_id == pif_id,
                FirmResearchSnapshotRow.module == module,
            )
            .order_by(FirmResearchSnapshotRow.captured_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        previous = _as_dict(previous_row.payload_json) if previous_row else None
        baseline_created = previous is None
        state_id = f"{module}:{pif_id}"
        state = await session.get(FirmResearchStateRow, state_id)

        changed = previous is None or previous_row.fingerprint != fingerprint
        if changed:
            session.add(FirmResearchSnapshotRow(
                id=uuid.uuid4().hex,
                pif_id=pif_id,
                module=module,
                fingerprint=fingerprint,
                payload_json=normalized,
                captured_at=now,
            ))

        should_diff = changed and (
            previous is not None
            or (emit_initial_events and module in {MODULE_JOBS, MODULE_REVIEWS})
            or (emit_initial_events and module == MODULE_PROFILE and bool(
                _as_dict(normalized.get("ai_adoption")).get("statements")
            ))
        )
        vendor_specs: list[dict[str, Any]] = []
        if module == MODULE_PROFILE:
            vendor_specs = await _update_vendor_relationships(
                session, pif_id=pif_id, previous=previous, current=normalized, now=now,
            )
        if should_diff:
            candidates = _candidate_specs(
                module,
                previous or {},
                normalized,
                reference_time=now,
                vendor_specs=vendor_specs,
            )
            if previous is None and module == MODULE_PROFILE:
                candidates = [item for item in candidates if item.get("event_type") == "ai_adoption_changed"]
        elif not changed and state is not None:
            detector_state = _as_dict(_as_dict(state.metadata_json).get("trigger_detector"))
            candidates = [
                restored
                for item in _as_list(detector_state.get("pending_candidates"))
                if (restored := _restore_pending_candidate(item)) is not None
            ]

        if state is None:
            state = FirmResearchStateRow(id=state_id, pif_id=pif_id, module=module)
            session.add(state)
        refresh_days = refresh_days_for(module, firm.icp_tier)
        state.status = "completed"
        state.last_attempt_at = now
        state.last_success_at = now
        state.next_due_at = now + timedelta(days=refresh_days)
        state.failure_count = 0
        state.last_error = None
        state.snapshot_fingerprint = fingerprint
        state.metadata_json = {
            "changed": changed,
            "events_created": 0,
            "refresh_days": refresh_days,
            "trigger_detector": {
                "status": "pending" if candidates else "not_needed",
                "version": TRIGGER_DETECTOR_VERSION,
                "candidate_count": len(candidates),
                "calls": 0,
                "pending_candidates": [_json_safe(item) for item in candidates],
            },
        }
        state.updated_at = now
        next_due_at = state.next_due_at
        await session.commit()

    confirmed_specs, detector_summary = await evaluate_trigger_candidates(
        firm=firm_context,
        module=module,
        previous=previous or {},
        current=normalized,
        candidates=candidates,
        captured_at=now,
    )

    created_events: list[FirmTriggerEventRow] = []
    decided_ids = {
        _clean(item.get("candidate_id"), 64)
        for item in _as_list(detector_summary.get("outcomes"))
        if isinstance(item, dict)
    }
    pending_candidates = [
        item for item in candidates if _clean(item.get("candidate_id"), 64) not in decided_ids
    ]
    detector_state = {
        **detector_summary,
        "pending_candidate_count": len(pending_candidates),
        "pending_candidates": [_json_safe(item) for item in pending_candidates],
    }
    async with AsyncSessionLocal() as session:
        for spec in confirmed_specs:
            event = await _store_event(session, pif_id, spec, now)
            if event is not None:
                created_events.append(event)
        state = await session.get(FirmResearchStateRow, f"{module}:{pif_id}")
        if state is not None:
            state.metadata_json = {
                **_as_dict(state.metadata_json),
                "events_created": len(created_events),
                "trigger_detector": detector_state,
            }
            if pending_candidates:
                retry_at = _utcnow() + timedelta(hours=1)
                if state.next_due_at is None or state.next_due_at > retry_at:
                    state.next_due_at = retry_at
                next_due_at = state.next_due_at
            state.updated_at = _utcnow()
        await session.commit()

    return {
        "pif_id": pif_id,
        "module": module,
        "baseline_created": baseline_created,
        "changed": changed,
        "fingerprint": fingerprint,
        "events_created": len(created_events),
        "event_types": [event.event_type for event in created_events],
        "trigger_detector": detector_summary,
        "next_due_at": next_due_at.isoformat() if next_due_at else None,
    }


async def mark_research_failure(
    pif_id: str,
    module: str,
    error: str,
    *,
    attempted_at: datetime | None = None,
) -> None:
    now = attempted_at or _utcnow()
    async with AsyncSessionLocal() as session:
        state_id = f"{module}:{pif_id}"
        state = await session.get(FirmResearchStateRow, state_id)
        if state is None:
            state = FirmResearchStateRow(id=state_id, pif_id=pif_id, module=module)
            session.add(state)
        state.failure_count = int(state.failure_count or 0) + 1
        retry_hours = min(72, [1, 3, 12, 24, 72][min(state.failure_count - 1, 4)])
        state.status = "failed"
        state.last_attempt_at = now
        state.next_due_at = now + timedelta(hours=retry_hours)
        state.last_error = _clean(error, 2_000)
        state.metadata_json = {"retry_hours": retry_hours}
        state.updated_at = now
        await session.commit()


async def mark_research_status(
    pif_id: str,
    module: str,
    status: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    if module not in RESEARCH_MODULES or status not in {"queued", "in_progress"}:
        raise ValueError("unsupported_research_status")
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        state_id = f"{module}:{pif_id}"
        state = await session.get(FirmResearchStateRow, state_id)
        if state is None:
            state = FirmResearchStateRow(id=state_id, pif_id=pif_id, module=module)
            session.add(state)
        state.status = status
        if status == "in_progress":
            state.last_attempt_at = now
        state.metadata_json = {**_as_dict(state.metadata_json), **(metadata or {})}
        state.updated_at = now
        await session.commit()


def serialize_trigger_event(row: FirmTriggerEventRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "pif_id": row.pif_id,
        "event_type": row.event_type,
        "category": row.category,
        "title": row.title,
        "summary": row.summary,
        "old_value": row.old_value or {},
        "new_value": row.new_value or {},
        "evidence": row.evidence_json or [],
        "decision_metadata": row.decision_metadata or {},
        "source_date": row.source_date.isoformat() if row.source_date else None,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "confidence": row.confidence,
        "severity": row.severity,
        "score": row.score,
        "active": bool(row.active),
    }


def _serialize_state(row: FirmResearchStateRow) -> dict[str, Any]:
    now = _utcnow()
    return {
        "module": row.module,
        "status": row.status,
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "next_due_at": row.next_due_at.isoformat() if row.next_due_at else None,
        "fresh": bool(row.last_success_at and (row.next_due_at is None or row.next_due_at > now)),
        "failure_count": row.failure_count,
        "last_error": row.last_error,
    }


def _recency_weight(detected_at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - detected_at).total_seconds() / 86_400)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.82
    if age_days <= 60:
        return 0.62
    return 0.45


async def list_priority_firms(
    *,
    search: str | None = None,
    event_types: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
    within_days: int = 30,
    min_score: int = 0,
    min_confidence: float = 0.0,
    match_mode: str = "any",
    icp_tier: str | None = None,
    icp_tiers: list[str] | None = None,
    entity_type: str | None = None,
    entity_types: list[str] | None = None,
    staff_count_min: int | None = None,
    staff_count_max: int | None = None,
    staff_count_ranges: list[str] | None = None,
    vendor: str | None = None,
    vendors: list[str] | None = None,
    sort_by: str = "priority",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    now = _utcnow()
    cutoff = now - timedelta(days=max(1, min(3650, int(within_days))))
    wanted_types = {_clean(item, 64) for item in (event_types or []) if _clean(item, 64)}
    wanted_categories = {_clean(item, 32) for item in (categories or []) if _clean(item, 32)}
    event_time = func.coalesce(FirmTriggerEventRow.source_date, FirmTriggerEventRow.detected_at)
    conditions = [
        FirmTriggerEventRow.active.is_(True),
        event_time >= cutoff,
        or_(FirmTriggerEventRow.expires_at.is_(None), FirmTriggerEventRow.expires_at > now),
        FirmTriggerEventRow.score >= max(0, min(100, int(min_score))),
        FirmTriggerEventRow.confidence >= max(0.0, min(1.0, float(min_confidence))),
    ]
    merged_into = PifFirmRow.source_json["merged_into"].astext
    conditions.append(or_(merged_into.is_(None), merged_into == ""))
    type_filter = FirmTriggerEventRow.event_type.in_(sorted(wanted_types)) if wanted_types else None
    category_filter = FirmTriggerEventRow.category.in_(sorted(wanted_categories)) if wanted_categories else None
    if type_filter is not None and category_filter is not None:
        conditions.append(or_(type_filter, category_filter))
    elif type_filter is not None:
        conditions.append(type_filter)
    elif category_filter is not None:
        conditions.append(category_filter)
    selected_icp_tiers = {
        value for value in [*list(icp_tiers or []), *([icp_tier] if icp_tier else [])] if value
    }
    selected_entity_types = {
        _key(value) for value in [*list(entity_types or []), *([entity_type] if entity_type else [])] if _key(value)
    }
    if selected_icp_tiers:
        conditions.append(PifFirmRow.icp_tier.in_(sorted(selected_icp_tiers)))
    if selected_entity_types:
        conditions.append(PifFirmRow.entity_type.in_(sorted(selected_entity_types)))
    staff_count = func.jsonb_array_length(PifFirmRow.staff)
    staff_count_range_condition = count_ranges_condition(staff_count, staff_count_ranges)
    if staff_count_range_condition is not None:
        conditions.append(staff_count_range_condition)
    if staff_count_min is not None:
        conditions.append(staff_count >= staff_count_min)
    if staff_count_max is not None:
        conditions.append(staff_count <= staff_count_max)
    selected_vendor_values = [*list(vendors or []), *([vendor] if vendor else [])]
    include_missing_vendor = any(_key(value) == "__missing" for value in selected_vendor_values)
    wanted_vendors = sorted({
        _vendor_identity(value)[0]
        for value in selected_vendor_values
        if _key(value) and _key(value) != "__missing"
    })
    active_vendor_exists = exists(select(FirmVendorRelationshipRow.id).where(
        FirmVendorRelationshipRow.pif_id == PifFirmRow.id,
        FirmVendorRelationshipRow.status == "active",
    ))
    selected_vendor_exists = exists(select(FirmVendorRelationshipRow.id).where(
            FirmVendorRelationshipRow.pif_id == PifFirmRow.id,
            FirmVendorRelationshipRow.vendor.in_(wanted_vendors),
            FirmVendorRelationshipRow.status == "active",
    )) if wanted_vendors else None
    if selected_vendor_exists is not None and include_missing_vendor:
        conditions.append(or_(selected_vendor_exists, ~active_vendor_exists))
    elif selected_vendor_exists is not None:
        conditions.append(selected_vendor_exists)
    elif include_missing_vendor:
        conditions.append(~active_vendor_exists)
    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        conditions.append(or_(
            func.lower(PifFirmRow.firm_name).like(needle),
            func.lower(FirmTriggerEventRow.title).like(needle),
            func.lower(FirmTriggerEventRow.summary).like(needle),
        ))

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FirmTriggerEventRow, PifFirmRow)
            .join(PifFirmRow, PifFirmRow.id == FirmTriggerEventRow.pif_id)
            .where(*conditions)
            .order_by(event_time.desc())
        )).all()
        firm_ids = {firm.id for _, firm in rows}
        state_rows = list((await session.execute(
            select(FirmResearchStateRow).where(FirmResearchStateRow.pif_id.in_(firm_ids))
        )).scalars().all()) if firm_ids else []
        vendor_rows = list((await session.execute(
            select(FirmVendorRelationshipRow).where(
                FirmVendorRelationshipRow.pif_id.in_(firm_ids),
                FirmVendorRelationshipRow.status == "active",
            )
        )).scalars().all()) if firm_ids else []

    grouped: dict[str, dict[str, Any]] = {}
    for event, firm in rows:
        item = grouped.setdefault(firm.id, {"firm": firm, "events": []})
        item["events"].append(event)
    if match_mode == "all" and (wanted_types or wanted_categories):
        grouped = {
            firm_id: item for firm_id, item in grouped.items()
            if wanted_types.issubset({event.event_type for event in item["events"]})
            and wanted_categories.issubset({event.category for event in item["events"]})
        }
    states_by_firm: dict[str, list[FirmResearchStateRow]] = {}
    for state in state_rows:
        states_by_firm.setdefault(state.pif_id, []).append(state)
    vendors_by_firm: dict[str, list[FirmVendorRelationshipRow]] = {}
    for relationship in vendor_rows:
        vendors_by_firm.setdefault(relationship.pif_id, []).append(relationship)

    items: list[dict[str, Any]] = []
    for firm_id, grouped_item in grouped.items():
        firm = grouped_item["firm"]
        events = grouped_item["events"]
        effective = sorted(
            [
                (
                    event.score
                    * event.confidence
                    * _recency_weight(event.source_date or event.detected_at, now),
                    event,
                )
                for event in events
            ],
            key=lambda item: item[0],
            reverse=True,
        )
        trigger_score = min(100, round(
            (effective[0][0] if effective else 0)
            + sum(value * 0.2 for value, _ in effective[1:4])
        ))
        fit_score = int(firm.icp_score or 0)
        priority_score = round(trigger_score * 0.6 + fit_score * 0.4)
        states = states_by_firm.get(firm_id, [])
        fresh_count = sum(
            bool(state.last_success_at and (state.next_due_at is None or state.next_due_at > now))
            for state in states
        )
        items.append({
            "firm": {
                "id": firm.id,
                "firm_name": firm.firm_name or "",
                "entity_type": firm.entity_type or "",
                "website": firm.canonical_website or firm.website,
                "metro": firm.metro,
                "staff_count": len(firm.staff or []),
                "icp_score": firm.icp_score,
                "icp_tier": firm.icp_tier,
                "leadership": (firm.leadership or [])[:5],
                "emails": (firm.emails or [])[:5],
                "phones": (firm.phones or [])[:5],
            },
            "fit_score": fit_score,
            "trigger_score": trigger_score,
            "priority_score": priority_score,
            "latest_trigger_at": max(event.source_date or event.detected_at for event in events).isoformat(),
            "triggers": [serialize_trigger_event(event) for _, event in effective[:5]],
            "freshness": {
                "fresh_modules": fresh_count,
                "total_modules": len(RESEARCH_MODULES),
                "percent": round(fresh_count / len(RESEARCH_MODULES) * 100),
                "modules": [_serialize_state(state) for state in sorted(states, key=lambda row: row.module)],
            },
            "vendors": [{
                "vendor": relationship.vendor,
                "product": relationship.product,
                "first_seen_at": relationship.first_seen_at.isoformat(),
                "last_seen_at": relationship.last_seen_at.isoformat(),
                "confidence": relationship.confidence,
            } for relationship in vendors_by_firm.get(firm_id, [])],
        })

    if sort_by == "newest":
        items.sort(key=lambda item: item["latest_trigger_at"], reverse=True)
    elif sort_by == "fit":
        items.sort(key=lambda item: (item["fit_score"], item["trigger_score"]), reverse=True)
    else:
        items.sort(key=lambda item: (item["priority_score"], item["latest_trigger_at"]), reverse=True)
    total = len(items)
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    start = (page - 1) * page_size
    return {
        "items": items[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "within_days": within_days,
        "generated_at": now.isoformat(),
    }


async def list_firm_trigger_events(pif_id: str, *, limit: int = 100) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            raise ValueError("firm_not_found")
        events = list((await session.execute(
            select(FirmTriggerEventRow)
            .where(FirmTriggerEventRow.pif_id == pif_id)
            .order_by(FirmTriggerEventRow.detected_at.desc())
            .limit(max(1, min(500, int(limit))))
        )).scalars().all())
        states = list((await session.execute(
            select(FirmResearchStateRow)
            .where(FirmResearchStateRow.pif_id == pif_id)
            .order_by(FirmResearchStateRow.module.asc())
        )).scalars().all())
        vendors = list((await session.execute(
            select(FirmVendorRelationshipRow)
            .where(FirmVendorRelationshipRow.pif_id == pif_id)
            .order_by(FirmVendorRelationshipRow.vendor.asc(), FirmVendorRelationshipRow.product.asc())
        )).scalars().all())
    return {
        "pif_id": pif_id,
        "firm_name": firm.firm_name,
        "events": [serialize_trigger_event(event) for event in events],
        "research_freshness": [_serialize_state(state) for state in states],
        "vendor_history": [{
            "vendor": row.vendor,
            "product": row.product,
            "status": row.status,
            "first_seen_at": row.first_seen_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
            "removed_at": row.removed_at.isoformat() if row.removed_at else None,
            "absent_scans": row.absent_scans,
            "confidence": row.confidence,
            "evidence": row.evidence_json or [],
        } for row in vendors],
    }


async def revalidate_active_trigger_events(
    *,
    pif_id: str | None = None,
    limit: int = 250,
) -> dict[str, Any]:
    """Rejudge stored active events in firm/module batches and retire false positives."""
    async with AsyncSessionLocal() as session:
        query = (
            select(FirmTriggerEventRow, PifFirmRow)
            .join(PifFirmRow, PifFirmRow.id == FirmTriggerEventRow.pif_id)
            .where(
                FirmTriggerEventRow.active.is_(True),
                or_(
                    FirmTriggerEventRow.decision_metadata["version"].astext.is_(None),
                    FirmTriggerEventRow.decision_metadata["version"].astext != TRIGGER_DETECTOR_VERSION,
                ),
            )
            .order_by(FirmTriggerEventRow.detected_at.desc())
            .limit(max(1, min(2_000, int(limit))))
        )
        if pif_id:
            query = query.where(FirmTriggerEventRow.pif_id == pif_id)
        rows = (await session.execute(query)).all()

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    skipped = 0
    for event, firm in rows:
        module = EVENT_MODULES.get(event.event_type)
        if module is None:
            skipped += 1
            continue
        group = groups.setdefault((firm.id, module), {
            "firm": {
                "id": firm.id,
                "name": firm.firm_name,
                "website": firm.canonical_website or firm.website,
                "entity_type": firm.entity_type,
                "icp_tier": firm.icp_tier,
            },
            "candidates": [],
        })
        group["candidates"].append({
            "candidate_id": event.id,
            "event_type": event.event_type,
            "category": event.category,
            "title": event.title,
            "summary": event.summary,
            "old_value": event.old_value or {},
            "new_value": event.new_value or {},
            "evidence": event.evidence_json or [],
            "source_date": event.source_date,
            "confidence": event.confidence,
            "score": event.score,
            "severity": event.severity,
        })

    confirmed = 0
    deactivated = 0
    failed = 0
    group_results: list[dict[str, Any]] = []
    for (firm_id, module), group in groups.items():
        async with AsyncSessionLocal() as session:
            snapshots = list((await session.execute(
                select(FirmResearchSnapshotRow)
                .where(
                    FirmResearchSnapshotRow.pif_id == firm_id,
                    FirmResearchSnapshotRow.module == module,
                )
                .order_by(FirmResearchSnapshotRow.captured_at.desc())
                .limit(2)
            )).scalars().all())
        current = _as_dict(snapshots[0].payload_json) if snapshots else {}
        previous = _as_dict(snapshots[1].payload_json) if len(snapshots) > 1 else {}
        captured_at = snapshots[0].captured_at if snapshots else _utcnow()
        accepted, detector = await evaluate_trigger_candidates(
            firm=group["firm"],
            module=module,
            previous=previous,
            current=current,
            candidates=group["candidates"],
            captured_at=captured_at,
        )
        accepted_by_id = {str(item["candidate_id"]): item for item in accepted}
        outcomes = {
            str(item["candidate_id"]): item
            for item in _as_list(detector.get("outcomes"))
            if isinstance(item, dict) and item.get("candidate_id")
        }
        successful_ids = set(outcomes)
        failed += len(group["candidates"]) - len(successful_ids)

        if successful_ids:
            async with AsyncSessionLocal() as session:
                event_rows = list((await session.execute(
                    select(FirmTriggerEventRow).where(FirmTriggerEventRow.id.in_(successful_ids))
                )).scalars().all())
                for row in event_rows:
                    accepted_spec = accepted_by_id.get(row.id)
                    outcome = outcomes[row.id]
                    if accepted_spec is None:
                        row.active = False
                        row.decision_metadata = {
                            **_as_dict(outcome.get("decision_metadata")),
                            "revalidated_at": _utcnow().isoformat(),
                        }
                        deactivated += 1
                        continue
                    row.event_type = accepted_spec["event_type"]
                    row.category = accepted_spec["category"]
                    row.title = _clean(accepted_spec.get("title"), 255)
                    row.summary = _clean(accepted_spec.get("summary"), 4_000) or None
                    row.source_date = accepted_spec.get("source_date")
                    row.confidence = _confidence(accepted_spec.get("confidence"))
                    row.score = max(0, min(100, int(accepted_spec.get("score") or 0)))
                    row.severity = max(1, min(3, int(accepted_spec.get("severity") or 1)))
                    row.expires_at = (row.source_date or row.detected_at) + timedelta(days=90)
                    row.decision_metadata = {
                        **_as_dict(accepted_spec.get("decision_metadata")),
                        "revalidated_at": _utcnow().isoformat(),
                    }
                    confirmed += 1
                await session.commit()
        group_results.append({
            "pif_id": firm_id,
            "firm_name": group["firm"].get("name"),
            "module": module,
            "candidates": len(group["candidates"]),
            "confirmed": len(accepted_by_id),
            "deactivated": len(successful_ids - set(accepted_by_id)),
            "detector_status": detector.get("status"),
            "calls": detector.get("calls"),
            "errors": detector.get("errors") or [],
        })

    return {
        "considered": len(rows),
        "groups": len(groups),
        "confirmed": confirmed,
        "deactivated": deactivated,
        "failed": failed,
        "skipped": skipped,
        "results": group_results,
    }


async def trigger_filter_options() -> dict[str, Any]:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(
                FirmTriggerEventRow.category,
                FirmTriggerEventRow.event_type,
                func.count(FirmTriggerEventRow.id),
            )
            .where(
                FirmTriggerEventRow.active.is_(True),
                or_(FirmTriggerEventRow.expires_at.is_(None), FirmTriggerEventRow.expires_at > now),
            )
            .group_by(FirmTriggerEventRow.category, FirmTriggerEventRow.event_type)
            .order_by(FirmTriggerEventRow.category.asc(), FirmTriggerEventRow.event_type.asc())
        )).all()
    category_counts = {category: 0 for category, _, _ in EVENT_CONFIG.values()}
    event_counts: dict[str, int] = {event_type: 0 for event_type in EVENT_CONFIG}
    for category, event_type, count in rows:
        category_counts[str(category)] = category_counts.get(str(category), 0) + int(count)
        event_counts[str(event_type)] = int(count)
    event_types = [{
        "value": event_type,
        "category": category,
        "count": event_counts[event_type],
    } for event_type, (category, _, _) in sorted(EVENT_CONFIG.items())]
    return {
        "categories": [{"value": key, "count": value} for key, value in sorted(category_counts.items())],
        "event_types": event_types,
    }


async def baseline_existing_firm_research(*, limit: int = 500) -> dict[str, Any]:
    """Create non-alerting baselines from current local research data."""
    from app.db.models import FirmReviewRow, FirmSitemapSnapshotRow

    async with AsyncSessionLocal() as session:
        firms = list((await session.execute(
            select(PifFirmRow).order_by(PifFirmRow.created_at.asc()).limit(max(1, min(5_000, limit)))
        )).scalars().all())
        firm_ids = [firm.id for firm in firms]
        reviews = {
            row.pif_id: row for row in (await session.execute(
                select(FirmReviewRow).where(FirmReviewRow.pif_id.in_(firm_ids))
            )).scalars().all()
        } if firm_ids else {}
        sitemap_rows = list((await session.execute(
            select(FirmSitemapSnapshotRow)
            .where(FirmSitemapSnapshotRow.pif_id.in_(firm_ids), FirmSitemapSnapshotRow.status == "completed")
            .order_by(FirmSitemapSnapshotRow.pif_id.asc(), FirmSitemapSnapshotRow.fetched_at.desc())
        )).scalars().all()) if firm_ids else []
    latest_sitemap: dict[str, FirmSitemapSnapshotRow] = {}
    for row in sitemap_rows:
        latest_sitemap.setdefault(row.pif_id, row)

    counts = {module: 0 for module in RESEARCH_MODULES}
    failures: list[dict[str, str]] = []
    baseline_now = _utcnow()
    for firm in firms:
        research = _as_dict(firm.research_data)
        profile = {
            "practice_areas": research.get("practice_areas"),
            "office_locations": research.get("office_locations"),
            "firm_size": research.get("firm_size"),
            "leadership": firm.leadership,
            "vendor_stack": firm.vendor_stack,
            "ai_adoption": research.get("ai_adoption"),
            "sources": research.get("sources"),
            "website_sources": research.get("website_sources"),
        }
        has_profile = bool(firm.last_researched_at and any(
            value for key, value in profile.items() if key != "vendor_stack"
        )) or bool(normalize_vendor_snapshot(profile.get("vendor_stack")))
        review_row = reviews.get(firm.id)
        sitemap_row = latest_sitemap.get(firm.id)
        def baseline_time(module: str, value: datetime | None) -> datetime:
            return value or baseline_now - timedelta(days=refresh_days_for(module, firm.icp_tier))

        payloads: list[tuple[str, dict[str, Any] | None, datetime | None]] = [
            (
                MODULE_PROFILE,
                profile if has_profile else None,
                baseline_time(MODULE_PROFILE, firm.last_researched_at),
            ),
            (
                MODULE_JOBS,
                _as_dict(research.get("job_postings")) or None,
                baseline_time(
                    MODULE_JOBS,
                    _parse_datetime(research.get("last_job_postings_researched_at")),
                ),
            ),
            (
                MODULE_REVIEWS,
                _as_dict(review_row.reviews_json) if review_row else None,
                baseline_time(
                    MODULE_REVIEWS,
                    review_row.last_review_researched_at if review_row else None,
                ),
            ),
            (
                MODULE_SITEMAP,
                {"website": sitemap_row.website, "urls": sitemap_row.urls} if sitemap_row else None,
                baseline_time(MODULE_SITEMAP, sitemap_row.fetched_at if sitemap_row else None),
            ),
        ]
        for module, payload, captured_at in payloads:
            if not payload:
                continue
            try:
                await record_research_snapshot(
                    firm.id,
                    module,
                    payload,
                    captured_at=captured_at,
                    emit_initial_events=False,
                )
                counts[module] += 1
            except Exception as exc:
                failures.append({"pif_id": firm.id, "module": module, "error": _clean(exc, 300)})
    return {"firms_considered": len(firms), "baselines": counts, "failures": failures[:100]}
