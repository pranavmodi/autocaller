"""Durable, provider-aware queue for operator-supplied job URLs."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import Boolean, DateTime, String, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.services import job_agent as core
from app.services.career_job_store import source_identity


class JobUrlImportQueue(core.Base):
    __tablename__ = "job_agent_url_import_queue"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(2000), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    start_website_application: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_run_id: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_urls: list[HttpUrl] = Field(min_length=1, max_length=50)
    start_website_application: bool = False
    ai_provider: Literal["gateway", "openai"] = "gateway"


WAKE = asyncio.Event()


def view(row: JobUrlImportQueue):
    return {
        "id": row.id,
        "source_url": row.source_url,
        "ai_provider": row.provider,
        "start_website_application": row.start_website_application,
        "status": row.status,
        "current_run_id": row.current_run_id,
        "result": row.result or {},
        "error": row.error,
        "created_at": row.created_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "updated_at": row.updated_at.isoformat(),
    }


async def enqueue(request: BatchRequest):
    await core.ensure_tables()
    unique: dict[str, str] = {}
    for supplied in request.source_urls:
        url = str(supplied)
        unique.setdefault(source_identity(url), url)
    async with core.AsyncSessionLocal() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(734985229)"))
        active = list((await session.scalars(select(JobUrlImportQueue).where(
            JobUrlImportQueue.source_identity.in_(list(unique)),
            JobUrlImportQueue.status.in_(["queued", "running"])))).all())
        active_by_identity = {row.source_identity: row for row in active}
        rows, new_rows = [], []
        for identity, url in unique.items():
            row = active_by_identity.get(identity)
            if row is None:
                row = JobUrlImportQueue(
                    id=uuid4().hex,
                    source_url=url,
                    source_identity=identity,
                    provider=request.ai_provider,
                    start_website_application=request.start_website_application,
                    status="queued",
                    result={},
                    created_at=core.now(),
                    updated_at=core.now(),
                )
                new_rows.append(row)
            rows.append(row)
        session.add_all(new_rows)
        await session.commit()
    WAKE.set()
    return {"items": [view(row) for row in rows],
            "duplicates_skipped": len(request.source_urls) - len(unique),
            "active_reused": len(rows) - len(new_rows)}


async def detail(identity: str):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobUrlImportQueue, identity)
        if not row:
            raise KeyError(identity)
        payload = view(row)
    if row.current_run_id:
        from app.services.job_saved_searches import run_detail
        try:
            payload["run"] = await run_detail(row.current_run_id)
        except KeyError:
            payload["run"] = None
    else:
        payload["run"] = None
    return payload


async def recent(limit: int = 50):
    await core.ensure_tables()
    async with core.AsyncSessionLocal() as session:
        rows = list((await session.scalars(select(JobUrlImportQueue).order_by(
            JobUrlImportQueue.created_at.desc()).limit(limit))).all())
    return {"items": [view(row) for row in rows]}


async def _claim(identity: str):
    run_id = uuid4().hex
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobUrlImportQueue, identity, with_for_update=True)
        if not row or row.status != "queued":
            return None
        row.status = "running"
        row.current_run_id = run_id
        row.started_at = core.now()
        row.completed_at = None
        row.error = None
        row.updated_at = core.now()
        await session.commit()
        return view(row)


async def _process(claimed: dict):
    identity = claimed["id"]
    try:
        result = await core.import_listing_url(core.UrlImportRequest(
            source_url=claimed["source_url"],
            start_website_application=claimed["start_website_application"],
            ai_provider=claimed["ai_provider"],
            attempt_id=UUID(claimed["current_run_id"]),
        ))
        status, error = "completed", None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        result, status = {}, "failed"
        error = str(exc)[:2000] or type(exc).__name__
    async with core.AsyncSessionLocal() as session:
        row = await session.get(JobUrlImportQueue, identity, with_for_update=True)
        if row and row.status == "running" and row.current_run_id == claimed["current_run_id"]:
            row.status = status
            row.result = result
            row.error = error
            row.completed_at = core.now()
            row.updated_at = core.now()
            await session.commit()
    WAKE.set()


async def worker():
    await core.ensure_tables()
    # A stopped backend cannot still own an HTTP import coroutine. Requeue its
    # rows and give each retry a fresh underlying research-run identifier.
    async with core.AsyncSessionLocal() as session:
        await session.execute(update(JobUrlImportQueue).where(
            JobUrlImportQueue.status == "running").values(
                status="queued", current_run_id=None,
                error="Backend restarted; queued again without starting an application twice.",
                updated_at=core.now()))
        await session.commit()
    tasks: dict[asyncio.Task, str] = {}
    try:
        while True:
            WAKE.clear()
            for task in [task for task in tasks if task.done()]:
                tasks.pop(task, None)
                try:
                    task.result()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # _process persists ordinary failures; this protects the scheduler.
                    pass
            active = list(tasks.values())
            capacity = {"gateway": 1 - active.count("gateway"),
                        "openai": 3 - active.count("openai")}
            async with core.AsyncSessionLocal() as session:
                queued = list((await session.scalars(select(JobUrlImportQueue).where(
                    JobUrlImportQueue.status == "queued").order_by(
                        JobUrlImportQueue.created_at).limit(20))).all())
            launched = False
            for row in queued:
                if capacity.get(row.provider, 0) <= 0:
                    continue
                claimed = await _claim(row.id)
                if not claimed:
                    continue
                task = asyncio.create_task(_process(claimed))
                tasks[task] = row.provider
                capacity[row.provider] -= 1
                launched = True
            if launched:
                continue
            waiters = [asyncio.create_task(WAKE.wait())]
            waiters.extend(tasks)
            done, pending = await asyncio.wait(waiters, timeout=3,
                                               return_when=asyncio.FIRST_COMPLETED)
            if waiters[0] in pending:
                waiters[0].cancel()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
