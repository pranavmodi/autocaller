"""EmailTag firm-intel v2 mirror.

Pulls the published firm_profile contract into the local pif_directory_firms
mirror and maintains a local alias table so lead-gen can resolve firms without
calling EmailTag on the hot path.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any

import httpx
from sqlalchemy import String, cast, func, inspect, or_, select, text

from app.db import AsyncSessionLocal, async_engine
from app.db.models import FirmAliasRow, FirmIntelSyncStateRow, PifFirmRow
from app.services.front_sync import is_consumer_domain, normalize_domain
from app.services.persona_mapper import classify_contact

logger = logging.getLogger(__name__)

FIRM_INTEL_BASE_URL = os.getenv(
    "FIRM_INTEL_BASE_URL",
    "https://emailprocessing.mediflow360.com/api/v2/firm-intel",
).rstrip("/")

ALIAS_TYPES = ("domain", "vanity_domain", "legacy_pif_id")
STATUS_RUNNING = {"queued", "in_progress", "running", "started"}

_tables_checked = False


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
    case_mgmt = _vendor_key(value.get("case_mgmt"))
    if case_mgmt:
        entries.append({"vendor": case_mgmt, "source": "case_mgmt"})
    other = value.get("other")
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
    for stack in (
        source.get("vendor_stack") if isinstance(source, dict) else None,
        row.vendor_stack,
        raw.get("vendor_stack") if isinstance(raw, dict) else None,
    ):
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
    row.research_data = _research_data(profile)
    row.raw_json = profile
    row.source_updated_at = _source_updated_at(profile)
    row.warm_score = _as_float(relationship.get("warm_score_neutral"))
    row.vendor_stack = _as_dict(profile.get("vendor_stack"))
    row.profile_source = "v2"
    row.synced_at = now
    row.updated_at = now

    _apply_source_record(row, _source_record(profile))

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
    _tables_checked = True


async def _upsert_aliases(session, profile: dict[str, Any], *, now: datetime) -> int:
    firm_id = str(profile.get("firm_id") or "").strip()
    if not firm_id:
        return 0
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
            row.firm_id = firm_id
            row.synced_at = now
        touched += 1
    return touched


async def _upsert_profile(session, profile: dict[str, Any], *, now: datetime) -> tuple[str, int]:
    firm_id = str(profile.get("firm_id") or "").strip()
    if not firm_id:
        return "skipped", 0
    row = await session.get(PifFirmRow, firm_id)
    status = "updated"
    if row is None:
        row = PifFirmRow(id=firm_id, created_at=now)
        status = "created"
        session.add(row)
    _apply_v2_profile(row, profile, now=now)
    aliases = await _upsert_aliases(session, profile, now=now)
    return status, aliases


async def sync_firm_intel(
    *, full: bool = False, limit: int | None = None, restart: bool = False
) -> dict[str, Any]:
    """Sync EmailTag firm-intel v2 profiles into the local mirror.

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
                    resp = await _get_with_retry(client, "/firms", params)
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
                    status, alias_count = await _upsert_profile(session, profile, now=now)
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

    return {
        "total_firms": total,
        "alias_count": alias_count,
        "watermark": _dt_iso(state.last_updated_since) if state else None,
        "last_synced_at": _dt_iso(state.last_synced_at) if state else None,
        "last_result": state.last_result if state else {},
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
            UNION
            SELECT id, lower(vendor_stack->>'case_mgmt') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(vendor_stack->>'case_mgmt', '') <> ''
            UNION
            SELECT id, lower(raw_json #>> '{vendor_stack,case_mgmt}') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(raw_json #>> '{vendor_stack,case_mgmt}', '') <> ''
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
            UNION
            SELECT id, lower(vendor_stack->>'case_mgmt') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(vendor_stack->>'case_mgmt', '') <> ''
            UNION
            SELECT id, lower(raw_json #>> '{vendor_stack,case_mgmt}') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(raw_json #>> '{vendor_stack,case_mgmt}', '') <> ''
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
        )
        SELECT DISTINCT id
        FROM vendor_rows
        WHERE vendor = :vendor
    """)
    async with AsyncSessionLocal() as session:
        return {str(row[0]) for row in (await session.execute(vendor_sql, {"vendor": wanted})).all()}


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
            UNION
            SELECT id, lower(vendor_stack->>'case_mgmt') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(vendor_stack->>'case_mgmt', '') <> ''
            UNION
            SELECT id, lower(raw_json #>> '{vendor_stack,case_mgmt}') AS vendor
            FROM pif_directory_firms
            WHERE coalesce(raw_json #>> '{vendor_stack,case_mgmt}', '') <> ''
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
    return {
        "id": row.id,
        "firm_name": row.firm_name or "",
        "entity_type": row.entity_type or "",
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


def _person_matches(value: str | None, needle: str | None) -> bool:
    if not needle or not needle.strip():
        return True
    return needle.strip().lower() in str(value or "").lower()


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
    title: str | None = None,
    role_category: str | None = None,
    source: str | None = "all",
    leader: str | None = "any",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """List people extracted into the local EmailTag firm mirror."""
    await ensure_firm_intel_tables()
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    source_filter = (source or "all").strip().lower()
    leader_filter = (leader or "any").strip().lower()
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

    async with AsyncSessionLocal() as session:
        stmt = select(
            PifFirmRow.id,
            PifFirmRow.firm_name,
            PifFirmRow.contacts,
            PifFirmRow.leadership,
            PifFirmRow.staff,
            PifFirmRow.source_updated_at,
            PifFirmRow.updated_at,
        ).order_by(PifFirmRow.source_updated_at.desc().nullslast(), PifFirmRow.firm_name.asc())
        if conditions:
            stmt = stmt.where(*conditions)
        rows = (await session.execute(stmt)).all()

    people: list[dict[str, Any]] = []
    for row in rows:
        for person in _people_for_row(row):
            if source_filter != "all" and person.get("source") != source_filter:
                continue
            is_leader = bool(person.get("is_decision_maker"))
            if leader_filter == "leader" and not is_leader:
                continue
            if leader_filter == "non_leader" and is_leader:
                continue
            if not _person_matches(person.get("name"), name):
                continue
            if not _person_matches(person.get("firm_name"), firm):
                continue
            if not _person_matches(person.get("title"), title):
                continue
            if role_category and role_category.strip() and not (
                _person_matches(person.get("role_category"), role_category)
                or _person_matches(person.get("title"), role_category)
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
            return status == "completed"
        if value == "missing":
            return status not in {"completed", *STATUS_RUNNING}
        if value == "queued_or_running":
            return status in STATUS_RUNNING
        if value == "failed":
            return status == "failed"
    if field == "staff_presence":
        status = row.staff_research_status
        if value == "completed":
            return status == "completed"
        if value == "missing":
            return status not in {"completed", *STATUS_RUNNING}
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
    website_presence: str | None = None,
    research_presence: str | None = None,
    staff_presence: str | None = None,
    behavior_presence: str | None = None,
    icp_presence: str | None = None,
    vendor_presence: str | None = None,
    vendor: str | None = None,
    first_contacted_from: date | None = None,
    first_contacted_to: date | None = None,
    active_only: bool = True,
) -> dict[str, Any]:
    """List local mirror rows, including vendor-name filtering absent upstream."""
    del active_only  # The local mirror excludes merged rows at source sync time.
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
    if recently_researched is not None:
        conditions.append(PifFirmRow.last_researched_at >= datetime.now(timezone.utc) - timedelta(days=recently_researched))
    if first_contacted_from is not None:
        conditions.append(PifFirmRow.first_contacted_precise_at >= datetime.combine(first_contacted_from, time.min, tzinfo=timezone.utc))
    if first_contacted_to is not None:
        conditions.append(PifFirmRow.first_contacted_precise_at < datetime.combine(first_contacted_to + timedelta(days=1), time.min, tzinfo=timezone.utc))

    for field, value in (
        ("website_presence", website_presence),
        ("research_presence", research_presence),
        ("staff_presence", staff_presence),
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
                conditions.append(PifFirmRow.research_status == "completed")
            elif value == "missing":
                conditions.append(or_(PifFirmRow.research_status.is_(None), ~PifFirmRow.research_status.in_(["completed", *STATUS_RUNNING])))
            elif value == "queued_or_running":
                conditions.append(PifFirmRow.research_status.in_(list(STATUS_RUNNING)))
            elif value == "failed":
                conditions.append(PifFirmRow.research_status == "failed")
        elif field == "staff_presence":
            if value == "completed":
                conditions.append(PifFirmRow.staff_research_status == "completed")
            elif value == "missing":
                conditions.append(or_(PifFirmRow.staff_research_status.is_(None), ~PifFirmRow.staff_research_status.in_(["completed", *STATUS_RUNNING])))
            elif value == "queued_or_running":
                conditions.append(PifFirmRow.staff_research_status.in_(list(STATUS_RUNNING)))
            elif value == "failed":
                conditions.append(PifFirmRow.staff_research_status == "failed")
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
