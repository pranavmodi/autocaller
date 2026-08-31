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
CLASSIFIER_VERSION = "job-taxonomy-v1"
CLASSIFIER_PROVIDER = "possibleos_local_rules"

ROLE_CATEGORIES = (
    "intake_conversion",
    "marketing_growth",
    "case_operations",
    "attorney_legal",
    "client_communication",
    "firm_operations",
    "technology_data",
    "finance_billing",
    "executive_leadership",
    "other",
)

_CATEGORY_TERMS = {
    "intake_conversion": (
        "intake", "receptionist", "call center", "new client", "prospective client",
        "conversion", "sales specialist", "client relations specialist",
    ),
    "marketing_growth": (
        "marketing", "seo", "ppc", "paid search", "growth", "social media",
        "business development", "content strategist", "media buyer",
    ),
    "case_operations": (
        "case manager", "paralegal", "legal assistant", "litigation assistant",
        "case coordinator", "legal secretary", "demand writer",
    ),
    "attorney_legal": (
        "attorney", "lawyer", "associate counsel", "trial counsel", "litigation counsel",
    ),
    "client_communication": (
        "client communication", "client experience", "client success", "client care",
        "client liaison", "status update",
    ),
    "firm_operations": (
        "operations", "office manager", "administrator", "human resources", "recruiter",
        "facilities", "chief operating officer",
    ),
    "technology_data": (
        "technology", "systems", "software", "automation", "crm administrator",
        "information technology", "data analyst", "business intelligence", "developer",
    ),
    "finance_billing": (
        "billing", "bookkeeper", "accounting", "accountant", "finance", "controller",
        "accounts payable", "settlement specialist",
    ),
    "executive_leadership": (
        "chief executive", "chief operating", "chief marketing", "director", "vice president",
        "managing partner", "executive",
    ),
}

_TRIGGER_TERMS = {
    "rapid_lead_followup": ("rapid follow", "immediate follow", "speed to lead", "respond quickly"),
    "lead_conversion": ("lead conversion", "convert leads", "conversion rate", "sign up", "retain clients"),
    "high_volume": ("high volume", "large volume", "fast-paced", "hundreds of calls"),
    "after_hours_or_24_7": ("after hours", "after-hours", "24/7", "weekend", "evening shift", "night shift"),
    "crm_management": ("crm", "lead docket", "lawmatics", "law ruler", "captorra", "clio grow"),
    "case_management_system": ("filevine", "casepeer", "smartadvocate", "litify", "clio manage", "case management system"),
    "call_tracking": ("callrail", "call tracking", "call reporting", "phone analytics"),
    "marketing_attribution": ("attribution", "cost per lead", "return on ad spend", "marketing roi", "campaign performance"),
    "kpi_reporting": ("kpi", "key performance", "dashboard", "performance reporting", "metrics"),
    "workflow_automation": ("automation", "automate", "workflow", "process improvement"),
    "ai_adoption": ("artificial intelligence", " ai ", "machine learning", "generative ai"),
    "client_status_updates": ("status update", "client update", "keep clients informed"),
    "new_office_or_market": ("new office", "new market", "expansion", "launching"),
    "spanish_language_capacity": ("spanish", "bilingual"),
    "team_expansion": ("growing team", "rapidly growing", "expanding team", "newly created role"),
}

_TECHNOLOGY_NAMES = {
    "Filevine": ("filevine",),
    "Lead Docket": ("lead docket",),
    "Lawmatics": ("lawmatics",),
    "Law Ruler": ("law ruler",),
    "Captorra": ("captorra",),
    "Clio Grow": ("clio grow",),
    "Clio Manage": ("clio manage",),
    "CASEpeer": ("casepeer",),
    "SmartAdvocate": ("smartadvocate",),
    "Litify": ("litify",),
    "CallRail": ("callrail",),
    "Salesforce": ("salesforce",),
    "HubSpot": ("hubspot",),
    "Zapier": ("zapier",),
}


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


def classify_job_posting(posting: dict[str, Any], *, classified_at: datetime | None = None) -> dict[str, Any]:
    """Add stable GTM taxonomy fields without changing source-backed posting data."""
    title = str(posting.get("title") or "").lower()
    body_parts = [
        posting.get("description_summary"),
        *(posting.get("responsibilities") or []),
        *(posting.get("qualifications") or []),
    ]
    body = " ".join(str(value) for value in body_parts if value).lower()
    combined = f" {title} {body} "

    scores: dict[str, int] = {}
    for category, terms in _CATEGORY_TERMS.items():
        scores[category] = sum(3 for term in terms if term in title) + sum(
            1 for term in terms if term in body
        )
    best_category = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else "other"
    best_score = scores.get(best_category, 0)
    confidence = 0.95 if any(term in title for term in _CATEGORY_TERMS.get(best_category, ())) else (
        0.78 if best_score >= 2 else 0.65 if best_score == 1 else 0.4
    )

    tags = [tag for tag, terms in _TRIGGER_TERMS.items() if any(term in combined for term in terms)]
    if best_category in {"intake_conversion", "marketing_growth", "technology_data", "client_communication"}:
        relevance = "high"
    elif tags or best_category in {"case_operations", "firm_operations", "executive_leadership"}:
        relevance = "medium"
    else:
        relevance = "low"
    technology_mentions = [
        label for label, terms in _TECHNOLOGY_NAMES.items() if any(term in combined for term in terms)
    ]

    return {
        **posting,
        "role_category": best_category,
        "trigger_tags": tags,
        "technology_mentions": technology_mentions,
        "gtm_relevance": relevance,
        "classification_confidence": confidence,
        "classification_provider": CLASSIFIER_PROVIDER,
        "classification_version": CLASSIFIER_VERSION,
        "classified_at": (classified_at or _utcnow()).isoformat(),
    }


def classify_job_postings(postings: Any, *, classified_at: datetime | None = None) -> list[dict[str, Any]]:
    if not isinstance(postings, list):
        return []
    return [
        classify_job_posting(posting, classified_at=classified_at)
        for posting in postings
        if isinstance(posting, dict)
    ]


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
        postings.append(classify_job_posting({
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
        }))
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
                PifJobResearchTaskRow.kind == "research",
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
            kind="research",
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
            "kind": task.kind,
            "status": task.status,
            "requested_at": task.requested_at.isoformat() if task.requested_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            **summary,
        }


async def _claim_next_task() -> tuple[str, str, str] | None:
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
        if firm is not None and task.kind == "research":
            firm.research_data = _research_data_with_status(firm, "in_progress")
            firm.updated_at = _utcnow()
        await session.commit()
        return task.task_id, task.pif_id, task.kind


async def _finish_task(
    task_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    kind: str = "research",
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
            if firm is not None and kind == "research":
                firm.research_data = _research_data_with_status(
                    firm,
                    "completed",
                    result=result,
                    checked_at=checked_at,
                )
            elif firm is not None and kind == "classify":
                research_data = dict(firm.research_data) if isinstance(firm.research_data, dict) else {}
                job_data = dict(research_data.get("job_postings") or {})
                job_data.update({
                    "postings": result.get("postings") or [],
                    "classification_status": "completed",
                    "classification_version": CLASSIFIER_VERSION,
                    "classified_at": checked_at.isoformat(),
                })
                research_data["job_postings"] = job_data
                firm.research_data = research_data
        else:
            task.result_summary = {
                "firm_name": firm.firm_name if firm else None,
                "message": error or "Job-posting research failed",
            }
            if firm is not None and kind == "research":
                firm.research_data = _research_data_with_status(
                    firm,
                    "failed",
                    checked_at=checked_at,
                )
            elif firm is not None and kind == "classify":
                research_data = dict(firm.research_data) if isinstance(firm.research_data, dict) else {}
                job_data = dict(research_data.get("job_postings") or {})
                job_data["classification_status"] = "failed"
                job_data["classification_error"] = error or "Job-posting classification failed"
                research_data["job_postings"] = job_data
                firm.research_data = research_data
        if firm is not None:
            firm.updated_at = checked_at
        await session.commit()


async def _run_task(task_id: str, pif_id: str, kind: str = "research") -> None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        firm_name = str(firm.firm_name or "").strip() if firm else ""
        website = _firm_website(firm) if firm else None
    if not firm or not firm_name:
        await _finish_task(task_id, status="failed", error="Firm record or name is missing", kind=kind)
        return
    if kind == "classify":
        try:
            research_data = firm.research_data if isinstance(firm.research_data, dict) else {}
            job_data = research_data.get("job_postings") if isinstance(research_data.get("job_postings"), dict) else {}
            postings = classify_job_postings(job_data.get("postings"), classified_at=_utcnow())
            await _finish_task(
                task_id,
                status="completed",
                result={"postings": postings, "has_recent_openings": bool(postings)},
                kind=kind,
            )
        except Exception as exc:
            logger.exception("Local job-opening classification failed for %s", pif_id)
            await _finish_task(task_id, status="failed", error=str(exc)[:500], kind=kind)
        return
    try:
        result = await research_recent_job_postings(firm_name, website)
    except Exception as exc:
        logger.exception("Local job-opening research failed for %s", pif_id)
        await _finish_task(task_id, status="failed", error=str(exc)[:500], kind=kind)
        return
    await _finish_task(task_id, status="completed", result=result, kind=kind)


async def queue_job_posting_classification_backfill(*, force: bool = False) -> dict[str, Any]:
    """Queue local classification for every firm with stored postings."""
    now = _utcnow()
    queued: list[dict[str, str]] = []
    skipped_current = 0
    skipped_running = 0
    async with AsyncSessionLocal() as session:
        firms = (await session.execute(
            select(PifFirmRow).where(
                PifFirmRow.research_data["job_postings"]["postings"].isnot(None)
            )
        )).scalars().all()
        open_ids = set((await session.execute(
            select(PifJobResearchTaskRow.pif_id).where(
                PifJobResearchTaskRow.kind == "classify",
                PifJobResearchTaskRow.status.in_(OPEN_STATUSES),
            )
        )).scalars().all())
        for firm in firms:
            research_data = firm.research_data if isinstance(firm.research_data, dict) else {}
            job_data = research_data.get("job_postings") if isinstance(research_data.get("job_postings"), dict) else {}
            postings = job_data.get("postings") if isinstance(job_data, dict) else []
            if not postings:
                continue
            if firm.id in open_ids:
                skipped_running += 1
                continue
            if not force and job_data.get("classification_version") == CLASSIFIER_VERSION:
                skipped_current += 1
                continue
            task_id = f"job-tags-{uuid.uuid4().hex}"
            session.add(PifJobResearchTaskRow(
                task_id=task_id,
                pif_id=firm.id,
                kind="classify",
                status="queued",
                requested_at=now,
            ))
            updated = dict(research_data)
            updated_jobs = dict(job_data)
            updated_jobs["classification_status"] = "queued"
            updated["job_postings"] = updated_jobs
            firm.research_data = updated
            queued.append({"task_id": task_id, "pif_id": firm.id, "firm_name": firm.firm_name})
        await session.commit()
    return {
        "status": "queued",
        "classifier_version": CLASSIFIER_VERSION,
        "queued_count": len(queued),
        "skipped_current": skipped_current,
        "skipped_running": skipped_running,
        "queued": queued,
    }


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
