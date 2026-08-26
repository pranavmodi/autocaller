"""Possible OS firm-research orchestration.

Production entry points delegate to the durable local enrichment queue. The
legacy client remains only for compatibility with historical tests and data.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from sqlalchemy import desc, func, or_, select

from app.db import AsyncSessionLocal
from app.db.models import (
    FirmAliasRow,
    FirmContactRow,
    FrontFirmActivityRow,
    PifEnrichmentTaskRow,
    PifFirmRow,
    ResearchTaskRow,
)
from app.services.front_sync import normalize_domain
from app.services.persona_mapper import map_personas


PIF_BASE = os.getenv(
    "PIF_BASE",
    os.getenv("PIFSTATS_BASE_URL", "https://emailprocessing.mediflow360.com/api/v1/pif-info"),
).rstrip("/")

TASK_KINDS = ("research", "research_staff", "analyze_behavior")
KIND_ENDPOINTS = {
    "research": "research",
    "research_staff": "research-staff",
    "analyze_behavior": "analyze-behavior",
}
TERMINAL_SUCCESS = {"completed", "complete", "done", "success", "succeeded"}
TERMINAL_FAILURE = {"failed", "failure", "error", "errored", "revoked", "cancelled", "canceled"}
OPEN_STATUSES = {"queued", "pending", "running", "started", "in_progress", "processing"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any, limit: int | None = None) -> str:
    text = str(value or "").strip()
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _norm_email(value: Any) -> str | None:
    email = _clean(value).lower()
    return email or None


def _first_name(full_name: str) -> str:
    parts = _clean(full_name).split()
    return parts[0] if parts else ""


def _normalize_phone(raw: Any) -> str | None:
    digits = "".join(c for c in _clean(raw) if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if 10 <= len(digits) <= 15:
        return f"+{digits}"
    return _clean(raw, 32) or None


def _status_key(status: Any) -> str:
    return _clean(status).lower() or "unknown"


def _is_success(status: Any) -> bool:
    return _status_key(status) in TERMINAL_SUCCESS


def _is_failure(status: Any) -> bool:
    return _status_key(status) in TERMINAL_FAILURE


def _auth_headers() -> dict[str, str]:
    header_name = os.getenv("PIFSTATS_AUTH_HEADER", "").strip()
    token = os.getenv("PIFSTATS_AUTH_TOKEN", "").strip() or os.getenv("PIF_AUTH_TOKEN", "").strip()
    api_key = os.getenv("PIFSTATS_API_KEY", "").strip()
    if header_name and (token or api_key):
        return {header_name: token or api_key}
    if token:
        return {"Authorization": f"Bearer {token}"}
    if api_key:
        return {"X-API-Key": api_key}
    return {}


@dataclass
class PifStatsBudget:
    max_task_posts: int = 30
    post_min_interval_seconds: float = 2.0
    get_min_interval_seconds: float = 0.5
    task_posts_made: int = 0
    get_calls_made: int = 0
    rate_limited_count: int = 0
    _last_post_monotonic: float = 0.0
    _last_get_monotonic: float = 0.0

    @property
    def remaining_task_posts(self) -> int:
        return max(0, self.max_task_posts - self.task_posts_made)

    def exhausted(self) -> bool:
        return self.remaining_task_posts <= 0

    async def before_post(self) -> bool:
        if self.exhausted():
            return False
        now = time.monotonic()
        delay = self.post_min_interval_seconds - (now - self._last_post_monotonic)
        if self._last_post_monotonic and delay > 0:
            await asyncio.sleep(delay)
        self.task_posts_made += 1
        self._last_post_monotonic = time.monotonic()
        return True

    async def before_get(self) -> None:
        now = time.monotonic()
        delay = self.get_min_interval_seconds - (now - self._last_get_monotonic)
        if self._last_get_monotonic and delay > 0:
            await asyncio.sleep(delay)
        self.get_calls_made += 1
        self._last_get_monotonic = time.monotonic()


class PifStatsClient:
    def __init__(
        self,
        *,
        budget: PifStatsBudget | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ):
        self.base = (base_url or PIF_BASE).rstrip("/")
        self.budget = budget or PifStatsBudget()
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Accept": "application/json", **_auth_headers()},
        )

    async def __aenter__(self) -> "PifStatsClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    async def post_task(self, pif_id: str, kind: str) -> dict[str, Any] | None:
        if kind not in KIND_ENDPOINTS:
            raise ValueError(f"unknown_research_kind:{kind}")
        if not await self.budget.before_post():
            return None
        resp = await self._client.post(f"{self.base}/{pif_id}/{KIND_ENDPOINTS[kind]}")
        for _retry in range(2):
            if resp.status_code != 429:
                break
            self.budget.rate_limited_count += 1
            try:
                retry_after = float(resp.headers.get("Retry-After") or 5.0)
            except ValueError:
                retry_after = 5.0
            self.budget.post_min_interval_seconds = min(self.budget.post_min_interval_seconds * 2, 30.0)
            await asyncio.sleep(min(max(retry_after, 1.0), 90.0))
            if not await self.budget.before_post():
                return None
            resp = await self._client.post(f"{self.base}/{pif_id}/{KIND_ENDPOINTS[kind]}")
        if resp.status_code in (401, 403) and not _auth_headers():
            raise RuntimeError("pifstats_auth_required_set_env")
        resp.raise_for_status()
        return resp.json()

    async def get_status(self, task_id: str) -> dict[str, Any]:
        await self.budget.before_get()
        resp = await self._client.get(f"{self.base}/research-status/{task_id}")
        if resp.status_code in (401, 403) and not _auth_headers():
            raise RuntimeError("pifstats_auth_required_set_env")
        resp.raise_for_status()
        return resp.json()

    async def get_firm(self, pif_id: str) -> dict[str, Any]:
        await self.budget.before_get()
        resp = await self._client.get(f"{self.base}/{pif_id}")
        if resp.status_code in (401, 403) and not _auth_headers():
            raise RuntimeError("pifstats_auth_required_set_env")
        resp.raise_for_status()
        return resp.json()


def normalize_kinds(kinds: Iterable[str] | None, *, staff: bool = True, behavior: bool = True) -> list[str]:
    if kinds is None:
        out = ["research"]
        if staff:
            out.append("research_staff")
        if behavior:
            out.append("analyze_behavior")
        return out
    aliases = {
        "firm": "research",
        "research": "research",
        "staff": "research_staff",
        "research_staff": "research_staff",
        "research-staff": "research_staff",
        "behavior": "analyze_behavior",
        "analyze_behavior": "analyze_behavior",
        "analyze-behavior": "analyze_behavior",
    }
    out: list[str] = []
    for raw in kinds:
        key = aliases.get(_clean(raw).lower())
        if not key:
            raise ValueError(f"unknown_research_kind:{raw}")
        if key not in out:
            out.append(key)
    return out or ["research"]


async def _has_existing_task(session, pif_id: str, kind: str) -> ResearchTaskRow | None:
    return (await session.execute(
        select(ResearchTaskRow)
        .where(ResearchTaskRow.pif_id == pif_id, ResearchTaskRow.kind == kind)
        .where(~ResearchTaskRow.status.in_(TERMINAL_FAILURE))
        .order_by(desc(ResearchTaskRow.requested_at))
        .limit(1)
    )).scalar_one_or_none()


async def queue_firm_research(
    pif_id: str,
    *,
    staff: bool = True,
    behavior: bool = True,
    kinds: Iterable[str] | None = None,
    client: PifStatsClient | None = None,
) -> dict[str, Any]:
    if client is None:
        from app.services.pif_local_enrichment import start_local_firm_enrichment

        result = await start_local_firm_enrichment(pif_id)
        return {
            "pif_id": pif_id,
            "queued": [{
                "kind": "local_enrichment",
                "task_id": result["task_id"],
                "status": result["status"],
            }],
            "skipped": [],
            "budget": {"task_posts_made": 0, "remaining_task_posts": None, "rate_limited": 0},
            "owner": "possibleos",
        }
    requested_kinds = normalize_kinds(kinds, staff=staff, behavior=behavior)
    own_client = client is None
    pif_client = client or PifStatsClient()
    queued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        if own_client:
            await pif_client.__aenter__()
        async with AsyncSessionLocal() as session:
            for kind in requested_kinds:
                existing = await _has_existing_task(session, pif_id, kind)
                if existing:
                    skipped.append({
                        "kind": kind,
                        "task_id": existing.task_id,
                        "status": existing.status,
                        "reason": "existing_task",
                    })
                    continue
                data = await pif_client.post_task(pif_id, kind)
                if data is None:
                    skipped.append({"kind": kind, "reason": "post_budget_exhausted"})
                    break
                task_id = _clean(data.get("task_id"), 128)
                if not task_id:
                    task_id = f"local-{uuid.uuid4().hex}"
                status = _status_key(data.get("status") or "queued")
                row = ResearchTaskRow(
                    task_id=task_id,
                    pif_id=_clean(data.get("pif_id") or pif_id, 64),
                    kind=kind,
                    status=status,
                    requested_at=_utcnow(),
                    result_summary={
                        "firm_name": data.get("firm_name"),
                        "message": data.get("message"),
                    },
                )
                session.add(row)
                queued.append({"kind": kind, "task_id": task_id, "status": status})
            await session.commit()
    finally:
        if own_client:
            await pif_client.__aexit__(None, None, None)
    return {
        "pif_id": pif_id,
        "queued": queued,
        "skipped": skipped,
        "budget": {
            "task_posts_made": pif_client.budget.task_posts_made,
            "remaining_task_posts": pif_client.budget.remaining_task_posts,
            "rate_limited": pif_client.budget.rate_limited_count,
        },
    }


def _person_iter(firm: dict[str, Any]) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    for source_key in ("leadership", "staff"):
        for person in firm.get(source_key) or []:
            if isinstance(person, dict):
                people.append({**person, "_research_group": source_key})
    return people


async def _upsert_research_contacts(session, pif_id: str, firm: dict[str, Any]) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    for person in _person_iter(firm):
        full_name = _clean(person.get("name"), 255)
        email = _norm_email(person.get("email"))
        if not full_name and not email:
            counts["skipped"] += 1
            continue
        title = _clean(person.get("title") or person.get("role"), 255) or None
        phone = _normalize_phone(person.get("phone"))
        linkedin = _clean(person.get("linkedin_url") or person.get("linkedin"), 512) or None
        if email:
            existing = (await session.execute(
                select(FirmContactRow).where(FirmContactRow.pif_id == pif_id, FirmContactRow.email == email)
            )).scalar_one_or_none()
        else:
            existing = (await session.execute(
                select(FirmContactRow).where(
                    FirmContactRow.pif_id == pif_id,
                    FirmContactRow.full_name == full_name,
                    FirmContactRow.email.is_(None),
                )
            )).scalar_one_or_none()
        if existing:
            if full_name and not existing.full_name:
                existing.full_name = full_name
            if full_name and not existing.first_name:
                existing.first_name = _first_name(full_name)
            if email and not existing.email:
                existing.email = email
            if phone:
                existing.phone = phone
            if linkedin:
                existing.linkedin_url = linkedin
            if title:
                existing.research_title = title
                if not existing.title or existing.source == "pif_research":
                    existing.title = title
            if existing.source in ("manual", "", None):
                existing.source = "pif_research"
            counts["updated"] += 1
            continue
        session.add(FirmContactRow(
            id=uuid.uuid4().hex,
            pif_id=pif_id,
            full_name=full_name,
            first_name=_first_name(full_name),
            email=email,
            phone=phone,
            title=title,
            research_title=title,
            linkedin_url=linkedin,
            source="pif_research",
        ))
        counts["inserted"] += 1
    return counts


async def _sync_behavior(session, pif_id: str, firm: dict[str, Any]) -> int:
    behavior = firm.get("behavioral_data")
    if not isinstance(behavior, dict) or not behavior:
        return 0
    rows = (await session.execute(
        select(FrontFirmActivityRow).where(FrontFirmActivityRow.pif_id == pif_id)
    )).scalars().all()
    for row in rows:
        row.behavioral_json = behavior
    return len(rows)


def _result_summary(firm: dict[str, Any], contact_counts: dict[str, int], behavior_rows: int) -> dict[str, Any]:
    return {
        "firm_name": firm.get("firm_name"),
        "pif_id": firm.get("id"),
        "research_status": firm.get("research_status"),
        "staff_research_status": firm.get("staff_research_status"),
        "leadership_count": len(firm.get("leadership") or []),
        "staff_count": len(firm.get("staff") or []),
        "behavioral_data": bool(firm.get("behavioral_data")),
        "behavior_rows_updated": behavior_rows,
        "contacts": contact_counts,
    }


def _firm_payload_indicates_complete(kind: str, firm: dict[str, Any]) -> bool:
    if kind == "research":
        return _status_key(firm.get("research_status")) in TERMINAL_SUCCESS or bool(firm.get("last_researched_at"))
    if kind == "research_staff":
        return _status_key(firm.get("staff_research_status")) in TERMINAL_SUCCESS or bool(firm.get("staff"))
    if kind == "analyze_behavior":
        return bool(firm.get("behavioral_data"))
    return False


async def poll_research_tasks(
    *,
    client: PifStatsClient | None = None,
    task_ids: Iterable[str] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if client is None:
        task_id_filter = {str(value) for value in (task_ids or []) if value}
        async with AsyncSessionLocal() as session:
            stmt = select(PifEnrichmentTaskRow).order_by(PifEnrichmentTaskRow.requested_at.asc())
            if task_id_filter:
                stmt = stmt.where(PifEnrichmentTaskRow.task_id.in_(task_id_filter))
            else:
                stmt = stmt.where(PifEnrichmentTaskRow.status.in_({"queued", "in_progress"}))
            rows = (await session.execute(stmt.limit(max(1, min(limit, 500))))).scalars().all()
        tasks = [{
            "task_id": row.task_id,
            "pif_id": row.pif_id,
            "kind": "local_enrichment",
            "status": row.status,
            "summary": row.result_summary or {},
        } for row in rows]
        return {
            "polled": len(tasks),
            "completed": sum(row["status"] == "completed" for row in tasks),
            "failed": sum(row["status"] == "failed" for row in tasks),
            "open": sum(row["status"] in {"queued", "in_progress"} for row in tasks),
            "tasks": tasks,
            "persona_mapping": await map_personas(),
            "budget": {"task_posts_made": 0, "get_calls_made": 0, "remaining_task_posts": None, "rate_limited": 0},
            "owner": "possibleos",
        }
    own_client = client is None
    pif_client = client or PifStatsClient()
    task_id_filter = {str(t) for t in (task_ids or []) if t}
    updated: list[dict[str, Any]] = []
    completed = failed = open_count = 0
    try:
        if own_client:
            await pif_client.__aenter__()
        async with AsyncSessionLocal() as session:
            stmt = (
                select(ResearchTaskRow)
                .where(~ResearchTaskRow.status.in_(TERMINAL_SUCCESS | TERMINAL_FAILURE))
                .order_by(ResearchTaskRow.requested_at.asc())
                .limit(max(1, min(limit, 500)))
            )
            if task_id_filter:
                stmt = stmt.where(ResearchTaskRow.task_id.in_(task_id_filter))
            tasks = (await session.execute(stmt)).scalars().all()
            for task in tasks:
                status_data = await pif_client.get_status(task.task_id)
                status = _status_key(status_data.get("status"))
                firm: dict[str, Any] | None = None
                if not (_is_success(status) or _is_failure(status)):
                    firm = await pif_client.get_firm(task.pif_id)
                    if _firm_payload_indicates_complete(task.kind, firm):
                        status = "completed"
                task.status = status
                entry: dict[str, Any] = {
                    "task_id": task.task_id,
                    "pif_id": task.pif_id,
                    "kind": task.kind,
                    "status": status,
                }
                if _is_success(status):
                    firm = firm or await pif_client.get_firm(task.pif_id)
                    contact_counts = await _upsert_research_contacts(session, task.pif_id, firm)
                    behavior_rows = await _sync_behavior(session, task.pif_id, firm)
                    task.completed_at = _utcnow()
                    task.result_summary = _result_summary(firm, contact_counts, behavior_rows)
                    entry["summary"] = task.result_summary
                    completed += 1
                elif _is_failure(status):
                    task.completed_at = _utcnow()
                    task.result_summary = {
                        "message": status_data.get("message"),
                        "firm_name": status_data.get("firm_name"),
                    }
                    failed += 1
                else:
                    open_count += 1
                updated.append(entry)
            await session.commit()
    finally:
        if own_client:
            await pif_client.__aexit__(None, None, None)
    persona_result = await map_personas()
    return {
        "polled": len(updated),
        "completed": completed,
        "failed": failed,
        "open": open_count,
        "tasks": updated,
        "persona_mapping": persona_result,
        "budget": {
            "task_posts_made": pif_client.budget.task_posts_made,
            "get_calls_made": pif_client.budget.get_calls_made,
            "remaining_task_posts": pif_client.budget.remaining_task_posts,
            "rate_limited": pif_client.budget.rate_limited_count,
        },
    }


async def _has_titled_research_contact(session, pif_id: str) -> bool:
    return bool((await session.execute(
        select(FirmContactRow.id)
        .where(FirmContactRow.pif_id == pif_id)
        .where(or_(FirmContactRow.research_title.isnot(None), FirmContactRow.title.isnot(None)))
        .limit(1)
    )).scalar_one_or_none())


async def _needs_kind(session, activity: FrontFirmActivityRow, kind: str) -> bool:
    if not activity.pif_id:
        return False
    completed_task = (await session.execute(
        select(ResearchTaskRow.task_id)
        .where(
            ResearchTaskRow.pif_id == activity.pif_id,
            ResearchTaskRow.kind == kind,
            ResearchTaskRow.status.in_(TERMINAL_SUCCESS),
        )
        .limit(1)
    )).scalar_one_or_none()
    if completed_task:
        return False
    if kind == "research" and await _has_titled_research_contact(session, activity.pif_id):
        return False
    if kind == "analyze_behavior" and activity.behavioral_json:
        return False
    return True


async def orchestrate_warm_research(
    *,
    top_n: int = 50,
    kinds: Iterable[str] | None = None,
    timeout_seconds: int = 1800,
    poll_interval_seconds: float = 15.0,
    client: PifStatsClient | None = None,
) -> dict[str, Any]:
    if client is None:
        async with AsyncSessionLocal() as session:
            pif_ids = [str(value) for value in (await session.execute(
                select(FrontFirmActivityRow.pif_id)
                .where(FrontFirmActivityRow.pif_id.isnot(None))
                .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
                .limit(max(1, min(top_n, 500)))
            )).scalars().all() if value]
        queue_results = [await queue_firm_research(pif_id) for pif_id in dict.fromkeys(pif_ids)]
        task_ids = [row["task_id"] for result in queue_results for row in result.get("queued") or []]
        poll_result: dict[str, Any] = {"polled": 0, "completed": 0, "failed": 0, "open": 0, "tasks": []}
        deadline = time.monotonic() + max(1, timeout_seconds)
        while task_ids and time.monotonic() < deadline:
            poll_result = await poll_research_tasks(task_ids=task_ids, limit=len(task_ids))
            if not poll_result.get("open"):
                break
            await asyncio.sleep(max(0.1, poll_interval_seconds))
        return {
            "top_n": top_n,
            "requested_kinds": ["local_enrichment"],
            "queued_task_ids": task_ids,
            "queue_results": queue_results,
            "skipped_firms": max(0, top_n - len(queue_results)),
            "poll": poll_result,
            "timed_out": bool(task_ids) and bool(poll_result.get("open")),
            "budget": {"task_posts_made": 0, "remaining_task_posts": None, "rate_limited": 0},
            "owner": "possibleos",
        }
    requested_kinds = normalize_kinds(kinds)
    own_client = client is None
    pif_client = client or PifStatsClient()
    queued_task_ids: list[str] = []
    queue_results: list[dict[str, Any]] = []
    skipped_firms = 0
    try:
        if own_client:
            await pif_client.__aenter__()
        async with AsyncSessionLocal() as session:
            activities = (await session.execute(
                select(FrontFirmActivityRow)
                .where(FrontFirmActivityRow.pif_id.isnot(None))
                .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
                .limit(max(1, min(top_n, 500)))
            )).scalars().all()
            candidates: list[tuple[str, list[str]]] = []
            for activity in activities:
                needed = [kind for kind in requested_kinds if await _needs_kind(session, activity, kind)]
                if needed and activity.pif_id:
                    candidates.append((activity.pif_id, needed))
                else:
                    skipped_firms += 1
        for pif_id, needed in candidates:
            if pif_client.budget.exhausted():
                break
            result = await queue_firm_research(pif_id, kinds=needed, client=pif_client)
            queued_task_ids.extend([row["task_id"] for row in result.get("queued") or []])
            queue_results.append(result)
    finally:
        if own_client:
            await pif_client.__aexit__(None, None, None)

    poll_result: dict[str, Any] = {"polled": 0, "completed": 0, "failed": 0, "open": 0, "tasks": []}
    deadline = time.monotonic() + max(1, timeout_seconds)
    if queued_task_ids:
        while time.monotonic() < deadline:
            poll_result = await poll_research_tasks(task_ids=queued_task_ids, limit=len(queued_task_ids))
            open_task_ids = [
                task["task_id"] for task in poll_result.get("tasks") or []
                if not (_is_success(task.get("status")) or _is_failure(task.get("status")))
            ]
            if not open_task_ids:
                break
            await asyncio.sleep(max(0.1, poll_interval_seconds))

    return {
        "top_n": top_n,
        "requested_kinds": requested_kinds,
        "queued_task_ids": queued_task_ids,
        "queue_results": queue_results,
        "skipped_firms": skipped_firms,
        "poll": poll_result,
        "timed_out": bool(queued_task_ids) and poll_result.get("open", 0) > 0,
        "budget": {
            "task_posts_made": pif_client.budget.task_posts_made,
            "remaining_task_posts": pif_client.budget.remaining_task_posts,
            "rate_limited": pif_client.budget.rate_limited_count,
        },
    }


async def resolve_domain_or_pif(value: str) -> str:
    raw = _clean(value)
    domain = normalize_domain(raw)
    async with AsyncSessionLocal() as session:
        direct = await session.get(PifFirmRow, raw)
        if direct:
            return str(direct.id)
        if domain:
            alias = await session.get(FirmAliasRow, {"alias_type": "domain", "alias_value": domain})
            if alias:
                return str(alias.firm_id)
            firm_id = (await session.execute(
                select(PifFirmRow.id)
                .where(or_(PifFirmRow.canonical_website == domain, PifFirmRow.website == domain))
                .limit(1)
            )).scalar_one_or_none()
            if firm_id:
                return str(firm_id)
            pif_id = (await session.execute(
                select(FrontFirmActivityRow.pif_id)
                .where(FrontFirmActivityRow.domain == domain)
                .where(FrontFirmActivityRow.pif_id.isnot(None))
                .limit(1)
            )).scalar_one_or_none()
            if pif_id:
                return str(pif_id)
        pif_id = (await session.execute(
            select(FrontFirmActivityRow.pif_id)
            .where(FrontFirmActivityRow.pif_id == raw)
            .limit(1)
        )).scalar_one_or_none()
        if pif_id:
            return str(pif_id)
    return raw


async def research_coverage() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(select(func.count(PifFirmRow.id)))).scalar_one() or 0)
        researched = int((await session.execute(
            select(func.count(PifFirmRow.id)).where(PifFirmRow.research_status == "completed")
        )).scalar_one() or 0)
        staff = int((await session.execute(
            select(func.count(PifFirmRow.id)).where(PifFirmRow.staff_research_status == "completed")
        )).scalar_one() or 0)
        open_tasks = (await session.execute(
            select(PifEnrichmentTaskRow)
            .where(PifEnrichmentTaskRow.status.in_({"queued", "in_progress"}))
            .order_by(desc(PifEnrichmentTaskRow.requested_at))
            .limit(100)
        )).scalars().all()
        task_counts = (await session.execute(
            select(PifEnrichmentTaskRow.status, func.count(PifEnrichmentTaskRow.task_id))
            .group_by(PifEnrichmentTaskRow.status)
        )).all()
    return {
        "coverage": {
            "matched_firms": total,
            "researched_firms": researched,
            "staff_researched_firms": staff,
            "behavior_analyzed_firms": 0,
            "research_percent": round((researched / total) * 100, 1) if total else 0.0,
            "staff_percent": round((staff / total) * 100, 1) if total else 0.0,
            "behavior_percent": 0.0,
        },
        "open_tasks": [{
            "task_id": row.task_id,
            "pif_id": row.pif_id,
            "kind": "local_enrichment",
            "status": row.status,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        } for row in open_tasks],
        "task_counts": {str(status): int(count) for status, count in task_counts},
        "owner": "possibleos",
    }

    # Historical EmailTag task coverage remains below for migration reference.
    async with AsyncSessionLocal() as session:
        matched_pifs = {
            pif_id for pif_id in (await session.execute(
                select(FrontFirmActivityRow.pif_id).where(FrontFirmActivityRow.pif_id.isnot(None))
            )).scalars().all()
            if pif_id
        }
        completed = (await session.execute(
            select(ResearchTaskRow.pif_id, ResearchTaskRow.kind)
            .where(ResearchTaskRow.status.in_(TERMINAL_SUCCESS))
        )).all()
        completed_by_kind: dict[str, set[str]] = {kind: set() for kind in TASK_KINDS}
        for pif_id, kind in completed:
            completed_by_kind.setdefault(kind, set()).add(pif_id)
        titled_pifs = {
            pif_id for pif_id in (await session.execute(
                select(FirmContactRow.pif_id)
                .where(or_(FirmContactRow.research_title.isnot(None), FirmContactRow.title.isnot(None)))
                .distinct()
            )).scalars().all()
            if pif_id
        }
        behavior_pifs = {
            pif_id for pif_id in (await session.execute(
                select(FrontFirmActivityRow.pif_id)
                .where(FrontFirmActivityRow.behavioral_json.isnot(None))
                .where(FrontFirmActivityRow.pif_id.isnot(None))
            )).scalars().all()
            if pif_id
        }
        open_tasks = (await session.execute(
            select(ResearchTaskRow)
            .where(~ResearchTaskRow.status.in_(TERMINAL_SUCCESS | TERMINAL_FAILURE))
            .order_by(desc(ResearchTaskRow.requested_at))
            .limit(100)
        )).scalars().all()
        task_counts = (await session.execute(
            select(ResearchTaskRow.status, func.count(ResearchTaskRow.task_id)).group_by(ResearchTaskRow.status)
        )).all()
    total = len(matched_pifs)
    researched = (completed_by_kind.get("research", set()) | titled_pifs) & matched_pifs
    staff = completed_by_kind.get("research_staff", set()) & matched_pifs
    behavior = (completed_by_kind.get("analyze_behavior", set()) | behavior_pifs) & matched_pifs
    return {
        "coverage": {
            "matched_firms": total,
            "researched_firms": len(researched),
            "staff_researched_firms": len(staff),
            "behavior_analyzed_firms": len(behavior),
            "research_percent": round((len(researched) / total) * 100, 1) if total else 0.0,
            "staff_percent": round((len(staff) / total) * 100, 1) if total else 0.0,
            "behavior_percent": round((len(behavior) / total) * 100, 1) if total else 0.0,
        },
        "open_tasks": [
            {
                "task_id": row.task_id,
                "pif_id": row.pif_id,
                "kind": row.kind,
                "status": row.status,
                "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            }
            for row in open_tasks
        ],
        "task_counts": {str(status): int(count) for status, count in task_counts},
    }


async def personas_for_domain(domain_or_pif: str) -> dict[str, Any]:
    raw = _clean(domain_or_pif)
    domain = normalize_domain(raw)
    async with AsyncSessionLocal() as session:
        pif_id = raw
        if domain:
            found = (await session.execute(
                select(FrontFirmActivityRow.pif_id)
                .where(FrontFirmActivityRow.domain == domain)
                .limit(1)
            )).scalar_one_or_none()
            if found:
                pif_id = found
        contacts = (await session.execute(
            select(FirmContactRow)
            .where(FirmContactRow.pif_id == pif_id)
            .where(FirmContactRow.persona.isnot(None))
            .order_by(FirmContactRow.full_name.asc(), FirmContactRow.email.asc())
        )).scalars().all()
    return {
        "domain": domain or None,
        "pif_id": pif_id,
        "contacts": [
            {
                "id": row.id,
                "name": row.full_name,
                "email": row.email,
                "title": row.research_title or row.title,
                "persona": row.persona,
                "persona_source": row.persona_source,
                "persona_confidence": row.persona_confidence,
                "source": row.source,
            }
            for row in contacts
        ],
    }
