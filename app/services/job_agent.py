"""Job-agent control surface: durable preferences, operator review and audit trail.

Imports existing postings and exposes preferences, review decisions and processing
state. Classification and explicitly requested email applications live in the
processing service. Shortlisting alone never sends an application.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from uuid import uuid4
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, Integer, String, Boolean, case, delete, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db import AsyncSessionLocal, Base, async_engine
from app.services.career_job_store import PROVIDER, source_identity
from app.services.job_agent_resumes import ResumeCategory, default_categories, inspect_resume


ReviewStatus = Literal["new", "shortlisted", "needs_info", "skipped"]
JobSource = Literal["possibleos", "external_search"]


def now():
    return datetime.now(timezone.utc)


class JobAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    classification_enabled: bool = False
    classification_threshold: float = Field(0.8, ge=0, le=1)
    resume_categories: list[ResumeCategory] = Field(default_factory=default_categories)
    collection_enabled: bool = True
    search: str = Field("", max_length=255)
    remote_scope: Literal["any", "remote", "global"] = "any"
    posted_within_days: int | None = Field(None, ge=1, le=365)
    target_roles: str = Field("Applied AI, AI agents, workflow automation, engineering and product leadership; entry-level personal-injury case management, paralegal/legal-assistant and intake roles", max_length=2000)
    preferred_industries: str = Field("Legal technology, personal injury firms, healthcare operations", max_length=2000)
    location_preferences: str = Field("Remote from Bengaluru, India; planning to move to Medellín, Colombia (UTC-5). Verify country-specific eligibility.", max_length=2000)
    prefer_overseas_employers: bool = True
    application_notes: str = Field("Founder-led, concise applications. Use verified experience. Reuse the best suitable one-page PDF resume. Do not call it 'tailored' in emails.", max_length=4000)


    @model_validator(mode="after")
    def unique_categories(self):
        if len({category.id for category in self.resume_categories}) != len(self.resume_categories):
            raise ValueError("Category identifiers must be unique.")
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
            for model in (JobAgentState, JobAgentCandidate, JobAgentEvent, JobAgentCollectionRun, JobAgentCollectionItem, JobProcessing):
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
        "name": "Job Agent legal AI search",
        "target_roles": config.target_roles,
        "preferred_industries": config.preferred_industries,
        "location_preferences": config.location_preferences,
        "prefer_overseas_employers": config.prefer_overseas_employers,
    }


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
                message=(f"Legal AI search {result.get('status')}: "
                         f"{counters.get('new_jobs', 0)} new, "
                         f"{counters.get('duplicates_skipped', 0)} duplicates skipped"),
                details={"run_id": result.get("id"), "status": result.get("status"),
                         "new_jobs": counters.get("new_jobs", 0),
                         "duplicates_skipped": counters.get("duplicates_skipped", 0)},
            ))
            await session.commit()
        return result
    except Exception:
        logger.exception("Manual Job Agent search failed")
        return {"status": "failed"}


async def request_search():
    """Start one non-sending search in the daemon and return immediately."""
    global _search_task
    from app.services.daily_career_search import status as career_status
    current = await career_status()
    running = next((run for run in current["runs"] if run["status"] == "running"), None)
    if (_search_task and not _search_task.done()) or running:
        return {"status": "busy", "run_id": running["id"] if running else None}
    settings = await configuration()
    profile = search_profile(JobAgentConfig.model_validate(settings["config"]))
    _search_task = asyncio.create_task(_search_and_import(profile), name="job-agent-external-search")
    return {"status": "queued", "search_profile": profile,
            "message": "Searching public sources. Verified new jobs will be added to the review queue."}


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


def normalize_posting(posting):
    posting = dict(posting)
    posting["job_source"] = posting_source(posting)
    raw = posting.get("posted_date")
    try:
        posting["posted_date"] = date.fromisoformat(str(raw)).isoformat() if raw else None
    except ValueError:
        posting["posted_date"] = None
        posting["posted_date_raw"] = raw
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


async def open_stored_listing(request: ListingSelection):
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
        if outcome in {"added", "updated"}:
            session.add(JobAgentEvent(
                kind="listing_opened_from_leads",
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


JobOrder = Literal["posted_desc", "posted_asc", "found_desc"]


async def candidates(status: ReviewStatus | None = None, search: str = "", page: int = 1,
                     order: JobOrder = "posted_desc", category: str = "",
                     source: JobSource | None = None):
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
    if search.strip():
        phrase = f"%{search.strip()}%"
        query = query.where(JobAgentCandidate.posting["firm_name"].astext.ilike(phrase)
                            | JobAgentCandidate.posting["title"].astext.ilike(phrase))
    async with AsyncSessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        posted = JobAgentCandidate.posting["posted_date"].astext
        # Normalized on sync; guard legacy unknown labels while backfill catches up.
        posted = case((posted.op("~")(r"^\d{4}-\d{2}-\d{2}$"), posted), else_=None)
        ordering = {"posted_desc": posted.desc().nulls_last(), "posted_asc": posted.asc().nulls_last(),
                    "found_desc": JobAgentCandidate.created_at.desc()}[order]
        rows = (await session.scalars(query.order_by(ordering, JobAgentCandidate.id)
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
                             "verification_rejections", "manual_search", "search_profile")}}
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
            "source": source, "source_error": source_error}
