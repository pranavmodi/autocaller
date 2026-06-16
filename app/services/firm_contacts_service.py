"""firm_contacts: backfill + lookup helpers.

Sources, in priority:
  1. PIF Stats `/pif-info/{pif_id}` → `leadership[]` — canonical roster
  2. The autocaller `patients` row keyed `pif-{pif_id}` — the DM we
     picked during ICP scoring
  3. captured_contacts on call_logs — out of scope for v1; can be
     wired in later without schema changes

Idempotent: dedup is by (pif_id, lower(email)). Email-less roster
entries still get a row so they're selectable; the sequence
scheduler will pause those with `paused_reason='no_email_on_contact'`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import Optional

import httpx
from sqlalchemy import func, select

from app.db import AsyncSessionLocal
from app.db.models import FirmContactRow, PatientRow

logger = logging.getLogger(__name__)


PIF_BASE = os.getenv(
    "PIFSTATS_BASE_URL",
    "https://emailprocessing.mediflow360.com/api/v1/pif-info",
)


def _norm_email(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip().lower()
    return s or None


def _first_name_of(full: str) -> str:
    parts = (full or "").strip().split()
    return parts[0] if parts else ""


async def _list_known_pif_ids() -> list[str]:
    """Every firm we've touched. Two keying conventions live in
    `patients` today: `pif-{id}` (older `pifstats_sync.py` path) and
    `mc-{id}` (newer LLM-driven `sync-mission` path). Both reference
    the same upstream pif_id space. We walk both, plus existing
    firm_contacts rows so backfill reruns on stale lists still work."""
    async with AsyncSessionLocal() as session:
        patient_ids = (await session.execute(
            select(PatientRow.patient_id).where(
                PatientRow.patient_id.like("pif-%")
                | PatientRow.patient_id.like("mc-%")
            )
        )).scalars().all()
        contact_pifs = (await session.execute(
            select(FirmContactRow.pif_id).distinct()
        )).scalars().all()
    pif_ids: set[str] = set()
    for pid in patient_ids:
        if not pid:
            continue
        if pid.startswith("pif-"):
            pif_ids.add(pid[4:])
        elif pid.startswith("mc-"):
            pif_ids.add(pid[3:])
    for c in contact_pifs:
        if c:
            pif_ids.add(c)
    return sorted(pif_ids)


async def _fetch_pif_info(pif_id: str, client: httpx.AsyncClient) -> Optional[dict]:
    try:
        r = await client.get(f"{PIF_BASE}/{pif_id}")
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        logger.warning("pif-info fetch failed for %s: %s", pif_id, e)
        return None


async def _upsert(
    session, *,
    pif_id: str,
    full_name: str,
    email: Optional[str],
    phone: Optional[str],
    title: Optional[str],
    linkedin_url: Optional[str],
    source: str,
) -> str:
    """Returns 'inserted' | 'updated' | 'skipped'."""
    full_name = (full_name or "").strip()
    if not full_name and not email:
        return "skipped"
    email = _norm_email(email)
    # Dedup: prefer matching by (pif_id, email) when email is present;
    # fall back to (pif_id, full_name) when not.
    if email:
        existing = (await session.execute(
            select(FirmContactRow).where(
                FirmContactRow.pif_id == pif_id,
                FirmContactRow.email == email,
            )
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
        # Light merge — fill blanks but never overwrite operator edits.
        changed = False
        if not existing.email and email:
            existing.email = email; changed = True
        if not existing.phone and phone:
            existing.phone = phone; changed = True
        if not existing.title and title:
            existing.title = title; changed = True
        if not existing.linkedin_url and linkedin_url:
            existing.linkedin_url = linkedin_url; changed = True
        if not existing.first_name and full_name:
            existing.first_name = _first_name_of(full_name); changed = True
        return "updated" if changed else "skipped"

    row = FirmContactRow(
        id=uuid.uuid4().hex,
        pif_id=pif_id,
        full_name=full_name,
        first_name=_first_name_of(full_name),
        email=email,
        phone=phone,
        title=title,
        linkedin_url=linkedin_url,
        source=source,
    )
    session.add(row)
    return "inserted"


_PHONE_RX = re.compile(r"\D+")


def _normalize_phone(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    digits = _PHONE_RX.sub("", p)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if digits:
        return "+" + digits
    return None


async def backfill_one(pif_id: str, client: httpx.AsyncClient) -> dict:
    """Backfill contacts for a single firm. Returns counts."""
    counts = {"pif_id": pif_id, "inserted": 0, "updated": 0, "skipped": 0}

    info = await _fetch_pif_info(pif_id, client)
    leadership = (info or {}).get("leadership") or []

    async with AsyncSessionLocal() as session:
        for person in leadership:
            full = (person.get("name") or "").strip()
            email = person.get("email")
            phone = _normalize_phone(person.get("phone"))
            title = person.get("title") or person.get("role")
            li = person.get("linkedin_url") or person.get("linkedin")
            r = await _upsert(
                session,
                pif_id=pif_id,
                full_name=full,
                email=email,
                phone=phone,
                title=title,
                linkedin_url=li,
                source="pif_leadership",
            )
            counts[r] = counts.get(r, 0) + 1

        # Add the autocaller-DM patient row if its email/name aren't
        # already in firm_contacts (it often duplicates the leadership
        # row; the upsert dedup handles that).
        # Look up the autocaller-DM patient row across both keying
        # conventions; prefer the pif- variant when both exist.
        patient = (await session.execute(
            select(PatientRow).where(
                PatientRow.patient_id.in_([f"pif-{pif_id}", f"mc-{pif_id}"])
            ).order_by(PatientRow.patient_id)  # 'mc-' < 'pif-' lex; we want pif- first
        )).scalars().first()
        if patient and patient.patient_id.startswith("mc-"):
            # If we got mc-, see if a pif- exists too and prefer it.
            pif_variant = (await session.execute(
                select(PatientRow).where(PatientRow.patient_id == f"pif-{pif_id}")
            )).scalar_one_or_none()
            if pif_variant:
                patient = pif_variant
        if patient:
            r = await _upsert(
                session,
                pif_id=pif_id,
                full_name=patient.name or "",
                email=patient.email,
                phone=patient.phone,
                title=patient.title,
                linkedin_url=None,
                source="patients_dm",
            )
            counts[r] = counts.get(r, 0) + 1

        await session.commit()
    return counts


async def backfill_all(limit: Optional[int] = None) -> dict:
    """Backfill contacts for every known firm. Hits PIF Stats
    sequentially — small data, no need for concurrency limits."""
    pif_ids = await _list_known_pif_ids()
    if limit:
        pif_ids = pif_ids[:limit]
    totals = {"firms": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    async with httpx.AsyncClient(timeout=15.0) as client:
        for pid in pif_ids:
            try:
                c = await backfill_one(pid, client)
                totals["firms"] += 1
                totals["inserted"] += c.get("inserted", 0)
                totals["updated"] += c.get("updated", 0)
                totals["skipped"] += c.get("skipped", 0)
            except Exception as e:
                logger.warning("backfill failed for %s: %s", pid, e)
                totals["errors"] += 1
    return totals


# ---------------------------------------------------------------------------
# read helpers used by the API + UI
# ---------------------------------------------------------------------------

async def list_firms_with_contacts() -> list[dict]:
    """Source for the firm dropdown. Returns one row per firm that has at
    least one contact, with firm_name + contact count + has-yelp-quote
    badge."""
    async with AsyncSessionLocal() as session:
        pifs = (await session.execute(
            select(FirmContactRow.pif_id).distinct()
        )).scalars().all()
        if not pifs:
            return []
        # Look up firm_name across both keying conventions. Where a firm
        # exists as both pif- and mc-, we prefer whichever has a non-empty
        # name; ties go to pif- (older, usually richer).
        all_keys = [f"pif-{p}" for p in pifs] + [f"mc-{p}" for p in pifs]
        rows = (await session.execute(
            select(PatientRow.patient_id, PatientRow.firm_name).where(
                PatientRow.patient_id.in_(all_keys)
            )
        )).all()
        name_map: dict[str, str] = {}
        for pid, fname in rows:
            if not pid or not fname:
                continue
            raw_pif = pid[4:] if pid.startswith("pif-") else (pid[3:] if pid.startswith("mc-") else pid)
            # Don't overwrite a name from pif- with one from mc-.
            if raw_pif not in name_map or pid.startswith("pif-"):
                name_map[raw_pif] = fname
        count_map = dict(
            (await session.execute(
                select(
                    FirmContactRow.pif_id, func.count(FirmContactRow.id),
                ).group_by(FirmContactRow.pif_id)
            )).all()
        )

    out = []
    for pid in pifs:
        # Per-firm quote check is one parse; volumes are tiny.
        quote = await fetch_pain_quote_for_firm(pid)
        out.append({
            "pif_id": pid,
            "firm_name": name_map.get(pid) or "",
            "contact_count": count_map.get(pid, 0),
            "has_pain_quote": bool(quote.get("pain_quote")),
            "extracted_at": quote.get("extracted_at"),
        })
    # Firms with a usable pain quote first, ordered by extraction recency
    # (newest first — operator sees latest research at the top). Firms
    # without a quote drop to the bottom, sorted by name.
    def _sort_key(r: dict):
        if r["has_pain_quote"]:
            return (0, -1 * _sortable_extracted_at(r.get("extracted_at")))
        return (1, (r["firm_name"] or "").lower())
    out.sort(key=_sort_key)
    return out


def _sortable_extracted_at(iso: Optional[str]) -> float:
    """Parse ISO-8601 extraction timestamp to a sortable epoch float.
    Returns 0 (oldest) when missing/unparseable so firms with a quote
    but a bad timestamp fall to the bottom of the with-quote group."""
    if not iso:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


async def resolve_firm_name(pif_id: str) -> str:
    """Return the best firm_name for a pif_id, walking both keying
    conventions (`pif-{id}` and `mc-{id}`). Used by the sequence
    scheduler, the comms assembler, and the sequences API to display
    firm names on the dashboard regardless of which sync produced the
    patient row."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(PatientRow.patient_id, PatientRow.firm_name).where(
                PatientRow.patient_id.in_([f"pif-{pif_id}", f"mc-{pif_id}"])
            )
        )).all()
    pif_name, mc_name = "", ""
    for pid, fname in rows:
        if pid == f"pif-{pif_id}" and fname:
            pif_name = fname
        elif pid == f"mc-{pif_id}" and fname:
            mc_name = fname
    return pif_name or mc_name


async def list_contacts_for_firm(pif_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        contacts = (await session.execute(
            select(FirmContactRow).where(FirmContactRow.pif_id == pif_id)
            .order_by(FirmContactRow.full_name)
        )).scalars().all()
    return [
        {
            "id": c.id,
            "pif_id": c.pif_id,
            "full_name": c.full_name,
            "first_name": c.first_name,
            "email": c.email,
            "phone": c.phone,
            "title": c.title,
            "source": c.source,
        }
        for c in contacts
    ]


async def get_contact(contact_id: str) -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        c = (await session.execute(
            select(FirmContactRow).where(FirmContactRow.id == contact_id)
        )).scalar_one_or_none()
    if not c:
        return None
    return {
        "id": c.id,
        "pif_id": c.pif_id,
        "full_name": c.full_name,
        "first_name": c.first_name,
        "email": c.email,
        "phone": c.phone,
        "title": c.title,
        "source": c.source,
    }


async def fetch_pain_quote_for_firm(pif_id: str) -> dict:
    """Pulls the highest-confidence client_communication quote from the
    firm's stored Yelp extraction. Returns dict with pain_quote /
    reviewer_name / review_date / pain_point_key — any of which may be
    None when no usable quote exists. Caller decides 'with_quote' vs
    'without_quote' variant from the truthiness of pain_quote."""
    import json
    import re as _re
    from app.db.models import FirmReviewRow

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
        )).scalar_one_or_none()

    blank = {
        "pain_quote": None,
        "reviewer_name": None,
        "review_date": None,
        "pain_point_key": None,
        "extracted_at": None,
    }
    if not row or not row.yelp_content:
        return blank
    m = _re.search(
        r"<!--\s*EXTRACTED v\d+\s*([\s\S]*?)\s*-->", row.yelp_content
    )
    if not m:
        return blank
    try:
        data = json.loads(m.group(1))
    except Exception:
        return blank
    extracted_at = data.get("extracted_at")
    quotes = (data.get("pain_points") or {}).get("client_communication") or []
    if not quotes:
        return {**blank, "extracted_at": extracted_at}
    top = max(quotes, key=lambda q: q.get("confidence", 0))
    return {
        "pain_quote": top.get("quote"),
        "reviewer_name": top.get("reviewer_name"),
        "review_date": top.get("review_date"),
        "pain_point_key": "client_communication",
        "extracted_at": extracted_at,
    }


async def ingest_pif_directory_contacts(*, map_personas_after: bool = True) -> dict:
    """Bulk-populate firm_contacts from the locally-synced PI-firm directory.

    Roadmap step 1: emailtag already extracts named, titled contacts +
    leadership per firm. Pull those (from pif_directory_firms, no API calls) into
    FirmContactRow so we get titles (-> personas via map_personas) and firm names
    for free — instead of re-deriving title-less contacts from raw inbox senders,
    which is what suppresses selection (missing firm name / non-persona) down to a
    handful of eligible leads.

    Enriches existing title-less rows AND inserts new contacts for firms that had
    none. In-memory dedup keyed by (pif_id, email|name); single commit. Then runs
    the idempotent persona mapper so the new/enriched contacts become selectable.
    """
    from app.db.models import PifFirmRow

    counts = {"firms": 0, "persons": 0, "inserted": 0, "updated": 0, "skipped": 0}
    async with AsyncSessionLocal() as session:
        firm_rows = (await session.execute(
            select(PifFirmRow.id, PifFirmRow.leadership, PifFirmRow.contacts)
        )).all()
        existing_rows = (await session.execute(select(FirmContactRow))).scalars().all()
        by_email: dict[tuple[str, str], FirmContactRow] = {}
        by_name: dict[tuple[str, str], FirmContactRow] = {}
        for r in existing_rows:
            if r.email:
                by_email[(r.pif_id, r.email.strip().lower())] = r
            elif r.full_name:
                by_name[(r.pif_id, r.full_name.strip().lower())] = r

        for pif_id, leadership, contacts in firm_rows:
            pid = str(pif_id)
            people = [(p, "pif_leadership") for p in (leadership or [])]
            people += [(p, "pif_contacts") for p in (contacts or [])]
            if not people:
                continue
            counts["firms"] += 1
            for person, src in people:
                if not isinstance(person, dict):
                    continue
                counts["persons"] += 1
                # Clamp to column widths — emailtag values can exceed them
                # (e.g. multi-number phone strings > varchar(32)).
                full = (person.get("name") or "").strip()[:255]
                email = (_norm_email(person.get("email")) or "")[:320] or None
                phone = (_normalize_phone(person.get("phone")) or "")[:32] or None
                title = ((person.get("title") or person.get("role")) or "").strip()[:255] or None
                li = ((person.get("linkedin_url") or person.get("linkedin")) or "").strip()[:512] or None
                if not full and not email:
                    counts["skipped"] += 1
                    continue
                existing = None
                if email:
                    existing = by_email.get((pid, email))
                if existing is None and full:
                    existing = by_name.get((pid, full.lower()))
                if existing is not None:
                    changed = False
                    if not existing.email and email:
                        existing.email = email; by_email[(pid, email)] = existing; changed = True
                    if not existing.phone and phone:
                        existing.phone = phone; changed = True
                    if not existing.title and title:
                        existing.title = title; changed = True
                    if not existing.linkedin_url and li:
                        existing.linkedin_url = li; changed = True
                    if not existing.first_name and full:
                        existing.first_name = _first_name_of(full); changed = True
                    counts["updated" if changed else "skipped"] += 1
                else:
                    row = FirmContactRow(
                        id=uuid.uuid4().hex,
                        pif_id=pid,
                        full_name=full,
                        first_name=_first_name_of(full),
                        email=email,
                        phone=phone,
                        title=title,
                        linkedin_url=li,
                        source=src,
                    )
                    session.add(row)
                    if email:
                        by_email[(pid, email)] = row
                    elif full:
                        by_name[(pid, full.lower())] = row
                    counts["inserted"] += 1
        await session.commit()

    if map_personas_after:
        from app.services.persona_mapper import map_personas
        counts["personas"] = await map_personas()
    return counts
