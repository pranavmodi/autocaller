"""Independent 30-day maintenance scheduling for firm jobs and sitemaps."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import PifFirmRow, PifJobResearchTaskRow
from app.services.pif_job_posting_research import (
    OPEN_STATUSES,
    start_job_posting_research,
    start_sitemap_research,
)


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


async def _maintenance_candidates(*, now: datetime) -> dict[str, Any]:
    refresh_days = _int_env("PIF_RESEARCH_MAINTENANCE_REFRESH_DAYS", DEFAULT_REFRESH_DAYS)
    retry_days = _int_env("PIF_RESEARCH_MAINTENANCE_RETRY_DAYS", DEFAULT_RETRY_DAYS)
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with AsyncSessionLocal() as session:
        firms = (await session.execute(
            select(
                PifFirmRow.id,
                PifFirmRow.firm_name,
                PifFirmRow.website,
                PifFirmRow.canonical_website,
                PifFirmRow.research_data,
                PifFirmRow.created_at,
            ).order_by(PifFirmRow.created_at.asc(), PifFirmRow.id.asc())
        )).all()
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
    open_keys = {(str(pif_id), str(kind)) for pif_id, kind in open_rows}
    daily_counts = {str(kind): int(count) for kind, count in daily_rows}
    job_due: list[tuple[datetime | None, str]] = []
    sitemap_due: list[tuple[datetime | None, str]] = []
    for firm in firms:
        if str(firm.firm_name or "").strip() and (firm.id, "research") not in open_keys:
            due, due_at = _job_due(
                firm,
                now=now,
                refresh_days=refresh_days,
                retry_days=retry_days,
            )
            if due:
                job_due.append((due_at, firm.id))
        if (firm.canonical_website or firm.website) and (firm.id, "sitemap") not in open_keys:
            due, due_at = _sitemap_due(
                firm,
                now=now,
                refresh_days=refresh_days,
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
    return {
        "job_ids": [firm_id for _, firm_id in job_due],
        "sitemap_ids": [firm_id for _, firm_id in sitemap_due],
        "open_job_tasks": sum(kind == "research" for _, kind in open_keys),
        "open_sitemap_tasks": sum(kind == "sitemap" for _, kind in open_keys),
        "today_job_tasks": daily_counts.get("research", 0),
        "today_sitemap_tasks": daily_counts.get("sitemap", 0),
        "refresh_days": refresh_days,
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
        "retry_days": candidates["retry_days"],
        "total_firms": candidates["total_firms"],
        "firms_with_websites": candidates["firms_with_websites"],
        "due_job_postings": len(candidates["job_ids"]),
        "due_sitemaps": len(candidates["sitemap_ids"]),
        "open_job_tasks": candidates["open_job_tasks"],
        "open_sitemap_tasks": candidates["open_sitemap_tasks"],
        "today_job_tasks": candidates["today_job_tasks"],
        "today_sitemap_tasks": candidates["today_sitemap_tasks"],
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
    sitemap_limit = max(0, queue_limit - candidates["today_sitemap_tasks"])
    job_limit = max(0, queue_limit - candidates["today_job_tasks"])
    sitemap_ids = candidates["sitemap_ids"][:sitemap_limit]
    job_ids = candidates["job_ids"][:job_limit]
    queued_sitemaps: list[str] = []
    queued_jobs: list[str] = []
    failures: list[dict[str, str]] = []

    # Sitemap requests are fast and are deliberately placed ahead of gateway jobs.
    for firm_id in sitemap_ids:
        try:
            result = await start_sitemap_research(firm_id)
            if result.get("status") in OPEN_STATUSES:
                queued_sitemaps.append(firm_id)
        except Exception as exc:
            failures.append({"pif_id": firm_id, "kind": "sitemap", "error": str(exc)[:300]})
    for firm_id in job_ids:
        try:
            result = await start_job_posting_research(firm_id)
            if result.get("status") in OPEN_STATUSES:
                queued_jobs.append(firm_id)
        except Exception as exc:
            failures.append({"pif_id": firm_id, "kind": "job_postings", "error": str(exc)[:300]})
    return {
        "status": "queued",
        "queued_at": queued_at.isoformat(),
        "limit_per_kind": queue_limit,
        "refresh_days": candidates["refresh_days"],
        "retry_days": candidates["retry_days"],
        "due_job_postings_before_queue": len(candidates["job_ids"]),
        "due_sitemaps_before_queue": len(candidates["sitemap_ids"]),
        "already_queued_job_postings_today": candidates["today_job_tasks"],
        "already_queued_sitemaps_today": candidates["today_sitemap_tasks"],
        "queued_job_postings": len(queued_jobs),
        "queued_sitemaps": len(queued_sitemaps),
        "job_pif_ids": queued_jobs,
        "sitemap_pif_ids": queued_sitemaps,
        "failures": failures,
    }


async def research_maintenance_loop() -> None:
    startup_delay = _int_env("PIF_RESEARCH_MAINTENANCE_STARTUP_DELAY_SECONDS", 120, minimum=0)
    interval = _int_env("PIF_RESEARCH_MAINTENANCE_INTERVAL_SECONDS", 86_400)
    await asyncio.sleep(startup_delay)
    while True:
        try:
            if maintenance_enabled():
                result = await queue_due_firm_maintenance()
                logger.info("PIF research maintenance: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("PIF research maintenance tick failed")
        await asyncio.sleep(interval)
