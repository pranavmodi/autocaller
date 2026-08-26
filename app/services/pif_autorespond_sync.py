"""Local mirror of EmailTag autorespond events for fast firm filtering."""
from __future__ import annotations

import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal, async_engine
from app.db.models import FirmAliasRow, PifAutorespondEventRow, PifFirmRow

AUTORESPOND_API_URL = os.getenv(
    "PIF_AUTORESPOND_API_URL",
    "https://emailprocessing.mediflow360.com/api/v1/pif-info/autorespond-events",
)


def pifstats_session_cookie() -> str:
    expires_at = int(time.time()) + 24 * 60 * 60
    payload = f"admin:v2:{expires_at}"
    secret = os.getenv("PIFSTATS_AUTH_SECRET", "emailtag-pifstats-admin-auth").encode()
    signature = hmac.new(secret, payload.encode(), sha256).hexdigest()
    return f"{payload}:{signature}"


def _session_cookie() -> str:
    """Backward-compatible alias for older sync callers and tests."""
    return pifstats_session_cookie()


def _parse_dt(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def ensure_autorespond_table() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(PifAutorespondEventRow.__table__.create, checkfirst=True)


async def _canonical_map() -> dict[str, str]:
    async with AsyncSessionLocal() as session:
        firms = (await session.execute(select(PifFirmRow.id, PifFirmRow.source_json))).all()
        aliases = (await session.execute(
            select(FirmAliasRow.alias_value, FirmAliasRow.firm_id)
            .where(FirmAliasRow.alias_type == "legacy_pif_id")
        )).all()
    mapping = {str(firm_id): str(firm_id) for firm_id, _ in firms}
    for firm_id, source in firms:
        merged_into = (source or {}).get("merged_into") if isinstance(source, dict) else None
        if merged_into:
            mapping[str(firm_id)] = str(merged_into)
    for alias_value, firm_id in aliases:
        mapping[str(alias_value)] = mapping.get(str(firm_id), str(firm_id))
    return mapping


async def sync_autorespond_events(*, full: bool = False) -> dict[str, Any]:
    await ensure_autorespond_table()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        latest = (await session.execute(select(func.max(PifAutorespondEventRow.event_created_at)))).scalar_one()
    date_from = None if full or latest is None else (latest - timedelta(days=2)).date().isoformat()
    canonical = await _canonical_map()
    fetched = upserted = pages = 0
    params: dict[str, Any] = {"page": 1, "page_size": 100}
    if date_from:
        params["date_from"] = date_from
    cookies = {"pifstats_session": _session_cookie()}
    async with httpx.AsyncClient(timeout=60.0, cookies=cookies) as client:
        while True:
            response = await client.get(AUTORESPOND_API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") or []
            if not items:
                break
            rows = []
            for item in items:
                source_pif_id = str(item.get("pif_id") or "").strip() or None
                rows.append({
                    "id": str(item["id"]),
                    "source_pif_id": source_pif_id,
                    "canonical_pif_id": canonical.get(source_pif_id, source_pif_id) if source_pif_id else None,
                    "firm_name": item.get("firm_name"),
                    "contact_email": item.get("contact_email"),
                    "agent_type": str(item.get("agent_type") or "unknown"),
                    "response_sent": bool(item.get("response_sent")),
                    "test_mode": bool(item.get("test_mode")),
                    "event_created_at": _parse_dt(item["created_at"]),
                    "synced_at": now,
                })
            async with AsyncSessionLocal() as session:
                stmt = pg_insert(PifAutorespondEventRow).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[PifAutorespondEventRow.id],
                    set_={key: getattr(stmt.excluded, key) for key in rows[0] if key != "id"},
                )
                await session.execute(stmt)
                await session.commit()
            fetched += len(items)
            upserted += len(rows)
            pages += 1
            if int(params["page"]) >= int(payload.get("total_pages") or 0):
                break
            params["page"] = int(params["page"]) + 1
    return {
        "fetched": fetched,
        "upserted": upserted,
        "pages": pages,
        "full": full,
        "date_from": date_from,
        "synced_at": now.isoformat(),
    }
