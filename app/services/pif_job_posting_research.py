"""Durable, local job-opening web research for the PI-firm directory."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import case, select, update

from app.db import AsyncSessionLocal
from app.db.models import PifFirmRow, PifJobResearchTaskRow
from app.services.llm_gateway import call_skill_json


logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/job-opening-research/SKILL.md"
OPEN_STATUSES = {"queued", "in_progress"}
WINDOW_DAYS = 30
LOCAL_RESEARCH_PROVIDER = "possibleos_openclaw"
CLASSIFIER_VERSION = "job-taxonomy-v2"
CLASSIFIER_PROVIDER = "possibleos_local_rules"
JOB_RESEARCH_DEFAULT_MAX_ATTEMPTS = 4
JOB_RESEARCH_DEFAULT_BACKOFF_SECONDS = 300
JOB_RESEARCH_DEFAULT_MAX_BACKOFF_SECONDS = 3600

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

_GLOBAL_REMOTE_PATTERNS = (
    r"\bwork from anywhere\b",
    r"\banywhere in (?:the )?world\b",
    r"\bworldwide\b",
    r"\bglobally remote\b",
    r"\bremote worldwide\b",
    r"\bremote (?:from )?anywhere\b",
    r"\bopen to (?:candidates|applicants) (?:globally|worldwide)\b",
    r"\binternational (?:candidates|applicants)\b",
)
_COUNTRY_REMOTE_PATTERNS = (
    r"\b(?:u\.?s\.?|united states|canada|united kingdom|u\.?k\.?|australia|mexico|india)\s+(?:only|based|residents?)\b",
    r"\bremote (?:within|in|from) (?:the )?(?:u\.?s\.?|united states|canada|united kingdom|u\.?k\.?|australia|mexico|india)\b",
)
_LOCATION_REMOTE_PATTERNS = (
    r"\bmust (?:reside|live|be located|be based) in\b",
    r"\bremote (?:within|in|from) [a-z][a-z .'-]+(?:state|province|region|time zone|timezone)\b",
    r"\b(?:state|province|region) residents? only\b",
)


def _matched_phrases(patterns: tuple[str, ...], text_value: str) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text_value, flags=re.IGNORECASE)
        if match:
            phrase = match.group(0).strip()
            if phrase not in matches:
                matches.append(phrase)
    return matches


def classify_remote_eligibility(posting: dict[str, Any]) -> dict[str, Any]:
    """Classify remote scope conservatively from source-backed posting text."""
    values = [
        posting.get("title"),
        posting.get("location"),
        posting.get("employment_type"),
        posting.get("remote_eligibility"),
        posting.get("description_summary"),
        *(posting.get("responsibilities") or []),
        *(posting.get("qualifications") or []),
    ]
    text_value = " ".join(str(value) for value in values if value)
    lowered = f" {text_value.lower()} "
    global_evidence = _matched_phrases(_GLOBAL_REMOTE_PATTERNS, text_value)
    country_evidence = _matched_phrases(_COUNTRY_REMOTE_PATTERNS, text_value)
    location_evidence = _matched_phrases(_LOCATION_REMOTE_PATTERNS, text_value)
    has_remote = bool(re.search(r"\b(remote|work from home|distributed)\b", lowered)) or bool(global_evidence)
    has_hybrid = bool(re.search(r"\bhybrid\b", lowered))
    has_onsite = bool(re.search(r"\b(on[- ]?site|in[- ]?office)\b", lowered))

    if has_remote:
        work_arrangement = "remote"
    elif has_hybrid:
        work_arrangement = "hybrid"
    elif has_onsite:
        work_arrangement = "onsite"
    else:
        work_arrangement = "unclear"

    if not has_remote:
        remote_scope = "not_remote" if work_arrangement in {"hybrid", "onsite"} else "unclear"
        evidence: list[str] = []
        confidence = 0.9 if remote_scope == "not_remote" else 0.4
    elif country_evidence:
        remote_scope = "country_restricted"
        evidence = country_evidence
        confidence = 0.95
    elif location_evidence:
        remote_scope = "location_restricted"
        evidence = location_evidence
        confidence = 0.95
    elif global_evidence:
        remote_scope = "global"
        evidence = global_evidence
        confidence = 0.98
    else:
        remote_scope = "unclear"
        evidence = ["remote"]
        confidence = 0.6

    return {
        "work_arrangement": work_arrangement,
        "remote_scope": remote_scope,
        "global_remote": remote_scope == "global",
        "global_remote_evidence": evidence,
        "global_remote_confidence": confidence,
    }


class PifResearchUpstreamError(Exception):
    """Compatibility error used by the existing PIF API handlers."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _job_research_max_attempts() -> int:
    return max(1, int(os.getenv("PIF_JOB_RESEARCH_TASK_ATTEMPTS", JOB_RESEARCH_DEFAULT_MAX_ATTEMPTS)))


def _retry_delay_seconds(task_id: str, attempt_count: int) -> int:
    """Return capped exponential backoff with stable per-task jitter."""
    base = max(1, int(os.getenv(
        "PIF_JOB_RESEARCH_BACKOFF_SECONDS",
        JOB_RESEARCH_DEFAULT_BACKOFF_SECONDS,
    )))
    maximum = max(base, int(os.getenv(
        "PIF_JOB_RESEARCH_MAX_BACKOFF_SECONDS",
        JOB_RESEARCH_DEFAULT_MAX_BACKOFF_SECONDS,
    )))
    exponential = min(maximum, base * (2 ** max(0, attempt_count - 1)))
    digest = hashlib.sha256(f"{task_id}:{attempt_count}".encode("utf-8")).digest()
    jitter = int(exponential * 0.2 * (int.from_bytes(digest[:2], "big") / 65535))
    return min(maximum, exponential + jitter)


def _retry_plan(
    task_id: str,
    summary: dict[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    current = dict(summary) if isinstance(summary, dict) else {}
    attempt_count = max(1, int(current.get("attempt_count") or 1))
    max_attempts = max(1, int(current.get("max_attempts") or _job_research_max_attempts()))
    if attempt_count >= max_attempts:
        return None
    delay_seconds = _retry_delay_seconds(task_id, attempt_count)
    retry_at = now + timedelta(seconds=delay_seconds)
    return {
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
        "retry_delay_seconds": delay_seconds,
        "retry_at": retry_at,
    }


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
    remote_eligibility = classify_remote_eligibility(posting)

    return {
        **posting,
        "role_category": best_category,
        "trigger_tags": tags,
        "technology_mentions": technology_mentions,
        "gtm_relevance": relevance,
        "classification_confidence": confidence,
        **remote_eligibility,
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
    if status in {"completed", "failed"}:
        data.pop("job_postings_research_retry", None)
    return data


def _research_data_with_sitemap_status(
    firm: PifFirmRow,
    status: str,
    *,
    checked_at: datetime | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    data = dict(firm.research_data) if isinstance(firm.research_data, dict) else {}
    current = data.get("sitemap_monitor")
    monitor = dict(current) if isinstance(current, dict) else {}
    monitor.update({"status": status, "provider": "possibleos_sitemap_monitor"})
    if checked_at is not None:
        monitor["checked_at"] = checked_at.isoformat()
    if error is not None:
        monitor["error"] = error
    elif status in OPEN_STATUSES:
        monitor.pop("error", None)
    data["sitemap_monitor"] = monitor
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
            "remote_eligibility": (
                str(raw["remote_eligibility"]).strip() if raw.get("remote_eligibility") else None
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
        timeout_s=int(os.getenv("PIF_JOB_RESEARCH_TIMEOUT_S", "420")),
        max_tokens=int(os.getenv("PIF_JOB_RESEARCH_MAX_TOKENS", "4000")),
        retries=1,
        schema_repair_retries=1,
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


async def start_sitemap_research(firm_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id)
        if firm is None:
            raise PifResearchUpstreamError(404, "firm_not_found")
        if not _firm_website(firm):
            raise PifResearchUpstreamError(400, "firm_website_required")
        existing = (await session.execute(
            select(PifJobResearchTaskRow)
            .where(
                PifJobResearchTaskRow.pif_id == firm_id,
                PifJobResearchTaskRow.kind == "sitemap",
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
                "message": "Sitemap research is already queued or running",
            }

        task_id = f"sitemap-{uuid.uuid4().hex}"
        session.add(PifJobResearchTaskRow(
            task_id=task_id,
            pif_id=firm_id,
            kind="sitemap",
            status="queued",
            requested_at=_utcnow(),
        ))
        firm.research_data = _research_data_with_sitemap_status(firm, "queued")
        firm.updated_at = _utcnow()
        await session.commit()
        return {
            "task_id": task_id,
            "pif_id": firm_id,
            "firm_name": firm.firm_name,
            "status": "queued",
            "message": "Queued for local sitemap research",
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


def _aggregate_job_research_daily_stats(
    rows: list[Any],
    *,
    days: int,
    now: datetime,
    open_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Summarize the latest terminal job-research result per firm and UTC day."""
    normalized_now = now.astimezone(timezone.utc)
    first_day = normalized_now.date() - timedelta(days=days - 1)
    latest_by_firm_day: dict[tuple[date, str], Any] = {}
    attempts_by_day: dict[date, int] = {}
    for row in rows:
        completed_at = row.completed_at
        if completed_at is None:
            continue
        completed_at = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=timezone.utc)
        day = completed_at.astimezone(timezone.utc).date()
        if day < first_day:
            continue
        attempts_by_day[day] = attempts_by_day.get(day, 0) + 1
        key = (day, str(row.pif_id))
        current = latest_by_firm_day.get(key)
        if current is None or (current.completed_at or datetime.min.replace(tzinfo=timezone.utc)) < completed_at:
            latest_by_firm_day[key] = row

    daily: list[dict[str, Any]] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        firm_rows = [row for (row_day, _), row in latest_by_firm_day.items() if row_day == day]
        completed = [row for row in firm_rows if row.status == "completed"]
        failed = [row for row in firm_rows if row.status == "failed"]
        summaries = [row.result_summary if isinstance(row.result_summary, dict) else {} for row in completed]
        daily.append({
            "date": day.isoformat(),
            "firms_processed": len(firm_rows),
            "firms_completed": len(completed),
            "firms_failed": len(failed),
            "firms_with_openings": sum(bool(summary.get("has_recent_openings")) for summary in summaries),
            "job_postings_found": sum(int(summary.get("posting_count") or 0) for summary in summaries),
            "research_attempts": attempts_by_day.get(day, 0),
        })
    counts = open_counts or {}
    return {
        "timezone": "UTC",
        "days": days,
        "today": daily[-1],
        "daily": list(reversed(daily)),
        "queue": {
            "queued": int(counts.get("queued") or 0),
            "in_progress": int(counts.get("in_progress") or 0),
        },
        "generated_at": normalized_now.isoformat(),
    }


async def get_job_research_daily_stats(*, days: int = 14) -> dict[str, Any]:
    days = max(1, min(90, int(days)))
    now = _utcnow()
    first_day = now.date() - timedelta(days=days - 1)
    start = datetime.combine(first_day, datetime.min.time(), tzinfo=timezone.utc)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(
                PifJobResearchTaskRow.pif_id,
                PifJobResearchTaskRow.status,
                PifJobResearchTaskRow.completed_at,
                PifJobResearchTaskRow.result_summary,
            ).where(
                PifJobResearchTaskRow.kind == "research",
                PifJobResearchTaskRow.status.in_(("completed", "failed")),
                PifJobResearchTaskRow.completed_at >= start,
            )
        )).all()
        open_rows = (await session.execute(
            select(PifJobResearchTaskRow.status).where(
                PifJobResearchTaskRow.kind == "research",
                PifJobResearchTaskRow.status.in_(OPEN_STATUSES),
            )
        )).scalars().all()
    open_counts = {status: open_rows.count(status) for status in OPEN_STATUSES}
    return _aggregate_job_research_daily_stats(
        list(rows),
        days=days,
        now=now,
        open_counts=open_counts,
    )


async def _claim_next_task() -> tuple[str, str, str] | None:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        task = (await session.execute(
            select(PifJobResearchTaskRow)
            .where(
                PifJobResearchTaskRow.status == "queued",
                PifJobResearchTaskRow.requested_at <= now,
            )
            .order_by(
                case((PifJobResearchTaskRow.kind == "classify", 0), else_=1),
                PifJobResearchTaskRow.requested_at.asc(),
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )).scalar_one_or_none()
        if task is None:
            return None
        task.status = "in_progress"
        task.started_at = now
        if task.kind == "research":
            summary = dict(task.result_summary) if isinstance(task.result_summary, dict) else {}
            attempt_count = max(0, int(summary.get("attempt_count") or 0)) + 1
            summary.update({
                "attempt_count": attempt_count,
                "max_attempts": max(1, int(summary.get("max_attempts") or _job_research_max_attempts())),
                "attempt_started_at": now.isoformat(),
                "message": f"Research attempt {attempt_count} started",
            })
            summary.pop("retry_at", None)
            summary.pop("retry_delay_seconds", None)
            task.result_summary = summary
        firm = await session.get(PifFirmRow, task.pif_id)
        if firm is not None:
            if task.kind == "research":
                research_data = _research_data_with_status(firm, "in_progress")
                research_data["job_postings_research_retry"] = {
                    "attempt_count": task.result_summary.get("attempt_count"),
                    "max_attempts": task.result_summary.get("max_attempts"),
                }
                firm.research_data = research_data
            elif task.kind == "sitemap":
                firm.research_data = _research_data_with_sitemap_status(firm, "in_progress")
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
        previous_summary = dict(task.result_summary) if isinstance(task.result_summary, dict) else {}
        attempt_metadata = {
            key: previous_summary[key]
            for key in ("attempt_count", "max_attempts", "attempt_started_at")
            if key in previous_summary
        }
        task.status = status
        task.completed_at = checked_at
        if status == "completed" and result is not None and kind == "sitemap":
            task.result_summary = {
                **attempt_metadata,
                "firm_name": firm.firm_name if firm else None,
                "sitemap_status": result.get("status"),
                "url_count": int(result.get("url_count") or 0),
                "changed": result.get("changed"),
                "added_count": int(result.get("added_count") or 0),
                "removed_count": int(result.get("removed_count") or 0),
            }
        elif status == "completed" and result is not None:
            posting_count = len(result.get("postings") or [])
            task.result_summary = {
                **attempt_metadata,
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
                **attempt_metadata,
                "firm_name": firm.firm_name if firm else None,
                "message": error or (
                    "Sitemap research failed" if kind == "sitemap" else "Job-posting research failed"
                ),
                "retries_exhausted": kind == "research",
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
            elif firm is not None and kind == "sitemap":
                firm.research_data = _research_data_with_sitemap_status(
                    firm,
                    "failed",
                    checked_at=checked_at,
                    error=error or "Sitemap research failed",
                )
        if firm is not None:
            firm.updated_at = checked_at
        await session.commit()


async def _schedule_job_research_retry(task_id: str, error: Exception) -> bool:
    """Requeue a transient job-research failure without losing attempt state."""
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        task = await session.get(PifJobResearchTaskRow, task_id)
        if task is None or task.kind != "research":
            return False
        summary = dict(task.result_summary) if isinstance(task.result_summary, dict) else {}
        plan = _retry_plan(task.task_id, summary, now=now)
        if plan is None:
            return False
        retry_at = plan["retry_at"]
        error_text = str(error).strip() or error.__class__.__name__
        task.status = "queued"
        task.requested_at = retry_at
        task.started_at = None
        task.completed_at = None
        task.result_summary = {
            **summary,
            "attempt_count": plan["attempt_count"],
            "max_attempts": plan["max_attempts"],
            "retry_delay_seconds": plan["retry_delay_seconds"],
            "retry_at": retry_at.isoformat(),
            "last_error": error_text[:500],
            "message": (
                f"Attempt {plan['attempt_count']} failed; retrying at "
                f"{retry_at.isoformat()}"
            ),
        }
        firm = await session.get(PifFirmRow, task.pif_id)
        if firm is not None:
            research_data = _research_data_with_status(firm, "queued")
            research_data["job_postings_research_retry"] = {
                "attempt_count": plan["attempt_count"],
                "max_attempts": plan["max_attempts"],
                "retry_at": retry_at.isoformat(),
                "last_error": error_text[:500],
            }
            firm.research_data = research_data
            firm.updated_at = now
        await session.commit()
    logger.warning(
        "Retrying job-opening research task %s after attempt %s at %s",
        task_id,
        plan["attempt_count"],
        retry_at.isoformat(),
    )
    return True


async def _run_task(task_id: str, pif_id: str, kind: str = "research") -> None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        firm_name = str(firm.firm_name or "").strip() if firm else ""
        website = _firm_website(firm) if firm else None
    if not firm or (kind != "sitemap" and not firm_name):
        await _finish_task(task_id, status="failed", error="Firm record or name is missing", kind=kind)
        return
    if kind == "sitemap" and not website:
        await _finish_task(task_id, status="failed", error="Firm website is missing", kind=kind)
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
    if kind == "sitemap":
        try:
            from app.services.pif_sitemap_monitor import monitor_firm_sitemap

            result = await monitor_firm_sitemap(pif_id)
            await _finish_task(task_id, status="completed", result=result, kind=kind)
        except Exception as exc:
            logger.exception("Local sitemap research failed for %s", pif_id)
            await _finish_task(task_id, status="failed", error=str(exc)[:500], kind=kind)
        return
    try:
        result = await research_recent_job_postings(firm_name, website)
    except Exception as exc:
        logger.exception("Local job-opening research failed for %s", pif_id)
        if await _schedule_job_research_retry(task_id, exc):
            return
        error_text = str(exc).strip() or exc.__class__.__name__
        await _finish_task(task_id, status="failed", error=error_text[:500], kind=kind)
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
