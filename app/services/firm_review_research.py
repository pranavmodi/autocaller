"""Durable local collection of source-backed public firm reviews."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx
from sqlalchemy import select, update

from app.db import AsyncSessionLocal
from app.db.models import FirmReviewResearchTaskRow, FirmReviewRow, PifFirmRow
from app.services.llm_gateway import call_skill_json


logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/firm-review-research/SKILL.md"
OPEN_STATUSES = {"queued", "in_progress"}
LOCAL_RESEARCH_PROVIDER = "possibleos_openclaw"
MAX_REVIEWS_PER_SOURCE = 1_000
INDEPENDENT_REVIEW_SOURCES = {
    "google", "yelp", "avvo", "bbb", "facebook", "reviews.io",
    "trustpilot", "martindale", "lawyers.com",
}
GOOGLE_MAPS_BASE_URL = "https://www.google.com"
GOOGLE_MAPS_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


class FirmReviewResearchError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _valid_url(value: Any) -> str | None:
    candidate = str(value or "").strip()
    return candidate if candidate.lower().startswith(("https://", "http://")) else None


def _valid_date(value: Any) -> str | None:
    candidate = str(value or "").strip()
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


class _FirstLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.href is not None or tag.lower() != "link":
            return
        values = dict(attrs)
        href = html.unescape(str(values.get("href") or ""))
        if href.startswith(("/search?tbm=map", "/maps/preview/place")):
            self.href = href


def _first_link_href(document: str) -> str | None:
    parser = _FirstLinkParser()
    parser.feed(document)
    return parser.href


def _google_json(response_text: str) -> Any:
    payload = response_text.lstrip()
    if payload.startswith(")]}'"):
        payload = payload[4:].lstrip()
    return json.loads(payload)


async def _get_with_backoff(client: httpx.AsyncClient, url: str) -> httpx.Response:
    retries = max(1, min(5, int(os.getenv("FIRM_REVIEW_HTTP_RETRIES", "3"))))
    delay = max(0.0, float(os.getenv("FIRM_REVIEW_REQUEST_DELAY_S", "0.15")))
    last_response: httpx.Response | None = None
    for attempt in range(retries):
        if delay:
            await asyncio.sleep(delay)
        response = await client.get(url)
        last_response = response
        if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
            response.raise_for_status()
            return response
        if attempt + 1 < retries:
            await asyncio.sleep(min(8.0, 0.5 * (2 ** attempt)))
    assert last_response is not None
    last_response.raise_for_status()
    return last_response


def _domain(value: str | None) -> str | None:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    hostname = (urlparse(candidate).hostname or "").lower()
    return hostname.removeprefix("www.") or None


def _domains_match(expected: str | None, actual: str | None) -> bool:
    if not expected or not actual:
        return True
    if expected == actual:
        return True
    return re.sub(r"[^a-z0-9]", "", expected) == re.sub(r"[^a-z0-9]", "", actual)


def _listing_from_search_payload(payload: Any) -> dict[str, Any] | None:
    try:
        rows = payload[0][1]
    except (IndexError, KeyError, TypeError):
        return None
    for row in rows if isinstance(rows, list) else []:
        try:
            listing = row[14]
            identity = str(listing[10])
            firm_name = str(listing[11])
        except (IndexError, TypeError):
            continue
        match = re.search(r"0x[0-9a-f]+:0x([0-9a-f]+)", identity, re.IGNORECASE)
        if not match:
            continue
        website = None
        try:
            website = str(listing[7][1] or "").strip() or None
        except (IndexError, TypeError):
            pass
        return {
            "cid": str(int(match.group(1), 16)),
            "firm_name": firm_name,
            "website": website,
        }
    return None


def _reviews_from_profile_payload(payload: Any, listing_url: str) -> list[dict[str, Any]]:
    try:
        rows = payload[6][175][9][0][0]
    except (IndexError, KeyError, TypeError):
        return []
    reviews: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            record = row[0]
            reviewer_name = str(record[1][4][5][0] or "").strip() or None
            rating = float(record[2][0][0])
            text = str(record[2][15][0][0] or "").strip()
        except (IndexError, TypeError, ValueError):
            continue
        if not text:
            continue
        review_date = None
        try:
            timestamp_us = float(record[1][2])
            review_date = datetime.fromtimestamp(timestamp_us / 1_000_000, tz=timezone.utc).date().isoformat()
        except (IndexError, TypeError, ValueError, OSError):
            pass
        review_url = None
        try:
            review_url = _valid_url(record[4][3][0])
        except (IndexError, TypeError):
            pass
        reviews.append({
            "reviewer_name": reviewer_name,
            "rating": rating,
            "review_date": review_date,
            "text": text,
            "review_url": review_url or listing_url,
        })
    return reviews


async def research_google_maps_reviews(
    firm_name: str,
    website: str | None,
    address: str | None = None,
) -> dict[str, Any] | None:
    """Collect the public review records exposed by an exact Google Maps listing."""
    expected_domain = _domain(website)
    clean_name = re.sub(r"[^a-zA-Z0-9&'. -]+", " ", firm_name)
    clean_name = re.sub(r"\s+", " ", clean_name).strip()
    location = ""
    address_parts = [part.strip() for part in str(address or "").split(",") if part.strip()]
    if len(address_parts) >= 2:
        location = " ".join(address_parts[-2:])
        location = re.sub(r"\b\d{5}(?:-\d{4})?\b", "", location).strip()
    query = " ".join(part for part in (clean_name, location) if part)
    timeout = float(os.getenv("FIRM_REVIEW_GOOGLE_TIMEOUT_S", "30"))
    async with httpx.AsyncClient(
        timeout=timeout,
        headers=GOOGLE_MAPS_HEADERS,
        follow_redirects=True,
    ) as client:
        search_url = f"{GOOGLE_MAPS_BASE_URL}/maps/search/{quote(query)}?hl=en"
        search_page = await _get_with_backoff(client, search_url)
        search_href = _first_link_href(search_page.text)
        if not search_href:
            return None
        search_data = await _get_with_backoff(client, urljoin(GOOGLE_MAPS_BASE_URL, search_href))
        listing = _listing_from_search_payload(_google_json(search_data.text))
        if not listing:
            return None
        listing_domain = _domain(listing.get("website"))
        if not _domains_match(expected_domain, listing_domain):
            logger.warning(
                "Rejected Google Maps listing domain mismatch for %s: expected=%s actual=%s",
                firm_name,
                expected_domain,
                listing_domain,
            )
            return None
        listing_url = f"{GOOGLE_MAPS_BASE_URL}/maps?cid={listing['cid']}&hl=en"
        profile_page = await _get_with_backoff(client, listing_url)
        profile_href = _first_link_href(profile_page.text)
        if not profile_href:
            return None
        profile_data = await _get_with_backoff(client, urljoin(GOOGLE_MAPS_BASE_URL, profile_href))
        reviews = _reviews_from_profile_payload(_google_json(profile_data.text), listing_url)
    if not reviews:
        return None
    normalized_sources = normalize_review_sources([{
            "source": "google",
            "listing_url": listing_url,
            "coverage_note": (
                f"Collected {len(reviews)} complete public reviews exposed by the live Google Maps profile payload."
            ),
            "reviews": reviews,
        }])
    return {
        "sources": normalized_sources,
        "review_count": len(reviews),
        "source_count": 1,
        "coverage_note": "Google Maps was checked directly; its public profile payload exposes a bounded review sample.",
        "researched_at": _utcnow().isoformat(),
        "provider": "google_maps_public_payload",
    }


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _review_text_hash(text: Any) -> str:
    return hashlib.sha256(_normalized_text(text).encode("utf-8")).hexdigest()


def _review_key(source: str, listing_url: str, review: dict[str, Any]) -> tuple[str, ...]:
    return (
        source.casefold(),
        listing_url.lower().rstrip("/"),
        _normalized_text(review.get("reviewer_name")),
        str(review.get("review_date") or ""),
        str(review.get("text_hash") or _review_text_hash(review.get("text"))),
    )


def normalize_review_sources(
    raw_sources: Any,
    *,
    collected_at: str | None = None,
) -> list[dict[str, Any]]:
    """Keep only public, source-backed, verbatim review records."""
    if not isinstance(raw_sources, list):
        return []
    sources: list[dict[str, Any]] = []
    collected_at = collected_at or _utcnow().isoformat()
    seen_reviews: set[tuple[str, str, str]] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            continue
        listing_url = _valid_url(raw_source.get("listing_url"))
        source = str(raw_source.get("source") or "other").strip().lower()[:64]
        if not listing_url or not source:
            continue
        reviews: list[dict[str, Any]] = []
        raw_reviews = raw_source.get("reviews") if isinstance(raw_source.get("reviews"), list) else []
        for raw_review in raw_reviews[:MAX_REVIEWS_PER_SOURCE]:
            if not isinstance(raw_review, dict):
                continue
            text = str(raw_review.get("text") or "").strip()
            if not text:
                continue
            reviewer_name = str(raw_review.get("reviewer_name") or "").strip() or None
            review_url = _valid_url(raw_review.get("review_url"))
            rating_raw = raw_review.get("rating")
            try:
                rating = float(rating_raw) if rating_raw is not None else None
            except (TypeError, ValueError):
                rating = None
            if rating is not None and not 0 <= rating <= 5:
                rating = None
            key = (listing_url.lower().rstrip("/"), (reviewer_name or "").lower(), text.lower())
            if key in seen_reviews:
                continue
            seen_reviews.add(key)
            reviews.append({
                "reviewer_name": reviewer_name,
                "rating": rating,
                "review_date": _valid_date(raw_review.get("review_date")),
                "text": text[:20_000],
                "review_url": review_url,
                "text_hash": _review_text_hash(text[:20_000]),
                "collected_at": str(raw_review.get("collected_at") or collected_at),
            })
        sources.append({
            "source": source,
            "listing_url": listing_url,
            "coverage_note": str(raw_source.get("coverage_note") or "").strip()[:2_000] or None,
            "reviews": reviews,
        })
    return sources


def merge_review_payloads(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Merge a research result without deleting previously collected evidence."""
    prior = existing if isinstance(existing, dict) else {}
    merged_sources: list[dict[str, Any]] = []
    source_index: dict[tuple[str, str], dict[str, Any]] = {}
    review_index: dict[tuple[str, ...], dict[str, Any]] = {}

    def absorb(raw_sources: Any, *, preserve_fields: bool) -> None:
        for raw_source in raw_sources if isinstance(raw_sources, list) else []:
            if not isinstance(raw_source, dict):
                continue
            source = str(raw_source.get("source") or "other").strip().lower()[:64]
            listing_url = _valid_url(raw_source.get("listing_url"))
            if not source or not listing_url:
                continue
            source_key = (source, listing_url.lower().rstrip("/"))
            target_source = source_index.get(source_key)
            if target_source is None:
                target_source = {
                    "source": source,
                    "listing_url": listing_url,
                    "coverage_note": raw_source.get("coverage_note"),
                    "reviews": [],
                }
                source_index[source_key] = target_source
                merged_sources.append(target_source)
            elif raw_source.get("coverage_note"):
                target_source["coverage_note"] = raw_source.get("coverage_note")

            for raw_review in raw_source.get("reviews") or []:
                if not isinstance(raw_review, dict) or not str(raw_review.get("text") or "").strip():
                    continue
                review = dict(raw_review) if preserve_fields else dict(raw_review)
                review.setdefault("text_hash", _review_text_hash(review.get("text")))
                review.setdefault("collected_at", _utcnow().isoformat())
                key = _review_key(source, listing_url, review)
                current = review_index.get(key)
                if current is None:
                    review_index[key] = review
                    target_source["reviews"].append(review)
                else:
                    for field, value in review.items():
                        if value is not None and (current.get(field) in (None, "") or field == "classification"):
                            current[field] = value

    absorb(prior.get("sources"), preserve_fields=True)
    before = len(review_index)
    absorb(incoming.get("sources"), preserve_fields=True)
    after = len(review_index)

    merged = dict(prior)
    for key, value in incoming.items():
        if key not in {"sources", "review_count", "source_count"} and value is not None:
            merged[key] = value
    merged["sources"] = merged_sources
    merged["review_count"] = after
    merged["source_count"] = len(merged_sources)
    merged["last_merged_at"] = _utcnow().isoformat()
    classified = sum(
        1 for source in merged_sources for review in source["reviews"]
        if isinstance(review.get("classification"), dict)
    )
    merged["classified_count"] = classified
    merged["unclassified_count"] = after - classified
    if after and classified == after:
        merged["classification_status"] = "completed"
    elif after:
        merged["classification_status"] = "partial"
    return merged, {
        "existing_reviews": before,
        "incoming_reviews": sum(
            len(source.get("reviews") or [])
            for source in incoming.get("sources") or []
            if isinstance(source, dict)
        ),
        "reviews_added": after - before,
        "deduplicated": max(0, before + sum(
            len(source.get("reviews") or [])
            for source in incoming.get("sources") or []
            if isinstance(source, dict)
        ) - after),
        "total_reviews": after,
    }


async def research_public_reviews(
    firm_name: str,
    website: str | None,
    address: str | None,
) -> dict[str, Any]:
    google_result: dict[str, Any] | None = None
    try:
        google_result = await research_google_maps_reviews(firm_name, website, address)
    except Exception:
        logger.exception("Direct Google Maps review research failed for %s", firm_name)

    if os.getenv("FIRM_REVIEW_OPENCLAW_FALLBACK", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return google_result or {
            "sources": [],
            "review_count": 0,
            "source_count": 0,
            "coverage_note": "No exact Google Maps listing with public review text was verified.",
            "researched_at": _utcnow().isoformat(),
            "provider": "google_maps_public_payload",
        }

    session_key = hashlib.sha256(
        f"{firm_name}|{website or ''}|{address or ''}".encode("utf-8")
    ).hexdigest()[:16]
    result = await call_skill_json(
        skill_path=SKILL_PATH,
        payload={
            "firm_name": firm_name,
            "official_website": website,
            "address": address,
        },
        required_fields=["sources", "coverage_note"],
        model=os.getenv("FIRM_REVIEW_RESEARCH_MODEL", "openclaw/main"),
        timeout_s=int(os.getenv("FIRM_REVIEW_RESEARCH_TIMEOUT_S", "600")),
        max_tokens=int(os.getenv("FIRM_REVIEW_RESEARCH_MAX_TOKENS", "20000")),
        retries=1,
        gateway_user=f"firm-review-research:{session_key}:{uuid.uuid4().hex[:8]}",
    )
    sources = normalize_review_sources(result.parsed.get("sources"))
    supplemental = {
        "sources": sources,
        "review_count": sum(len(source["reviews"]) for source in sources),
        "source_count": len(sources),
        "coverage_note": str(result.parsed.get("coverage_note") or "").strip()[:4_000] or None,
        "researched_at": _utcnow().isoformat(),
        "provider": LOCAL_RESEARCH_PROVIDER,
    }
    if google_result is None:
        return supplemental
    merged, _ = merge_review_payloads(google_result, supplemental)
    merged["provider"] = f"google_maps_public_payload+{LOCAL_RESEARCH_PROVIDER}"
    merged["coverage_note"] = " ".join(filter(None, [
        google_result.get("coverage_note"),
        supplemental.get("coverage_note"),
    ]))[:4_000]
    return merged


async def start_firm_review_research(pif_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            raise FirmReviewResearchError(404, "firm_not_found")
        task = (await session.execute(
            select(FirmReviewResearchTaskRow)
            .where(
                FirmReviewResearchTaskRow.pif_id == pif_id,
                FirmReviewResearchTaskRow.status.in_(OPEN_STATUSES),
            )
            .order_by(FirmReviewResearchTaskRow.requested_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if task is not None:
            return {
                "task_id": task.task_id,
                "pif_id": pif_id,
                "firm_name": firm.firm_name,
                "status": task.status,
                "message": "Public review research is already queued or running",
            }
        review_row = await session.get(FirmReviewRow, pif_id)
        if review_row is None:
            review_row = FirmReviewRow(pif_id=pif_id)
            session.add(review_row)
        task_id = f"firm-reviews-{uuid.uuid4().hex}"
        session.add(FirmReviewResearchTaskRow(
            task_id=task_id,
            pif_id=pif_id,
            status="queued",
            requested_at=_utcnow(),
        ))
        review_row.review_research_status = "queued"
        review_row.review_research_provider = LOCAL_RESEARCH_PROVIDER
        review_row.review_research_error = None
        review_row.updated_at = _utcnow()
        await session.commit()
    return {
        "task_id": task_id,
        "pif_id": pif_id,
        "firm_name": firm.firm_name,
        "status": "queued",
        "message": "Queued for local public-review research",
    }


def _payload_review_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    return sum(
        len(source.get("reviews") or [])
        for source in payload.get("sources") or []
        if isinstance(source, dict)
    )


def _is_canonical_firm_id(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


async def queue_firm_review_campaign(
    *,
    limit: int = 500,
    include_researched: bool = False,
) -> dict[str, Any]:
    """Queue canonical firms in the order most likely to expand the corpus."""
    limit = max(1, min(5_000, int(limit)))
    async with AsyncSessionLocal() as session:
        firms = list((await session.execute(
            select(
                PifFirmRow.id,
                PifFirmRow.firm_name,
                PifFirmRow.website,
                PifFirmRow.canonical_website,
                PifFirmRow.entity_type,
                PifFirmRow.icp_score,
            )
        )).all())
        review_rows = {
            row.pif_id: row
            for row in (await session.execute(select(FirmReviewRow))).scalars().all()
        }
        task_rows = list(
            (await session.execute(select(FirmReviewResearchTaskRow))).scalars().all()
        )
        active_ids = {row.pif_id for row in task_rows if row.status in OPEN_STATUSES}
        researched_ids = {row.pif_id for row in task_rows if row.status == "completed"}

        candidates: list[tuple[int, int, int, str, str]] = []
        for firm_id, raw_firm_name, raw_website, raw_canonical_website, entity_type, icp_score in firms:
            website = str(raw_canonical_website or raw_website or "").strip()
            firm_name = str(raw_firm_name or "").strip()
            if (
                entity_type not in {"pi_law_firm", "personal_injury_law_firm"}
                or not _is_canonical_firm_id(firm_id)
                or not website
                or not firm_name
                or firm_id in active_ids
            ):
                continue
            was_researched = firm_id in researched_ids
            if was_researched and not include_researched:
                continue
            review_count = _payload_review_count(
                review_rows.get(firm_id).reviews_json if review_rows.get(firm_id) else {}
            )
            candidates.append((
                1 if was_researched else 0,
                review_count,
                -int(icp_score or 0),
                firm_name.casefold(),
                firm_id,
            ))

        candidates.sort(key=lambda item: item[:3])
        queued_ids: list[str] = []
        now = _utcnow()
        for _, _, _, _, firm_id in candidates[:limit]:
            review_row = review_rows.get(firm_id)
            if review_row is None:
                review_row = FirmReviewRow(pif_id=firm_id)
                session.add(review_row)
                review_rows[firm_id] = review_row
            task_id = f"firm-reviews-{uuid.uuid4().hex}"
            session.add(FirmReviewResearchTaskRow(
                task_id=task_id,
                pif_id=firm_id,
                status="queued",
                requested_at=now,
            ))
            review_row.review_research_status = "queued"
            review_row.review_research_provider = LOCAL_RESEARCH_PROVIDER
            review_row.review_research_error = None
            review_row.updated_at = now
            queued_ids.append(firm_id)
        await session.commit()
    return {
        "queued": len(queued_ids),
        "eligible": len(candidates),
        "include_researched": include_researched,
        "sample_pif_ids": queued_ids[:10],
    }


async def get_review_corpus_progress() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        review_rows = list((await session.execute(select(FirmReviewRow))).scalars().all())
        tasks = list((await session.execute(select(FirmReviewResearchTaskRow))).scalars().all())

    raw_count = 0
    distinct_keys: set[tuple[str, ...]] = set()
    independent_keys: set[tuple[str, ...]] = set()
    classified_keys: set[tuple[str, ...]] = set()
    source_counts: dict[str, int] = {}
    firms_with_reviews: set[str] = set()
    cross_source_text: dict[tuple[str, str], set[str]] = {}
    for row in review_rows:
        payload = row.reviews_json if isinstance(row.reviews_json, dict) else {}
        for source_block in payload.get("sources") or []:
            if not isinstance(source_block, dict):
                continue
            source = str(source_block.get("source") or "other").strip().lower()
            listing_url = str(source_block.get("listing_url") or "").strip()
            for review in source_block.get("reviews") or []:
                if not isinstance(review, dict) or not str(review.get("text") or "").strip():
                    continue
                raw_count += 1
                text_hash = str(review.get("text_hash") or _review_text_hash(review.get("text")))
                key = _review_key(source, listing_url, review)
                distinct_keys.add((row.pif_id, *key))
                firms_with_reviews.add(row.pif_id)
                source_counts[source] = source_counts.get(source, 0) + 1
                cross_source_text.setdefault((row.pif_id, text_hash), set()).add(source)
                if source in INDEPENDENT_REVIEW_SOURCES:
                    independent_keys.add((row.pif_id, *key))
                classification = review.get("classification")
                if (
                    isinstance(classification, dict)
                    and classification.get("classification_version") == "pi_reviews_v1"
                ):
                    classified_keys.add((row.pif_id, *key))

    task_counts: dict[str, int] = {}
    reviews_added = 0
    for task in tasks:
        task_counts[task.status] = task_counts.get(task.status, 0) + 1
        if isinstance(task.result_summary, dict):
            reviews_added += int(task.result_summary.get("reviews_added") or 0)
    distinct_count = len(distinct_keys)
    return {
        "target_distinct_reviews": 5_000,
        "raw_reviews": raw_count,
        "distinct_reviews": distinct_count,
        "deduplicated_reviews": raw_count - distinct_count,
        "independent_distinct_reviews": len(independent_keys),
        "cross_source_republications": sum(1 for sources in cross_source_text.values() if len(sources) > 1),
        "firms_with_reviews": len(firms_with_reviews),
        "source_distribution": dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))),
        "classified_reviews": len(classified_keys),
        "unclassified_reviews": distinct_count - len(classified_keys),
        "classification_version": "pi_reviews_v1",
        "task_counts": task_counts,
        "reviews_added_by_campaign_tasks": reviews_added,
        "progress_percent": round(min(100.0, distinct_count / 5_000 * 100), 2),
        "gate_met": distinct_count >= 5_000,
        "generated_at": _utcnow().isoformat(),
    }


async def get_firm_review_research_status(task_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        task = await session.get(FirmReviewResearchTaskRow, task_id)
        if task is None:
            raise FirmReviewResearchError(404, "review_research_task_not_found")
        return {
            "task_id": task.task_id,
            "pif_id": task.pif_id,
            "status": task.status,
            "requested_at": task.requested_at.isoformat() if task.requested_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            **(task.result_summary if isinstance(task.result_summary, dict) else {}),
        }


async def _claim_next_task() -> tuple[str, str] | None:
    async with AsyncSessionLocal() as session:
        task = (await session.execute(
            select(FirmReviewResearchTaskRow)
            .where(FirmReviewResearchTaskRow.status == "queued")
            .order_by(FirmReviewResearchTaskRow.requested_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )).scalar_one_or_none()
        if task is None:
            return None
        task.status = "in_progress"
        task.started_at = _utcnow()
        review_row = await session.get(FirmReviewRow, task.pif_id)
        if review_row is not None:
            review_row.review_research_status = "in_progress"
            review_row.updated_at = _utcnow()
        await session.commit()
        return task.task_id, task.pif_id


async def _finish_task(task_id: str, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        task = await session.get(FirmReviewResearchTaskRow, task_id)
        if task is None:
            return
        review_row = await session.get(FirmReviewRow, task.pif_id)
        firm = await session.get(PifFirmRow, task.pif_id)
        if result is not None:
            task.status = "completed"
            task.result_summary = {
                "firm_name": firm.firm_name if firm else None,
                "review_count": result["review_count"],
                "source_count": result["source_count"],
                "coverage_note": result.get("coverage_note"),
            }
            if review_row is not None:
                merged, merge_summary = merge_review_payloads(review_row.reviews_json, result)
                review_row.reviews_json = merged
                review_row.review_research_status = "completed"
                review_row.review_research_provider = str(result.get("provider") or LOCAL_RESEARCH_PROVIDER)
                review_row.last_review_researched_at = now
                review_row.review_research_error = None
                review_row.updated_at = now
                task.result_summary.update(merge_summary)
        else:
            task.status = "failed"
            task.result_summary = {"firm_name": firm.firm_name if firm else None, "message": error or "Public review research failed"}
            if review_row is not None:
                review_row.review_research_status = "failed"
                review_row.review_research_error = error or "Public review research failed"
                review_row.updated_at = now
        task.completed_at = now
        await session.commit()


async def _run_task(task_id: str, pif_id: str) -> None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            await _finish_task(task_id, error="Firm record is missing")
            return
        website = firm.canonical_website or firm.website
        address = firm.addresses[0] if isinstance(firm.addresses, list) and firm.addresses else None
        firm_name = str(firm.firm_name or "").strip()
    if not firm_name:
        await _finish_task(task_id, error="Firm name is missing")
        return
    try:
        result = await research_public_reviews(firm_name, website, str(address) if address else None)
    except Exception as exc:
        logger.exception("Public review research failed for %s", pif_id)
        await _finish_task(task_id, error=str(exc)[:500])
        return
    try:
        from app.services.firm_review_classification import classify_reviews_json, classify_reviews_locally

        if result.get("provider") == "google_maps_public_payload":
            result = classify_reviews_locally(result)
        else:
            result = await classify_reviews_json(firm_name, result)
    except Exception as exc:
        logger.exception("Public review classification failed for %s", pif_id)
        result.update({
            "classification_status": "failed",
            "classification_error": str(exc)[:500],
        })
    await _finish_task(task_id, result=result)


async def recover_interrupted_firm_review_research() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(FirmReviewResearchTaskRow)
            .where(FirmReviewResearchTaskRow.status == "in_progress")
            .values(status="queued", started_at=None)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def firm_review_research_loop(*, poll_seconds: float = 2.0) -> None:
    while True:
        try:
            claimed = await _claim_next_task()
            if claimed is None:
                await asyncio.sleep(poll_seconds)
                continue
            await _run_task(*claimed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Firm-review research worker tick failed")
            await asyncio.sleep(poll_seconds)
