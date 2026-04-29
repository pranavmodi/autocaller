"""Pull researched firms from PIF Stats into the local `patients` table.

Mirrors the CLI command `autocaller leads sync-pifstats` but is async
and reusable from the cadence background loop and the
`POST /api/firms/sync` endpoint.

For each researched firm the API returns, we pick the best
decision-maker (title + phone + email + linkedin scoring), normalise
the phone to E.164, and upsert a `patients` row keyed on
`patient_id = "pif-{firm_id}"`. Idempotent — re-running is a no-op
for unchanged firms.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import PatientRow

logger = logging.getLogger(__name__)

PIF_BASE = "https://emailprocessing.mediflow360.com/api/v1/pif-info"

# Title keywords that mark a true decision-maker.
_DM_TITLES = {
    "owner", "partner", "managing", "principal", "director",
    "ceo", "coo", "president", "founder", "shareholder",
}


def _pick_best_dm(leaders: list[dict]) -> Optional[dict]:
    """Score leaders by title + presence of contact info, return the top."""
    best = None
    best_score = -1
    for l in leaders:
        title_lower = (l.get("title") or "").lower()
        score = sum(1 for kw in _DM_TITLES if kw in title_lower) * 10
        if l.get("phone"):
            score += 5
        if l.get("email"):
            score += 3
        if l.get("linkedin"):
            score += 2
        if score > best_score:
            best_score = score
            best = l
    return best


def _normalize_phone(raw: str) -> Optional[str]:
    """E.164-ish normaliser. Returns None if the phone isn't usable."""
    if not raw:
        return None
    cleaned = raw.replace("‑", "-").replace(".", "-").strip()
    digits = "".join(c for c in cleaned if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if 10 <= len(digits) <= 15:
        return f"+{digits}" if not cleaned.startswith("+") else cleaned
    return None


def _build_notes(firm: dict) -> Optional[str]:
    beh = firm.get("behavioral_data") or {}
    parts = []
    pain = beh.get("primary_pain_point") or ""
    if pain:
        parts.append(f"Pain: {pain.replace('_', ' ')}")
    after_hrs = beh.get("after_hours_ratio")
    if after_hrs is not None:
        parts.append(f"After-hours: {round(after_hrs * 100)}%")
    email_vol = beh.get("monthly_email_volume") or []
    if email_vol:
        avg = sum(email_vol) / len(email_vol)
        parts.append(f"Email vol: {avg:.0f}/mo")
    parts.append(f"PIF ID: {firm.get('id', '')}")
    return " | ".join(parts) if parts else None


async def _fetch_researched_firms(
    *, recently_researched_days: int, limit: int
) -> list[dict]:
    """Page through PIF Stats and collect callable researched firms."""
    firms: list[dict] = []
    page = 1
    extra = (
        {"recently_researched": recently_researched_days}
        if recently_researched_days > 0
        else {}
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(firms) < limit and page <= 30:
            try:
                resp = await client.get(
                    f"{PIF_BASE}/",
                    params={"page": page, "page_size": 100, **extra},
                )
            except Exception as e:
                logger.warning("PIF Stats fetch page=%d failed: %s", page, e)
                break
            if resp.status_code != 200:
                logger.warning(
                    "PIF Stats page=%d HTTP %s: %s",
                    page, resp.status_code, resp.text[:200],
                )
                break
            data = resp.json()
            for f in data.get("items", []):
                researched = (
                    f.get("research_status") == "completed"
                    or f.get("last_researched_at")
                )
                if researched and f.get("phones") and f.get("leadership"):
                    firms.append(f)
            if page >= data.get("total_pages", 1):
                break
            page += 1
    return firms[:limit]


def _firm_to_patient_row(firm: dict) -> Optional[dict]:
    """Convert a PIF Stats firm dict to the kwargs for a PatientRow."""
    leaders = firm.get("leadership") or []
    phones = firm.get("phones") or []
    best = _pick_best_dm(leaders)
    if not best:
        return None
    phone = _normalize_phone(best.get("phone") or "")
    if not phone and phones:
        phone = _normalize_phone(phones[0])
    if not phone:
        return None
    return {
        "patient_id": f"pif-{firm['id']}",
        "name": best.get("name") or firm.get("firm_name") or "Unknown",
        "phone": phone,
        "firm_name": firm.get("firm_name"),
        "state": None,
        "practice_area": "personal injury",
        "email": best.get("email"),
        "title": (best.get("title") or "")[:128] or None,
        "website": firm.get("website"),
        "source": "pifstats",
        "tags": [f"pif-tier:{firm.get('icp_tier', '?')}"],
        "notes": _build_notes(firm),
    }


async def sync_pifstats_to_patients(
    *,
    limit: int = 500,
    recently_researched_days: int = 0,
) -> dict:
    """Pull researched firms from PIF Stats and upsert them as `patients`
    rows. Returns `{fetched, inserted, updated, skipped}`.

    `recently_researched_days=0` disables the recency filter so every
    researched firm is considered. The background scan defaults to 0
    so we don't miss older but newly-researched firms.
    """
    firms = await _fetch_researched_firms(
        recently_researched_days=recently_researched_days, limit=limit,
    )
    fetched = len(firms)
    inserted = updated = skipped = 0

    if not firms:
        return {"fetched": 0, "inserted": 0, "updated": 0, "skipped": 0}

    from app.services.firm_blocklist import is_blocked

    async with AsyncSessionLocal() as session:
        for firm in firms:
            # Blocklist guard — never insert/update Precise Imaging et al
            # into the patients table. The cadence queue already filters
            # them, but the dispatcher picks from `patients`, so without
            # this they'd still get dialed.
            if is_blocked(firm.get("id"), firm.get("firm_name")):
                skipped += 1
                continue
            payload = _firm_to_patient_row(firm)
            if not payload:
                skipped += 1
                continue
            existing = await session.execute(
                select(PatientRow).where(
                    PatientRow.patient_id == payload["patient_id"]
                )
            )
            row = existing.scalar_one_or_none()
            if row is None:
                session.add(PatientRow(**payload))
                inserted += 1
            else:
                # Only overwrite enrichment fields — preserve dispatcher
                # state (attempt_count, last_outcome, last_attempt_at).
                row.name = payload["name"]
                row.phone = payload["phone"]
                row.firm_name = payload["firm_name"]
                row.email = payload["email"]
                row.title = payload["title"]
                row.website = payload["website"]
                row.tags = payload["tags"]
                row.notes = payload["notes"]
                row.source = payload["source"]
                row.practice_area = payload["practice_area"]
                updated += 1
        await session.commit()

    logger.info(
        "pifstats sync: fetched=%d inserted=%d updated=%d skipped=%d",
        fetched, inserted, updated, skipped,
    )
    return {
        "fetched": fetched,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
    }
