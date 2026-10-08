"""Deterministic public job-source collection and durable coverage records.

Adapters own transport, pagination, cursors, and mechanical identifiers. They do
not decide whether a role suits the operator. TypeSafe Jev ranks the collected
facts later, and the existing evidence verifier remains authoritative before a
job is stored.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column

from app.db import AsyncSessionLocal, Base, async_engine
from app.db.models import PifFirmRow
from app.services.career_search_web import public_url


DIRECT_SOURCE_IDS = {"himalayas", "remoteok", "remotive"}
ATS_PROVIDERS = {"ashby", "greenhouse", "lever", "workable"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
USER_AGENT = "PossibleOSJobSourceCollector/1.0"


class JobSearchEmployerBoard(Base):
    __tablename__ = "job_search_employer_boards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    board_key: Mapped[str] = mapped_column(String(255), nullable=False)
    board_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    employer_name: Mapped[str] = mapped_column(String(512), nullable=False)
    employer_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    employer_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    firm_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discovered_from: Mapped[str] = mapped_column(String(2000), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cursor: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("provider", "board_key", name="uq_job_search_board_provider_key"),)


class JobSearchSourceRun(Base):
    __tablename__ = "job_search_source_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(String(320), nullable=False)
    source_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pages_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_emitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor_before: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cursor_after: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("run_id", "source_key", name="uq_job_search_source_run_key"),)


class SourceListing(BaseModel):
    """Normalized transport facts. Relevance and employer identity are undecided."""

    model_config = ConfigDict(extra="forbid")
    source_key: str
    provider: str
    native_id: str
    job_url: str
    title: str
    employer_name: str = ""
    location: str = ""
    employment_type: str = ""
    description: str = Field("", max_length=8000)
    published_at: str | None = None
    board_id: str | None = None
    employer_domain: str | None = None
    employer_url: str | None = None
    raw_fingerprint: str
    relevance: dict | None = None

    def compact(self) -> dict:
        return self.model_dump(exclude={"raw_fingerprint"})


@dataclass(frozen=True)
class SourceTarget:
    source_key: str
    source_name: str
    source_url: str
    adapter_type: str
    provider: str
    board_id: str | None = None
    board_key: str | None = None
    employer_name: str = ""
    employer_domain: str = ""
    employer_url: str = ""
    firm_id: str | None = None
    cursor: dict = field(default_factory=dict)


@dataclass
class AdapterResult:
    listings: list[SourceListing]
    pages_checked: int
    cursor: dict
    details: dict = field(default_factory=dict)


_ready = False
_ready_lock = asyncio.Lock()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_tables() -> None:
    global _ready
    if _ready:
        return
    async with _ready_lock:
        if _ready:
            return
        async with async_engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('possibleos:job-source-adapters:schema', 0))"))
            await conn.run_sync(JobSearchEmployerBoard.__table__.create, checkfirst=True)
            await conn.run_sync(JobSearchSourceRun.__table__.create, checkfirst=True)
        _ready = True


def _url_identity(value: str) -> str:
    parts = urlsplit(value.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _text(value: Any, limit: int = 8000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:limit]


def _published_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return None


def _within_window(value: Any, cutoff: datetime) -> bool:
    parsed = _published_datetime(value)
    return parsed is None or parsed >= cutoff


async def _fetch_json(url: str, *, max_bytes: int = 12_000_000, attempts: int = 5) -> Any:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            await public_url(url)
            async with httpx.AsyncClient(
                timeout=40, trust_env=False, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            ) as client:
                response = await client.get(url, follow_redirects=False)
            if response.status_code in RETRYABLE_STATUS:
                last_error = RuntimeError(f"HTTP {response.status_code}")
                if attempt + 1 < attempts:
                    retry_after = response.headers.get("retry-after", "")
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 0
                    await asyncio.sleep(min(60, max(delay, 2 * (2**attempt))))
                    continue
                raise last_error
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            if len(response.content) > max_bytes:
                raise RuntimeError(f"response exceeds {max_bytes} byte limit")
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError, RuntimeError, OSError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(min(60, 2 * (2**attempt)))
    raise RuntimeError(str(last_error) or "source fetch failed") from last_error


def _listing(target: SourceTarget, raw: dict, *, native_id: Any, job_url: Any, title: Any,
             employer_name: Any = "", location: Any = "", employment_type: Any = "",
             description: Any = "", published_at: Any = None) -> SourceListing | None:
    url = str(job_url or "").strip()
    name = str(title or "").strip()
    identity = str(native_id or "").strip() or _fingerprint({"url": url, "title": name})[:24]
    if not url.startswith("https://") or not name:
        return None
    published = _published_datetime(published_at)
    return SourceListing(
        source_key=target.source_key,
        provider=target.provider,
        native_id=identity,
        job_url=url,
        title=name,
        employer_name=str(employer_name or target.employer_name or "").strip(),
        location=_text(location, 1000),
        employment_type=_text(employment_type, 500),
        description=_text(description),
        published_at=published.isoformat() if published else None,
        board_id=target.board_id,
        employer_domain=target.employer_domain or None,
        employer_url=target.employer_url or None,
        raw_fingerprint=_fingerprint(raw),
    )


async def _collect_remoteok(target: SourceTarget, cutoff: datetime, _profile: Any) -> AdapterResult:
    document = await _fetch_json(target.source_url)
    if not isinstance(document, list):
        raise RuntimeError("Remote OK did not return a JSON array")
    listings = []
    for raw in document:
        if not isinstance(raw, dict) or not raw.get("position") or not _within_window(raw.get("date"), cutoff):
            continue
        item = _listing(target, raw, native_id=raw.get("id"), job_url=raw.get("url"), title=raw.get("position"),
                        employer_name=raw.get("company"), location=raw.get("location"),
                        employment_type=raw.get("job_type"), description=raw.get("description"),
                        published_at=raw.get("date"))
        if item:
            listings.append(item)
    return AdapterResult(listings=listings, pages_checked=1,
                         cursor={"retrieved_at": now_utc().isoformat(), "count": len(listings)})


async def _collect_remotive(target: SourceTarget, cutoff: datetime, _profile: Any) -> AdapterResult:
    document = await _fetch_json(target.source_url)
    rows = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Remotive did not return a jobs array")
    listings = []
    for raw in rows:
        if not isinstance(raw, dict) or not _within_window(raw.get("publication_date"), cutoff):
            continue
        item = _listing(target, raw, native_id=raw.get("id"), job_url=raw.get("url"), title=raw.get("title"),
                        employer_name=raw.get("company_name"), location=raw.get("candidate_required_location"),
                        employment_type=raw.get("job_type"), description=raw.get("description"),
                        published_at=raw.get("publication_date"))
        if item:
            listings.append(item)
    return AdapterResult(listings=listings, pages_checked=1,
                         cursor={"retrieved_at": now_utc().isoformat(), "count": len(listings)})


def _role_queries(profile: Any) -> list[str]:
    # Delimiter splitting is mechanical configuration parsing, not a relevance decision.
    values = str(profile.target_roles).replace(";", "\n").replace(",", "\n").splitlines()
    return list(dict.fromkeys(value.strip() for value in values if value.strip())) or [str(profile.target_roles)]


async def _collect_himalayas(target: SourceTarget, cutoff: datetime, profile: Any) -> AdapterResult:
    listings: list[SourceListing] = []
    pages_checked = 0
    queries = _role_queries(profile)
    for query in queries:
        page = 1
        while True:
            endpoint = "https://himalayas.app/jobs/api/search?" + urlencode({"q": query, "sort": "recent", "page": page})
            document = await _fetch_json(endpoint)
            rows = document.get("jobs") if isinstance(document, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("Himalayas did not return a jobs array")
            pages_checked += 1
            published_dates = []
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                published_value = raw.get("pubDate") or raw.get("publishedAt")
                published = _published_datetime(published_value)
                if published:
                    published_dates.append(published)
                if not _within_window(published_value, cutoff):
                    continue
                item = _listing(target, raw, native_id=raw.get("guid") or raw.get("id"),
                                job_url=raw.get("applicationLink") or raw.get("guid"), title=raw.get("title"),
                                employer_name=raw.get("companyName"), location=raw.get("locationRestrictions") or raw.get("location"),
                                employment_type=raw.get("employmentType"), description=raw.get("description"),
                                published_at=raw.get("pubDate") or raw.get("publishedAt"))
                if item:
                    listings.append(item)
            total = document.get("totalCount")
            # Himalayas currently returns 20 rows per page. Count all rows
            # consumed so a short final page cannot distort the page offset.
            consumed = (page - 1) * 20 + len(rows)
            # Results are requested newest first. Once an entire dated page is
            # older than the configured window, later pages cannot contribute.
            outside_window = bool(rows) and len(published_dates) == len(rows) and all(
                published < cutoff for published in published_dates)
            if outside_window or not rows or not isinstance(total, int) or consumed >= total:
                break
            page += 1
    return AdapterResult(listings=listings, pages_checked=pages_checked,
                         cursor={"retrieved_at": now_utc().isoformat(), "queries": queries,
                                 "count": len(listings)})


async def _collect_ashby(target: SourceTarget, cutoff: datetime, _profile: Any) -> AdapterResult:
    endpoint = f"https://api.ashbyhq.com/posting-api/job-board/{quote(target.board_key or '', safe='-_')}?includeCompensation=true"
    document = await _fetch_json(endpoint)
    rows = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Ashby did not return a jobs array")
    listings = []
    open_listings = []
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("isListed") is False:
            continue
        item = _listing(target, raw, native_id=raw.get("id"), job_url=raw.get("jobUrl") or raw.get("applyUrl"),
                        title=raw.get("title"), location=raw.get("location"), employment_type=raw.get("employmentType"),
                        description=raw.get("descriptionPlain") or raw.get("descriptionHtml"),
                        published_at=raw.get("publishedAt"))
        if item:
            open_listings.append(item)
            if _within_window(raw.get("publishedAt"), cutoff):
                listings.append(item)
    return _board_result(target, listings, 1, open_listings=open_listings)


async def _collect_greenhouse(target: SourceTarget, cutoff: datetime, _profile: Any) -> AdapterResult:
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{quote(target.board_key or '', safe='-_')}/jobs?content=true"
    document = await _fetch_json(endpoint)
    rows = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Greenhouse did not return a jobs array")
    listings = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = _listing(target, raw, native_id=raw.get("id"), job_url=raw.get("absolute_url"), title=raw.get("title"),
                        location=(raw.get("location") or {}).get("name") if isinstance(raw.get("location"), dict) else raw.get("location"),
                        description=raw.get("content"), published_at=None)
        if item:
            listings.append(item)
    return _board_result(target, listings, 1)


async def _collect_lever(target: SourceTarget, cutoff: datetime, _profile: Any) -> AdapterResult:
    listings = []
    open_listings = []
    pages_checked = 0
    skip = 0
    while True:
        endpoint = f"https://api.lever.co/v0/postings/{quote(target.board_key or '', safe='-_')}?mode=json&skip={skip}&limit=100"
        rows = await _fetch_json(endpoint)
        if not isinstance(rows, list):
            raise RuntimeError("Lever did not return a JSON array")
        pages_checked += 1
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            categories = raw.get("categories") if isinstance(raw.get("categories"), dict) else {}
            item = _listing(target, raw, native_id=raw.get("id"), job_url=raw.get("hostedUrl") or raw.get("applyUrl"),
                            title=raw.get("text"), location=categories.get("location"),
                            employment_type=categories.get("commitment"), description=raw.get("descriptionPlain"),
                            published_at=raw.get("createdAt"))
            if item:
                open_listings.append(item)
                if _within_window(raw.get("createdAt"), cutoff):
                    listings.append(item)
        if len(rows) < 100:
            break
        skip += len(rows)
    return _board_result(target, listings, pages_checked, open_listings=open_listings)


async def _collect_workable(target: SourceTarget, cutoff: datetime, _profile: Any) -> AdapterResult:
    endpoint = f"https://www.workable.com/api/accounts/{quote(target.board_key or '', safe='-_')}"
    document = await _fetch_json(endpoint)
    rows = document.get("jobs") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Workable did not return a jobs array")
    listings = []
    open_listings = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        shortcode = raw.get("shortcode")
        job_url = raw.get("url") or raw.get("application_url") or (
            f"https://apply.workable.com/{target.board_key}/j/{shortcode}/" if shortcode else ""
        )
        item = _listing(target, raw, native_id=shortcode or raw.get("id"), job_url=job_url,
                        title=raw.get("title"), location=raw.get("location") or raw.get("location_str"),
                        employment_type=raw.get("employment_type"), description=raw.get("description"),
                        published_at=raw.get("published_on"))
        if item:
            open_listings.append(item)
            if _within_window(raw.get("published_on"), cutoff):
                listings.append(item)
    return _board_result(target, listings, 1, open_listings=open_listings)


def _board_result(target: SourceTarget, listings: list[SourceListing], pages_checked: int,
                  *, open_listings: list[SourceListing] | None = None) -> AdapterResult:
    current = {item.native_id: {"url": item.job_url, "sha256": item.raw_fingerprint}
               for item in (open_listings if open_listings is not None else listings)}
    previous = target.cursor.get("open_jobs") if isinstance(target.cursor, dict) else {}
    previous = previous if isinstance(previous, dict) else {}
    closed = sorted(set(previous) - set(current))
    changed = sum(previous.get(key, {}).get("sha256") != value["sha256"] for key, value in current.items()
                  if key in previous)
    return AdapterResult(
        listings=listings,
        pages_checked=pages_checked,
        cursor={"open_jobs": current, "retrieved_at": now_utc().isoformat()},
        details={"closed_native_ids": closed, "changed_count": changed, "closed_count": len(closed)},
    )


COLLECTORS = {
    "remoteok": _collect_remoteok,
    "remotive": _collect_remotive,
    "himalayas": _collect_himalayas,
    "ashby": _collect_ashby,
    "greenhouse": _collect_greenhouse,
    "lever": _collect_lever,
    "workable": _collect_workable,
}


async def initialize_coverage(run_id: str, catalog: dict) -> None:
    await ensure_tables()
    now = now_utc()
    async with AsyncSessionLocal() as session:
        for item in catalog.get("items", []):
            source_key = f"catalog:{item['id']}"
            adapter = "structured" if item.get("id") in DIRECT_SOURCE_IDS else "web_search"
            await session.execute(insert(JobSearchSourceRun).values(
                id=uuid4().hex, run_id=run_id, source_key=source_key,
                source_name=item.get("name") or item["id"], source_url=item["url"],
                adapter_type=adapter, status="pending", updated_at=now,
            ).on_conflict_do_nothing(index_elements=["run_id", "source_key"]))
        await session.commit()


async def _board_targets() -> list[SourceTarget]:
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(JobSearchEmployerBoard).where(JobSearchEmployerBoard.active.is_(True))
                                      .order_by(JobSearchEmployerBoard.provider, JobSearchEmployerBoard.board_key))).all()
    return [SourceTarget(
        source_key=f"board:{row.id}", source_name=f"{row.employer_name} · {row.provider}",
        source_url=row.board_url, adapter_type="ats", provider=row.provider,
        board_id=row.id, board_key=row.board_key, employer_name=row.employer_name,
        employer_domain=row.employer_domain, employer_url=row.employer_url,
        firm_id=row.firm_id, cursor=row.cursor or {},
    ) for row in rows]


def _catalog_target(item: dict) -> SourceTarget:
    source_id = item["id"]
    url = item["url"]
    if source_id == "remotive":
        url = "https://remotive.com/api/remote-jobs"
    if source_id == "himalayas":
        url = "https://himalayas.app/jobs/api"
    return SourceTarget(source_key=f"catalog:{source_id}", source_name=item["name"], source_url=url,
                        adapter_type="structured", provider=source_id)


async def _start_source(run_id: str, target: SourceTarget) -> None:
    now = now_utc()
    async with AsyncSessionLocal() as session:
        row = await session.scalar(select(JobSearchSourceRun).where(
            JobSearchSourceRun.run_id == run_id, JobSearchSourceRun.source_key == target.source_key))
        if row is None:
            row = JobSearchSourceRun(id=uuid4().hex, run_id=run_id, source_key=target.source_key,
                source_name=target.source_name, source_url=target.source_url, adapter_type=target.adapter_type,
                status="running", cursor_before=target.cursor, started_at=now, updated_at=now)
            session.add(row)
        else:
            row.status = "running"; row.started_at = now; row.updated_at = now; row.cursor_before = target.cursor
            row.error = None
        await session.commit()

async def _finish_source(run_id: str, target: SourceTarget, result: AdapterResult | None,
                         error: Exception | None) -> None:
    now = now_utc()
    async with AsyncSessionLocal() as session:
        row = await session.scalar(select(JobSearchSourceRun).where(
            JobSearchSourceRun.run_id == run_id, JobSearchSourceRun.source_key == target.source_key))
        if row is None:
            return
        row.completed_at = now; row.updated_at = now
        if error is not None:
            row.status = "failed"; row.error = str(error)[:4000]
        else:
            row.status = "completed"; row.error = None
            row.pages_checked = result.pages_checked
            row.listings_seen = len(result.listings)
            row.cursor_after = result.cursor
            row.details = result.details
            row.closed_count = int(result.details.get("closed_count") or 0)
        if target.board_id:
            board = await session.get(JobSearchEmployerBoard, target.board_id, with_for_update=True)
            if board:
                board.last_sync_at = now; board.updated_at = now
                if error is not None:
                    board.last_error = str(error)[:4000]
                else:
                    board.cursor = result.cursor; board.last_success_at = now; board.last_error = None
        await session.commit()
    if result and target.board_id and result.details.get("closed_native_ids"):
        await _mark_closed_jobs(target, result.details["closed_native_ids"])


async def _mark_closed_jobs(target: SourceTarget, closed_native_ids: list[str]) -> None:
    if not target.firm_id or not closed_native_ids:
        return
    previous = target.cursor.get("open_jobs") if isinstance(target.cursor, dict) else {}
    urls = {_url_identity(previous[key]["url"]) for key in closed_native_ids
            if isinstance(previous.get(key), dict) and previous[key].get("url")}
    if not urls:
        return
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, target.firm_id, with_for_update=True)
        if not firm:
            return
        data = dict(firm.research_data or {})
        jobs = dict(data.get("job_postings") or {})
        postings = [dict(item) for item in jobs.get("postings") or []]
        changed = False
        for posting in postings:
            if _url_identity(str(posting.get("source_url") or "")) in urls and posting.get("status") != "closed":
                posting["status"] = "closed"
                posting["closed_reason"] = "Removed from the authoritative ATS board."
                posting["last_checked_at"] = now_utc().isoformat()
                changed = True
        if changed:
            jobs["postings"] = postings
            jobs["has_recent_openings"] = any(item.get("status") != "closed" for item in postings)
            data["job_postings"] = jobs
            firm.research_data = data
            firm.updated_at = now_utc()
            await session.commit()


async def collect_structured_sources(run_id: str, profile: Any, catalog: dict) -> tuple[list[SourceListing], dict]:
    """Exhaust supported structured sources and retain an auditable coverage row per target."""
    await initialize_coverage(run_id, catalog)
    items = {item["id"]: item for item in catalog.get("items", [])}
    targets = [_catalog_target(items[source_id]) for source_id in DIRECT_SOURCE_IDS if source_id in items]
    targets.extend(await _board_targets())
    cutoff = now_utc() - timedelta(days=profile.posted_within_days)
    semaphore = asyncio.Semaphore(int(os.getenv("JOB_SEARCH_ADAPTER_CONCURRENCY", "4")))
    source_timeout_s = max(30, int(os.getenv("JOB_SEARCH_ADAPTER_TIMEOUT_S", "180")))

    async def collect(target: SourceTarget):
        async with semaphore:
            await _start_source(run_id, target)
            try:
                result = await asyncio.wait_for(
                    COLLECTORS[target.provider](target, cutoff, profile),
                    timeout=source_timeout_s,
                )
                await _finish_source(run_id, target, result, None)
                return result.listings, None
            except asyncio.TimeoutError:
                exc = RuntimeError(
                    f"Source collection exceeded the {source_timeout_s}s per-source timeout")
                await _finish_source(run_id, target, None, exc)
                return [], {"source_key": target.source_key, "source_url": target.source_url,
                            "phase": "source_adapter", "error": str(exc)}
            except Exception as exc:
                await _finish_source(run_id, target, None, exc)
                return [], {"source_key": target.source_key, "source_url": target.source_url,
                            "phase": "source_adapter", "error": str(exc)[:1000]}

    outcomes = await asyncio.gather(*(collect(target) for target in targets))
    listings: list[SourceListing] = []
    errors = []
    seen: set[str] = set()
    for rows, error in outcomes:
        if error:
            errors.append(error)
        for listing in rows:
            identity = _url_identity(listing.job_url)
            if identity in seen:
                continue
            seen.add(identity)
            listings.append(listing)
    return listings, {"targets": len(targets), "listings_seen": len(listings), "errors": errors}


async def record_shortlist_counts(run_id: str, selected: Iterable[SourceListing]) -> None:
    counts: dict[str, int] = {}
    for item in selected:
        counts[item.source_key] = counts.get(item.source_key, 0) + 1
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(JobSearchSourceRun).where(JobSearchSourceRun.run_id == run_id))).all()
        for row in rows:
            row.candidates_emitted = counts.get(row.source_key, 0)
            row.updated_at = now_utc()
        await session.commit()


async def finalize_web_coverage(run_id: str, source_checks: list[dict]) -> None:
    """Persist researcher-reported fallback checks without presenting them as adapter fetches."""
    by_url = {_url_identity(str(item.get("url") or "")): item for item in source_checks if item.get("url")}
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(JobSearchSourceRun).where(JobSearchSourceRun.run_id == run_id))).all()
        now = now_utc()
        for row in rows:
            if row.adapter_type != "web_search" or row.status not in {"pending", "running"}:
                continue
            report = by_url.get(_url_identity(row.source_url))
            if report:
                status = str(report.get("status") or "not_checked")
                row.status = "completed" if status == "searched" else "unavailable" if status == "unavailable" else "not_checked"
                row.details = {"researcher_report": str(report.get("reason") or "")[:2000]}
            else:
                row.status = "not_checked"
                row.details = {"researcher_report": "No source-specific inspection was reported for this run."}
            row.completed_at = now; row.updated_at = now
        await session.commit()


def _coverage_item(row: JobSearchSourceRun) -> dict:
    return {
        "id": row.id, "source_key": row.source_key, "name": row.source_name,
        "url": row.source_url, "adapter_type": row.adapter_type, "status": row.status,
        "pages_checked": row.pages_checked, "listings_seen": row.listings_seen,
        "candidates_emitted": row.candidates_emitted, "closed_count": row.closed_count,
        "retry_count": row.retry_count, "details": row.details or {}, "error": row.error,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "updated_at": row.updated_at.isoformat(),
    }


async def coverage(run_id: str) -> dict:
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(JobSearchSourceRun).where(JobSearchSourceRun.run_id == run_id)
                                      .order_by(JobSearchSourceRun.source_name))).all()
    items = [_coverage_item(row) for row in rows]
    statuses = {status: sum(item["status"] == status for item in items)
                for status in ("pending", "running", "completed", "unavailable", "not_checked", "failed")}
    return {"run_id": run_id, "total": len(items), "statuses": statuses,
            "listings_seen": sum(item["listings_seen"] for item in items),
            "candidates_emitted": sum(item["candidates_emitted"] for item in items),
            "closed": sum(item["closed_count"] for item in items), "items": items}


def _board_reference(source_url: str) -> tuple[str, str, str] | None:
    parts = urlsplit(source_url)
    host = (parts.hostname or "").lower()
    path = [part for part in parts.path.split("/") if part]
    if host == "jobs.ashbyhq.com" and len(path) >= 2:
        return "ashby", path[0], f"https://jobs.ashbyhq.com/{path[0]}"
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and path:
        return "greenhouse", path[0], f"https://boards.greenhouse.io/{path[0]}"
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and path:
        return "lever", path[0], f"https://jobs.lever.co/{path[0]}"
    if host == "apply.workable.com" and path:
        return "workable", path[0], f"https://apply.workable.com/{path[0]}"
    return None


async def register_candidate_board(candidate: Any, firm_id: str | None = None) -> dict | None:
    """Remember a mechanically identified ATS tenant after employer identity was verified."""
    reference = _board_reference(str(candidate.source_url))
    if not reference:
        return None
    provider, board_key, board_url = reference
    now = now_utc()
    values = {
        "id": uuid4().hex, "provider": provider, "board_key": board_key, "board_url": board_url,
        "employer_name": candidate.firm_name, "employer_domain": candidate.canonical_domain,
        "employer_url": str(candidate.employer_evidence_url), "firm_id": firm_id,
        "discovered_from": str(candidate.source_url), "active": True, "cursor": {},
        "metadata_json": {}, "created_at": now, "updated_at": now,
    }
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        await session.execute(insert(JobSearchEmployerBoard).values(**values).on_conflict_do_update(
            index_elements=["provider", "board_key"], set_={
                "board_url": board_url, "employer_name": candidate.firm_name,
                "employer_domain": candidate.canonical_domain, "employer_url": str(candidate.employer_evidence_url),
                "firm_id": firm_id, "discovered_from": str(candidate.source_url), "active": True,
                "updated_at": now,
            }))
        await session.commit()
        row = await session.scalar(select(JobSearchEmployerBoard).where(
            JobSearchEmployerBoard.provider == provider, JobSearchEmployerBoard.board_key == board_key))
        return board_view(row)


def board_view(row: JobSearchEmployerBoard) -> dict:
    return {
        "id": row.id, "provider": row.provider, "board_key": row.board_key,
        "board_url": row.board_url, "employer_name": row.employer_name,
        "employer_domain": row.employer_domain, "employer_url": row.employer_url,
        "firm_id": row.firm_id, "active": row.active, "discovered_from": row.discovered_from,
        "open_jobs": len((row.cursor or {}).get("open_jobs") or {}),
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_error": row.last_error,
    }


async def list_boards() -> dict:
    await ensure_tables()
    async with AsyncSessionLocal() as session:
        rows = (await session.scalars(select(JobSearchEmployerBoard)
                                      .order_by(JobSearchEmployerBoard.employer_name))).all()
    return {"items": [board_view(row) for row in rows], "total": len(rows)}


async def discover_existing_boards() -> dict:
    """One-time, idempotent registry bootstrap from already verified stored jobs."""
    await ensure_tables()
    found = 0
    async with AsyncSessionLocal() as session:
        firms = (await session.scalars(select(PifFirmRow).where(PifFirmRow.research_data.is_not(None)))).all()
    for firm in firms:
        jobs = ((firm.research_data or {}).get("job_postings") or {}).get("postings") or []
        domain = str(firm.canonical_website or firm.website or "").strip()
        if not domain:
            continue
        if "://" in domain:
            domain = urlsplit(domain).hostname or ""
        employer_url = str(firm.canonical_website or firm.website or "")
        if employer_url and "://" not in employer_url:
            employer_url = "https://" + employer_url
        for posting in jobs:
            source_url = str(posting.get("source_url") or "")
            reference = _board_reference(source_url)
            if not reference:
                continue
            candidate = type("StoredCandidate", (), {
                "source_url": source_url, "firm_name": firm.firm_name or domain,
                "canonical_domain": domain, "employer_evidence_url": employer_url,
            })()
            if await register_candidate_board(candidate, firm.id):
                found += 1
    boards = await list_boards()
    return {"examined_firms": len(firms), "board_references_seen": found, **boards}
