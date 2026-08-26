"""Durable, local job-opening web research for the PI-firm directory."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.db import AsyncSessionLocal
from app.db.models import PifFirmRow, PifJobResearchTaskRow
from app.services.llm_gateway import call_skill_json


logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/job-opening-research/SKILL.md"
OPEN_STATUSES = {"queued", "in_progress"}
WINDOW_DAYS = 30
LOCAL_RESEARCH_PROVIDER = "possibleos_openclaw"


class PifResearchUpstreamError(Exception):
    """Compatibility error used by the existing PIF API handlers."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _firm_website(firm: PifFirmRow) -> str | None:
    return firm.canonical_website or firm.website or None


def _research_data_with_status(
    firm: PifFirmRow,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    data = dict(firm.research_data) if isinstance(firm.research_data, dict) else {}
    data["job_postings_research_status"] = status
    data["job_postings_research_provider"] = LOCAL_RESEARCH_PROVIDER
    if result is not None:
        data["job_postings"] = result
    if checked_at is not None:
        data["last_job_postings_researched_at"] = checked_at.isoformat()
    return data


def normalize_job_postings(
    raw_postings: Any,
    *,
    window_start: date,
    window_end: date,
) -> list[dict[str, Any]]:
    """Validate date/source requirements and remove duplicate gateway results."""
    if not isinstance(raw_postings, list):
        return []
    postings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_postings:
        if not isinstance(raw, dict):
            continue
        try:
            posted_date = date.fromisoformat(str(raw.get("posted_date") or ""))
        except ValueError:
            continue
        source_url = str(raw.get("source_url") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not title or not source_url.lower().startswith(("http://", "https://")):
            continue
        if not window_start <= posted_date <= window_end:
            continue
        key = (source_url.lower().rstrip("/"), title.lower())
        if key in seen:
            continue
        seen.add(key)
        postings.append({
            "title": title,
            "location": str(raw["location"]).strip() if raw.get("location") else None,
            "employment_type": (
                str(raw["employment_type"]).strip() if raw.get("employment_type") else None
            ),
            "posted_date": posted_date.isoformat(),
            "description_summary": str(raw.get("description_summary") or "").strip(),
            "responsibilities": [
                str(value).strip()
                for value in (raw.get("responsibilities") or [])
                if str(value).strip()
            ] if isinstance(raw.get("responsibilities"), list) else [],
            "qualifications": [
                str(value).strip()
                for value in (raw.get("qualifications") or [])
                if str(value).strip()
            ] if isinstance(raw.get("qualifications"), list) else [],
            "source_name": str(raw.get("source_name") or "Web source").strip(),
            "source_url": source_url,
        })
    return postings


async def research_recent_job_postings(
    firm_name: str,
    website: str | None,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    window_end = as_of_date or _utcnow().date()
    window_start = window_end - timedelta(days=WINDOW_DAYS - 1)
    result = await call_skill_json(
        skill_path=SKILL_PATH,
        payload={
            "firm_name": firm_name,
            "official_website": website or None,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        },
        required_fields=["postings"],
        model=os.getenv("PIF_JOB_RESEARCH_MODEL", "openclaw/main"),
        timeout_s=int(os.getenv("PIF_JOB_RESEARCH_TIMEOUT_S", "240")),
        max_tokens=int(os.getenv("PIF_JOB_RESEARCH_MAX_TOKENS", "4000")),
    )
    postings = normalize_job_postings(
        result.parsed.get("postings"),
        window_start=window_start,
        window_end=window_end,
    )
    return {
        "has_recent_openings": bool(postings),
        "window_days": WINDOW_DAYS,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "researched_at": _utcnow().isoformat(),
        "postings": postings,
    }


async def start_job_posting_research(firm_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id)
        if firm is None:
            raise PifResearchUpstreamError(404, "firm_not_found")
        existing = (await session.execute(
            select(PifJobResearchTaskRow)
            .where(
                PifJobResearchTaskRow.pif_id == firm_id,
                PifJobResearchTaskRow.status.in_(OPEN_STATUSES),
            )
            .order_by(PifJobResearchTaskRow.requested_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if existing:
            return {
                "task_id": existing.task_id,
                "pif_id": firm_id,
                "firm_name": firm.firm_name,
                "status": existing.status,
                "message": "Job-posting research is already queued or running",
            }

        task_id = f"job-openings-{uuid.uuid4().hex}"
        task = PifJobResearchTaskRow(
            task_id=task_id,
            pif_id=firm_id,
            status="queued",
            requested_at=_utcnow(),
        )
        firm.research_data = _research_data_with_status(firm, "queued")
        firm.updated_at = _utcnow()
        session.add(task)
        await session.commit()
        return {
            "task_id": task_id,
            "pif_id": firm_id,
            "firm_name": firm.firm_name,
            "status": "queued",
            "message": "Queued for local gateway research",
        }


async def get_research_status(task_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        task = await session.get(PifJobResearchTaskRow, task_id)
        if task is None:
            raise PifResearchUpstreamError(404, "research_task_not_found")
        summary = task.result_summary if isinstance(task.result_summary, dict) else {}
        return {
            "task_id": task.task_id,
            "pif_id": task.pif_id,
            "status": task.status,
            "requested_at": task.requested_at.isoformat() if task.requested_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            **summary,
        }


async def _claim_next_task() -> tuple[str, str] | None:
    async with AsyncSessionLocal() as session:
        task = (await session.execute(
            select(PifJobResearchTaskRow)
            .where(PifJobResearchTaskRow.status == "queued")
            .order_by(PifJobResearchTaskRow.requested_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )).scalar_one_or_none()
        if task is None:
            return None
        task.status = "in_progress"
        task.started_at = _utcnow()
        firm = await session.get(PifFirmRow, task.pif_id)
        if firm is not None:
            firm.research_data = _research_data_with_status(firm, "in_progress")
            firm.updated_at = _utcnow()
        await session.commit()
        return task.task_id, task.pif_id


async def _finish_task(
    task_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    checked_at = _utcnow()
    async with AsyncSessionLocal() as session:
        task = await session.get(PifJobResearchTaskRow, task_id)
        if task is None:
            return
        firm = await session.get(PifFirmRow, task.pif_id)
        task.status = status
        task.completed_at = checked_at
        if status == "completed" and result is not None:
            posting_count = len(result.get("postings") or [])
            task.result_summary = {
                "firm_name": firm.firm_name if firm else None,
                "has_recent_openings": bool(result.get("has_recent_openings")),
                "posting_count": posting_count,
            }
            if firm is not None:
                firm.research_data = _research_data_with_status(
                    firm,
                    "completed",
                    result=result,
                    checked_at=checked_at,
                )
        else:
            task.result_summary = {
                "firm_name": firm.firm_name if firm else None,
                "message": error or "Job-posting research failed",
            }
            if firm is not None:
                firm.research_data = _research_data_with_status(
                    firm,
                    "failed",
                    checked_at=checked_at,
                )
        if firm is not None:
            firm.updated_at = checked_at
        await session.commit()


async def _run_task(task_id: str, pif_id: str) -> None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        firm_name = str(firm.firm_name or "").strip() if firm else ""
        website = _firm_website(firm) if firm else None
    if not firm or not firm_name:
        await _finish_task(task_id, status="failed", error="Firm record or name is missing")
        return
    try:
        result = await research_recent_job_postings(firm_name, website)
    except Exception as exc:
        logger.exception("Local job-opening research failed for %s", pif_id)
        await _finish_task(task_id, status="failed", error=str(exc)[:500])
        return
    await _finish_task(task_id, status="completed", result=result)


async def recover_interrupted_job_research() -> int:
    """Return tasks interrupted by a daemon restart to the durable queue."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(PifJobResearchTaskRow)
            .where(PifJobResearchTaskRow.status == "in_progress")
            .values(status="queued", started_at=None)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def job_posting_research_loop(*, poll_seconds: float = 2.0) -> None:
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
            logger.exception("Job-opening research worker tick failed")
            await asyncio.sleep(poll_seconds)
