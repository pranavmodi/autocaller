"""Independent freshness scheduling for firm profile and signal research."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    FirmResearchStateRow,
    FirmReviewResearchTaskRow,
    PifEnrichmentTaskRow,
    PifFirmRow,
    PifJobResearchTaskRow,
)
from app.services.firm_review_research import start_firm_review_research
from app.services.pif_change_detection import (
    MODULE_JOBS,
    MODULE_PROFILE,
    MODULE_SITEMAP,
    refresh_days_for,
)
from app.services.pif_job_posting_research import (
    OPEN_STATUSES,
    start_job_posting_research,
    start_sitemap_research,
)
from app.services.pif_local_enrichment import start_local_firm_enrichment


logger = logging.getLogger(__name__)
DEFAULT_REFRESH_DAYS = 30
DEFAULT_RETRY_DAYS = 3
DEFAULT_DAILY_LIMIT = 175


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def maintenance_enabled() -> bool:
    return os.getenv("PIF_RESEARCH_MAINTENANCE_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _due_at(
    checked_at: datetime | None,
    status: str | None,
    *,
    refresh_days: int,
    retry_days: int,
) -> datetime | None:
    if checked_at is None:
        return None
    delay = retry_days if status in {"failed", "missing"} else refresh_days
    return checked_at + timedelta(days=delay)


def _is_due(due_at: datetime | None, *, now: datetime) -> bool:
    return due_at is None or due_at <= now


def _research_state(firm: PifFirmRow) -> dict[str, Any]:
    return dict(firm.research_data) if isinstance(firm.research_data, dict) else {}


def _job_due(
    firm: PifFirmRow,
    *,
    now: datetime,
    refresh_days: int,
    retry_days: int,
) -> tuple[bool, datetime | None]:
    data = _research_state(firm)
    checked_at = _parse_datetime(data.get("last_job_postings_researched_at"))
    status = str(data.get("job_postings_research_status") or "").lower() or None
    due_at = _due_at(checked_at, status, refresh_days=refresh_days, retry_days=retry_days)
    return _is_due(due_at, now=now), due_at


def _sitemap_due(
    firm: PifFirmRow,
    *,
    now: datetime,
    refresh_days: int,
    retry_days: int,
) -> tuple[bool, datetime | None]:
    data = _research_state(firm)
    monitor = data.get("sitemap_monitor") if isinstance(data.get("sitemap_monitor"), dict) else {}
    checked_at = _parse_datetime(monitor.get("checked_at"))
    status = str(monitor.get("status") or "").lower() or None
    due_at = _due_at(checked_at, status, refresh_days=refresh_days, retry_days=retry_days)
    return _is_due(due_at, now=now), due_at


def _state_due(
    states: dict[tuple[str, str], FirmResearchStateRow],
    *,
    pif_id: str,
    module: str,
    now: datetime,
    checked_at: datetime | None,
    status: str | None,
    refresh_days: int,
    retry_days: int,
) -> tuple[bool, datetime | None]:
    state = states.get((pif_id, module))
    if state is not None and state.next_due_at is not None:
        return _is_due(state.next_due_at, now=now), state.next_due_at
    due_at = _due_at(
        checked_at,
        status,
        refresh_days=refresh_days,
        retry_days=retry_days,
    )
    return _is_due(due_at, now=now), due_at


async def _maintenance_candidates(*, now: datetime) -> dict[str, Any]:
    refresh_days = _int_env("PIF_RESEARCH_MAINTENANCE_REFRESH_DAYS", DEFAULT_REFRESH_DAYS)
    retry_days = _int_env("PIF_RESEARCH_MAINTENANCE_RETRY_DAYS", DEFAULT_RETRY_DAYS)
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with AsyncSessionLocal() as session:
        firms = list((await session.execute(
            select(
                PifFirmRow.id,
                PifFirmRow.firm_name,
                PifFirmRow.canonical_website,
                PifFirmRow.website,
                PifFirmRow.entity_type,
                PifFirmRow.icp_tier,
                PifFirmRow.last_researched_at,
                PifFirmRow.research_status,
                PifFirmRow.research_data["last_job_postings_researched_at"].as_string().label(
                    "last_job_postings_researched_at"
                ),
                PifFirmRow.research_data["job_postings_research_status"].as_string().label(
                    "job_postings_research_status"
                ),
                PifFirmRow.research_data["sitemap_monitor"]["checked_at"].as_string().label(
                    "sitemap_checked_at"
                ),
                PifFirmRow.research_data["sitemap_monitor"]["status"].as_string().label(
                    "sitemap_status"
                ),
            ).order_by(PifFirmRow.created_at.asc(), PifFirmRow.id.asc())
        )).all())
        states = {
            (row.pif_id, row.module): row
            for row in (await session.execute(select(
                FirmResearchStateRow.pif_id,
                FirmResearchStateRow.module,
                FirmResearchStateRow.next_due_at,
            ))).all()
        }
        open_rows = (await session.execute(
            select(PifJobResearchTaskRow.pif_id, PifJobResearchTaskRow.kind).where(
                PifJobResearchTaskRow.status.in_(OPEN_STATUSES),
                PifJobResearchTaskRow.kind.in_(("research", "sitemap")),
            )
        )).all()
        daily_rows = (await session.execute(
            select(PifJobResearchTaskRow.kind, func.count())
            .where(
                PifJobResearchTaskRow.requested_at >= day_start,
                PifJobResearchTaskRow.kind.in_(("research", "sitemap")),
            )
            .group_by(PifJobResearchTaskRow.kind)
        )).all()
        open_profile_ids = set((await session.execute(
            select(PifEnrichmentTaskRow.pif_id).where(PifEnrichmentTaskRow.status.in_(OPEN_STATUSES))
        )).scalars().all())
        open_review_ids = set((await session.execute(
            select(FirmReviewResearchTaskRow.pif_id).where(FirmReviewResearchTaskRow.status.in_(OPEN_STATUSES))
        )).scalars().all())
        today_profile_tasks = int((await session.execute(
            select(func.count()).select_from(PifEnrichmentTaskRow).where(
                PifEnrichmentTaskRow.requested_at >= day_start,
            )
        )).scalar_one() or 0)
        today_review_tasks = int((await session.execute(
            select(func.count()).select_from(FirmReviewResearchTaskRow).where(
                FirmReviewResearchTaskRow.requested_at >= day_start,
            )
        )).scalar_one() or 0)
    open_keys = {(str(pif_id), str(kind)) for pif_id, kind in open_rows}
    daily_counts = {str(kind): int(count) for kind, count in daily_rows}
    job_due: list[tuple[datetime | None, str]] = []
    sitemap_due: list[tuple[datetime | None, str]] = []
    profile_due: list[tuple[datetime | None, str]] = []
    review_eligible_ids: set[str] = set()
    for firm in firms:
        profile_refresh_days = refresh_days_for(MODULE_PROFILE, firm.icp_tier)
        signal_refresh_days = refresh_days_for(MODULE_JOBS, firm.icp_tier)
        sitemap_refresh_days = refresh_days_for(MODULE_SITEMAP, firm.icp_tier)
        is_law_firm = firm.entity_type in {"pi_law_firm", "personal_injury_law_firm", "law_firm"}
        if is_law_firm and str(firm.firm_name or "").strip() and firm.id not in open_review_ids:
            review_eligible_ids.add(firm.id)
        if str(firm.firm_name or "").strip() and firm.id not in open_profile_ids:
            due, due_at = _state_due(
                states,
                pif_id=firm.id,
                module=MODULE_PROFILE,
                now=now,
                checked_at=firm.last_researched_at,
                status=firm.research_status,
                refresh_days=profile_refresh_days,
                retry_days=retry_days,
            )
            if due:
                profile_due.append((due_at, firm.id))
        if str(firm.firm_name or "").strip() and (firm.id, "research") not in open_keys:
            due, due_at = _state_due(
                states,
                pif_id=firm.id,
                module=MODULE_JOBS,
                now=now,
                checked_at=_parse_datetime(firm.last_job_postings_researched_at),
                status=str(firm.job_postings_research_status or "").lower() or None,
                refresh_days=signal_refresh_days,
                retry_days=retry_days,
            )
            if due:
                job_due.append((due_at, firm.id))
        if (firm.canonical_website or firm.website) and (firm.id, "sitemap") not in open_keys:
            due, due_at = _state_due(
                states,
                pif_id=firm.id,
                module=MODULE_SITEMAP,
                now=now,
                checked_at=_parse_datetime(firm.sitemap_checked_at),
                status=str(firm.sitemap_status or "").lower() or None,
                refresh_days=sitemap_refresh_days,
                retry_days=retry_days,
            )
            if due:
                sitemap_due.append((due_at, firm.id))
    def oldest_first(row: tuple[datetime | None, str]) -> tuple[bool, datetime, str]:
        return (
            row[0] is not None,
            row[0] or datetime.min.replace(tzinfo=timezone.utc),
            row[1],
        )
    job_due.sort(key=oldest_first)
    sitemap_due.sort(key=oldest_first)
    profile_due.sort(key=oldest_first)
    profile_ids = [firm_id for _, firm_id in profile_due]
    return {
        "profile_ids": profile_ids,
        "job_ids": [firm_id for _, firm_id in job_due],
        "sitemap_ids": [firm_id for _, firm_id in sitemap_due],
        # Review research follows the profile-maintenance cohort. It is no
        # longer scheduled independently by review age or alert enrollment.
        "review_ids": [firm_id for firm_id in profile_ids if firm_id in review_eligible_ids],
        "open_profile_tasks": len(open_profile_ids),
        "open_job_tasks": sum(kind == "research" for _, kind in open_keys),
        "open_sitemap_tasks": sum(kind == "sitemap" for _, kind in open_keys),
        "open_review_tasks": len(open_review_ids),
        "today_profile_tasks": today_profile_tasks,
        "today_job_tasks": daily_counts.get("research", 0),
        "today_sitemap_tasks": daily_counts.get("sitemap", 0),
        "today_review_tasks": today_review_tasks,
        "review_collection_mode": "nightly_profile_maintenance",
        "recent_review_window_days": 14,
        "refresh_days": refresh_days,
        "high_icp_refresh_days": _int_env("PIF_HIGH_ICP_SIGNAL_REFRESH_DAYS", 7),
        "retry_days": retry_days,
        "total_firms": len(firms),
        "firms_with_websites": sum(bool(firm.canonical_website or firm.website) for firm in firms),
    }


async def research_maintenance_status(*, now: datetime | None = None) -> dict[str, Any]:
    checked_at = now or _utcnow()
    candidates = await _maintenance_candidates(now=checked_at)
    return {
        "enabled": maintenance_enabled(),
        "checked_at": checked_at.isoformat(),
        "daily_limit": _int_env("PIF_RESEARCH_MAINTENANCE_DAILY_LIMIT", DEFAULT_DAILY_LIMIT),
        "refresh_days": candidates["refresh_days"],
        "high_icp_refresh_days": candidates["high_icp_refresh_days"],
        "retry_days": candidates["retry_days"],
        "total_firms": candidates["total_firms"],
        "firms_with_websites": candidates["firms_with_websites"],
        "due_profiles": len(candidates["profile_ids"]),
        "due_job_postings": len(candidates["job_ids"]),
        "due_sitemaps": len(candidates["sitemap_ids"]),
        "due_reviews": len(candidates["review_ids"]),
        "review_collection_mode": candidates["review_collection_mode"],
        "recent_review_window_days": candidates["recent_review_window_days"],
        "open_profile_tasks": candidates["open_profile_tasks"],
        "open_job_tasks": candidates["open_job_tasks"],
        "open_sitemap_tasks": candidates["open_sitemap_tasks"],
        "open_review_tasks": candidates["open_review_tasks"],
        "today_profile_tasks": candidates["today_profile_tasks"],
        "today_job_tasks": candidates["today_job_tasks"],
        "today_sitemap_tasks": candidates["today_sitemap_tasks"],
        "today_review_tasks": candidates["today_review_tasks"],
    }


async def queue_due_firm_maintenance(
    *,
    limit: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    queued_at = now or _utcnow()
    queue_limit = max(1, limit or _int_env(
        "PIF_RESEARCH_MAINTENANCE_DAILY_LIMIT",
        DEFAULT_DAILY_LIMIT,
    ))
    candidates = await _maintenance_candidates(now=queued_at)
    profile_limit = max(0, queue_limit - candidates.get("today_profile_tasks", 0))
    sitemap_limit = max(0, queue_limit - candidates.get("today_sitemap_tasks", 0))
    job_limit = max(0, queue_limit - candidates.get("today_job_tasks", 0))
    profile_ids = candidates.get("profile_ids", [])[:profile_limit]
    sitemap_ids = candidates.get("sitemap_ids", [])[:sitemap_limit]
    job_ids = candidates.get("job_ids", [])[:job_limit]
    review_eligible_ids = set(candidates.get("review_ids", []))
    review_ids = [firm_id for firm_id in profile_ids if firm_id in review_eligible_ids]
    queued_profiles: list[str] = []
    queued_sitemaps: list[str] = []
    queued_jobs: list[str] = []
    queued_reviews: list[str] = []
    failures: list[dict[str, str]] = []

    queue_concurrency = _int_env("PIF_RESEARCH_MAINTENANCE_QUEUE_CONCURRENCY", 8)

    async def queue_many(kind: str, firm_ids: list[str], starter) -> list[str]:
        semaphore = asyncio.Semaphore(queue_concurrency)

        async def queue_one(firm_id: str) -> tuple[str, bool, str | None]:
            async with semaphore:
                try:
                    result = await starter(firm_id)
                    return firm_id, result.get("status") in OPEN_STATUSES, None
                except Exception as exc:
                    return firm_id, False, str(exc)[:300]

        rows = await asyncio.gather(*(queue_one(firm_id) for firm_id in firm_ids))
        queued: list[str] = []
        for firm_id, accepted, error in rows:
            if accepted:
                queued.append(firm_id)
            elif error:
                failures.append({"pif_id": firm_id, "kind": kind, "error": error})
        return queued

    # Keep modules ordered while queueing each cohort with bounded concurrency.
    queued_sitemaps = await queue_many("sitemap", sitemap_ids, start_sitemap_research)
    queued_profiles = await queue_many("firm_profile", profile_ids, start_local_firm_enrichment)
    queued_reviews = await queue_many("reviews", review_ids, start_firm_review_research)
    queued_jobs = await queue_many("job_postings", job_ids, start_job_posting_research)
    return {
        "status": "queued",
        "queued_at": queued_at.isoformat(),
        "limit_per_kind": queue_limit,
        "queue_concurrency": queue_concurrency,
        "refresh_days": candidates["refresh_days"],
        "retry_days": candidates["retry_days"],
        "review_collection_mode": candidates.get("review_collection_mode", "nightly_profile_maintenance"),
        "recent_review_window_days": candidates.get("recent_review_window_days", 14),
        "due_profiles_before_queue": len(candidates.get("profile_ids", [])),
        "due_job_postings_before_queue": len(candidates["job_ids"]),
        "due_sitemaps_before_queue": len(candidates["sitemap_ids"]),
        "due_reviews_before_queue": len(candidates.get("review_ids", [])),
        "already_queued_profiles_today": candidates.get("today_profile_tasks", 0),
        "already_queued_job_postings_today": candidates["today_job_tasks"],
        "already_queued_sitemaps_today": candidates["today_sitemap_tasks"],
        "already_queued_reviews_today": candidates.get("today_review_tasks", 0),
        "queued_profiles": len(queued_profiles),
        "queued_job_postings": len(queued_jobs),
        "queued_sitemaps": len(queued_sitemaps),
        "queued_reviews": len(queued_reviews),
        "profile_pif_ids": queued_profiles,
        "job_pif_ids": queued_jobs,
        "sitemap_pif_ids": queued_sitemaps,
        "review_pif_ids": queued_reviews,
        "failures": failures,
    }
