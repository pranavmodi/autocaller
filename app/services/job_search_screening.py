"""Durable, inspectable snapshots for structured-source relevance screening."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db import AsyncSessionLocal, Base, async_engine


class JobSearchListingSnapshot(Base):
    __tablename__ = "job_search_listing_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    listing_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    native_id: Mapped[str] = mapped_column(String(512), nullable=False)
    job_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    employer_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    location: Mapped[str] = mapped_column(Text, nullable=False, default="")
    employment_type: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    listing: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="collected", index=True)
    choice: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    judgment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "listing_key", name="uq_job_search_snapshot_run_listing"),
    )


_ready = False


async def ensure_table() -> None:
    global _ready
    if _ready:
        return
    async with async_engine.begin() as connection:
        await connection.run_sync(JobSearchListingSnapshot.__table__.create, checkfirst=True)
    _ready = True


def canonical_listing_url(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def listing_key(value: str) -> str:
    return hashlib.sha256(canonical_listing_url(value).encode()).hexdigest()


def _listing_values(run_id: str, item, now: datetime) -> dict:
    compact = item.compact()
    compact.pop("relevance", None)
    return {
        "id": uuid4().hex,
        "run_id": run_id,
        "listing_key": listing_key(item.job_url),
        "source_key": item.source_key,
        "provider": item.provider,
        "native_id": item.native_id,
        "job_url": item.job_url,
        "title": item.title,
        "employer_name": item.employer_name,
        "location": item.location,
        "employment_type": item.employment_type,
        "description": item.description,
        "published_at": item.published_at,
        "raw_fingerprint": item.raw_fingerprint,
        "listing": compact,
        "status": "collected",
        "choice": None,
        "selected": False,
        "judgment": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


async def persist_collected(run_id: str, listings: list) -> None:
    """Upsert one row per canonical listing URL within a run.

    Reprocessing the same run resets its screening state and never adds another
    snapshot row. A later run intentionally receives its own evidence snapshot.
    """
    if not listings:
        return
    await ensure_table()
    now = datetime.now(timezone.utc)
    values = [_listing_values(run_id, item, now) for item in listings]
    statement = insert(JobSearchListingSnapshot).values(values)
    excluded = statement.excluded
    statement = statement.on_conflict_do_update(
        constraint="uq_job_search_snapshot_run_listing",
        set_={
            "source_key": excluded.source_key,
            "provider": excluded.provider,
            "native_id": excluded.native_id,
            "job_url": excluded.job_url,
            "title": excluded.title,
            "employer_name": excluded.employer_name,
            "location": excluded.location,
            "employment_type": excluded.employment_type,
            "description": excluded.description,
            "published_at": excluded.published_at,
            "raw_fingerprint": excluded.raw_fingerprint,
            "listing": excluded.listing,
            "status": "collected",
            "choice": None,
            "selected": False,
            "judgment": {},
            "error": None,
            "updated_at": now,
        },
    )
    async with AsyncSessionLocal() as session:
        await session.execute(statement)
        await session.commit()


async def persist_judgments(run_id: str, listings: list) -> None:
    await ensure_table()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        for item in listings:
            judgment = dict(item.relevance or {})
            await session.execute(update(JobSearchListingSnapshot).where(
                JobSearchListingSnapshot.run_id == run_id,
                JobSearchListingSnapshot.listing_key == listing_key(item.job_url),
            ).values(
                status="classified",
                choice=judgment.get("choice"),
                judgment=judgment,
                error=None,
                updated_at=now,
            ))
        await session.commit()


async def persist_errors(run_id: str, listings: list, error: str) -> None:
    await ensure_table()
    now = datetime.now(timezone.utc)
    keys = [listing_key(item.job_url) for item in listings]
    if not keys:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(update(JobSearchListingSnapshot).where(
            JobSearchListingSnapshot.run_id == run_id,
            JobSearchListingSnapshot.listing_key.in_(keys),
        ).values(status="error", choice=None, selected=False, judgment={},
                 error=error[:4000], updated_at=now))
        await session.commit()


async def mark_selected(run_id: str, listings: list) -> None:
    await ensure_table()
    now = datetime.now(timezone.utc)
    keys = [listing_key(item.job_url) for item in listings]
    async with AsyncSessionLocal() as session:
        await session.execute(update(JobSearchListingSnapshot).where(
            JobSearchListingSnapshot.run_id == run_id,
        ).values(selected=False, updated_at=now))
        if keys:
            await session.execute(update(JobSearchListingSnapshot).where(
                JobSearchListingSnapshot.run_id == run_id,
                JobSearchListingSnapshot.listing_key.in_(keys),
            ).values(selected=True, updated_at=now))
        await session.commit()


def _serialize(row: JobSearchListingSnapshot) -> dict:
    return {
        "id": row.id,
        "source_key": row.source_key,
        "provider": row.provider,
        "native_id": row.native_id,
        "job_url": row.job_url,
        "title": row.title,
        "employer_name": row.employer_name,
        "location": row.location,
        "employment_type": row.employment_type,
        "description": row.description,
        "published_at": row.published_at,
        "status": row.status,
        "choice": row.choice,
        "selected": row.selected,
        "judgment": row.judgment or {},
        "error": row.error,
        "updated_at": row.updated_at.isoformat(),
    }


async def inspect(run_id: str, *, view: str = "all", search: str = "",
                  source_key: str = "", page: int = 1, page_size: int = 50) -> dict:
    await ensure_table()
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    filters = [JobSearchListingSnapshot.run_id == run_id]
    if view == "selected":
        filters.append(JobSearchListingSnapshot.selected.is_(True))
    elif view in {"match", "possible", "unrelated"}:
        filters.append(JobSearchListingSnapshot.choice == view)
    elif view == "error":
        filters.append(JobSearchListingSnapshot.status == "error")
    elif view in {"pending", "collected"}:
        filters.append(JobSearchListingSnapshot.status == "collected")
    elif view != "all":
        raise ValueError("view must be all, selected, match, possible, unrelated, pending or error")
    if source_key:
        filters.append(JobSearchListingSnapshot.source_key == source_key)
    term = search.strip()
    if term:
        like = f"%{term}%"
        filters.append(or_(JobSearchListingSnapshot.title.ilike(like),
                           JobSearchListingSnapshot.employer_name.ilike(like)))

    base = select(JobSearchListingSnapshot).where(*filters)
    ordering = case(
        (JobSearchListingSnapshot.selected.is_(True), 0),
        (JobSearchListingSnapshot.choice == "match", 1),
        (JobSearchListingSnapshot.choice == "possible", 2),
        (JobSearchListingSnapshot.status == "error", 3),
        (JobSearchListingSnapshot.choice == "unrelated", 4),
        else_=5,
    )
    async with AsyncSessionLocal() as session:
        total = int(await session.scalar(select(func.count()).select_from(
            JobSearchListingSnapshot).where(*filters)) or 0)
        run_rows = (await session.scalars(select(JobSearchListingSnapshot).where(
            JobSearchListingSnapshot.run_id == run_id))).all()
        rows = (await session.scalars(base.order_by(ordering, JobSearchListingSnapshot.title,
            JobSearchListingSnapshot.employer_name).offset((page - 1) * page_size).limit(page_size))).all()
    choices = {key: sum(row.choice == key for row in run_rows) for key in ("match", "possible", "unrelated")}
    summary = {
        "total": len(run_rows),
        "classified": sum(row.choice is not None for row in run_rows),
        "selected": sum(row.selected for row in run_rows),
        "pending": sum(row.status == "collected" for row in run_rows),
        "errors": sum(row.status == "error" for row in run_rows),
        "choices": choices,
    }
    return {
        "run_id": run_id,
        "summary": summary,
        "items": [_serialize(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "view": view,
    }
