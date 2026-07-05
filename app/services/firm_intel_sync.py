"""EmailTag firm-intel v2 mirror.

Pulls the published firm_profile contract into the local pif_directory_firms
mirror and maintains a local alias table so lead-gen can resolve firms without
calling EmailTag on the hot path.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, inspect, select, text

from app.db import AsyncSessionLocal, async_engine
from app.db.models import FirmAliasRow, FirmIntelSyncStateRow, PifFirmRow
from app.services.front_sync import is_consumer_domain, normalize_domain

logger = logging.getLogger(__name__)

FIRM_INTEL_BASE_URL = os.getenv(
    "FIRM_INTEL_BASE_URL",
    "https://emailprocessing.mediflow360.com/api/v2/firm-intel",
).rstrip("/")

ALIAS_TYPES = ("domain", "vanity_domain", "legacy_pif_id")

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


async def _get_with_retry(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    attempts: int = 4,
) -> httpx.Response:
    """GET with backoff on 5xx/transport errors — the v2 endpoint 502s
    transiently when profile pages are slow under load."""
    delay = 2.0
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
    }
    for column, statement in ddl.items():
        if column not in existing:
            sync_conn.execute(text(statement))
    for index in PifFirmRow.__table__.indexes:
        if index.name == "ix_pif_directory_firms_canonical_website":
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


async def sync_firm_intel(*, full: bool = False, limit: int | None = None) -> dict[str, Any]:
    """Sync EmailTag firm-intel v2 profiles into the local mirror."""
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

        cursor: str | None = None
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

                resp = await _get_with_retry(client, "/firms", params)
                resp.raise_for_status()
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
            "previous_watermark": _dt_iso(updated_since),
            "candidate_watermark": _dt_iso(max_watermark),
            "watermark": _dt_iso(max_watermark if watermark_advanced else updated_since),
            "watermark_advanced": watermark_advanced,
            "stopped_by_limit_with_more": stopped_by_limit_with_more,
        }
        if watermark_advanced:
            state.last_updated_since = max_watermark
        state.last_synced_at = now
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
