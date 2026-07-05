"""Native PI-firm directory sync.

Pulls emailtag's PifInfo (the PI-firm directory, served at the pif-info API)
directly into possibleos Postgres (`pif_directory_firms`), so the lead-gen
matching universe no longer depends on mission.db — whose Mission Control sync
stopped running in March 2026, freezing the directory at ~1,711 firms while the
live source has ~3,500+.

Every extracted field is captured (titled contacts, leadership, per-contact
behavioral profiles, firm sender-role distributions, ICP scores), plus the full
untouched record in `raw_json` so nothing is ever lost.

Gated by PIF_DIRECTORY_NATIVE (default off). When off, nothing here runs and
front_sync keeps reading mission.db. When on, the sync loop populates the table
and matching reads the domain map from it.

PHI note: extraction_notes / conversation context may contain patient names.
This data is internal-only for selection/targeting; the PHI egress guard remains
authoritative for anything that leaves in outreach.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select

from app.db import AsyncSessionLocal, async_engine
from app.db.models import PifFirmRow
from app.services.front_sync import extract_emails, is_consumer_domain, normalize_domain

logger = logging.getLogger(__name__)

PIF_API_BASE = os.getenv(
    "PIFSTATS_BASE_URL", "https://emailprocessing.mediflow360.com/api/v1/pif-info"
).rstrip("/")

_tables_checked = False


def pif_native_enabled() -> bool:
    """Whether possibleos uses its own pulled directory (vs mission.db)."""
    return os.getenv("PIF_DIRECTORY_NATIVE", "0").strip().lower() in {"1", "true", "yes", "on"}


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


async def ensure_pif_tables() -> None:
    global _tables_checked
    if _tables_checked:
        return
    from app.services.firm_intel_sync import ensure_firm_intel_tables

    await ensure_firm_intel_tables()
    _tables_checked = True


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _apply_record(row: PifFirmRow, item: dict[str, Any], *, now: datetime) -> None:
    row.firm_name = (item.get("firm_name") or None)
    row.website = (item.get("website") or None)
    row.entity_type = (item.get("entity_type") or None)
    row.fax = (item.get("fax") or None)
    row.icp_score = item.get("icp_score")
    row.icp_tier = (item.get("icp_tier") or None)
    row.research_status = (item.get("research_status") or None)
    row.staff_research_status = (item.get("staff_research_status") or None)
    row.emails = _as_list(item.get("emails"))
    row.phones = _as_list(item.get("phones"))
    row.addresses = _as_list(item.get("addresses"))
    row.contacts = _as_list(item.get("contacts"))
    row.leadership = _as_list(item.get("leadership"))
    row.staff = _as_list(item.get("staff"))
    row.contact_profiles = _as_dict(item.get("contact_profiles"))
    row.research_data = _as_dict(item.get("research_data"))
    row.behavioral_data = _as_dict(item.get("behavioral_data"))
    row.score_breakdown = _as_dict(item.get("score_breakdown"))
    row.conversation_ids = _as_list(item.get("conversation_ids"))
    row.extraction_notes = item.get("extraction_notes")
    row.raw_json = item
    row.source_created_at = _parse_dt(item.get("created_at"))
    row.source_updated_at = _parse_dt(item.get("updated_at"))
    row.last_researched_at = _parse_dt(item.get("last_researched_at"))
    row.icp_scored_at = _parse_dt(item.get("icp_scored_at"))
    row.synced_at = now
    row.updated_at = now


async def sync_pif_directory(*, page_size: int = 100, max_pages: int = 500) -> dict[str, Any]:
    """Deprecated v1 pif-info sync.

    As of 2026-07-05 deployed EmailTag requires cookie auth on v1 routes, so
    header-token clients should use app.services.firm_intel_sync.sync_firm_intel.

    Returns a summary. Safe to call when the flag is off (it still syncs — the
    flag only governs whether matching *reads* from this table — so an operator
    can warm the table before cutover)."""
    logger.warning("sync_pif_directory is deprecated: emailtag v1 pif-info requires cookie auth; use firm-intel v2")
    page_size = max(1, min(int(page_size), 100))  # API caps page_size at 100
    await ensure_pif_tables()
    now = _utcnow()
    fetched = created = updated = pages = 0
    total_reported = 0
    headers = _auth_headers()
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        page = 1
        while page <= max_pages:
            resp = await client.get(f"{PIF_API_BASE}/", params={"page": page, "page_size": page_size})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            total_reported = int(data.get("total") or total_reported)
            if not items:
                break
            async with AsyncSessionLocal() as session:
                for item in items:
                    fid = str(item.get("id") or "").strip()
                    if not fid:
                        continue
                    row = await session.get(PifFirmRow, fid)
                    if row is None:
                        row = PifFirmRow(id=fid, created_at=now)
                        _apply_record(row, item, now=now)
                        session.add(row)
                        created += 1
                    else:
                        _apply_record(row, item, now=now)
                        updated += 1
                    fetched += 1
                await session.commit()
            pages += 1
            total_pages = int(data.get("total_pages") or 0)
            if total_pages and page >= total_pages:
                break
            page += 1
    result = {
        "fetched": fetched,
        "created": created,
        "updated": updated,
        "pages": pages,
        "total_reported": total_reported,
        "synced_at": now.isoformat(),
        "native_enabled": pif_native_enabled(),
    }
    logger.info("pif_directory sync: %s", result)
    return result


async def load_pif_domain_map_from_db() -> dict[str, str]:
    """Build the domain -> pif_id map from the local directory (mirrors
    front_sync._load_pif_domain_map, which reads mission.db)."""
    await ensure_pif_tables()
    domains: dict[str, str] = {}
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(PifFirmRow.id, PifFirmRow.website, PifFirmRow.emails)
        )).all()
    for pif_id, website, emails in rows:
        candidates: list[str] = []
        if website:
            candidates.append(str(website))
        for e in (emails or []):
            candidates.append(str(e))
            candidates.extend(extract_emails(str(e)))
        for candidate in candidates:
            domain = normalize_domain(candidate)
            if domain and not is_consumer_domain(domain):
                domains.setdefault(domain, str(pif_id))
    return domains


async def pif_directory_status() -> dict[str, Any]:
    await ensure_pif_tables()
    async with AsyncSessionLocal() as session:
        total = int((await session.execute(select(func.count()).select_from(PifFirmRow))).scalar_one() or 0)
        last_synced = (await session.execute(select(func.max(PifFirmRow.synced_at)))).scalar_one()
        last_source_update = (await session.execute(select(func.max(PifFirmRow.source_updated_at)))).scalar_one()
        with_website = int((await session.execute(
            select(func.count()).select_from(PifFirmRow).where(PifFirmRow.website.isnot(None))
        )).scalar_one() or 0)
        tier_rows = (await session.execute(
            select(PifFirmRow.icp_tier, func.count()).group_by(PifFirmRow.icp_tier)
        )).all()
    return {
        "native_enabled": pif_native_enabled(),
        "total_firms": total,
        "with_website": with_website,
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        "last_source_update": last_source_update.isoformat() if last_source_update else None,
        "icp_tiers": {str(t or "untiered"): int(c) for t, c in tier_rows},
        "api_base": PIF_API_BASE,
    }


async def pif_directory_sync_loop(*, interval_seconds: int = 86400) -> None:
    """Daily directory refresh. No-op while the flag is off so enabling the
    feature is a single env change. Never blocks startup."""
    logger.info("pif_directory_sync_loop starting (interval=%ss)", interval_seconds)
    # small stagger so it doesn't pile onto boot
    await asyncio.sleep(60)
    while True:
        try:
            if pif_native_enabled():
                from app.services.firm_intel_sync import sync_firm_intel

                await sync_firm_intel()
                # Roadmap step 1: fold the directory's titled contacts +
                # leadership into firm_contacts so daily selection has named,
                # persona-mapped decision-makers. Local-only.
                from app.services.firm_contacts_service import ingest_pif_directory_contacts
                ingest = await ingest_pif_directory_contacts()
                logger.info("pif_directory contact ingest: %s", ingest)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pif_directory_sync_loop tick failed")
        await asyncio.sleep(interval_seconds)
