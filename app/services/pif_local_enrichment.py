"""Durable local owner for all web enrichment after EmailTag PIF extraction."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
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
DEFAULT_REFRESH_DAYS = 30
STAGES = (
    ("web_research", "Firm, website, people, and vendors"),
    ("persist_research", "Save researched facts"),
    ("behavior", "Relationship behavior"),
    ("contact_intelligence", "Leadership communication and contact profiles"),
    ("contacts", "Contact directory"),
    ("job_postings", "Recent job postings"),
    ("score", "ICP score"),
)


class PifLocalEnrichmentError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _refresh_days() -> int:
    try:
        return max(1, int(os.getenv("PIF_LOCAL_ENRICHMENT_REFRESH_DAYS", str(DEFAULT_REFRESH_DAYS))))
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_DAYS


def _research_is_due(last_researched_at: datetime | None, *, now: datetime, refresh_days: int) -> bool:
    if last_researched_at is None:
        return True
    researched_at = (
        last_researched_at
        if last_researched_at.tzinfo is not None
        else last_researched_at.replace(tzinfo=timezone.utc)
    )
    return researched_at <= now - timedelta(days=refresh_days)


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


def _stage_list() -> list[dict[str, Any]]:
    return [
        {"key": key, "label": label, "status": "pending", "message": None}
        for key, label in STAGES
    ]


def _progress_summary(
    firm_name: str,
    *,
    current_stage: str | None = None,
    stages: list[dict[str, Any]] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    rows = stages or _stage_list()
    terminal = sum(row.get("status") in {"completed", "failed", "skipped"} for row in rows)
    active_fraction = 0.5 if any(row.get("status") == "in_progress" for row in rows) else 0
    return {
        "firm_name": firm_name,
        "current_stage": current_stage,
        "progress_percent": round(((terminal + active_fraction) / len(rows)) * 100) if rows else 100,
        "stages": rows,
        "message": message,
        "warning_count": sum(row.get("status") == "failed" for row in rows),
    }


def _meaningful(value: Any) -> bool:
    return value not in (None, "", [], {})


def _merge_people(existing: Any, researched: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = [dict(row) for row in _as_list(existing) if isinstance(row, dict)]
    positions: dict[str, int] = {}
    for index, row in enumerate(merged):
        email = str(row.get("email") or "").strip().lower()
        linkedin = str(row.get("linkedin") or "").strip().lower().rstrip("/")
        name = str(row.get("name") or "").strip().lower()
        key = email or linkedin or (f"name:{name}" if name else "")
        if key:
            positions[key] = index
    for raw in _as_list(researched):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        email = str(row.get("email") or "").strip().lower()
        linkedin = str(row.get("linkedin") or "").strip().lower().rstrip("/")
        name = str(row.get("name") or "").strip().lower()
        key = email or linkedin or (f"name:{name}" if name else "")
        if key and key in positions:
            current = merged[positions[key]]
            for field, value in row.items():
                if _meaningful(value) and not _meaningful(current.get(field)):
                    current[field] = value
        else:
            if key:
                positions[key] = len(merged)
            merged.append(row)
    return merged


def _merge_vendor_stack(existing: Any, researched: Any) -> dict[str, Any]:
    merged = _as_dict(existing)
    incoming = _as_dict(researched)
    for key, value in incoming.items():
        if key == "evidence":
            continue
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            nested = dict(merged[key])
            for nested_key, nested_value in value.items():
                if _meaningful(nested_value) and not _meaningful(nested.get(nested_key)):
                    nested[nested_key] = nested_value
            merged[key] = nested
        elif _meaningful(value) and not _meaningful(merged.get(key)):
            merged[key] = value
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in [*_as_list(merged.get("evidence")), *_as_list(incoming.get("evidence"))]:
        if not isinstance(raw, dict):
            continue
        key = (
            str(raw.get("vendor") or "").strip().lower(),
            str(raw.get("source_url") or "").strip().lower().rstrip("/"),
        )
        if key in seen:
            continue
        seen.add(key)
        evidence.append(dict(raw))
    merged["evidence"] = evidence
    return merged


async def _set_stage(
    task_id: str,
    stage_key: str,
    status: str,
    *,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    async with AsyncSessionLocal() as session:
        task = await session.get(PifEnrichmentTaskRow, task_id)
        if task is None:
            return
        firm = await session.get(PifFirmRow, task.pif_id)
        summary = _as_dict(task.result_summary)
        stages = [dict(row) for row in _as_list(summary.get("stages")) if isinstance(row, dict)] or _stage_list()
        for row in stages:
            if row.get("key") == stage_key:
                row["status"] = status
                row["message"] = message
                if status == "in_progress":
                    row["started_at"] = _utcnow().isoformat()
                if status in {"completed", "failed", "skipped"}:
                    row["completed_at"] = _utcnow().isoformat()
                if details:
                    row["details"] = details
                break
        current_stage = stage_key if status == "in_progress" else summary.get("current_stage")
        next_summary = {
            **summary,
            **_progress_summary(
                str((firm.firm_name if firm else None) or summary.get("firm_name") or task.pif_id),
                current_stage=current_stage,
                stages=stages,
                message=message,
            ),
        }
        task.result_summary = next_summary
        if firm is not None:
            firm.research_data = _local_state(
                firm,
                task.status,
                task_id=task_id,
                current_stage=current_stage,
                progress_percent=next_summary["progress_percent"],
                stages=stages,
                warning_count=next_summary["warning_count"],
                message=message,
            )
            firm.updated_at = _utcnow()
        await session.commit()


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
    person = {
        "name": name,
        "title": str(value.get("title") or "").strip() or None,
        "email": str(value.get("email") or "").strip().lower() or None,
        "phone": str(value.get("phone") or "").strip() or None,
        "linkedin": str(value.get("linkedin") or "").strip() or None,
        "source_url": source_url,
        "confidence": 0.8,
    }
    for key in (
        "role", "extension", "bio", "education", "experience", "skills",
        "certifications", "publications", "cases_handled", "bar_admissions",
        "department", "location",
    ):
        if _meaningful(value.get(key)):
            person[key] = value[key]
    return person


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
        "notable_cases": _as_list(value.get("notable_cases")),
        "awards_recognition": _as_list(value.get("awards_recognition")),
        "bar_associations": _as_list(value.get("bar_associations")),
        "additional_info": str(value.get("additional_info") or "").strip() or None,
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
            "notable_cases", "awards_recognition", "bar_associations",
            "social_media", "additional_info", "sources", "leadership", "staff", "vendor_stack",
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
            summary = _as_dict(existing.result_summary)
            return {
                "task_id": existing.task_id,
                "pif_id": firm_id,
                "firm_name": firm.firm_name,
                "status": existing.status,
                "message": "Local Possible OS enrichment is already queued or running",
                **summary,
            }

        task_id = f"firm-enrichment-{uuid.uuid4().hex}"
        summary = _progress_summary(
            str(firm.firm_name or firm_id),
            message="Waiting for a local enrichment worker",
        )
        session.add(PifEnrichmentTaskRow(
            task_id=task_id,
            pif_id=firm_id,
            status="queued",
            requested_at=_utcnow(),
            result_summary=summary,
        ))
        firm.research_status = "queued"
        firm.staff_research_status = "queued"
        firm.research_data = _local_state(
            firm,
            "queued",
            task_id=task_id,
            current_stage=None,
            progress_percent=0,
            stages=summary["stages"],
            warning_count=0,
            message=summary["message"],
            error=None,
        )
        firm.updated_at = _utcnow()
        await session.commit()
        return {
            "task_id": task_id,
            "pif_id": firm_id,
            "firm_name": firm.firm_name,
            "status": "queued",
            "message": "Queued for local Possible OS enrichment",
            **summary,
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
            **summary,
            "message": summary.get("message") or f"Local enrichment is {task.status}",
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
            summary = _as_dict(task.result_summary) or _progress_summary(str(firm.firm_name or task.pif_id))
            firm.research_data = _local_state(
                firm,
                "in_progress",
                task_id=task.task_id,
                current_stage=summary.get("current_stage"),
                progress_percent=summary.get("progress_percent", 0),
                stages=summary.get("stages") or _stage_list(),
                warning_count=summary.get("warning_count", 0),
            )
        await session.commit()
        return task.task_id, task.pif_id


async def _canonical_domain_owner(session, firm: PifFirmRow, domain: str | None) -> PifFirmRow | None:
    if not domain:
        return None
    owner_id = (await session.execute(
        select(PifFirmRow.id).where(
            PifFirmRow.id != firm.id,
            or_(PifFirmRow.canonical_website == domain, PifFirmRow.website == domain),
        ).limit(1)
    )).scalar_one_or_none()
    alias = await session.get(FirmAliasRow, {"alias_type": "domain", "alias_value": domain})
    if owner_id:
        return await session.get(PifFirmRow, owner_id)
    if alias and alias.firm_id != firm.id:
        return await session.get(PifFirmRow, alias.firm_id)
    return None


async def _claim_canonical_domain(session, firm: PifFirmRow, domain: str | None, now: datetime) -> bool:
    if not domain:
        return False
    if await _canonical_domain_owner(session, firm, domain):
        return False
    firm.canonical_website = domain
    firm.website = domain
    if alias is None:
        session.add(FirmAliasRow(alias_type="domain", alias_value=domain, firm_id=firm.id, synced_at=now))
    else:
        alias.firm_id = firm.id
        alias.synced_at = now
    return True


def _earliest(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _latest(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


async def _attach_extraction_to_canonical(
    session,
    source: PifFirmRow,
    canonical: PifFirmRow,
    *,
    now: datetime,
    reuse_recent_research: bool,
) -> str:
    source_json = _as_dict(source.source_json)
    extraction_id = str(source_json.get("extraction_id") or source.id).strip()

    canonical.emails = _merge_values(canonical.emails, source.emails)
    canonical.phones = _merge_values(canonical.phones, source.phones)
    canonical.addresses = _merge_values(canonical.addresses, source.addresses)
    canonical.contacts = _merge_values(canonical.contacts, source.contacts)
    canonical.conversation_ids = _merge_values(canonical.conversation_ids, source.conversation_ids)
    canonical.fax = canonical.fax or source.fax
    canonical.first_contacted_precise_at = _earliest(
        canonical.first_contacted_precise_at,
        source.first_contacted_precise_at,
    )
    canonical.source_created_at = _earliest(canonical.source_created_at, source.source_created_at)
    canonical.source_updated_at = _latest(canonical.source_updated_at, source.source_updated_at)
    canonical.synced_at = _latest(canonical.synced_at, source.synced_at) or now
    canonical.updated_at = now

    canonical_data = _as_dict(canonical.research_data)
    canonical_state = _as_dict(canonical_data.get("local_enrichment"))
    linked_ids = list(dict.fromkeys([
        *_as_list(canonical_state.get("linked_extraction_ids")),
        extraction_id,
    ]))
    canonical_state.update({
        "linked_extraction_ids": linked_ids,
        "identity_reconciled_at": now.isoformat(),
    })
    if reuse_recent_research:
        canonical_state.update({
            "dirty": False,
            "enriched_source_updated_at": (
                canonical.source_updated_at.isoformat() if canonical.source_updated_at else None
            ),
        })
    canonical_data["local_enrichment"] = canonical_state
    canonical.research_data = canonical_data

    source_json.update({"merge_status": "merged", "merged_into": canonical.id})
    source.source_json = source_json
    source.research_data = _local_state(
        source,
        "completed",
        dirty=False,
        reconciled_into=canonical.id,
        identity_reconciled_at=now.isoformat(),
        message=f"Attached to canonical firm {canonical.firm_name or canonical.id}",
    )
    source.research_status = "completed"
    source.staff_research_status = "completed"
    source.updated_at = now

    alias_key = {"alias_type": "legacy_pif_id", "alias_value": extraction_id.lower()}
    alias = await session.get(FirmAliasRow, alias_key)
    if alias is None:
        session.add(FirmAliasRow(
            alias_type="legacy_pif_id",
            alias_value=extraction_id.lower(),
            firm_id=canonical.id,
            synced_at=now,
        ))
    else:
        alias.firm_id = canonical.id
        alias.synced_at = now
    return extraction_id


def _merge_values(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, list) and isinstance(incoming, list):
        merged = list(existing)
        seen = {str(value).strip().lower() for value in merged}
        for value in incoming:
            key = str(value).strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(value)
        return merged
    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if _meaningful(value) and not _meaningful(merged.get(key)):
                merged[key] = value
        return merged
    return incoming if _meaningful(incoming) else existing


async def _persist_research_result(task_id: str, result: dict[str, Any]) -> dict[str, Any]:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        task = await session.get(PifEnrichmentTaskRow, task_id)
        if task is None:
            raise RuntimeError("research_task_not_found")
        firm = await session.get(PifFirmRow, task.pif_id)
        if firm is None:
            raise RuntimeError("firm_not_found")
        domain = result.get("canonical_website")
        canonical_owner = await _canonical_domain_owner(session, firm, domain)
        reused_recent_research = False
        reconciled_from_firm_id = None
        if canonical_owner is not None:
            reused_recent_research = not _research_is_due(
                canonical_owner.last_researched_at,
                now=now,
                refresh_days=_refresh_days(),
            )
            reconciled_from_firm_id = firm.id
            await _attach_extraction_to_canonical(
                session,
                firm,
                canonical_owner,
                now=now,
                reuse_recent_research=reused_recent_research,
            )
            if reused_recent_research:
                await session.commit()
                return {
                    "pif_id": canonical_owner.id,
                    "canonical_website": canonical_owner.canonical_website or canonical_owner.website,
                    "domain_claimed": False,
                    "reconciled_from_firm_id": reconciled_from_firm_id,
                    "reused_recent_research": True,
                    "last_researched_at": (
                        canonical_owner.last_researched_at.isoformat()
                        if canonical_owner.last_researched_at else None
                    ),
                }
            task.pif_id = canonical_owner.id
            firm = canonical_owner
        domain_claimed = canonical_owner is None and await _claim_canonical_domain(session, firm, domain, now)
        data = _as_dict(firm.research_data)
        for key in (
            "summary", "practice_areas", "founded_year", "firm_size",
            "office_locations", "notable_cases", "awards_recognition",
            "bar_associations", "social_media", "additional_info", "sources",
            "website_sources", "website_confidence",
        ):
            data[key] = _merge_values(data.get(key), result.get(key))
        data["research_provider"] = LOCAL_PROVIDER
        state = _as_dict(data.get("local_enrichment"))
        state.pop("canonical_domain_review", None)
        data["local_enrichment"] = state
        firm.research_data = data
        firm.leadership = _merge_people(firm.leadership, result.get("leadership"))
        firm.staff = _merge_people(firm.staff, result.get("staff"))
        firm.vendor_stack = _merge_vendor_stack(firm.vendor_stack, result.get("vendor_stack"))
        firm.updated_at = now
        await session.commit()
        return {
            "pif_id": firm.id,
            "canonical_website": firm.canonical_website,
            "domain_claimed": domain_claimed,
            "reconciled_from_firm_id": reconciled_from_firm_id,
            "reused_recent_research": reused_recent_research,
            "leadership_count": len(firm.leadership),
            "staff_count": len(firm.staff),
            "vendor_count": len(_as_list((firm.vendor_stack or {}).get("evidence"))),
        }


async def _finalize_task(task_id: str, status: str, *, error: str | None = None) -> None:
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        task = await session.get(PifEnrichmentTaskRow, task_id)
        if task is None:
            return
        firm = await session.get(PifFirmRow, task.pif_id)
        summary = _as_dict(task.result_summary)
        stages = _as_list(summary.get("stages")) or _stage_list()
        warning_count = sum(
            isinstance(row, dict) and row.get("status") == "failed"
            for row in stages
        )
        message = error or (
            f"Completed with {warning_count} warning{'s' if warning_count != 1 else ''}"
            if warning_count else "All enrichment stages completed"
        )
        summary.update({
            "current_stage": None,
            "progress_percent": 100 if status == "completed" else summary.get("progress_percent", 0),
            "warning_count": warning_count,
            "message": message,
        })
        task.status = status
        task.completed_at = now
        task.result_summary = summary
        if firm is not None:
            if status == "completed":
                firm.research_status = "completed"
                firm.staff_research_status = "completed"
                firm.last_researched_at = now
            else:
                firm.research_status = "failed"
                firm.staff_research_status = "failed"
            state = _as_dict(_as_dict(firm.research_data).get("local_enrichment"))
            extra = {
                "task_id": task_id,
                "current_stage": None,
                "progress_percent": summary["progress_percent"],
                "stages": stages,
                "warning_count": warning_count,
                "message": message,
                "error": error,
                "completed_at" if status == "completed" else "failed_at": now.isoformat(),
            }
            if status == "completed":
                extra.update({
                    "dirty": False,
                    "enriched_source_updated_at": state.get("source_updated_at"),
                })
            firm.research_data = _local_state(firm, status, **extra)
            firm.updated_at = now
        await session.commit()


async def _run_optional_stage(task_id: str, key: str, operation) -> Any:
    await _set_stage(task_id, key, "in_progress", message=f"Running {key.replace('_', ' ')}")
    try:
        result = await operation()
        if result is None:
            raise RuntimeError(f"{key}_returned_no_result")
        details = result if isinstance(result, dict) else None
        await _set_stage(task_id, key, "completed", message=f"Completed {key.replace('_', ' ')}", details=details)
        return result
    except Exception as exc:
        logger.exception("Local enrichment stage %s failed", key)
        await _set_stage(task_id, key, "failed", message=str(exc)[:300])
        return None


async def _wait_for_job_research(pif_id: str) -> dict[str, Any]:
    from app.services.pif_job_posting_research import get_research_status, start_job_posting_research

    started = await start_job_posting_research(pif_id)
    task_id = str(started.get("task_id") or "")
    deadline = asyncio.get_running_loop().time() + int(os.getenv("PIF_JOB_RESEARCH_WAIT_S", "420"))
    while asyncio.get_running_loop().time() < deadline:
        status = await get_research_status(task_id)
        if status.get("status") == "completed":
            return status
        if status.get("status") == "failed":
            raise RuntimeError(str(status.get("message") or "Job-posting research failed"))
        await asyncio.sleep(2)
    raise TimeoutError("Job-posting research did not finish before the local timeout")


async def _run_task(task_id: str, pif_id: str) -> None:
    await _set_stage(task_id, "web_research", "in_progress", message="Researching the official website, people, and vendor evidence")
    async with AsyncSessionLocal() as session:
        firm = await session.get(PifFirmRow, pif_id)
    if firm is None:
        await _set_stage(task_id, "web_research", "failed", message="Firm record not found")
        await _finalize_task(task_id, "failed", error="firm_not_found")
        return
    try:
        result = await research_firm_locally(firm)
    except Exception as exc:
        logger.exception("Local firm enrichment failed for %s", pif_id)
        await _set_stage(task_id, "web_research", "failed", message=str(exc)[:300])
        await _finalize_task(task_id, "failed", error=str(exc)[:500])
        return
    await _set_stage(task_id, "web_research", "completed", message="Web research completed")

    await _set_stage(task_id, "persist_research", "in_progress", message="Merging researched facts with existing firm data")
    try:
        persisted = await _persist_research_result(task_id, result)
    except Exception as exc:
        await _set_stage(task_id, "persist_research", "failed", message=str(exc)[:300])
        await _finalize_task(task_id, "failed", error=str(exc)[:500])
        return
    await _set_stage(task_id, "persist_research", "completed", message="Research saved without replacing existing facts", details=persisted)

    target_pif_id = str(persisted.get("pif_id") or pif_id)
    if persisted.get("reused_recent_research"):
        message = "Canonical firm was researched within the last 30 days; reused existing research"
        for stage_key in ("behavior", "contact_intelligence", "contacts", "job_postings", "score"):
            await _set_stage(task_id, stage_key, "skipped", message=message)
        await _finalize_task(task_id, "completed")
        return

    from app.services.firm_contacts_service import ingest_pif_directory_contacts
    from app.services.pif_local_derivations import (
        analyze_behavior_locally,
        score_firm_locally,
        synthesize_contact_intelligence_locally,
    )

    await _run_optional_stage(task_id, "behavior", lambda: analyze_behavior_locally(target_pif_id))
    await _run_optional_stage(
        task_id,
        "contact_intelligence",
        lambda: synthesize_contact_intelligence_locally(target_pif_id),
    )
    await _run_optional_stage(
        task_id,
        "contacts",
        lambda: ingest_pif_directory_contacts(pif_ids={target_pif_id}),
    )
    await _run_optional_stage(task_id, "job_postings", lambda: _wait_for_job_research(target_pif_id))
    await _run_optional_stage(task_id, "score", lambda: score_firm_locally(target_pif_id))
    await _finalize_task(task_id, "completed")


async def recover_interrupted_local_enrichment() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(PifEnrichmentTaskRow)
            .where(PifEnrichmentTaskRow.status == "in_progress")
            .values(status="queued", started_at=None)
        )
        await session.commit()
        return int(result.rowcount or 0)


async def _due_dirty_firm_ids(*, now: datetime, refresh_days: int, exclude: set[str]) -> list[str]:
    cutoff = now - timedelta(days=refresh_days)
    async with AsyncSessionLocal() as session:
        firms = (await session.execute(
            select(PifFirmRow)
            .where(or_(PifFirmRow.last_researched_at.is_(None), PifFirmRow.last_researched_at <= cutoff))
            .order_by(PifFirmRow.last_researched_at.asc().nullsfirst(), PifFirmRow.source_updated_at.desc().nullslast())
        )).scalars().all()
    return [
        firm.id
        for firm in firms
        if firm.id not in exclude
        and _as_dict(_as_dict(firm.research_data).get("local_enrichment")).get("dirty")
    ]


async def queue_dirty_firm_enrichment(firm_ids: list[str], *, limit: int = 100) -> dict[str, Any]:
    """Queue dirty firms whose last successful local research is no longer fresh."""
    now = _utcnow()
    refresh_days = _refresh_days()
    candidate_ids = list(dict.fromkeys(firm_ids))
    candidate_ids.extend(await _due_dirty_firm_ids(
        now=now,
        refresh_days=refresh_days,
        exclude=set(candidate_ids),
    ))
    queued: list[str] = []
    skipped: list[str] = []
    deferred: list[str] = []
    for firm_id in candidate_ids:
        if len(queued) >= max(0, limit):
            break
        async with AsyncSessionLocal() as session:
            firm = await session.get(PifFirmRow, firm_id)
            state = _as_dict(_as_dict(firm.research_data).get("local_enrichment")) if firm else {}
        if not firm or not state.get("dirty"):
            skipped.append(firm_id)
            continue
        if not _research_is_due(firm.last_researched_at, now=now, refresh_days=refresh_days):
            deferred.append(firm_id)
            continue
        result = await start_local_firm_enrichment(firm_id)
        if result.get("status") in OPEN_STATUSES:
            queued.append(firm_id)
        else:
            skipped.append(firm_id)
    return {
        "queued": queued,
        "skipped": skipped,
        "deferred": deferred,
        "refresh_days": refresh_days,
    }


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
