"""Durable local collection of source-backed public firm reviews."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.db import AsyncSessionLocal
from app.db.models import FirmReviewResearchTaskRow, FirmReviewRow, PifFirmRow
from app.services.llm_gateway import call_skill_json


logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/firm-review-research/SKILL.md"
OPEN_STATUSES = {"queued", "in_progress"}
LOCAL_RESEARCH_PROVIDER = "possibleos_openclaw"
MAX_REVIEWS_PER_SOURCE = 1_000


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


def normalize_review_sources(raw_sources: Any) -> list[dict[str, Any]]:
    """Keep only public, source-backed, verbatim review records."""
    if not isinstance(raw_sources, list):
        return []
    sources: list[dict[str, Any]] = []
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
            })
        sources.append({
            "source": source,
            "listing_url": listing_url,
            "coverage_note": str(raw_source.get("coverage_note") or "").strip()[:2_000] or None,
            "reviews": reviews,
        })
    return sources


async def research_public_reviews(
    firm_name: str,
    website: str | None,
    address: str | None,
) -> dict[str, Any]:
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
    )
    sources = normalize_review_sources(result.parsed.get("sources"))
    return {
        "sources": sources,
        "review_count": sum(len(source["reviews"]) for source in sources),
        "source_count": len(sources),
        "coverage_note": str(result.parsed.get("coverage_note") or "").strip()[:4_000] or None,
        "researched_at": _utcnow().isoformat(),
        "provider": LOCAL_RESEARCH_PROVIDER,
    }


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
                review_row.reviews_json = result
                review_row.review_research_status = "completed"
                review_row.review_research_provider = LOCAL_RESEARCH_PROVIDER
                review_row.last_review_researched_at = now
                review_row.review_research_error = None
                review_row.updated_at = now
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
        from app.services.firm_review_classification import classify_reviews_json

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
