"""Durable local owner for all web enrichment after EmailTag PIF extraction."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select, update

from app.db import AsyncSessionLocal
from app.db.models import FirmAliasRow, PifEnrichmentTaskRow, PifFirmRow
from app.services.front_sync import is_consumer_domain, normalize_domain
from app.services.llm_gateway import call_skill_json


logger = logging.getLogger(__name__)
SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/pif-local-enrichment/SKILL.md"
OPEN_STATUSES = {"queued", "in_progress"}
LOCAL_PROVIDER = "possibleos_openclaw"


class PifLocalEnrichmentError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _local_state(firm: PifFirmRow, status: str, **extra: Any) -> dict[str, Any]:
    data = _as_dict(firm.research_data)
    state = _as_dict(data.get("local_enrichment"))
    state.update({"status": status, "provider": LOCAL_PROVIDER, **extra})
    data["local_enrichment"] = state
    return data


def _identity_payload(firm: PifFirmRow) -> dict[str, Any]:
    source = _as_dict(firm.source_json)
    domains: list[str] = []
    observed = normalize_domain(source.get("observed_website") or firm.website)
    if observed:
        domains.append(observed)
    for email in _as_list(source.get("emails")):
        domain = normalize_domain(email)
        if domain and not is_consumer_domain(domain) and domain not in domains:
            domains.append(domain)
    return {
        "firm_name": firm.firm_name,
        "entity_type": firm.entity_type,
        "observed_domains": domains,
        "phones": _as_list(source.get("phones"))[:10],
        "addresses": _as_list(source.get("addresses"))[:10],
    }


def _person(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip()
    source_url = str(value.get("source_url") or "").strip()
    if not name or not source_url.lower().startswith(("http://", "https://")):
        return None
    return {
        "name": name,
        "title": str(value.get("title") or "").strip() or None,
        "email": str(value.get("email") or "").strip().lower() or None,
        "phone": str(value.get("phone") or "").strip() or None,
        "linkedin": str(value.get("linkedin") or "").strip() or None,
        "source_url": source_url,
        "confidence": 0.8,
    }


def normalize_enrichment(value: dict[str, Any]) -> dict[str, Any]:
    canonical = normalize_domain(value.get("canonical_website"))
    if canonical and is_consumer_domain(canonical):
        canonical = None
    try:
        website_confidence = max(0.0, min(1.0, float(value.get("website_confidence") or 0.0)))
    except (TypeError, ValueError):
        website_confidence = 0.0
    leadership = [person for item in _as_list(value.get("leadership")) if (person := _person(item))]
    staff = [person for item in _as_list(value.get("staff")) if (person := _person(item))]
    vendor_stack = _as_dict(value.get("vendor_stack"))
    evidence = [
        item for item in _as_list(vendor_stack.get("evidence"))
        if isinstance(item, dict)
        and str(item.get("vendor") or "").strip()
        and str(item.get("source_url") or "").lower().startswith(("http://", "https://"))
    ]
    vendor_stack["evidence"] = evidence
    return {
        "canonical_website": canonical,
        "website_confidence": website_confidence,
        "website_sources": _as_list(value.get("website_sources")),
        "summary": str(value.get("summary") or "").strip() or None,
        "practice_areas": _as_list(value.get("practice_areas")),
        "founded_year": value.get("founded_year"),
        "firm_size": str(value.get("firm_size") or "").strip() or None,
        "office_locations": _as_list(value.get("office_locations")),
        "social_media": _as_dict(value.get("social_media")),
        "sources": _as_list(value.get("sources")),
        "leadership": leadership[:15],
        "staff": staff[:30],
        "vendor_stack": vendor_stack,
    }


async def research_firm_locally(firm: PifFirmRow) -> dict[str, Any]:
    response = await call_skill_json(
        skill_path=SKILL_PATH,
        payload=_identity_payload(firm),
        required_fields=[
            "canonical_website", "website_confidence", "website_sources", "summary",
            "practice_areas", "founded_year", "firm_size", "office_locations",
            "social_media", "sources", "leadership", "staff", "vendor_stack",
        ],
        model=os.getenv("PIF_LOCAL_ENRICHMENT_MODEL", "openclaw/main"),
        timeout_s=int(os.getenv("PIF_LOCAL_ENRICHMENT_TIMEOUT_S", "300")),
        max_tokens=int(os.getenv("PIF_LOCAL_ENRICHMENT_MAX_TOKENS", "6000")),
    )
    return normalize_enrichment(response.parsed)


async def start_local_firm_enrichment(firm_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, firm_id)
        if firm is None:
            raise PifLocalEnrichmentError(404, "firm_not_found")
        existing = (await session.execute(
            select(PifEnrichmentTaskRow)
            .where(
                PifEnrichmentTaskRow.pif_id == firm_id,
                PifEnrichmentTaskRow.status.in_(OPEN_STATUSES),
            )
            .order_by(PifEnrichmentTaskRow.requested_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if existing:
            return {
                "task_id": existing.task_id,
                "pif_id": firm_id,
                "firm_name": firm.firm_name,
                "status": existing.status,
                "message": "Local Possible OS enrichment is already queued or running",
            }

        task_id = f"firm-enrichment-{uuid.uuid4().hex}"
        session.add(PifEnrichmentTaskRow(
            task_id=task_id,
            pif_id=firm_id,
            status="queued",
            requested_at=_utcnow(),
        ))
        firm.research_status = "queued"
        firm.staff_research_status = "queued"
        firm.research_data = _local_state(firm, "queued", error=None)
        firm.updated_at = _utcnow()
        await session.commit()
        return {
            "task_id": task_id,
            "pif_id": firm_id,
            "firm_name": firm.firm_name,
            "status": "queued",
            "message": "Queued for local Possible OS enrichment",
        }


async def get_local_enrichment_status(task_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        task = await session.get(PifEnrichmentTaskRow, task_id)
        if task is None:
            raise PifLocalEnrichmentError(404, "research_task_not_found")
        summary = _as_dict(task.result_summary)
        return {
            "task_id": task.task_id,
            "pif_id": task.pif_id,
            "status": task.status,
            "requested_at": task.requested_at.isoformat() if task.requested_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "message": summary.get("message") or f"Local enrichment is {task.status}",
            **summary,
        }


async def _claim_next_task() -> tuple[str, str] | None:
    async with AsyncSessionLocal() as session:
        task = (await session.execute(
            select(PifEnrichmentTaskRow)
            .where(PifEnrichmentTaskRow.status == "queued")
            .order_by(PifEnrichmentTaskRow.requested_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )).scalar_one_or_none()
        if task is None:
            return None
        task.status = "in_progress"
        task.started_at = _utcnow()
        firm = await session.get(PifFirmRow, task.pif_id)
        if firm:
            firm.research_status = "in_progress"
            firm.staff_research_status = "in_progress"
            firm.research_data = _local_state(firm, "in_progress")
        await session.commit()
        return task.task_id, task.pif_id


async def _claim_canonical_domain(session, firm: PifFirmRow, domain: str | None, now: datetime) -> bool:
    if not domain:
        return False
    owner = (await session.execute(
        select(PifFirmRow.id).where(
            PifFirmRow.id != firm.id,
            or_(PifFirmRow.canonical_website == domain, PifFirmRow.website == domain),
        ).limit(1)
    )).scalar_one_or_none()
    alias = await session.get(FirmAliasRow, {"alias_type": "domain", "alias_value": domain})
    if owner or (alias and alias.firm_id != firm.id):
        return False
    firm.canonical_website = domain
    firm.website = domain
    if alias is None:
        session.add(FirmAliasRow(alias_type="domain", alias_value=domain, firm_id=firm.id, synced_at=now))
    else:
        alias.firm_id = firm.id
        alias.synced_at = now
    return True


async def _finish_task(task_id: str, result: dict[str, Any] | None, error: str | None = None) -> None:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        task = await session.get(PifEnrichmentTaskRow, task_id)
        if task is None:
            return
        pif_id = task.pif_id
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            task.status = "failed"
            task.completed_at = now
            task.result_summary = {"message": "firm_not_found"}
            await session.commit()
            return
        if error or result is None:
            task.status = "failed"
            task.completed_at = now
            task.result_summary = {"firm_name": firm.firm_name, "message": error or "research_failed"}
            firm.research_status = "failed"
            firm.staff_research_status = "failed"
            firm.research_data = _local_state(firm, "failed", error=error, failed_at=now.isoformat())
            await session.commit()
            return

        domain_claimed = await _claim_canonical_domain(session, firm, result.get("canonical_website"), now)
        data = _as_dict(firm.research_data)
        data.update({
            "summary": result.get("summary"),
            "practice_areas": result.get("practice_areas") or [],
            "founded_year": result.get("founded_year"),
            "firm_size": result.get("firm_size"),
            "office_locations": result.get("office_locations") or [],
            "social_media": result.get("social_media") or {},
            "sources": result.get("sources") or [],
            "website_sources": result.get("website_sources") or [],
            "website_confidence": result.get("website_confidence"),
            "research_provider": LOCAL_PROVIDER,
        })
        state = _as_dict(data.get("local_enrichment"))
        state.update({
            "status": "completed",
            "provider": LOCAL_PROVIDER,
            "dirty": False,
            "enriched_source_updated_at": state.get("source_updated_at"),
            "completed_at": now.isoformat(),
            "error": None,
        })
        if result.get("canonical_website") and not domain_claimed:
            state["canonical_domain_review"] = {
                "candidate": result["canonical_website"],
                "reason": "domain_owned_by_another_firm",
            }
        data["local_enrichment"] = state
        firm.research_data = data
        firm.leadership = result.get("leadership") or []
        firm.staff = result.get("staff") or []
        firm.vendor_stack = result.get("vendor_stack") or {}
        firm.research_status = "completed"
        firm.staff_research_status = "completed"
        firm.last_researched_at = now
        firm.updated_at = now
        task.status = "completed"
        task.completed_at = now
        task.result_summary = {
            "firm_name": firm.firm_name,
            "canonical_website": firm.canonical_website,
            "domain_claimed": domain_claimed,
            "leadership_count": len(firm.leadership),
            "staff_count": len(firm.staff),
            "vendor_count": len(_as_list((firm.vendor_stack or {}).get("evidence"))),
        }
        await session.commit()

    from app.services.pif_local_derivations import analyze_behavior_locally, score_firm_locally
    from app.services.firm_contacts_service import ingest_pif_directory_contacts
    from app.services.pif_job_posting_research import start_job_posting_research

    followups = (
        ("behavior", lambda: analyze_behavior_locally(pif_id)),
        ("score", lambda: score_firm_locally(pif_id)),
        ("contact ingest", lambda: ingest_pif_directory_contacts(pif_ids={pif_id})),
        ("job research", lambda: start_job_posting_research(pif_id)),
    )
    for label, operation in followups:
        try:
            await operation()
        except Exception:
            logger.exception("Local post-enrichment %s failed for %s", label, pif_id)


async def _run_task(task_id: str, pif_id: str) -> None:
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
        if firm is None:
            await _finish_task(task_id, None, "firm_not_found")
            return
        try:
            result = await research_firm_locally(firm)
        except Exception as exc:
            logger.exception("Local firm enrichment failed for %s", pif_id)
            await _finish_task(task_id, None, str(exc)[:500])
            return
    await _finish_task(task_id, result)


async def recover_interrupted_local_enrichment() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(PifEnrichmentTaskRow)
            .where(PifEnrichmentTaskRow.status == "in_progress")
            .values(status="queued", started_at=None)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def queue_dirty_firm_enrichment(firm_ids: list[str], *, limit: int = 100) -> dict[str, Any]:
    queued: list[str] = []
    skipped: list[str] = []
    for firm_id in firm_ids[:max(0, limit)]:
        async with AsyncSessionLocal() as session:
            firm = await session.get(PifFirmRow, firm_id)
            state = _as_dict(_as_dict(firm.research_data).get("local_enrichment")) if firm else {}
        if not firm or not state.get("dirty"):
            skipped.append(firm_id)
            continue
        result = await start_local_firm_enrichment(firm_id)
        if result.get("status") in OPEN_STATUSES:
            queued.append(firm_id)
        else:
            skipped.append(firm_id)
    return {"queued": queued, "skipped": skipped}


async def local_enrichment_loop(*, poll_seconds: float = 2.0) -> None:
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
            logger.exception("Local enrichment worker tick failed")
            await asyncio.sleep(poll_seconds)
