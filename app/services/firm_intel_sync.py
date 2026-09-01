"""EmailTag PIF-extraction mirror.

EmailTag owns extraction only. Possible OS mirrors raw extraction deltas and
owns canonical identity, research, vendors, people, scoring, and job research.
The legacy refined-profile mapper remains readable during the cutover.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time as time_module
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

import httpx
from sqlalchemy import String, and_, bindparam, cast, exists, func, inspect, or_, select, text
from sqlalchemy.dialects.postgresql import JSONPATH

from app.db import AsyncSessionLocal, async_engine
from app.db.models import FirmAliasRow, FirmIntelSyncStateRow, PifAutorespondEventRow, PifFirmRow
from app.services.front_sync import is_consumer_domain, normalize_domain
from app.services.persona_mapper import classify_contact

logger = logging.getLogger(__name__)

FIRM_INTEL_BASE_URL = os.getenv(
    "FIRM_INTEL_BASE_URL",
    "https://emailprocessing.mediflow360.com/api/v2/firm-intel",
).rstrip("/")

ALIAS_TYPES = ("domain", "vanity_domain", "legacy_pif_id")
STATUS_COMPLETED = {"completed", "done", "enriched"}
STATUS_RUNNING = {"queued", "pending", "in_progress", "running", "started"}
SYNC_DETAIL_LIMIT = 100

_tables_checked = False
_vendor_firm_ids_cache: dict[str, tuple[float, set[str]]] = {}
_VENDOR_FIRM_IDS_CACHE_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _dt_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _page_size() -> int:
    """Delta-feed page size. The v2 endpoint builds full profiles per item, so
    large pages (~11s at 100) risk gateway timeouts under load; 25 stays ~1s."""
    try:
        return max(1, min(100, int(os.getenv("FIRM_INTEL_PAGE_SIZE", "25"))))
    except ValueError:
        return 25


def _page_pause() -> float:
    """Pause between delta-feed pages. The endpoint 502s under sustained
    back-to-back crawling (~27 pages) but recovers with breathing room —
    verified 2026-07-05: offsets that 502'd sequentially all 200 with pauses."""
    try:
        return max(0.0, float(os.getenv("FIRM_INTEL_PAGE_PAUSE", "2.0")))
    except ValueError:
        return 2.0


async def _get_with_retry(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    attempts: int = 4,
) -> httpx.Response:
    """GET with backoff on 5xx/transport errors — the v2 endpoint 502s
    transiently when profile pages are slow under load."""
    delay = 10.0
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(path, params=params)
            if resp.status_code < 500:
                return resp
            last_err: Exception = httpx.HTTPStatusError(
                f"server error {resp.status_code}", request=resp.request, response=resp
            )
        except httpx.TransportError as exc:
            last_err = exc
        if attempt == attempts:
            raise last_err
        logger.warning("firm-intel GET %s attempt %s failed (%s); retrying in %.0fs", path, attempt, last_err, delay)
        await asyncio.sleep(delay)
        delay *= 2
    raise last_err  # unreachable


def _auth_headers() -> dict[str, str]:
    token = os.getenv("PIFSTATS_AUTH_TOKEN", "").strip()
    return {"X-PIFStats-Auth-Token": token} if token else {}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _distinct(values: list[Any], *, lower: bool = False) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text_value = str(value or "").strip()
        if not text_value:
            continue
        if lower:
            text_value = text_value.lower()
        key = text_value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text_value)
    return out


def _merge_contact_values(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    positions: dict[str, int] = {}
    for value in [*existing, *incoming]:
        if not isinstance(value, dict):
            if value not in merged:
                merged.append(value)
            continue
        email = str(value.get("email") or "").strip().lower()
        name = str(value.get("name") or "").strip().lower()
        title = str(value.get("title") or "").strip().lower()
        key = email or f"{name}|{title}"
        if not key.strip("|"):
            if value not in merged:
                merged.append(dict(value))
            continue
        if key not in positions:
            positions[key] = len(merged)
            merged.append(dict(value))
            continue
        current = dict(merged[positions[key]])
        for field, field_value in value.items():
            if field_value not in (None, "", [], {}) and current.get(field) in (None, "", [], {}):
                current[field] = field_value
        merged[positions[key]] = current
    return merged


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_updated_at(profile: dict[str, Any]) -> datetime | None:
    if profile.get("extraction_id"):
        return _parse_dt(profile.get("updated_at"))
    provenance = _as_dict(profile.get("provenance"))
    return _parse_dt(provenance.get("refined_at")) or _parse_dt(profile.get("updated_at"))


def _profile_watermark(profile: dict[str, Any]) -> datetime | None:
    return _source_updated_at(profile)


def _source_record(profile: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(profile.get("source_record"))


def _profile_website(profile: dict[str, Any]) -> str | None:
    aliases = _as_dict(profile.get("aliases"))
    canonical = normalize_domain(profile.get("canonical_website"))
    if canonical:
        return canonical
    for domain in _as_list(aliases.get("domains")):
        normalized = normalize_domain(str(domain))
        if normalized:
            return normalized
    return None


def _vendor_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _vendor_label(value: str) -> str:
    overrides = {
        "case-status": "Case Status",
        "filevine": "Filevine",
        "casepeer": "Casepeer",
        "practicepanther": "PracticePanther",
        "smartadvocate": "SmartAdvocate",
        "foundationai": "FoundationAI",
        "lawmatics": "Lawmatics",
        "salesforce": "Salesforce",
        "chartsquad": "ChartSquad",
        "smokeball": "Smokeball",
        "mycase": "MyCase",
        "litify": "Litify",
        "clio": "Clio",
        "lexitas": "Lexitas",
        "gladiate": "Gladiate",
    }
    key = _vendor_key(value)
    return overrides.get(key) or key.replace("_", " ").replace("-", " ").title()


def _vendor_entries_from_stack(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict) and _vendor_key(item.get("vendor"))]
    if not isinstance(value, dict):
        return []

    entries: list[dict[str, Any]] = []
    other = value.get("other")
    case_mgmt = _vendor_key(value.get("case_mgmt"))
    if case_mgmt:
        case_detail = other.get(case_mgmt) if isinstance(other, dict) else None
        entry = dict(case_detail) if isinstance(case_detail, dict) else {}
        entry.setdefault("vendor", case_mgmt)
        entry.setdefault("source", "case_mgmt")
        entries.append(entry)
    if isinstance(other, dict):
        for vendor, detail in other.items():
            entry = dict(detail) if isinstance(detail, dict) else {}
            entry.setdefault("vendor", _vendor_key(vendor))
            entry.setdefault("source", "other")
            if _vendor_key(entry.get("vendor")):
                entries.append(entry)
    return entries


def _vendor_entries_for_row(row: PifFirmRow) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    source = row.source_json or {}
    raw = row.raw_json or {}
    manual_overrides = (
        source.get("_possibleos_manual_overrides")
        if isinstance(source, dict)
        else None
    )
    manual_stack = manual_overrides.get("vendor_stack") if isinstance(manual_overrides, dict) else None
    stacks = (
        (manual_stack,)
        if isinstance(manual_stack, (dict, list))
        else (
            row.vendor_stack,
            source.get("vendor_stack") if isinstance(source, dict) else None,
            raw.get("vendor_stack") if isinstance(raw, dict) else None,
        )
    )
    for stack in stacks:
        entries.extend(_vendor_entries_from_stack(stack))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        key = _vendor_key(entry.get("vendor"))
        if not key or key in seen:
            continue
        seen.add(key)
        normalized = dict(entry)
        normalized["vendor"] = key
        deduped.append(normalized)
    return deduped


def _row_has_vendor(row: PifFirmRow, vendor: str | None = None) -> bool:
    entries = _vendor_entries_for_row(row)
    if not vendor:
        return bool(entries)
    wanted = _vendor_key(vendor)
    return any(_vendor_key(entry.get("vendor")) == wanted for entry in entries)


def _people(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in _as_list(profile.get("people")) if isinstance(p, dict)]


def _behavioral_data(profile: dict[str, Any]) -> dict[str, Any]:
    behavior = dict(_as_dict(profile.get("behavior")))
    relationship = _as_dict(profile.get("relationship"))
    for key, value in relationship.items():
        behavior.setdefault(key, value)
    behavior["relationship"] = relationship
    return behavior


def _research_data(profile: dict[str, Any]) -> dict[str, Any]:
    research = dict(_as_dict(profile.get("research")))
    identity = _as_dict(profile.get("identity"))
    for key, value in identity.items():
        research.setdefault(key, value)
    research["identity"] = identity
    return research


_LOCAL_JOB_RESEARCH_KEYS = (
    "job_postings",
    "job_postings_research_status",
    "job_postings_research_provider",
    "last_job_postings_researched_at",
)

_LOCAL_RESEARCH_KEYS = (
    "sitemap_monitor",
)


def _preserve_local_job_research(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """Keep Possible OS-owned research across EmailTag mirror refreshes."""
    prior = existing if isinstance(existing, dict) else {}
    merged = dict(incoming)
    if prior.get("job_postings_research_provider") == "possibleos_openclaw":
        for key in _LOCAL_JOB_RESEARCH_KEYS:
            if key in prior:
                merged[key] = prior[key]
    for key in _LOCAL_RESEARCH_KEYS:
        value = prior.get(key)
        if isinstance(value, dict) and str(value.get("provider") or "").startswith("possibleos_"):
            merged[key] = value
    return merged


def _apply_source_record(row: PifFirmRow, source: dict[str, Any]) -> None:
    if not source:
        row.source_json = row.source_json or {}
        return

    row.source_json = source
    row.entity_type = source.get("entity_type")
    row.fax = source.get("fax")
    row.staff_research_status = source.get("staff_research_status")
    row.extraction_notes = source.get("extraction_notes")
    row.source_created_at = _parse_dt(source.get("created_at"))
    row.icp_scored_at = _parse_dt(source.get("icp_scored_at"))
    row.first_contacted_precise_at = _parse_dt(source.get("first_contacted_precise_at"))


def _apply_v2_profile(row: PifFirmRow, profile: dict[str, Any], *, now: datetime) -> None:
    existing_source = row.source_json if isinstance(row.source_json, dict) else {}
    manual_overrides = existing_source.get("_possibleos_manual_overrides")
    if not isinstance(manual_overrides, dict):
        manual_overrides = {}
    aliases = _as_dict(profile.get("aliases"))
    identity = _as_dict(profile.get("identity"))
    relationship = _as_dict(profile.get("relationship"))
    icp = _as_dict(profile.get("icp"))
    research = _as_dict(profile.get("research"))
    people = _people(profile)
    canonical = _profile_website(profile)

    row.firm_name = profile.get("firm_name") or None
    row.website = canonical
    row.canonical_website = canonical
    row.metro = identity.get("metro") or None
    row.icp_score = _as_int(icp.get("score"))
    row.icp_tier = icp.get("tier") or identity.get("icp_tier") or None
    row.score_breakdown = _as_dict(icp.get("score_breakdown"))
    row.research_status = research.get("research_status") or None
    row.last_researched_at = _parse_dt(research.get("last_researched_at"))
    row.leadership = [p for p in people if p.get("is_decision_maker") is True]
    row.staff = [p for p in people if p.get("is_decision_maker") is not True]
    row.emails = _distinct([p.get("email") for p in people], lower=True)
    row.phones = _distinct([p.get("phone") for p in people])
    row.behavioral_data = _behavioral_data(profile)
    row.research_data = _preserve_local_job_research(
        row.research_data,
        _research_data(profile),
    )
    row.raw_json = profile
    row.source_updated_at = _source_updated_at(profile)
    row.warm_score = _as_float(relationship.get("warm_score_neutral"))
    row.vendor_stack = _as_dict(profile.get("vendor_stack"))
    row.profile_source = "v2"
    row.synced_at = now
    row.updated_at = now

    _apply_source_record(row, _source_record(profile))

    if manual_overrides:
        from app.services.pif_firm_crud import apply_stored_manual_overrides

        apply_stored_manual_overrides(row, manual_overrides, now=now)

    # Preserve v1-only mirror fields unless v2 supplies an equivalent value.
    row.entity_type = row.entity_type
    row.fax = row.fax
    row.staff_research_status = row.staff_research_status
    row.addresses = row.addresses or []
    row.contacts = people
    row.contact_profiles = row.contact_profiles or {}
    row.conversation_ids = row.conversation_ids or []
    row.extraction_notes = row.extraction_notes
    row.icp_scored_at = row.icp_scored_at
    row.source_created_at = row.source_created_at
    if aliases and not canonical:
        row.website = _profile_website(profile)


def _apply_extraction(row: PifFirmRow, extraction: dict[str, Any], *, now: datetime) -> None:
    """Apply source facts without replacing Possible OS-owned derived fields."""
    existing_source = row.source_json if isinstance(row.source_json, dict) else {}
    manual_overrides = existing_source.get("_possibleos_manual_overrides")
    extraction_id = str(extraction.get("extraction_id") or "").strip()
    linked_to_canonical = bool(extraction_id and extraction_id != row.id)
    source = dict(extraction)
    if isinstance(manual_overrides, dict):
        source["_possibleos_manual_overrides"] = deepcopy(manual_overrides)
    linked_ids = _distinct([
        *_as_list(existing_source.get("_linked_extraction_ids")),
        *([extraction_id] if linked_to_canonical else []),
    ])
    if linked_ids:
        source["_linked_extraction_ids"] = linked_ids

    source_updated = _parse_dt(extraction.get("updated_at"))
    source_version = _dt_iso(source_updated)
    research_data = dict(row.research_data) if isinstance(row.research_data, dict) else {}
    local_state = _as_dict(research_data.get("local_enrichment"))
    local_state["source_updated_at"] = source_version
    local_state["dirty"] = local_state.get("enriched_source_updated_at") != source_version
    research_data["local_enrichment"] = local_state

    if not linked_to_canonical or not row.firm_name:
        row.firm_name = extraction.get("firm_name") or row.firm_name
    row.entity_type = extraction.get("entity_type") or row.entity_type
    observed_website = normalize_domain(extraction.get("observed_website"))
    if observed_website and not row.canonical_website:
        row.website = observed_website
    row.emails = _distinct([
        *(_as_list(row.emails) if linked_to_canonical else []),
        *_as_list(extraction.get("emails")),
        *[p.get("email") for p in [*(_as_list(row.leadership)), *(_as_list(row.staff))] if isinstance(p, dict)],
    ], lower=True)
    row.phones = _distinct([
        *(_as_list(row.phones) if linked_to_canonical else []),
        *_as_list(extraction.get("phones")),
        *[p.get("phone") for p in [*(_as_list(row.leadership)), *(_as_list(row.staff))] if isinstance(p, dict)],
    ])
    row.fax = extraction.get("fax") or row.fax
    row.addresses = _distinct([
        *(_as_list(row.addresses) if linked_to_canonical else []),
        *_as_list(extraction.get("addresses")),
    ])
    row.contacts = _merge_contact_values(
        _as_list(row.contacts) if linked_to_canonical else [],
        _as_list(extraction.get("contacts")),
    )
    row.conversation_ids = _distinct([
        *(_as_list(row.conversation_ids) if linked_to_canonical else []),
        *_as_list(extraction.get("conversation_ids")),
    ])
    row.extraction_notes = extraction.get("extraction_notes") or row.extraction_notes
    first_contacted = _parse_dt(extraction.get("first_contacted_precise_at"))
    source_created = _parse_dt(extraction.get("created_at"))
    if linked_to_canonical:
        first_values = [value for value in (row.first_contacted_precise_at, first_contacted) if value]
        created_values = [value for value in (row.source_created_at, source_created) if value]
        updated_values = [value for value in (row.source_updated_at, source_updated) if value]
        row.first_contacted_precise_at = min(first_values) if first_values else None
        row.source_created_at = min(created_values) if created_values else None
        row.source_updated_at = max(updated_values) if updated_values else None
    else:
        row.first_contacted_precise_at = first_contacted
        row.source_created_at = source_created
        row.source_updated_at = source_updated
    row.source_json = source
    row.research_data = research_data
    row.profile_source = "raw"
    row.synced_at = now
    row.updated_at = now

    if isinstance(manual_overrides, dict):
        from app.services.pif_firm_crud import apply_stored_manual_overrides

        apply_stored_manual_overrides(row, manual_overrides, now=now)


def _extraction_alias_profile(extraction: dict[str, Any], firm_id: str) -> dict[str, Any]:
    """Raw observations claim only their source ID; domains are resolved locally."""
    return {
        "firm_id": firm_id,
        "aliases": {"legacy_pif_ids": [str(extraction.get("extraction_id") or firm_id)]},
    }


def _alias_candidates(profile: dict[str, Any]) -> set[tuple[str, str]]:
    aliases = _as_dict(profile.get("aliases"))
    candidates: set[tuple[str, str]] = set()

    canonical = normalize_domain(profile.get("canonical_website"))
    if canonical and not is_consumer_domain(canonical):
        candidates.add(("domain", canonical))

    for domain in _as_list(aliases.get("domains")):
        normalized = normalize_domain(str(domain))
        if normalized and not is_consumer_domain(normalized):
            candidates.add(("domain", normalized))

    for domain in _as_list(aliases.get("vanity_domains")):
        normalized = normalize_domain(str(domain))
        if normalized and not is_consumer_domain(normalized):
            candidates.add(("vanity_domain", normalized))

    for legacy_id in _as_list(aliases.get("legacy_pif_ids")):
        value = str(legacy_id or "").strip().lower()
        if value:
            candidates.add(("legacy_pif_id", value))

    for person in _people(profile):
        email_domain = normalize_domain(person.get("email"))
        if email_domain and not is_consumer_domain(email_domain):
            candidates.add(("domain", email_domain))

    return candidates


def _ensure_v2_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    existing = {col["name"] for col in inspector.get_columns(PifFirmRow.__tablename__)}
    ddl = {
        "canonical_website": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS canonical_website VARCHAR(512)",
        "metro": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS metro VARCHAR(128)",
        "warm_score": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS warm_score DOUBLE PRECISION",
        "vendor_stack": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS vendor_stack JSONB NOT NULL DEFAULT '{}'::jsonb",
        "profile_source": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS profile_source VARCHAR(8)",
        "manually_added": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS manually_added BOOLEAN NOT NULL DEFAULT false",
        "source_json": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS source_json JSONB NOT NULL DEFAULT '{}'::jsonb",
        "first_contacted_precise_at": "ALTER TABLE pif_directory_firms ADD COLUMN IF NOT EXISTS first_contacted_precise_at TIMESTAMP WITH TIME ZONE",
    }
    for column, statement in ddl.items():
        if column not in existing:
            sync_conn.execute(text(statement))
    for index in PifFirmRow.__table__.indexes:
        if index.name in {
            "ix_pif_directory_firms_canonical_website",
            "ix_pif_directory_firms_first_contacted_precise_at",
        }:
            index.create(bind=sync_conn, checkfirst=True)


async def ensure_firm_intel_tables() -> None:
    global _tables_checked
    if _tables_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(PifFirmRow.__table__.create, checkfirst=True)
        await conn.run_sync(_ensure_v2_columns)
        await conn.run_sync(FirmAliasRow.__table__.create, checkfirst=True)
        await conn.run_sync(FirmIntelSyncStateRow.__table__.create, checkfirst=True)
        await conn.run_sync(PifAutorespondEventRow.__table__.create, checkfirst=True)
    _tables_checked = True


async def _upsert_aliases(session, profile: dict[str, Any], *, now: datetime) -> int:
    firm_id = str(profile.get("firm_id") or "").strip()
    if not firm_id:
        return 0
    canonical = _profile_website(profile)
    touched = 0
    for alias_type, alias_value in _alias_candidates(profile):
        row = await session.get(
            FirmAliasRow,
            {"alias_type": alias_type, "alias_value": alias_value},
        )
        if row is None:
            row = FirmAliasRow(
                alias_type=alias_type,
                alias_value=alias_value,
                firm_id=firm_id,
                synced_at=now,
            )
            session.add(row)
        else:
            if alias_type == "domain" and row.firm_id != firm_id:
                current_owner = await session.get(PifFirmRow, row.firm_id)
                current_is_canonical = bool(
                    current_owner
                    and (
                        normalize_domain(current_owner.canonical_website) == alias_value
                        or normalize_domain(current_owner.website) == alias_value
                    )
                )
                incoming_is_canonical = canonical == alias_value
                if current_is_canonical or not incoming_is_canonical:
                    logger.warning(
                        "firm-intel alias conflict: preserving %s owner %s over %s",
                        alias_value,
                        row.firm_id,
                        firm_id,
                    )
                    continue
            row.firm_id = firm_id
            row.synced_at = now
        touched += 1
    return touched


async def _upsert_profile(session, profile: dict[str, Any], *, now: datetime) -> tuple[str, int, str | None]:
    is_extraction = bool(profile.get("extraction_id"))
    firm_id = str(profile.get("extraction_id") or profile.get("firm_id") or "").strip()
    if not firm_id:
        return "skipped", 0, None
    linked_firm_id = await _firm_id_by_local_alias(session, firm_id) if is_extraction else None
    row = await session.get(PifFirmRow, linked_firm_id or firm_id)
    status = "updated"
    if row is None:
        canonical = _profile_website(profile)
        existing_id = await _firm_id_by_website(session, canonical) if canonical else None
        existing = await session.get(PifFirmRow, existing_id) if existing_id else None
        if existing is not None and existing.profile_source == "manual":
            row = existing
        else:
            row = PifFirmRow(id=firm_id, created_at=now)
            status = "created"
            session.add(row)
    if is_extraction:
        _apply_extraction(row, profile, now=now)
        alias_profile = _extraction_alias_profile(profile, row.id)
    else:
        _apply_v2_profile(row, profile, now=now)
        alias_profile = profile
    manual_overrides = (
        row.source_json.get("_possibleos_manual_overrides")
        if isinstance(row.source_json, dict)
        else None
    )
    if isinstance(manual_overrides, dict) and isinstance(manual_overrides.get("aliases"), dict):
        alias_profile = deepcopy(profile)
        alias_profile["canonical_website"] = row.canonical_website or row.website
        alias_profile["aliases"] = deepcopy(manual_overrides["aliases"])
        alias_profile["people"] = []
    if row.id != firm_id:
        alias_profile = deepcopy(profile)
        alias_profile["firm_id"] = row.id
        aliases_block = _as_dict(alias_profile.get("aliases"))
        legacy_ids = _as_list(aliases_block.get("legacy_pif_ids"))
        aliases_block["legacy_pif_ids"] = _distinct([*legacy_ids, firm_id])
        alias_profile["aliases"] = aliases_block
    aliases = await _upsert_aliases(session, alias_profile, now=now)
    return status, aliases, row.id


async def sync_firm_intel(
    *, full: bool = False, limit: int | None = None, restart: bool = False
) -> dict[str, Any]:
    """Sync raw EmailTag PIF extraction deltas into the local mirror.

    Full crawls are resumable: an interrupted run saves its cursor (and the
    max watermark seen so far) in the state row, and the next full run picks
    up from there instead of re-crawling from page 0 — the upstream feed
    tolerates only a bounded number of requests per session, so restarting
    from scratch can starve the tail forever. `restart=True` discards a saved
    resume point.
    """
    await ensure_firm_intel_tables()
    now = _utcnow()
    limit_value = None if limit is None else max(0, int(limit))
    fetched = created = updated = skipped = pages = aliases_touched = 0
    total_reported = 0
    max_watermark: datetime | None = None
    stopped_by_limit_with_more = False
    sync_items: list[dict[str, Any]] = []
    dirty_firm_ids: list[str] = []
    feed_path = "/extractions"

    async with AsyncSessionLocal() as session:
        state = await session.get(FirmIntelSyncStateRow, 1)
        if state is None:
            state = FirmIntelSyncStateRow(id=1, last_result={})
            session.add(state)
        updated_since = None if full else state.last_updated_since

        resumed_from: str | None = None
        cursor: str | None = None
        if full and limit_value is None and not restart:
            last = state.last_result if isinstance(state.last_result, dict) else {}
            resumed_from = str(last.get("resume_cursor") or "").strip() or None
            if resumed_from:
                cursor = resumed_from
                max_watermark = _parse_dt(last.get("resume_watermark"))
                logger.info("firm_intel sync resuming full crawl from cursor %s", resumed_from)

        async def _save_resume_point() -> None:
            """Persist crawl position so the next full run continues here."""
            if not (full and limit_value is None):
                return
            saved = dict(state.last_result) if isinstance(state.last_result, dict) else {}
            saved["resume_cursor"] = cursor
            saved["resume_watermark"] = _dt_iso(max_watermark)
            state.last_result = saved
            state.last_synced_at = now
            await session.commit()

        async with httpx.AsyncClient(
            base_url=FIRM_INTEL_BASE_URL,
            timeout=60.0,
            headers=_auth_headers(),
        ) as client:
            while True:
                if limit_value is not None and fetched >= limit_value:
                    break
                page_limit = _page_size()
                if limit_value is not None:
                    page_limit = max(1, min(page_limit, limit_value - fetched))
                params: dict[str, Any] = {"limit": page_limit}
                if updated_since is not None:
                    params["updated_since"] = _dt_iso(updated_since)
                if cursor:
                    params["cursor"] = cursor

                try:
                    resp = await _get_with_retry(client, feed_path, params)
                    if resp.status_code == 404 and feed_path == "/extractions" and pages == 0:
                        feed_path = "/firms"
                        logger.warning(
                            "EmailTag extraction feed is not deployed yet; using the legacy read-only firm feed"
                        )
                        resp = await _get_with_retry(client, feed_path, params)
                    resp.raise_for_status()
                except Exception:
                    await _save_resume_point()
                    raise
                data = resp.json()
                items = [item for item in _as_list(data.get("items")) if isinstance(item, dict)]
                total_reported = int(data.get("total") or total_reported or 0)
                pages += 1

                if not items:
                    break

                for profile in items:
                    if limit_value is not None and fetched >= limit_value:
                        break
                    status, alias_count, local_firm_id = await _upsert_profile(session, profile, now=now)
                    aliases_touched += alias_count
                    if status == "created":
                        created += 1
                    elif status == "updated":
                        updated += 1
                    else:
                        skipped += 1
                    fetched += 1
                    watermark = _profile_watermark(profile)
                    if watermark and (max_watermark is None or watermark > max_watermark):
                        max_watermark = watermark
                    source_firm_id = str(profile.get("extraction_id") or profile.get("firm_id") or "").strip()
                    firm_id = local_firm_id or source_firm_id
                    if profile.get("extraction_id") and firm_id and firm_id not in dirty_firm_ids:
                        dirty_firm_ids.append(firm_id)
                    if firm_id and len(sync_items) < SYNC_DETAIL_LIMIT:
                        sync_items.append({
                            "firm_id": firm_id,
                            "source_firm_id": source_firm_id if source_firm_id != firm_id else None,
                            "firm_name": profile.get("firm_name") or firm_id,
                            "status": status,
                            "canonical_website": (
                                (await session.get(PifFirmRow, firm_id)).canonical_website
                                if firm_id else None
                            ),
                            "source_updated_at": _dt_iso(_source_updated_at(profile)),
                            "people_count": len(_people(profile)),
                            "aliases_touched": alias_count,
                        })

                cursor = data.get("next_cursor") or None
                await session.commit()
                if limit_value is not None and fetched >= limit_value:
                    stopped_by_limit_with_more = bool(cursor)
                    break
                if not cursor:
                    break
                await asyncio.sleep(_page_pause())

        watermark_advanced = max_watermark is not None and not stopped_by_limit_with_more
        result = {
            "fetched": fetched,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "pages": pages,
            "aliases_touched": aliases_touched,
            "total_reported": total_reported,
            "synced_at": now.isoformat(),
            "full": bool(full),
            "limit": limit_value,
            "resumed_from": resumed_from,
            "previous_watermark": _dt_iso(updated_since),
            "candidate_watermark": _dt_iso(max_watermark),
            "watermark": _dt_iso(max_watermark if watermark_advanced else updated_since),
            "watermark_advanced": watermark_advanced,
            "stopped_by_limit_with_more": stopped_by_limit_with_more,
            "items": sync_items,
            "items_truncated": fetched > len(sync_items),
            "source_feed": feed_path,
        }
        if watermark_advanced:
            state.last_updated_since = max_watermark
        state.last_synced_at = now
        # A completed full crawl clears any resume point (result carries none);
        # limited/delta runs must not wipe a resume point saved by a failed
        # full crawl.
        previous = state.last_result if isinstance(state.last_result, dict) else {}
        if (not full or limit_value is not None) and previous.get("resume_cursor"):
            result["resume_cursor"] = previous["resume_cursor"]
            result["resume_watermark"] = previous.get("resume_watermark")
        state.last_result = result
        await session.commit()

    enrichment_queue = {"queued": [], "skipped": []}
    should_queue = bool(dirty_firm_ids) and (
        not full or os.getenv("PIF_ENRICH_ON_FULL_SYNC", "false").strip().lower() in {"1", "true", "yes", "on"}
    )
    if should_queue:
        from app.services.pif_local_enrichment import queue_dirty_firm_enrichment

        enrichment_queue = await queue_dirty_firm_enrichment(
            dirty_firm_ids,
            limit=max(1, int(os.getenv("PIF_LOCAL_ENRICHMENT_QUEUE_LIMIT", "100"))),
        )
    result["local_enrichment"] = enrichment_queue
    async with AsyncSessionLocal() as session:
        state = await session.get(FirmIntelSyncStateRow, 1)
        if state is not None:
            state.last_result = result
            await session.commit()
    logger.info("firm_intel sync: %s", result)
    return result


def _resolve_values(value: str) -> list[str]:
    raw = str(value or "").strip().lower()
    normalized = normalize_domain(raw)
    values = [raw]
    if normalized and normalized not in values:
        values.append(normalized)
    return [v for v in values if v]


async def _firm_id_by_local_alias(session, value: str) -> str | None:
    for alias_value in _resolve_values(value):
        for alias_type in ALIAS_TYPES:
            row = await session.get(
                FirmAliasRow,
                {"alias_type": alias_type, "alias_value": alias_value},
            )
            if row and row.firm_id:
                return str(row.firm_id)
    return None


async def _firm_id_by_website(session, value: str) -> str | None:
    domain = normalize_domain(value)
    if not domain:
        return None
    result = await session.execute(
        select(PifFirmRow.id, PifFirmRow.canonical_website, PifFirmRow.website)
    )
    for firm_id, canonical_website, website in result.all():
        if normalize_domain(canonical_website) == domain or normalize_domain(website) == domain:
            return str(firm_id)
    return None


async def resolve_firm_local(value: str) -> str | None:
    """Resolve a domain, email, URL, or legacy PIF ID using local mirror data only."""
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        firm_id = await _firm_id_by_local_alias(session, value)
        if firm_id:
            return firm_id
        return await _firm_id_by_website(session, value)


def _remote_resolve_params(value: str) -> dict[str, str]:
    raw = str(value or "").strip()
    if "@" in raw:
        return {"email": raw}
    domain = normalize_domain(raw)
    if domain and ("." in domain or "/" in raw or "://" in raw):
        return {"domain": domain}
    return {"legacy_pif_id": raw}


async def resolve_firm_remote(value: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(
        base_url=FIRM_INTEL_BASE_URL,
        timeout=30.0,
        headers=_auth_headers(),
    ) as client:
        resp = await client.get("/firms/resolve", params=_remote_resolve_params(value))
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        firm_id = data.get("firm_id")
        if firm_id and not data.get("firm_name"):
            profile_resp = await client.get(f"/firms/{firm_id}")
            if profile_resp.status_code < 400:
                profile = profile_resp.json()
                data["firm_name"] = profile.get("firm_name")
                data["canonical_website"] = profile.get("canonical_website")
        return data


async def get_local_firm_summary(value: str) -> dict[str, Any] | None:
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(PifFirmRow, str(value).strip())
        if row is None:
            firm_id = await _firm_id_by_local_alias(session, value) or await _firm_id_by_website(session, value)
            row = await session.get(PifFirmRow, firm_id) if firm_id else None
        if row is None:
            return None
        return {
            "firm_id": row.id,
            "firm_name": row.firm_name,
            "website": row.canonical_website or row.website,
            "metro": row.metro,
            "icp_tier": row.icp_tier,
            "warm_score": row.warm_score,
            "decision_makers": row.leadership or [],
            "vendor_stack": row.vendor_stack or {},
            "profile_source": row.profile_source,
        }


async def firm_intel_status() -> dict[str, Any]:
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(select(func.count()).select_from(PifFirmRow))).scalar_one() or 0)
        source_rows = (await session.execute(
            select(PifFirmRow.profile_source, func.count()).group_by(PifFirmRow.profile_source)
        )).all()
        alias_count = int((await session.execute(select(func.count()).select_from(FirmAliasRow))).scalar_one() or 0)
        state = await session.get(FirmIntelSyncStateRow, 1)

    remote_health: dict[str, Any]
    try:
        async with httpx.AsyncClient(
            base_url=FIRM_INTEL_BASE_URL,
            timeout=15.0,
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/health")
            resp.raise_for_status()
            remote_health = resp.json()
    except Exception as exc:
        remote_health = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    return {
        "total_firms": total,
        "profile_sources": {str(source or "unknown"): int(count) for source, count in source_rows},
        "alias_count": alias_count,
        "watermark": _dt_iso(state.last_updated_since) if state else None,
        "last_synced_at": _dt_iso(state.last_synced_at) if state else None,
        "last_result": state.last_result if state else {},
        "api_base": FIRM_INTEL_BASE_URL,
        "remote_health": remote_health,
    }


async def firm_intel_sync_status() -> dict[str, Any]:
    """Local-only mirror sync status for lightweight UI polling."""
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(select(func.count()).select_from(PifFirmRow))).scalar_one() or 0)
        alias_count = int((await session.execute(select(func.count()).select_from(FirmAliasRow))).scalar_one() or 0)
        state = await session.get(FirmIntelSyncStateRow, 1)
        last_result = dict(state.last_result) if state and isinstance(state.last_result, dict) else {}
        if "items" not in last_result and state and state.last_synced_at:
            rows = (await session.execute(
                select(
                    PifFirmRow.id,
                    PifFirmRow.firm_name,
                    PifFirmRow.canonical_website,
                    PifFirmRow.website,
                    PifFirmRow.source_updated_at,
                    PifFirmRow.contacts,
                )
                .where(PifFirmRow.synced_at == state.last_synced_at)
                .order_by(PifFirmRow.source_updated_at.desc().nullslast(), PifFirmRow.firm_name.asc())
                .limit(SYNC_DETAIL_LIMIT)
            )).all()
            created = int(last_result.get("created") or 0)
            updated = int(last_result.get("updated") or 0)
            inferred_status = (
                "created" if created and not updated
                else "updated" if updated and not created
                else "synced"
            )
            last_result["items"] = [
                {
                    "firm_id": firm_id,
                    "firm_name": firm_name or firm_id,
                    "status": inferred_status,
                    "canonical_website": canonical_website or website,
                    "source_updated_at": _dt_iso(source_updated_at),
                    "people_count": len(_as_list(contacts)),
                    "aliases_touched": None,
                }
                for firm_id, firm_name, canonical_website, website, source_updated_at, contacts in rows
            ]
            last_result["items_inferred"] = True
            last_result["items_truncated"] = int(last_result.get("fetched") or 0) > len(rows)

    return {
        "total_firms": total,
        "alias_count": alias_count,
        "watermark": _dt_iso(state.last_updated_since) if state else None,
        "last_synced_at": _dt_iso(state.last_synced_at) if state else None,
        "last_result": last_result,
        "api_base": FIRM_INTEL_BASE_URL,
    }


async def list_extracted_vendors() -> dict[str, Any]:
    """Return all vendor names currently extracted in the local EmailTag mirror."""
    await ensure_firm_intel_tables()
    vendor_sql = text("""
        WITH vendor_rows AS (
            SELECT id, lower(elem->>'vendor') AS vendor
            FROM pif_directory_firms
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(source_json->'vendor_stack') = 'array'
                    THEN source_json->'vendor_stack'
                    ELSE '[]'::jsonb
                END
            ) elem
            WHERE coalesce(elem->>'vendor', '') <> ''
              AND source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
            UNION
            SELECT id, lower(vendor_stack->>'case_mgmt') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(vendor_stack->>'case_mgmt', '') <> ''
            UNION
            SELECT f.id, lower(other.key) AS vendor
            FROM pif_directory_firms f
            CROSS JOIN LATERAL jsonb_each(
                CASE
                    WHEN jsonb_typeof(f.vendor_stack->'other') = 'object'
                    THEN f.vendor_stack->'other'
                    ELSE '{}'::jsonb
                END
            ) other
            WHERE coalesce(other.key, '') <> ''
            UNION
            SELECT id, lower(raw_json #>> '{vendor_stack,case_mgmt}') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(raw_json #>> '{vendor_stack,case_mgmt}', '') <> ''
              AND source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
            UNION
            SELECT f.id, lower(other.key) AS vendor
            FROM pif_directory_firms f
            CROSS JOIN LATERAL jsonb_each(
                CASE
                    WHEN jsonb_typeof(f.raw_json #> '{vendor_stack,other}') = 'object'
                    THEN f.raw_json #> '{vendor_stack,other}'
                    ELSE '{}'::jsonb
                END
            ) other
            WHERE coalesce(other.key, '') <> ''
              AND f.source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
        )
        SELECT vendor, count(DISTINCT id) AS firm_count
        FROM vendor_rows
        WHERE vendor <> ''
        GROUP BY vendor
        ORDER BY firm_count DESC, vendor ASC
    """)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(vendor_sql)).all()

    vendors = [
        {"vendor": vendor, "label": _vendor_label(vendor), "count": int(count)}
        for vendor, count in rows
    ]
    return {"vendors": vendors, "total_vendors": len(vendors), "total_firms": sum(item["count"] for item in vendors)}


async def _firm_ids_for_vendor(vendor: str) -> set[str]:
    wanted = _vendor_key(vendor)
    if not wanted:
        return set()
    cached = _vendor_firm_ids_cache.get(wanted)
    now = time_module.monotonic()
    if cached and cached[0] > now:
        return set(cached[1])
    vendor_sql = text("""
        WITH vendor_rows AS (
            SELECT id, lower(elem->>'vendor') AS vendor
            FROM pif_directory_firms
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(source_json->'vendor_stack') = 'array'
                    THEN source_json->'vendor_stack'
                    ELSE '[]'::jsonb
                END
            ) elem
            WHERE coalesce(elem->>'vendor', '') <> ''
              AND source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
            UNION
            SELECT id, lower(vendor_stack->>'case_mgmt') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(vendor_stack->>'case_mgmt', '') <> ''
            UNION
            SELECT f.id, lower(other.key) AS vendor
            FROM pif_directory_firms f
            CROSS JOIN LATERAL jsonb_each(
                CASE
                    WHEN jsonb_typeof(f.vendor_stack->'other') = 'object'
                    THEN f.vendor_stack->'other'
                    ELSE '{}'::jsonb
                END
            ) other
            WHERE coalesce(other.key, '') <> ''
            UNION
            SELECT id, lower(raw_json #>> '{vendor_stack,case_mgmt}') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(raw_json #>> '{vendor_stack,case_mgmt}', '') <> ''
              AND source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
            UNION
            SELECT f.id, lower(other.key) AS vendor
            FROM pif_directory_firms f
            CROSS JOIN LATERAL jsonb_each(
                CASE
                    WHEN jsonb_typeof(f.raw_json #> '{vendor_stack,other}') = 'object'
                    THEN f.raw_json #> '{vendor_stack,other}'
                    ELSE '{}'::jsonb
                END
            ) other
            WHERE coalesce(other.key, '') <> ''
              AND f.source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
        )
        SELECT DISTINCT id
        FROM vendor_rows
        WHERE vendor = :vendor
    """)
    async with AsyncSessionLocal() as session:
        firm_ids = {
            str(row[0])
            for row in (await session.execute(vendor_sql, {"vendor": wanted})).all()
        }
    _vendor_firm_ids_cache[wanted] = (
        now + _VENDOR_FIRM_IDS_CACHE_SECONDS,
        firm_ids,
    )
    return set(firm_ids)


async def _firm_ids_with_any_vendor() -> set[str]:
    vendor_sql = text("""
        WITH vendor_rows AS (
            SELECT id, lower(elem->>'vendor') AS vendor
            FROM pif_directory_firms
            CROSS JOIN LATERAL jsonb_array_elements(
                CASE
                    WHEN jsonb_typeof(source_json->'vendor_stack') = 'array'
                    THEN source_json->'vendor_stack'
                    ELSE '[]'::jsonb
                END
            ) elem
            WHERE coalesce(elem->>'vendor', '') <> ''
              AND source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
            UNION
            SELECT id, lower(vendor_stack->>'case_mgmt') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(vendor_stack->>'case_mgmt', '') <> ''
            UNION
            SELECT f.id, lower(other.key) AS vendor
            FROM pif_directory_firms f
            CROSS JOIN LATERAL jsonb_each(
                CASE
                    WHEN jsonb_typeof(f.vendor_stack->'other') = 'object'
                    THEN f.vendor_stack->'other'
                    ELSE '{}'::jsonb
                END
            ) other
            WHERE coalesce(other.key, '') <> ''
            UNION
            SELECT id, lower(raw_json #>> '{vendor_stack,case_mgmt}') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(raw_json #>> '{vendor_stack,case_mgmt}', '') <> ''
              AND source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
            UNION
            SELECT f.id, lower(other.key) AS vendor
            FROM pif_directory_firms f
            CROSS JOIN LATERAL jsonb_each(
                CASE
                    WHEN jsonb_typeof(f.raw_json #> '{vendor_stack,other}') = 'object'
                    THEN f.raw_json #> '{vendor_stack,other}'
                    ELSE '{}'::jsonb
                END
            ) other
            WHERE coalesce(other.key, '') <> ''
              AND f.source_json #> '{_possibleos_manual_overrides,vendor_stack}' IS NULL
        )
        SELECT DISTINCT id
        FROM vendor_rows
        WHERE vendor <> ''
    """)
    async with AsyncSessionLocal() as session:
        return {str(row[0]) for row in (await session.execute(vendor_sql)).all()}


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _source_value(row: PifFirmRow, key: str) -> Any:
    source = row.source_json if isinstance(row.source_json, dict) else {}
    raw_source = _source_record(row.raw_json if isinstance(row.raw_json, dict) else {})
    return source.get(key, raw_source.get(key))


def _serialize_pif_row(row: PifFirmRow) -> dict[str, Any]:
    source = row.source_json if isinstance(row.source_json, dict) else {}
    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    return {
        "id": row.id,
        "firm_name": row.firm_name or "",
        "entity_type": row.entity_type or "",
        "metro": row.metro,
        "profile_source": row.profile_source,
        "manually_added": bool(row.manually_added),
        "operator_managed": bool(row.manually_added or source.get("operator_managed")),
        "website": row.website,
        "canonical_website": row.canonical_website,
        "website_status": _source_value(row, "website_status"),
        "website_source": _source_value(row, "website_source"),
        "website_confidence": _source_value(row, "website_confidence"),
        "emails": row.emails or [],
        "phones": row.phones or [],
        "fax": row.fax,
        "addresses": row.addresses or [],
        "contacts": row.contacts or [],
        "first_contacted_precise_at": _dt_to_iso(row.first_contacted_precise_at),
        "conversation_ids": row.conversation_ids or source.get("conversation_ids") or [],
        "extraction_notes": row.extraction_notes,
        "leadership": row.leadership or [],
        "research_data": row.research_data or None,
        "research_status": row.research_status,
        "last_researched_at": _dt_to_iso(row.last_researched_at),
        "staff": row.staff or [],
        "staff_research_status": row.staff_research_status,
        "behavioral_data": row.behavioral_data or None,
        "icp_score": row.icp_score,
        "icp_tier": row.icp_tier,
        "score_breakdown": row.score_breakdown or None,
        "icp_scored_at": _dt_to_iso(row.icp_scored_at),
        "vendor_stack": _vendor_entries_for_row(row) or None,
        "aliases": raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {},
        "provenance": raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {},
        "created_at": _dt_to_iso(row.source_created_at or row.created_at) or "",
        "updated_at": _dt_to_iso(row.source_updated_at or row.updated_at) or "",
    }


def _person_value(person: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = person.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _has_contact_email(value: Any) -> bool:
    email = str(value or "").strip()
    if email.lower() in {"null", "none", "n/a", "na", "unknown", "-"}:
        return False
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def _person_matches(value: str | None, needle: str | None) -> bool:
    if not needle or not needle.strip():
        return True
    return needle.strip().lower() in str(value or "").lower()


def _people_filter_values(values: str | list[str] | None) -> list[str]:
    if isinstance(values, str):
        values = [values]
    return [value.strip() for value in (values or []) if value and value.strip()]


def _person_matches_any(value: str | None, needles: str | list[str] | None) -> bool:
    filters = _people_filter_values(needles)
    return not filters or any(_person_matches(value, needle) for needle in filters)


@lru_cache(maxsize=8192)
def _role_from_title(title: str | None) -> str | None:
    return classify_contact(title, None, None)[0]


@lru_cache(maxsize=8192)
def _role_from_email(email: str | None) -> str | None:
    return classify_contact(None, email, None)[0]


def _derived_role_category(title: str | None, email: str | None, name: str | None) -> str | None:
    del name
    return _role_from_title(title) or _role_from_email(email)


def _people_for_row(row: PifFirmRow) -> list[dict[str, Any]]:
    """Flatten local mirrored people, preferring classified leadership/staff rows."""
    people: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_many(source: str, raw_people: Any) -> None:
        for person in _as_list(raw_people):
            if not isinstance(person, dict):
                continue
            name = _person_value(person, "name", "full_name")
            title = _person_value(person, "title", "job_title", "position")
            email = _person_value(person, "email")
            phone = _person_value(person, "phone")
            linkedin = _person_value(person, "linkedin", "linkedin_url")
            role_category = _person_value(person, "role_category", "persona", "role")
            if not role_category:
                role_category = _derived_role_category(title, email, name)
            if not any((name, title, email, phone, linkedin)):
                continue
            dedupe_key = (email or f"{name or ''}|{title or ''}").strip().lower()
            if not dedupe_key:
                continue
            scoped_key = f"{row.id}:{dedupe_key}"
            if scoped_key in seen:
                continue
            seen.add(scoped_key)
            is_decision_maker = bool(person.get("is_decision_maker")) or source == "leadership"
            people.append({
                "name": name or email or phone or "Unknown contact",
                "title": title or "",
                "role_category": role_category,
                "source": source,
                "firm_name": row.firm_name,
                "firm_id": row.id,
                "email": email,
                "phone": phone,
                "linkedin": linkedin,
                "bio": _person_value(person, "bio"),
                "is_decision_maker": is_decision_maker,
                "updated_at": _dt_to_iso(row.source_updated_at or row.updated_at),
            })

    add_many("leadership", row.leadership)
    add_many("staff", row.staff)
    add_many("contacts", row.contacts)
    return people


def _people_option_counts(people: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for person in people:
        value = str(person.get(key) or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    ]


async def list_mirrored_pif_people_filter_options() -> dict[str, Any]:
    """Return local mirrored contact filter values with counts."""
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(
            PifFirmRow.id,
            PifFirmRow.firm_name,
            PifFirmRow.contacts,
            PifFirmRow.leadership,
            PifFirmRow.staff,
            PifFirmRow.source_updated_at,
            PifFirmRow.updated_at,
        ))).all()

    people: list[dict[str, Any]] = []
    for row in rows:
        people.extend(_people_for_row(row))

    titles = _people_option_counts(people, "title")
    roles = _people_option_counts(people, "role_category")
    return {
        "titles": titles,
        "roles": roles,
        "total_titles": len(titles),
        "total_roles": len(roles),
        "total_people": len(people),
    }


async def list_mirrored_pif_people(
    *,
    name: str | None = None,
    firm: str | None = None,
    vendor: str | None = None,
    title: str | list[str] | None = None,
    role_category: str | list[str] | None = None,
    source: str | None = "all",
    leader: str | None = "any",
    email_presence: str | None = "any",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """List people extracted into the local EmailTag firm mirror."""
    await ensure_firm_intel_tables()
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    source_filter = (source or "all").strip().lower()
    leader_filter = (leader or "any").strip().lower()
    email_filter = (email_presence or "any").strip().lower()
    if source_filter not in {"all", "leadership", "staff", "contacts"}:
        raise ValueError(f"unsupported_contact_source:{source_filter}")
    if leader_filter not in {"any", "leader", "non_leader"}:
        raise ValueError(f"unsupported_leader_filter:{leader_filter}")
    if email_filter not in {"any", "has", "missing"}:
        raise ValueError(f"unsupported_email_presence:{email_filter}")
    vendor_ids = await _firm_ids_for_vendor(vendor) if vendor and vendor.strip() else None
    if vendor_ids is not None and not vendor_ids:
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
        }

    conditions = []
    if vendor_ids is not None:
        conditions.append(PifFirmRow.id.in_(vendor_ids))
    if firm and firm.strip():
        needle = f"%{firm.strip().lower()}%"
        conditions.append(or_(
            func.lower(PifFirmRow.id).like(needle),
            func.lower(PifFirmRow.firm_name).like(needle),
        ))

    candidate_people: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        if source_filter == "leadership":
            sql = """
                SELECT f.id, f.firm_name, f.source_updated_at, f.updated_at, person.value AS person
                FROM pif_directory_firms f
                CROSS JOIN LATERAL jsonb_array_elements(COALESCE(f.leadership, '[]'::jsonb)) person(value)
            """
            params: dict[str, Any] = {}
            if vendor_ids is not None:
                sql += " WHERE f.id IN :vendor_ids"
                params["vendor_ids"] = sorted(vendor_ids)
            sql += " ORDER BY f.source_updated_at DESC NULLS LAST, f.firm_name ASC"
            stmt = text(sql)
            if vendor_ids is not None:
                stmt = stmt.bindparams(bindparam("vendor_ids", expanding=True))
            rows = (await session.execute(stmt, params)).all()
            grouped: dict[str, SimpleNamespace] = {}
            for row in rows:
                people_row = grouped.setdefault(row.id, SimpleNamespace(
                    id=row.id,
                    firm_name=row.firm_name,
                    contacts=[],
                    leadership=[],
                    staff=[],
                    source_updated_at=row.source_updated_at,
                    updated_at=row.updated_at,
                ))
                people_row.leadership.append(row.person)
            for people_row in grouped.values():
                candidate_people.extend(_people_for_row(people_row))
        else:
            columns = [PifFirmRow.id, PifFirmRow.firm_name]
            if source_filter in {"all", "contacts"}:
                columns.append(PifFirmRow.contacts)
            if source_filter == "all":
                columns.append(PifFirmRow.leadership)
            if source_filter in {"all", "staff"}:
                columns.append(PifFirmRow.staff)
            columns.extend([PifFirmRow.source_updated_at, PifFirmRow.updated_at])
            stmt = select(*columns).order_by(
                PifFirmRow.source_updated_at.desc().nullslast(),
                PifFirmRow.firm_name.asc(),
            )
            if conditions:
                stmt = stmt.where(*conditions)
            rows = (await session.execute(stmt)).all()
            for row in rows:
                people_row = SimpleNamespace(
                    id=row.id,
                    firm_name=row.firm_name,
                    contacts=getattr(row, "contacts", []),
                    leadership=getattr(row, "leadership", []),
                    staff=getattr(row, "staff", []),
                    source_updated_at=row.source_updated_at,
                    updated_at=row.updated_at,
                )
                candidate_people.extend(_people_for_row(people_row))

    people: list[dict[str, Any]] = []
    for person in candidate_people:
        if source_filter != "all" and person.get("source") != source_filter:
            continue
        is_leader = bool(person.get("is_decision_maker"))
        if leader_filter == "leader" and not is_leader:
            continue
        if leader_filter == "non_leader" and is_leader:
            continue
        has_email = _has_contact_email(person.get("email"))
        if email_filter == "has" and not has_email:
            continue
        if email_filter == "missing" and has_email:
            continue
        if not _person_matches(person.get("name"), name):
            continue
        if not _person_matches(person.get("firm_name"), firm):
            continue
        if not _person_matches_any(person.get("title"), title):
            continue
        role_filters = _people_filter_values(role_category)
        if role_filters and not any(
            _person_matches(person.get("role_category"), role)
            or _person_matches(person.get("title"), role)
            for role in role_filters
        ):
            continue
        people.append(person)

    total = len(people)
    start = (page - 1) * page_size
    return {
        "items": people[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


async def list_mirrored_pif_job_postings(
    *,
    search: str | None = None,
    role_category: str | None = None,
    trigger_tag: str | None = None,
    technology: str | None = None,
    gtm_relevance: str | None = None,
    global_remote: bool | None = None,
    posted_within_days: int | None = None,
    order: str = "posted_desc",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """List individual, locally stored job postings without firm-detail payloads."""
    await ensure_firm_intel_tables()
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    relevance = (gtm_relevance or "").strip().lower()
    ordering = (order or "posted_desc").strip().lower()
    if relevance and relevance not in {"high", "medium", "low"}:
        raise ValueError(f"unsupported_gtm_relevance:{relevance}")
    if ordering not in {"posted_desc", "found_desc"}:
        raise ValueError(f"unsupported_job_posting_order:{ordering}")

    sql = """
        SELECT
            f.id AS firm_id,
            f.firm_name,
            f.entity_type,
            COALESCE(f.canonical_website, f.website) AS website,
            f.updated_at,
            COALESCE(
                NULLIF(f.research_data->'job_postings'->>'researched_at', '')::timestamptz,
                NULLIF(f.research_data->>'last_job_postings_researched_at', '')::timestamptz
            ) AS found_at,
            posting.value AS posting
        FROM pif_directory_firms f
        CROSS JOIN LATERAL jsonb_array_elements(
            COALESCE(f.research_data->'job_postings'->'postings', '[]'::jsonb)
        ) posting(value)
        WHERE COALESCE(f.source_json->>'merged_into', '') = ''
    """
    params: dict[str, Any] = {}
    if search and search.strip():
        params["search"] = f"%{search.strip()}%"
        sql += """
            AND (
                f.firm_name ILIKE :search
                OR COALESCE(posting.value->>'title', '') ILIKE :search
                OR COALESCE(posting.value->>'description_summary', '') ILIKE :search
            )
        """
    if role_category and role_category.strip():
        params["role_category"] = role_category.strip().lower()
        sql += " AND COALESCE(posting.value->>'role_category', '') = :role_category"
    if trigger_tag and trigger_tag.strip():
        params["trigger_tag"] = trigger_tag.strip().lower()
        sql += " AND COALESCE(posting.value->'trigger_tags', '[]'::jsonb) ? :trigger_tag"
    if technology and technology.strip():
        params["technology"] = f"%{technology.strip().lower()}%"
        sql += " AND LOWER(COALESCE(posting.value->'technology_mentions', '[]'::jsonb)::text) LIKE :technology"
    if relevance:
        params["gtm_relevance"] = relevance
        sql += " AND COALESCE(posting.value->>'gtm_relevance', '') = :gtm_relevance"
    if global_remote is not None:
        params["global_remote"] = "true" if global_remote else "false"
        sql += " AND COALESCE(posting.value->>'global_remote', 'false') = :global_remote"
    if posted_within_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, posted_within_days))).date().isoformat()
        params["posted_after"] = cutoff
        sql += " AND NULLIF(posting.value->>'posted_date', '') >= :posted_after"

    count_sql = f"SELECT COUNT(*) FROM ({sql}) job_postings"
    order_sql = (
        "found_at DESC NULLS LAST, NULLIF(posting.value->>'posted_date', '') DESC NULLS LAST"
        if ordering == "found_desc"
        else "NULLIF(posting.value->>'posted_date', '') DESC NULLS LAST, found_at DESC NULLS LAST"
    )
    list_sql = f"""
        {sql}
        ORDER BY {order_sql}, f.firm_name ASC, posting.value->>'title' ASC
        LIMIT :limit OFFSET :offset
    """
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(text(count_sql), params)).scalar_one() or 0)
        rows = (await session.execute(text(list_sql), {
            **params,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        })).all()

    items = []
    for row in rows:
        posting = row.posting if isinstance(row.posting, dict) else {}
        items.append({
            "firm_id": row.firm_id,
            "firm_name": row.firm_name,
            "entity_type": row.entity_type,
            "website": row.website,
            "updated_at": _dt_iso(row.updated_at),
            "found_at": _dt_iso(row.found_at),
            "title": str(posting.get("title") or ""),
            "location": posting.get("location"),
            "employment_type": posting.get("employment_type"),
            "remote_eligibility": posting.get("remote_eligibility"),
            "posted_date": posting.get("posted_date"),
            "description_summary": str(posting.get("description_summary") or ""),
            "source_name": str(posting.get("source_name") or "Web source"),
            "source_url": str(posting.get("source_url") or ""),
            "role_category": posting.get("role_category"),
            "trigger_tags": posting.get("trigger_tags") if isinstance(posting.get("trigger_tags"), list) else [],
            "technology_mentions": posting.get("technology_mentions") if isinstance(posting.get("technology_mentions"), list) else [],
            "gtm_relevance": posting.get("gtm_relevance"),
            "classification_confidence": posting.get("classification_confidence"),
            "work_arrangement": posting.get("work_arrangement"),
            "remote_scope": posting.get("remote_scope"),
            "global_remote": bool(posting.get("global_remote")),
            "global_remote_evidence": posting.get("global_remote_evidence") if isinstance(posting.get("global_remote_evidence"), list) else [],
            "global_remote_confidence": posting.get("global_remote_confidence"),
        })
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


def _row_matches_presence(row: PifFirmRow, field: str, value: str | None) -> bool:
    if value in (None, "", "any"):
        return True
    if field == "website_presence":
        has_website = bool(row.canonical_website or row.website or _source_value(row, "website_status") == "resolved")
        if value == "has":
            return has_website
        if value == "missing":
            return not has_website
        if value == "resolved":
            return _source_value(row, "website_status") == "resolved"
        if value == "unresolved":
            return _source_value(row, "website_status") != "resolved"
    if field == "research_presence":
        status = row.research_status
        if value == "completed":
            return status in STATUS_COMPLETED
        if value == "missing":
            return status not in {*STATUS_COMPLETED, *STATUS_RUNNING, "failed"}
        if value == "queued_or_running":
            return status in STATUS_RUNNING
        if value == "failed":
            return status == "failed"
    if field == "staff_presence":
        status = row.staff_research_status
        if value == "completed":
            return status in STATUS_COMPLETED
        if value == "missing":
            return status not in {*STATUS_COMPLETED, *STATUS_RUNNING, "failed"}
        if value == "queued_or_running":
            return status in STATUS_RUNNING
        if value == "failed":
            return status == "failed"
    if field == "job_postings_presence":
        research_data = row.research_data if isinstance(row.research_data, dict) else {}
        status = research_data.get("job_postings_research_status")
        job_postings = research_data.get("job_postings")
        job_postings = job_postings if isinstance(job_postings, dict) else {}
        has_recent = bool(job_postings.get("has_recent_openings") or job_postings.get("postings"))
        if value == "has":
            return has_recent
        if value == "none":
            return status in STATUS_COMPLETED and not has_recent
        if value == "not_researched":
            return status not in {*STATUS_COMPLETED, *STATUS_RUNNING, "failed"}
        if value == "queued_or_running":
            return status in STATUS_RUNNING
        if value == "failed":
            return status == "failed"
    if field == "behavior_presence":
        has_value = bool(row.behavioral_data)
        return has_value if value == "has" else not has_value if value == "missing" else True
    if field == "icp_presence":
        has_value = row.icp_score is not None
        return has_value if value == "has" else not has_value if value == "missing" else True
    if field == "vendor_presence":
        has_value = _row_has_vendor(row)
        return has_value if value == "has" else not has_value if value == "missing" else True
    return True


def _row_matches_search(row: PifFirmRow, search: str | None) -> bool:
    if not search:
        return True
    needle = search.strip().lower()
    if not needle:
        return True
    haystack = [
        row.firm_name,
        row.website,
        row.canonical_website,
        *(row.emails or []),
        *(row.phones or []),
    ]
    return any(needle in str(value or "").lower() for value in haystack)


def _row_matches_dates(
    row: PifFirmRow,
    *,
    recently_researched: int | None = None,
    first_contacted_from: date | None = None,
    first_contacted_to: date | None = None,
) -> bool:
    if recently_researched is not None:
        if row.last_researched_at is None:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(days=recently_researched)
        if row.last_researched_at < cutoff:
            return False
    if first_contacted_from is not None:
        start = datetime.combine(first_contacted_from, time.min, tzinfo=timezone.utc)
        if row.first_contacted_precise_at is None or row.first_contacted_precise_at < start:
            return False
    if first_contacted_to is not None:
        end = datetime.combine(first_contacted_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        if row.first_contacted_precise_at is None or row.first_contacted_precise_at >= end:
            return False
    return True


async def list_mirrored_pif_firms(
    *,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str | None = "updated_at",
    research_status: str | None = None,
    icp_tier: str | None = None,
    entity_type: str | None = None,
    recently_researched: int | None = None,
    contact_email_min: int | None = None,
    contact_email_max: int | None = None,
    staff_count_min: int | None = None,
    staff_count_max: int | None = None,
    autorespond_window: str | None = None,
    autorespond_type: str | None = None,
    website_presence: str | None = None,
    research_presence: str | None = None,
    staff_presence: str | None = None,
    job_postings_presence: str | None = None,
    job_posting_role: str | None = None,
    job_posting_tag: str | None = None,
    job_posting_query: str | None = None,
    job_posted_within_days: int | None = None,
    behavior_presence: str | None = None,
    icp_presence: str | None = None,
    vendor_presence: str | None = None,
    vendor: str | None = None,
    manually_added: bool | None = None,
    first_contacted_from: date | None = None,
    first_contacted_to: date | None = None,
    active_only: bool = True,
) -> dict[str, Any]:
    """List local mirror rows, including vendor-name filtering absent upstream."""
    await ensure_firm_intel_tables()
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))

    vendor_ids = await _firm_ids_for_vendor(vendor) if vendor else None
    if vendor_ids is not None and not vendor_ids:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    any_vendor_ids: set[str] | None = None
    if vendor_presence in {"has", "missing"} and vendor_ids is None:
        any_vendor_ids = await _firm_ids_with_any_vendor()

    conditions = []
    if active_only:
        merged_into = PifFirmRow.source_json["merged_into"].astext
        conditions.append(or_(merged_into.is_(None), merged_into == ""))
    if vendor_ids is not None:
        conditions.append(PifFirmRow.id.in_(vendor_ids))
    elif vendor_presence == "has":
        if not any_vendor_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}
        conditions.append(PifFirmRow.id.in_(any_vendor_ids))
    elif vendor_presence == "missing" and any_vendor_ids:
        conditions.append(PifFirmRow.id.notin_(any_vendor_ids))

    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        conditions.append(or_(
            func.lower(PifFirmRow.firm_name).like(needle),
            func.lower(PifFirmRow.website).like(needle),
            func.lower(PifFirmRow.canonical_website).like(needle),
            func.lower(cast(PifFirmRow.emails, String)).like(needle),
            func.lower(cast(PifFirmRow.phones, String)).like(needle),
        ))
    if research_status:
        conditions.append(PifFirmRow.research_status == research_status)
    if icp_tier:
        conditions.append(PifFirmRow.icp_tier == icp_tier)
    if entity_type:
        conditions.append(PifFirmRow.entity_type == entity_type)
    if manually_added is not None:
        conditions.append(PifFirmRow.manually_added.is_(manually_added))
    if recently_researched is not None:
        conditions.append(PifFirmRow.last_researched_at >= datetime.now(timezone.utc) - timedelta(days=recently_researched))
    email_count = func.jsonb_array_length(PifFirmRow.emails)
    staff_count = func.jsonb_array_length(PifFirmRow.staff)
    if contact_email_min is not None:
        conditions.append(email_count >= contact_email_min)
    if contact_email_max is not None:
        conditions.append(email_count <= contact_email_max)
    if staff_count_min is not None:
        conditions.append(staff_count >= staff_count_min)
    if staff_count_max is not None:
        conditions.append(staff_count <= staff_count_max)
    if autorespond_window and autorespond_window != "any":
        event_conditions = [
            PifAutorespondEventRow.canonical_pif_id == PifFirmRow.id,
            PifAutorespondEventRow.response_sent.is_(True),
            PifAutorespondEventRow.test_mode.is_(False),
        ]
        if autorespond_type:
            event_conditions.append(PifAutorespondEventRow.agent_type == autorespond_type)
        window_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(autorespond_window)
        if window_days is not None:
            event_conditions.append(
                PifAutorespondEventRow.event_created_at >= datetime.now(timezone.utc) - timedelta(days=window_days)
            )
        has_event = exists(select(PifAutorespondEventRow.id).where(*event_conditions))
        conditions.append(~has_event if autorespond_window == "never" else has_event)
    elif autorespond_type:
        conditions.append(exists(select(PifAutorespondEventRow.id).where(
            PifAutorespondEventRow.canonical_pif_id == PifFirmRow.id,
            PifAutorespondEventRow.response_sent.is_(True),
            PifAutorespondEventRow.test_mode.is_(False),
            PifAutorespondEventRow.agent_type == autorespond_type,
        )))
    if first_contacted_from is not None:
        conditions.append(PifFirmRow.first_contacted_precise_at >= datetime.combine(first_contacted_from, time.min, tzinfo=timezone.utc))
    if first_contacted_to is not None:
        conditions.append(PifFirmRow.first_contacted_precise_at < datetime.combine(first_contacted_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    postings_text = func.lower(cast(PifFirmRow.research_data["job_postings"]["postings"], String))
    role_categories = {
        "intake": ("intake_conversion",),
        "marketing": ("marketing_growth",),
        "case_operations": ("case_operations", "attorney_legal", "client_communication"),
        "firm_operations": ("firm_operations", "finance_billing", "executive_leadership"),
        "technology": ("technology_data",),
    }
    selected_categories = role_categories.get(str(job_posting_role or "").strip().lower())
    if selected_categories:
        category_path = "$.job_postings.postings[*].role_category"
        conditions.append(or_(*(
            func.jsonb_path_exists(
                PifFirmRow.research_data,
                cast(f'{category_path} ? (@ == "{category}")', JSONPATH),
            )
            for category in selected_categories
        )))
    if job_posting_tag and job_posting_tag.strip():
        safe_tag = re.sub(r"[^a-z0-9_]", "", job_posting_tag.strip().lower())
        if safe_tag:
            conditions.append(func.jsonb_path_exists(
                PifFirmRow.research_data,
                cast(f'$.job_postings.postings[*].trigger_tags[*] ? (@ == "{safe_tag}")', JSONPATH),
            ))
    if job_posting_query and job_posting_query.strip():
        terms = list(dict.fromkeys(
            term.lower() for term in re.split(r"[\s,]+", job_posting_query.strip()) if term
        ))
        conditions.extend(postings_text.like(f"%{term}%") for term in terms)
    if job_posted_within_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, job_posted_within_days))).date()
        path = f'$.job_postings.postings[*] ? (@.posted_date >= "{cutoff.isoformat()}")'
        conditions.append(func.jsonb_path_exists(PifFirmRow.research_data, cast(path, JSONPATH)))

    for field, value in (
        ("website_presence", website_presence),
        ("research_presence", research_presence),
        ("staff_presence", staff_presence),
        ("job_postings_presence", job_postings_presence),
        ("behavior_presence", behavior_presence),
        ("icp_presence", icp_presence),
    ):
        if value in (None, "", "any"):
            continue
        if field == "website_presence":
            has_website = or_(
                PifFirmRow.canonical_website.isnot(None),
                PifFirmRow.website.isnot(None),
                PifFirmRow.source_json["website_status"].astext == "resolved",
            )
            if value == "has":
                conditions.append(has_website)
            elif value == "missing":
                conditions.append(~has_website)
            elif value == "resolved":
                conditions.append(PifFirmRow.source_json["website_status"].astext == "resolved")
            elif value == "unresolved":
                conditions.append(PifFirmRow.source_json["website_status"].astext != "resolved")
        elif field == "research_presence":
            if value == "completed":
                conditions.append(PifFirmRow.research_status.in_(list(STATUS_COMPLETED)))
            elif value == "missing":
                conditions.append(or_(PifFirmRow.research_status.is_(None), ~PifFirmRow.research_status.in_(list({*STATUS_COMPLETED, *STATUS_RUNNING, "failed"}))))
            elif value == "queued_or_running":
                conditions.append(PifFirmRow.research_status.in_(list(STATUS_RUNNING)))
            elif value == "failed":
                conditions.append(PifFirmRow.research_status == "failed")
        elif field == "staff_presence":
            if value == "completed":
                conditions.append(PifFirmRow.staff_research_status.in_(list(STATUS_COMPLETED)))
            elif value == "missing":
                conditions.append(or_(PifFirmRow.staff_research_status.is_(None), ~PifFirmRow.staff_research_status.in_(list({*STATUS_COMPLETED, *STATUS_RUNNING, "failed"}))))
            elif value == "queued_or_running":
                conditions.append(PifFirmRow.staff_research_status.in_(list(STATUS_RUNNING)))
            elif value == "failed":
                conditions.append(PifFirmRow.staff_research_status == "failed")
        elif field == "job_postings_presence":
            status = PifFirmRow.research_data["job_postings_research_status"].astext
            has_recent = PifFirmRow.research_data["job_postings"]["has_recent_openings"].astext
            has_postings = func.jsonb_path_exists(
                PifFirmRow.research_data,
                cast("$.job_postings.postings[*]", JSONPATH),
            )
            if value == "has":
                conditions.append(or_(has_recent == "true", has_postings))
            elif value == "none":
                conditions.append(and_(
                    status.in_(list(STATUS_COMPLETED)),
                    func.coalesce(has_recent, "false") != "true",
                    ~has_postings,
                ))
            elif value == "not_researched":
                conditions.append(or_(
                    status.is_(None),
                    ~status.in_(list({*STATUS_COMPLETED, *STATUS_RUNNING, "failed"})),
                ))
            elif value == "queued_or_running":
                conditions.append(status.in_(list(STATUS_RUNNING)))
            elif value == "failed":
                conditions.append(status == "failed")
        elif field == "behavior_presence":
            has_value = PifFirmRow.behavioral_data != {}
            conditions.append(has_value if value == "has" else ~has_value)
        elif field == "icp_presence":
            conditions.append(PifFirmRow.icp_score.isnot(None) if value == "has" else PifFirmRow.icp_score.is_(None))

    order_by = [PifFirmRow.source_updated_at.desc().nullslast(), PifFirmRow.updated_at.desc()]
    if sort_by == "conversation_count":
        order_by = [func.jsonb_array_length(PifFirmRow.conversation_ids).desc(), PifFirmRow.firm_name.asc()]
    elif sort_by == "firm_name":
        order_by = [PifFirmRow.firm_name.asc()]
    elif sort_by == "first_contacted_precise_at":
        order_by = [PifFirmRow.first_contacted_precise_at.desc().nullslast(), PifFirmRow.firm_name.asc()]

    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count()).select_from(PifFirmRow)
        stmt = select(PifFirmRow)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
            stmt = stmt.where(*conditions)
        total = int((await session.execute(count_stmt)).scalar_one() or 0)
        rows = (await session.execute(
            stmt.order_by(*order_by).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()

    items = [_serialize_pif_row(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


async def get_mirrored_pif_firm(firm_id: str) -> dict[str, Any] | None:
    await ensure_firm_intel_tables()
    async with AsyncSessionLocal() as session:
        row = await session.get(PifFirmRow, str(firm_id).strip())
    return _serialize_pif_row(row) if row is not None else None
