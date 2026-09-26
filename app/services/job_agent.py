"""Job-agent control surface: durable preferences, operator review and audit trail.

Imports existing postings and exposes preferences, review decisions and processing
state. Classification and explicitly requested email applications live in the
processing service. Shortlisting alone never sends an application.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from uuid import uuid4
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import DateTime, Integer, String, Boolean, and_, case, cast, delete, func, not_, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db import AsyncSessionLocal, Base, async_engine
from app.services.career_job_store import PROVIDER, source_identity
from app.services.job_agent_resumes import ResumeCategory, default_categories, inspect_resume
from app.services.job_search_sources import DEFAULT_SOURCE_IDS, catalog_payload, source_urls, validate_source_ids


ReviewStatus = Literal["new", "shortlisted", "needs_info", "skipped"]
JobSource = Literal["possibleos", "external_search"]
LegalDegreeFilter = Literal["exclude", "all", "required"]
ContractFilter = Literal["all", "contract", "non_contract", "unknown"]


def now():
    return datetime.now(timezone.utc)


class JobAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    browser_ai_provider: Literal['gateway', 'openai'] = 'gateway'
    browser_openai_model: str = Field('gpt-5-mini', min_length=1, max_length=120, pattern=r'^\S+$')
    classification_enabled: bool = False
    # Compatibility with saved configurations/older clients; selection has no confidence gate.
    classification_threshold: float = Field(0.0, ge=0, le=1)
    resume_categories: list[ResumeCategory] = Field(default_factory=default_categories)
    collection_enabled: bool = True
    search: str = Field("", max_length=255)
    remote_scope: Literal["any", "remote", "global"] = "any"
    posted_within_days: int | None = Field(None, ge=1, le=365)
    target_roles: str = Field("Applied AI, AI agents, workflow automation, engineering and product leadership; entry-level personal-injury case management, paralegal/legal-assistant and intake roles", max_length=2000)
    preferred_industries: str = Field("Legal technology, personal injury firms, healthcare operations", max_length=2000)
    location_preferences: str = Field("Remote from Bengaluru, India; planning to move to Medellín, Colombia (UTC-5). Verify country-specific eligibility.", max_length=2000)
    prefer_overseas_employers: bool = True
    search_source_ids: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCE_IDS), max_length=30)
    application_notes: str = Field("Founder-led, concise applications. Use verified experience. Reuse the best suitable one-page PDF resume. Do not call it 'tailored' in emails.", max_length=4000)


    @model_validator(mode="after")
    def unique_categories(self):
        if len({category.id for category in self.resume_categories}) != len(self.resume_categories):
            raise ValueError("Category identifiers must be unique.")
        validate_source_ids(self.search_source_ids)
        return self


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    config: JobAgentConfig


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    status: ReviewStatus
    note: str = Field("", max_length=4000)


class ListingSelection(BaseModel):
    """Stable pointer from the Leads job-listing view to its stored posting."""
    model_config = ConfigDict(extra="forbid", strict=True)
    firm_id: str = Field(min_length=1, max_length=64)
    job_id: str | None = Field(None, max_length=512)
    source_url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=1000)
    location: str | None = Field(None, max_length=1000)


class UrlImportRequest(BaseModel):
    """One public job URL supplied directly by an operator or external agent."""
    model_config = ConfigDict(extra="forbid")
    source_url: HttpUrl


class JobAgentState(Base):
    __tablename__ = "job_agent_state"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JobAgentCandidate(Base):
    __tablename__ = "job_agent_candidates"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    posting: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new", index=True)
    note: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JobAgentEvent(Base):
    __tablename__ = "job_agent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class JobAgentCollectionRun(Base):
    __tablename__ = "job_agent_collection_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_revision: Mapped[int] = mapped_column(Integer)
    snapshot_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAgentCollectionItem(Base):
    __tablename__ = "job_agent_collection_items"
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    posting: Mapped[dict] = mapped_column(JSONB, nullable=False)


def saved_config(value):
    # Read old saved settings without retaining the retired total-import ceiling.
    return JobAgentConfig.model_validate({k: v for k, v in value.items() if k != "import_limit"})


def serialize_run(row):
    if row is None:
        return None
    return {**{key: getattr(row, key) for key in
               ("id", "status", "total", "processed", "added", "updated", "invalid", "error", "config_revision")},
            "remaining": row.total - row.processed,
            "started_at": row.started_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None}


BATCH_SIZE = 100  # Transaction size only: every snapshot is drained to completion.
SYNC_INTERVAL_SECONDS = 60
_wakeup = asyncio.Event()
logger = logging.getLogger(__name__)
_search_task: asyncio.Task | None = None

_ready = False
_schema_lock = asyncio.Lock()


async def ensure_tables():
    global _ready
    if _ready:
        return
    async with _schema_lock:
        if _ready:
            return
        async with async_engine.begin() as conn:
            # Serialize additive initialization across workers too.
            await conn.execute(text("SELECT pg_advisory_xact_lock(734985215)"))
            from app.services.job_agent_processing import JobProcessing
            from app.services.job_browser import BrowserRun, BrowserEvent
            from app.services.job_applicant_profile import ApplicantAnswer
            for model in (JobAgentState, JobAgentCandidate, JobAgentEvent, JobAgentCollectionRun, JobAgentCollectionItem, JobProcessing, BrowserRun, BrowserEvent, ApplicantAnswer):
                await conn.run_sync(model.__table__.create, checkfirst=True)
        _ready = True


async def state_for_update(session):
    await session.execute(insert(JobAgentState).values(
        id="default", config=JobAgentConfig().model_dump(), revision=0, updated_at=now(),
    ).on_conflict_do_nothing(index_elements=["id"]))
    return await session.get(JobAgentState, "default", with_for_update=True)


def candidate_id(posting: dict) -> str:
    """Use a stored job ID, or distinguish roles sharing a careers-page URL."""
    url = str(posting.get("source_url") or "").strip()
    if urlsplit(url).scheme not in {"https", "http"} or not urlsplit(url).hostname:
        raise ValueError("A posting needs a valid source URL")
    role = str(posting.get("title") or "").strip().casefold()
    location = str(posting.get("location") or "").strip().casefold()
    source = f"id:{posting['job_id']}" if posting.get("job_id") else f"url:{source_identity(url)}:{role}:{location}"
    key = f"{posting['firm_id']}:{source}"
    return hashlib.sha256(key.encode()).hexdigest()[:40]


def legacy_candidate_id(posting: dict) -> str:
    # Preserve IDs and reviews created by the initial URL-only importer.
    key = f"{posting['firm_id']}:{source_identity(posting['source_url'])}"
    return hashlib.sha256(key.encode()).hexdigest()[:40]


def serialize_candidate(row):
    return {"id": row.id, "posting": normalize_posting(row.posting), "status": row.status,
            "note": row.note, "revision": row.revision,
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
            "decision_source": "operator" if row.status != "new" or row.note else None,
            "email_status": "not_tracked", "form_status": "not_tracked"}


async def configuration():
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        state = await session.get(JobAgentState, "default")
        return {"config": saved_config(state.config).model_dump() if state else JobAgentConfig().model_dump(),
                "revision": state.revision if state else 0}


async def update_config(request: ConfigUpdate):
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        state = await state_for_update(session)
        if state.revision != request.revision:
            raise ValueError("Settings changed in another window. Reload before saving.")
        from app.services.job_agent_processing import JobProcessing, taxonomy_key, _wakeup as processing_wakeup
        for category in request.config.resume_categories:
            if category.resume_path:
                await asyncio.to_thread(inspect_resume, category.resume_path)
        previous_config = saved_config(state.config)
        new_config = request.config.model_dump()
        changed = [k for k, v in new_config.items() if state.config.get(k) != v]
        if "import_limit" in state.config:
            changed.append("import_limit")
        if changed:
            state.config = new_config
            state.revision += 1
            state.updated_at = now()
            session.add(JobAgentEvent(kind="settings_updated", message="Job agent preferences updated",
                                      details={"changed_fields": changed, "revision": state.revision}))
        if taxonomy_key(previous_config) != taxonomy_key(request.config):
            await session.execute(text("UPDATE job_agent_processing SET classification_status='pending', revision=revision+1 WHERE COALESCE(classification->>'source','') != 'operator' AND application_status IN ('not_started','failed','needs_review')"))
        await session.commit()
        _wakeup.set()
        processing_wakeup.set()
        return {"config": saved_config(state.config).model_dump(), "revision": state.revision}


async def collect(*, automatic=False):
    """Create or resume one durable, uncapped collection run; the worker drains it."""
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        state = await state_for_update(session)
        config = saved_config(state.config)
        if not config.collection_enabled:
            if automatic:
                return None
            raise ValueError("Collection is paused. Resume it in Settings before syncing listings.")
        run = await session.scalar(select(JobAgentCollectionRun).where(
            JobAgentCollectionRun.completed_at.is_(None)).order_by(JobAgentCollectionRun.started_at).limit(1))
        if run is None:
            if automatic and state.last_collected_at and now() - state.last_collected_at < timedelta(seconds=SYNC_INTERVAL_SECONDS):
                return None
            run = JobAgentCollectionRun(id=uuid4().hex, config=config.model_dump(), config_revision=state.revision)
            session.add(run)
            await session.flush()
        elif automatic and run.status == "failed" and now() - run.updated_at < timedelta(seconds=SYNC_INTERVAL_SECONDS):
            return None
        if run.status == "failed":
            run.status, run.error = "running", None
        await session.commit()
        if not automatic:
            _wakeup.set()
        return serialize_run(run)


def search_profile(config: JobAgentConfig) -> dict:
    """Only operator search intent; application notes and resume data stay out."""
    return {
        "name": "Job Agent target-job search",
        "target_roles": config.target_roles,
        "preferred_industries": config.preferred_industries,
        "location_preferences": config.location_preferences,
        "prefer_overseas_employers": config.prefer_overseas_employers,
        "source_ids": config.search_source_ids,
        "source_urls": source_urls(config.search_source_ids),
    }


async def search_sources():
    settings = await configuration()
    config = JobAgentConfig.model_validate(settings["config"])
    return catalog_payload(config.search_source_ids)


async def _search_and_import(profile: dict):
    """Run verified discovery, then wake the existing durable queue importer."""
    from app.services.daily_career_search import run as career_search_run
    try:
        result = await career_search_run(search_profile=profile)
        if result.get("status") in {"completed", "partial"}:
            try:
                await collect()
            except ValueError:
                # Search results remain stored when queue collection is paused.
                pass
        await ensure_tables()
        async with AsyncSessionLocal() as session:
            counters = result.get("result") or {}
            session.add(JobAgentEvent(
                kind="external_search_finished",
                message=(f"Target-job search {result.get('status')}: "
                         f"{counters.get('new_jobs', 0)} new, "
                         f"{counters.get('duplicates_skipped', 0)} duplicates skipped, "
                         f"{counters.get('contacts_found', 0)} contacts verified"),
                details={"run_id": result.get("id"), "status": result.get("status"),
                         "new_jobs": counters.get("new_jobs", 0),
                         "duplicates_skipped": counters.get("duplicates_skipped", 0),
                         "contacts_found": counters.get("contacts_found", 0)},
            ))
            await session.commit()
        return result
    except Exception:
        logger.exception("Manual Job Agent search failed")
        return {"status": "failed"}


async def request_search():
    from app.services.job_saved_searches import enqueue
    return await enqueue('default')


async def snapshot_source(session, run):
    """One database statement fixes the source set, so concurrent research cannot shift pages."""
    config = saved_config(run.config)
    conditions = ["COALESCE(f.source_json->>'merged_into', '') = ''"]
    params = {"run_id": run.id}
    if config.search.strip():
        conditions.append("(f.firm_name ILIKE :search OR posting.value->>'title' ILIKE :search OR posting.value->>'description_summary' ILIKE :search)")
        params["search"] = f"%{config.search.strip()}%"
    if config.remote_scope == "remote":
        conditions.append("posting.value->>'work_arrangement' = 'remote'")
    elif config.remote_scope == "global":
        conditions.append("posting.value->>'global_remote' = 'true'")
    if config.posted_within_days is not None:
        conditions.append("posting.value->>'posted_date' ~ '^\\d{4}-\\d{2}-\\d{2}$' AND posting.value->>'posted_date' >= :cutoff")
        params["cutoff"] = (now() - timedelta(days=config.posted_within_days)).date().isoformat()
    # Closed postings are included so source closures reach previously imported jobs.
    await session.execute(text("""
        INSERT INTO job_agent_collection_items (run_id, position, posting)
        SELECT :run_id, row_number() OVER (ORDER BY f.id, posting.ordinality),
            posting.value || jsonb_build_object(
                'firm_id', f.id, 'firm_name', f.firm_name, 'entity_type', f.entity_type,
                'website', COALESCE(f.canonical_website, f.website),
                'job_id', posting.value->>'id',
                'found_at', COALESCE(NULLIF(posting.value->>'first_seen_at', ''),
                    NULLIF(f.research_data->'job_postings'->>'researched_at', ''),
                    NULLIF(f.research_data->>'last_job_postings_researched_at', '')))
        FROM pif_directory_firms f
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE WHEN jsonb_typeof(f.research_data->'job_postings'->'postings') = 'array'
            THEN f.research_data->'job_postings'->'postings' ELSE '[]'::jsonb END
        ) WITH ORDINALITY AS posting(value, ordinality)
        WHERE """ + " AND ".join(conditions)), params)
    run.total = await session.scalar(select(func.count()).select_from(JobAgentCollectionItem).where(JobAgentCollectionItem.run_id == run.id))
    run.snapshot_ready = True


def posting_source(posting: dict) -> JobSource:
    """Classify durable provenance while remaining compatible with older rows."""
    if posting.get("job_source") == "external_search" or posting.get("discovery_provider") == PROVIDER:
        return "external_search"
    return "possibleos"


_LEGAL_PRACTITIONER_TITLE = re.compile(r"\b(attorney|lawyer|solicitor|barrister|prosecutor|counsel)\b", re.I)
_NON_PRACTITIONER_TITLE = re.compile(
    r"\b(attorney|lawyer|counsel|legal)\s+(recruiting|recruitment|talent|development)\b|"
    r"\b(recruiting|recruitment|talent)\b.*\b(attorney|lawyer|counsel)\b",
    re.I,
)
_LEGAL_CREDENTIAL = re.compile(
    r"(?:\b(?:j\.?\s*d\.?|juris doctor|law degree|ll\.?\s*b\.?)(?=\W|$)(?:\s+degree)?(?:\s+or equivalent)?\s+(?:is\s+)?(?:required|mandatory)\b)|"
    r"(?:\b(?:required|mandatory)(?:\s+(?:degree|qualification))?\s*[:\-]?\s*(?:an?\s+)?(?:j\.?\s*d\.?|juris doctor|law degree|ll\.?\s*b\.?)(?=\W|$))|"
    r"(?:\bmust have\s+(?:an?\s+)?(?:j\.?\s*d\.?|juris doctor|law degree|ll\.?\s*b\.?)(?=\W|$))|"
    r"(?:\bminimum qualification.{0,30}\b(?:j\.?\s*d\.?|juris doctor|law degree|ll\.?\s*b\.?)(?=\W|$))|"
    r"(?:\b(?:active|current)\b.{0,40}\bbar\b.{0,30}\b(?:membership|admission|license|standing)\b)|"
    r"(?:\b(?:admitted to|member of)\b.{0,40}\bbar\b)|"
    r"(?:\blicensed (?:as an )?attorney\b)|(?:\blicensed to practice law\b)",
    re.I,
)


def legal_degree_assessment(posting: dict) -> dict:
    """Flag only explicit practitioner roles or mandatory legal credentials.

    This is a transparent queue eligibility signal, not job classification. An
    absent requirement remains unknown so legal-adjacent roles are not rejected.
    """
    title = " ".join(str(posting.get("title") or "").split())
    if _LEGAL_PRACTITIONER_TITLE.search(title) and not _NON_PRACTITIONER_TITLE.search(title):
        return {
            "status": "required",
            "reason": f"The role title is {title}, which is a licensed legal-practitioner role.",
            "evidence": title,
        }
    fields = []
    for key in ("qualifications", "requirements", "required_qualifications", "minimum_qualifications", "description_summary"):
        value = posting.get(key)
        if isinstance(value, list):
            fields.extend(str(item) for item in value if item)
        elif isinstance(value, str) and value.strip():
            fields.append(value)
    requirements = " ".join(" ".join(fields).split())
    match = _LEGAL_CREDENTIAL.search(requirements)
    if match:
        evidence = match.group(0).strip()
        return {
            "status": "required",
            "reason": "The listing explicitly requires a law degree, bar admission, or an attorney license.",
            "evidence": evidence,
        }
    return {
        "status": "unknown",
        "reason": "No explicit law-degree or attorney-license requirement was detected in the stored listing.",
        "evidence": None,
    }


def normalize_posting(posting):
    posting = dict(posting)
    posting["job_source"] = posting_source(posting)
    raw = posting.get("posted_date")
    try:
        posting["posted_date"] = date.fromisoformat(str(raw)).isoformat() if raw else None
    except ValueError:
        posting["posted_date"] = None
        posting["posted_date_raw"] = raw
    assessment = legal_degree_assessment(posting)
    posting["legal_degree_requirement"] = assessment["status"]
    posting["legal_degree_reason"] = assessment["reason"]
    posting["legal_degree_evidence"] = assessment["evidence"]
    return posting


def select_stored_posting(postings, request: ListingSelection):
    """Resolve one canonical posting without trusting the browser's job body."""
    rows = [row for row in postings if isinstance(row, dict)]
    if request.job_id:
        matches = [row for row in rows if str(row.get("id") or row.get("job_id") or "") == request.job_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("The stored job ID is ambiguous. Refresh the listings and try again.")
    requested_source = source_identity(request.source_url)
    requested_title = " ".join(request.title.casefold().split())
    requested_location = " ".join((request.location or "").casefold().split())
    matches = []
    for row in rows:
        url = str(row.get("source_url") or "")
        title = " ".join(str(row.get("title") or "").casefold().split())
        location = " ".join(str(row.get("location") or "").casefold().split())
        if url and source_identity(url) == requested_source and title == requested_title and location == requested_location:
            matches.append(row)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("This source contains duplicate stored listings. Refresh the source before opening Job Agent.")
    raise KeyError("Stored job listing not found")


async def open_stored_listing(request: ListingSelection, *,
                              event_kind: str | None = "listing_opened_from_leads"):
    """Resolve a Leads listing into the canonical Job Agent candidate."""
    from app.db.models import PifFirmRow
    from app.services import job_agent_processing as processing

    await ensure_tables()
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, request.firm_id, with_for_update=True)
        if firm is None:
            raise KeyError(request.firm_id)
        research = firm.research_data if isinstance(firm.research_data, dict) else {}
        jobs = research.get("job_postings") if isinstance(research.get("job_postings"), dict) else {}
        stored = select_stored_posting(jobs.get("postings") or [], request)
        posting = normalize_posting({
            **stored,
            "firm_id": firm.id,
            "firm_name": firm.firm_name,
            "entity_type": firm.entity_type,
            "website": firm.canonical_website or firm.website,
            "job_id": stored.get("id") or stored.get("job_id"),
            "found_at": stored.get("first_seen_at") or jobs.get("researched_at")
                or research.get("last_job_postings_researched_at"),
        })
        outcome = await upsert_posting(session, posting)
        identity = candidate_id(posting)
        legacy = await session.get(JobAgentCandidate, legacy_candidate_id(posting))
        if legacy and all(str(legacy.posting.get(k) or "").strip().casefold() ==
                          str(posting.get(k) or "").strip().casefold() for k in ("title", "location")):
            identity = legacy.id
        if outcome in {"added", "updated"} and event_kind:
            session.add(JobAgentEvent(
                kind=event_kind,
                message=f"{firm.firm_name}: opened in Job Agent",
                details={"candidate_id": identity, "firm_id": firm.id,
                         "title": posting.get("title"), "outcome": outcome},
            ))
        await session.commit()
    await processing.enqueue_missing()
    settings = await configuration()
    return {
        "candidate": await processing.detail(identity),
        "categories": settings["config"]["resume_categories"],
        "created": outcome == "added",
    }


def _url_import_failure(result: dict) -> str:
    audit = result.get("result") if isinstance(result.get("result"), dict) else {}
    rejections = audit.get("candidate_rejections") or []
    errors = audit.get("errors") or []
    if rejections:
        reason = rejections[-1].get("reason") or rejections[-1].get("error")
        if reason:
            return str(reason)
    if errors:
        reason = errors[-1].get("error")
        if reason:
            return str(reason)
    return "The employer, exact role, or live application status could not be verified."


async def _record_url_import_event(kind: str, message: str, **details):
    """Make every external-agent import attempt visible in Job Agent activity."""
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        session.add(JobAgentEvent(kind=kind, message=message, details=details))
        await session.commit()


async def import_listing_url(request: UrlImportRequest):
    """Resolve one arbitrary public job URL into the durable Job Agent queue."""
    from app.services import daily_career_search as career_search

    source_url = str(request.source_url)
    attempt_id = uuid4().hex
    await _record_url_import_event(
        "listing_import_started",
        "Started verifying a supplied job URL",
        attempt_id=attempt_id,
        source_url=source_url,
    )
    try:
        settings = await configuration()
        profile = search_profile(JobAgentConfig.model_validate(settings["config"]))
        result = await career_search.import_url(source_url, search_profile=profile)
    except Exception as exc:
        await _record_url_import_event(
            "listing_import_failed",
            "Job URL import failed before a verified listing was stored",
            attempt_id=attempt_id,
            source_url=source_url,
            reason=str(exc)[:2000] or type(exc).__name__,
        )
        raise
    if result.get("status") == "busy":
        await _record_url_import_event(
            "listing_import_busy",
            "This job URL is already being verified",
            attempt_id=attempt_id,
            source_url=source_url,
        )
        return result
    audit = result.get("result") if isinstance(result.get("result"), dict) else {}
    stored_rows = audit.get("stored") or []
    decisions = audit.get("decisions") or []
    if not stored_rows or not decisions:
        reason = _url_import_failure(result)
        await _record_url_import_event(
            "listing_import_stopped",
            "Job URL import stopped before a verified listing was stored",
            attempt_id=attempt_id,
            run_id=result.get("id"),
            source_url=source_url,
            status=result.get("status"),
            reason=reason,
        )
        raise ValueError("Job URL import stopped: " + reason)
    stored = stored_rows[-1]
    decision = decisions[-1]["decision"]
    opened = await open_stored_listing(ListingSelection(
        firm_id=stored["firm_id"],
        job_id=stored.get("job_id"),
        source_url=stored.get("source_url") or source_url,
        title=decision["title"],
        location=decision.get("location") or None,
    ), event_kind=None)
    opened["import"] = {
        "run_id": result.get("id"),
        "status": result.get("status"),
        "source_url": source_url,
        "verified": audit.get("verified", 0),
        "new_job": bool(stored.get("added")),
        "contacts": stored.get("contacts") or {},
        "message": "Job verified and added to Job Agent. No classification, preparation or email was started.",
    }
    firm_name = (
        opened.get("candidate", {}).get("posting", {}).get("firm_name")
        or decisions[-1].get("candidate", {}).get("firm_name")
        or "Employer"
    )
    await _record_url_import_event(
        "listing_imported_from_url",
        f"{decision['title']} at {firm_name}: verified and added to Job Agent",
        attempt_id=attempt_id,
        run_id=result.get("id"),
        source_url=source_url,
        candidate_id=opened["candidate"]["id"],
        firm_id=stored["firm_id"],
        job_id=stored.get("job_id"),
        outcome="added" if opened["created"] else "reused",
    )
    return opened


async def upsert_posting(session, posting):
    identity = candidate_id(posting)
    legacy = await session.get(JobAgentCandidate, legacy_candidate_id(posting), with_for_update=True)
    if legacy and all(str(legacy.posting.get(k) or "").strip().casefold() ==
                      str(posting.get(k) or "").strip().casefold() for k in ("title", "location")):
        identity = legacy.id
    created = await session.scalar(insert(JobAgentCandidate).values(
        id=identity, posting=posting, status="new", note="", revision=1,
        created_at=now(), updated_at=now(),
    ).on_conflict_do_nothing(index_elements=["id"]).returning(JobAgentCandidate.id))
    if created:
        return "added"
    row = await session.get(JobAgentCandidate, identity, with_for_update=True)
    from app.services.job_contract_classification import current_contract_classification
    if current_contract_classification(row.posting) and not current_contract_classification(posting):
        posting = {
            **posting,
            "contract_status": row.posting.get("contract_status"),
            "contract_classification": row.posting.get("contract_classification"),
        }
    if row.posting != posting:
        from app.services.job_agent_processing import JobProcessing, job_key
        if job_key(row.posting) != job_key(posting):
            processing = await session.get(JobProcessing, identity, with_for_update=True)
            if processing and processing.application_status in {'not_started', 'failed', 'needs_review'} and processing.classification.get('source') != 'operator':
                processing.classification_status = 'pending'
                processing.revision += 1
        row.posting = posting
        row.updated_at = now()
        row.revision += 1
        return "updated"
    return "unchanged"


async def process_batch(run_id):
    """Commit candidates and checkpoint atomically; retry only uncommitted work."""
    await ensure_tables()
    try:
        async with AsyncSessionLocal() as session:
            state = await state_for_update(session)
            if not saved_config(state.config).collection_enabled:
                return None
            run = await session.get(JobAgentCollectionRun, run_id, with_for_update=True)
            if run is None or run.completed_at:
                return None
            if not run.snapshot_ready:
                await snapshot_source(session, run)
            items = (await session.scalars(select(JobAgentCollectionItem).where(
                JobAgentCollectionItem.run_id == run.id, JobAgentCollectionItem.position > run.processed)
                .order_by(JobAgentCollectionItem.position).limit(BATCH_SIZE))).all()
            for item in items:
                posting = normalize_posting(item.posting)
                try:
                    candidate_id(posting)
                except (KeyError, ValueError, TypeError):
                    run.invalid += 1
                    session.add(JobAgentEvent(kind="invalid_listing", message="Listing needs a valid employer and source URL",
                        details={"run_id": run.id, "position": item.position, "posting": posting}))
                else:
                    outcome = await upsert_posting(session, posting)
                    if outcome in {"added", "updated"}:
                        setattr(run, outcome, getattr(run, outcome) + 1)
                run.processed = item.position
            run.status, run.error, run.updated_at = "running", None, now()
            if run.processed == run.total:
                run.status = "completed_with_errors" if run.invalid else "completed"
                run.completed_at = now()
                # Keep the durable summary/audit, release the now-unneeded snapshot.
                await session.execute(delete(JobAgentCollectionItem).where(JobAgentCollectionItem.run_id == run.id))
                if run.added or run.updated or run.invalid or state.last_collected_at is None:
                    session.add(JobAgentEvent(kind="listings_collected",
                        message=f"Synced {run.total} listings: {run.added} new, {run.updated} refreshed, {run.invalid} invalid",
                        details=serialize_run(run)))
                state.last_collected_at = now()
            await session.commit()
            return serialize_run(run)
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            run = await session.get(JobAgentCollectionRun, run_id, with_for_update=True)
            if run and not run.completed_at:
                run.status, run.updated_at = "failed", now()
                run.error = f"Collection failed ({type(exc).__name__}). Saved progress is safe; retrying automatically."
                session.add(JobAgentEvent(kind="collection_failed", message=run.error, details={"run_id": run_id, "processed": run.processed}))
                await session.commit()
        raise


async def collection_loop():
    while True:
        _wakeup.clear()
        try:
            run = await collect(automatic=True)
            while run and run["status"] == "running":
                run = await process_batch(run["id"])
                await asyncio.sleep(0)
        except Exception:
            logger.exception("Job-agent collection failed; retrying after the polling interval")
        try:
            await asyncio.wait_for(_wakeup.wait(), timeout=SYNC_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def review(identity: str, request: ReviewUpdate):
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(JobAgentCandidate, identity, with_for_update=True)
        if row is None:
            raise KeyError(identity)
        if row.revision != request.revision:
            raise ValueError("This job changed in another window. Reload before saving.")
        old_status = row.status
        if row.status != request.status or row.note != request.note.strip():
            row.status, row.note = request.status, request.note.strip()
            row.revision += 1
            row.updated_at = now()
            session.add(JobAgentEvent(kind="job_reviewed",
                message=f"{row.posting.get('firm_name', 'Company')}: {request.status.replace('_', ' ')}",
                details={"candidate_id": identity, "title": row.posting.get("title"),
                         "previous_status": old_status, "status": row.status, "note": row.note,
                         "actor": "operator"}))
        await session.commit()
        return serialize_candidate(row)


JobOrder = Literal["posted_desc", "posted_asc", "found_desc", "contact_desc"]


def legal_degree_required_expression():
    """PostgreSQL expression matching ``legal_degree_assessment`` for queue filters."""
    normalized_title = func.concat(
        " ",
        func.regexp_replace(
            func.lower(func.coalesce(JobAgentCandidate.posting["title"].astext, "")),
            r"[^a-z]+", " ", "g",
        ),
        " ",
    )
    practitioner_title = or_(*(
        normalized_title.contains(f" {term} ")
        for term in ("attorney", "lawyer", "solicitor", "barrister", "prosecutor", "counsel")
    ))
    non_practitioner_title = or_(*(
        normalized_title.contains(f" {phrase} ")
        for phrase in (
            "attorney recruiting", "attorney recruitment", "attorney talent", "attorney development",
            "lawyer recruiting", "lawyer recruitment", "lawyer talent", "lawyer development",
            "counsel recruiting", "counsel recruitment", "counsel talent", "counsel development",
            "recruiting attorney", "recruitment attorney", "talent attorney",
            "recruiting lawyer", "recruitment lawyer", "talent lawyer",
            "recruiting counsel", "recruitment counsel", "talent counsel",
        )
    ))
    requirement_text = func.regexp_replace(
        func.lower(func.concat(
            " ", cast(JobAgentCandidate.posting["qualifications"], String),
            " ", cast(JobAgentCandidate.posting["requirements"], String),
            " ", cast(JobAgentCandidate.posting["required_qualifications"], String),
            " ", cast(JobAgentCandidate.posting["minimum_qualifications"], String),
            " ", func.coalesce(JobAgentCandidate.posting["description_summary"].astext, ""), " ",
        )),
        r"[^a-z]+", " ", "g",
    )
    credential_required = requirement_text.op("~")(
        r"((^| )(jd|j d|juris doctor|law degree|llb|ll b)( degree)?( or equivalent)? (is )?(required|mandatory)( |$))|"
        r"((required|mandatory)( degree| qualification)? (a |an )?(jd|j d|juris doctor|law degree|llb|ll b)( |$))|"
        r"(must have (a |an )?(jd|j d|juris doctor|law degree|llb|ll b)( |$))|"
        r"(minimum qualification.{0,30}(jd|j d|juris doctor|law degree|llb|ll b)( |$))|"
        r"((active|current).{0,40}bar.{0,30}(membership|admission|license|standing))|"
        r"((admitted to|member of).{0,40}bar)|"
        r"(licensed (as an )?attorney)|(licensed to practice law)"
    )
    stored_required = func.coalesce(
        JobAgentCandidate.posting["legal_degree_requirement"].astext == "required", False,
    )
    return or_(stored_required, and_(practitioner_title, not_(non_practitioner_title)), credential_required)


async def candidates(status: ReviewStatus | None = None, search: str = "", page: int = 1,
                     order: JobOrder = "posted_desc", category: str = "",
                     source: JobSource | None = None,
                     legal_degree: LegalDegreeFilter = "exclude",
                     contract: ContractFilter = "all"):
    from app.services.job_agent_processing import JobProcessing, attach_details
    await ensure_tables()
    query = select(JobAgentCandidate)
    if category:
        query = query.join(JobProcessing, JobProcessing.candidate_id == JobAgentCandidate.id)
        if category == 'needs_review':
            query = query.where(JobProcessing.classification_status == 'needs_review')
        else:
            query = query.where(JobProcessing.classification['category_id'].astext == category)
    if status:
        query = query.where(JobAgentCandidate.status == status)
    if source:
        stored_source = JobAgentCandidate.posting["job_source"].astext
        provider = JobAgentCandidate.posting["discovery_provider"].astext
        derived_source = case(
            (stored_source == "external_search", "external_search"),
            (stored_source == "possibleos", "possibleos"),
            (provider == PROVIDER, "external_search"),
            else_="possibleos",
        )
        query = query.where(derived_source == source)
    if contract == "unknown":
        query = query.where(func.coalesce(
            JobAgentCandidate.posting["contract_status"].astext, "unknown"
        ) == "unknown")
    elif contract != "all":
        query = query.where(JobAgentCandidate.posting["contract_status"].astext == contract)
    if search.strip():
        phrase = f"%{search.strip()}%"
        query = query.where(JobAgentCandidate.posting["firm_name"].astext.ilike(phrase)
                            | JobAgentCandidate.posting["title"].astext.ilike(phrase))
    legal_degree_required = legal_degree_required_expression()
    if legal_degree == "exclude":
        query = query.where(not_(legal_degree_required))
    elif legal_degree == "required":
        query = query.where(legal_degree_required)
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        posted = JobAgentCandidate.posting["posted_date"].astext
        # Normalized on sync; guard legacy unknown labels while backfill catches up.
        posted = case((posted.op("~")(r"^\d{4}-\d{2}-\d{2}$"), posted), else_=None)
        from app.db.models import FirmContactRow
        from app.services.job_agent_research import (
            BLOCKED_MAILBOXES, RECRUITING_MAILBOXES, RECRUITING_TERMS,
            ROUTING_MAILBOXES, ROUTING_TERMS,
        )
        email_host = func.lower(func.split_part(FirmContactRow.email, "@", 2))
        website_host = func.regexp_replace(
            func.regexp_replace(
                func.lower(func.coalesce(
                    JobAgentCandidate.posting["website"].astext,
                    JobAgentCandidate.posting["employer_evidence_url"].astext,
                    "",
                )),
                r"^https?://(www\.)?", "", "g",
            ),
            r"/.*$", "", "g",
        )
        mailbox = func.lower(func.split_part(FirmContactRow.email, "@", 1))
        contact_title = func.lower(func.coalesce(
            FirmContactRow.research_title, FirmContactRow.title, "",
        ))
        suitable_role = or_(
            mailbox.in_((*RECRUITING_MAILBOXES, *ROUTING_MAILBOXES)),
            *(contact_title.contains(term) for term in (*RECRUITING_TERMS, *ROUTING_TERMS)),
        )
        contact_count = select(func.count(FirmContactRow.id)).where(
            FirmContactRow.pif_id == JobAgentCandidate.posting["firm_id"].astext,
            FirmContactRow.email.isnot(None),
            website_host != "",
            or_(email_host == website_host,
                email_host.endswith("." + website_host),
                website_host.endswith("." + email_host)),
            mailbox.not_in(BLOCKED_MAILBOXES),
            suitable_role,
        ).correlate(JobAgentCandidate).scalar_subquery()
        ordering = {
            "posted_desc": (posted.desc().nulls_last(),),
            "posted_asc": (posted.asc().nulls_last(),),
            "found_desc": (JobAgentCandidate.created_at.desc(),),
            "contact_desc": (contact_count.desc(), posted.desc().nulls_last()),
        }[order]
        legal_degree_rank = case((legal_degree_required, 1), else_=0)
        rows = (await session.scalars(query.order_by(legal_degree_rank, *ordering, JobAgentCandidate.id)
                                     .offset((page - 1) * 25).limit(25))).all()
        return {"items": await attach_details(session, rows), "total": total, "page": page,
                "page_size": 25, "total_pages": (total + 24) // 25}


async def events(page: int = 1):
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(JobAgentEvent))
        rows = (await session.scalars(select(JobAgentEvent).order_by(JobAgentEvent.id.desc()).offset((page - 1) * 25).limit(25))).all()
        return {"total": total, "page": page, "page_size": 25, "total_pages": (total + 24) // 25,
                "items": [{"id": row.id, "kind": row.kind, "message": row.message,
                 "details": row.details, "created_at": row.created_at.isoformat()} for row in rows]}


async def overview():
    from app.services.daily_career_search import status as career_status
    from app.services.job_agent_processing import JobProcessing
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        processing_counts = dict((await session.execute(select(JobProcessing.classification_status, func.count()).group_by(JobProcessing.classification_status))).all())
        counts = dict((await session.execute(select(JobAgentCandidate.status, func.count())
                      .group_by(JobAgentCandidate.status))).all())
        state = await session.get(JobAgentState, "default")
        run = await session.scalar(select(JobAgentCollectionRun).order_by(JobAgentCollectionRun.started_at.desc()).limit(1))
    try:
        source = await career_status()
        source = {**{k: source[k] for k in ("config", "next_due_at", "schedule_enabled", "timer_installation")},
                  "runs": [{"id": r["id"], "status": r["status"], "started_at": r["started_at"],
                            "completed_at": r["completed_at"], "result": {k: r["result"].get(k) for k in
                             ("new_jobs", "verified", "closed", "duplicates_skipped", "errors", "attempt_errors",
                             "verification_rejections", "job_agent_search", "search_trigger", "manual_search",
                             "search_profile", "interrupted_reason",
                             "search_source_ids", "search_sources_consulted",
                             "contacts_found", "contacts_inserted")}}
                           for r in source["runs"]]}
        source_error = None
    except Exception:
        source, source_error = None, "Career-search status is unavailable. Review queue and settings remain available."
    return {"config": saved_config(state.config).model_dump() if state else JobAgentConfig().model_dump(),
            "revision": state.revision if state else 0,
            "last_collected_at": state.last_collected_at.isoformat() if state and state.last_collected_at else None,
            "counts": {s: counts.get(s, 0) for s in ("new", "shortlisted", "needs_info", "skipped")},
            "mode": "operator_requested_applications", "execution_connected": True,
            "processing_counts": processing_counts,
            "collection": serialize_run(run), "sync_interval_seconds": SYNC_INTERVAL_SECONDS,
            "source": source, "source_error": source_error,
            "search_sources": catalog_payload(saved_config(state.config).search_source_ids) if state else catalog_payload(JobAgentConfig().search_source_ids)}
