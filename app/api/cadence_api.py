"""Cadence tracking API — manage multi-day outreach sequences."""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func, desc

from app.db import AsyncSessionLocal
from app.db.models import CadenceEntryRow, CallLogRow

router = APIRouter(prefix="/api/cadence", tags=["cadence"])


@router.get("")
async def list_cadence(
    stage: Optional[str] = None,
    owner: Optional[str] = None,
    outcome: Optional[str] = "in_progress",
    due_today: bool = False,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """List cadence entries with filters."""
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        stmt = select(CadenceEntryRow)

        if stage:
            stmt = stmt.where(CadenceEntryRow.cadence_stage == stage)
        if owner and owner != "all":
            stmt = stmt.where(CadenceEntryRow.owner == owner)
        if outcome and outcome != "all":
            stmt = stmt.where(CadenceEntryRow.outcome == outcome)
        if due_today:
            today_end = now.replace(hour=23, minute=59, second=59)
            stmt = stmt.where(
                CadenceEntryRow.next_action_due <= today_end,
                CadenceEntryRow.next_action_due.isnot(None),
            )
        if search and search.strip():
            stmt = stmt.where(CadenceEntryRow.firm_name.ilike(f"%{search.strip()}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = stmt.order_by(
            CadenceEntryRow.next_action_due.asc().nulls_last()
        ).limit(limit).offset(offset)
        result = await session.execute(stmt)
        entries = list(result.scalars().all())

    return {
        "items": [_row_to_dict(e) for e in entries],
        "total": total,
    }


@router.get("/stats")
async def cadence_stats():
    """Summary statistics for the cadence dashboard."""
    from app.services.cadence_service import get_cadence_stats
    return await get_cadence_stats()


@router.put("/{entry_id}")
async def update_cadence(entry_id: str, body: dict):
    """Update a cadence entry — mark actions, advance stages, add notes."""
    action = body.get("action", "")
    note = body.get("note", "")
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CadenceEntryRow).where(CadenceEntryRow.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(404, "Cadence entry not found")

        if action == "mark_email_sent":
            entry.cadence_stage = "linkedin"
            entry.stage_entered_at = now
            entry.next_action = "LinkedIn connection request from Pranav"
            entry.next_action_due = now + __import__("datetime").timedelta(days=4)
            entry.owner = "pranav"

        elif action == "mark_linkedin_sent":
            entry.cadence_stage = "call_retry"
            entry.stage_entered_at = now
            entry.next_action = "Second call attempt (different contact)"
            entry.next_action_due = now + __import__("datetime").timedelta(days=7)
            entry.owner = "autocaller"

        elif action == "skip":
            # Advance to next logical stage
            stage_order = [
                "signal_detected", "call_1", "call_1_alt",
                "callback_pending", "email_intro", "linkedin",
                "call_retry",
            ]
            idx = stage_order.index(entry.cadence_stage) if entry.cadence_stage in stage_order else -1
            if idx >= 0 and idx < len(stage_order) - 1:
                next_stage = stage_order[idx + 1]
                entry.cadence_stage = next_stage
                entry.stage_entered_at = now
                entry.next_action = f"Skipped to {next_stage}"
                entry.next_action_due = now
            else:
                entry.outcome = "exhausted"
                entry.next_action = None
                entry.next_action_due = None

        elif action == "mark_dnc":
            entry.cadence_stage = "dnc"
            entry.outcome = "dnc"
            entry.next_action = None
            entry.next_action_due = None
            entry.owner = None

        elif action == "mark_demo_booked":
            entry.cadence_stage = "completed"
            entry.outcome = "demo_booked"
            entry.next_action = None
            entry.next_action_due = None
            entry.owner = None

        elif action == "add_note":
            existing = entry.notes or ""
            entry.notes = f"{existing}\n{now.strftime('%m/%d')}: {note}".strip()

        else:
            raise HTTPException(400, f"Unknown action: {action}")

        await session.commit()
        return _row_to_dict(entry)


@router.post("/{entry_id}/call")
async def cadence_call(entry_id: str, body: dict):
    """Place a call to a specific contact at a cadence firm.

    Body: {"name": "...", "phone": "+1...", "title": "...", "email": "..."}

    Creates/finds a lead in the patients table, places the call via the
    orchestrator, and links the call to this cadence entry.
    """
    from app.db.models import PatientRow
    from app.services.call_orchestrator import get_orchestrator
    from app.services.phone_normalize import normalize_phone

    name = body.get("name", "").strip()
    phone_raw = body.get("phone", "").strip()
    title = body.get("title", "")
    email = body.get("email")

    if not name or not phone_raw:
        raise HTTPException(400, "name and phone are required")

    # Cadence research rows often carry multi-value phone strings like
    # "Primary: 818-784-8544; Additional: 424-283-5822, Fax: ...". The
    # old inline normalizer stripped non-digits across the whole string
    # and rejected because the concatenated 30-digit result didn't match
    # 10/11 — silently dropping the lead. normalize_phone splits on the
    # first separator first, so the primary number wins.
    phone = normalize_phone(phone_raw)
    if not phone:
        raise HTTPException(400, f"phone not parseable to E.164: {phone_raw!r}")
    digits = re.sub(r"\D", "", phone)

    async with AsyncSessionLocal() as session:
        # Get cadence entry
        result = await session.execute(
            select(CadenceEntryRow).where(CadenceEntryRow.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(404, "Cadence entry not found")

        # Create or find lead
        patient_id = f"pif-{entry.pif_id}-{digits[-4:]}"
        result = await session.execute(
            select(PatientRow).where(PatientRow.patient_id == patient_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            lead = PatientRow(
                patient_id=patient_id,
                name=name,
                phone=phone,
                firm_name=entry.firm_name,
                title=title[:128] if title else None,
                email=email,
                source="cadence",
                practice_area="personal injury",
                tags=[f"cadence:{entry.id[:8]}"],
                notes=f"Cadence call for {entry.firm_name} | PIF ID: {entry.pif_id}",
            )
            session.add(lead)
            await session.commit()

    # Place the call
    orchestrator = get_orchestrator()
    persona_key = body.get("persona", "").strip().lower() or None
    call = await orchestrator.start_call(patient_id, call_mode="twilio", persona=persona_key)

    if call is None:
        raise HTTPException(409, "Call could not be started")

    # Link call to cadence entry
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CadenceEntryRow).where(CadenceEntryRow.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if entry:
            entry.call_ids = list(entry.call_ids or []) + [call.call_id]
            tried = list(entry.contacts_tried or [])
            contact = {"name": name, "phone": phone, "title": title}
            if contact not in tried:
                tried.append(contact)
                entry.contacts_tried = tried
            await session.commit()

    return {"call_id": call.call_id, "patient_id": patient_id}


@router.get("/{entry_id}/calls")
async def cadence_call_history(entry_id: str):
    """Get all calls linked to a cadence entry + any calls matching the firm's phone numbers."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CadenceEntryRow).where(CadenceEntryRow.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(404, "Cadence entry not found")

        # Get all phone numbers from available_contacts
        phones = set()
        for c in (entry.available_contacts or []):
            digits = "".join(ch for ch in (c.get("phone") or "") if ch.isdigit())
            if len(digits) >= 10:
                phones.add(digits[-10:])  # last 10 digits for matching

        # Find calls matching any of these phones OR linked via call_ids
        from sqlalchemy import or_, func
        conditions = []
        if entry.call_ids:
            conditions.append(CallLogRow.call_id.in_(entry.call_ids))
        for phone_digits in phones:
            conditions.append(CallLogRow.phone.contains(phone_digits))
        if entry.firm_name:
            conditions.append(func.lower(CallLogRow.firm_name) == entry.firm_name.lower())

        if not conditions:
            return {"calls": []}

        result = await session.execute(
            select(CallLogRow)
            .where(or_(*conditions))
            .order_by(CallLogRow.started_at.desc())
            .limit(50)
        )
        rows = list(result.scalars().all())

    calls = []
    for r in rows:
        calls.append({
            "call_id": r.call_id,
            "patient_name": r.patient_name,
            "phone": r.phone,
            "outcome": r.outcome,
            "duration_seconds": r.duration_seconds,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "carrier": getattr(r, "carrier", None),
            "voice_provider": r.voice_provider,
            "prompt_version": r.prompt_version,
            "mock_mode": r.mock_mode,
            "judge_score": getattr(r, "judge_score", None),
            "gatekeeper_contact": getattr(r, "gatekeeper_contact", None),
        })
    return {"calls": calls}


@router.post("/refresh")
async def refresh_cadence():
    """Manually trigger the daily cadence scan."""
    from app.services.cadence_service import run_daily_scan
    result = await run_daily_scan()
    return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# Priority queue — what the operator should call next
# ---------------------------------------------------------------------------

# In-memory cache for the autorespond fetch — burst-protect the PIF
# API when the /cadence page polls. Single-process only; that's fine
# for our 1-daemon-per-host deployment.
_autorespond_cache: dict = {"at": 0.0, "data": {}, "summary": None}
_AUTORESPOND_CACHE_TTL_SECS = 60


async def _cached_autorespond_signals() -> dict:
    import time
    from app.services.autorespond_signals import fetch_recent_events_grouped
    now = time.time()
    if (now - _autorespond_cache["at"]) < _AUTORESPOND_CACHE_TTL_SECS and _autorespond_cache["data"]:
        return _autorespond_cache["data"]
    try:
        data = await fetch_recent_events_grouped(days=7)
        _autorespond_cache["data"] = data
        _autorespond_cache["at"] = now
        return data
    except Exception:
        return _autorespond_cache.get("data") or {}


@router.get("/next-up")
async def cadence_next_up(
    limit: int = 50,
    include_completed: bool = False,
):
    """Priority-ordered call queue. Highest-score firms first.

    Joins cadence_entries with fresh autorespond-events signals
    (60s-cached) and computes a score per row. The order this returns
    is what the operator should call top-to-bottom.

    Score components in `app/services/autorespond_signals.py`:
        events_24h × 8 + events_7d × 2
        + ICP tier weight (A=20, B=10, C=3)
        + DM phone known: +10
        + cadence stage weight (callback_pending +15, signal +5, retry -5)
        - recent-call penalty
    """
    from app.services.autorespond_signals import priority_score
    autorespond = await _cached_autorespond_signals()

    async with AsyncSessionLocal() as session:
        stmt = select(CadenceEntryRow)
        if not include_completed:
            stmt = stmt.where(CadenceEntryRow.outcome == "in_progress")
        result = await session.execute(stmt)
        entries = list(result.scalars().all())

        # Recent calls per pif_id — for the call-age penalty.
        from sqlalchemy import desc as _desc
        recent_calls_by_phone: dict[str, datetime] = {}
        # Cheap lookup: pull the last 200 calls; index recent ones by
        # phone so we don't N+1 the DB.
        rec_stmt = (
            select(CallLogRow.phone, CallLogRow.started_at)
            .where(CallLogRow.started_at >= datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=48))
            .order_by(_desc(CallLogRow.started_at))
            .limit(500)
        )
        rec_res = await session.execute(rec_stmt)
        for phone, started in rec_res.all():
            digits = "".join(c for c in (phone or "") if c.isdigit())[-10:]
            if digits and digits not in recent_calls_by_phone:
                recent_calls_by_phone[digits] = started

    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    for e in entries:
        ar = autorespond.get(e.pif_id) or (e.intel or {}).get("autorespond") or {}
        events_24h = int(ar.get("events_24h") or 0)
        events_7d = int(ar.get("events_7d") or 0)
        contacts = e.available_contacts or []
        has_dm_phone = any((c.get("phone") or "").strip() for c in contacts)
        # last-call age — match against any phone in available_contacts
        last_call_age_hours: Optional[float] = None
        for c in contacts:
            digits = "".join(d for d in (c.get("phone") or "") if d.isdigit())[-10:]
            if not digits:
                continue
            ts = recent_calls_by_phone.get(digits)
            if ts:
                age = (now - ts).total_seconds() / 3600.0
                if last_call_age_hours is None or age < last_call_age_hours:
                    last_call_age_hours = age

        score = priority_score(
            events_24h=events_24h,
            events_7d=events_7d,
            icp_tier=e.icp_tier,
            has_dm_phone=has_dm_phone,
            cadence_stage=e.cadence_stage,
            last_call_age_hours=last_call_age_hours,
        )
        d = _row_to_dict(e)
        d["priority_score"] = score
        d["autorespond"] = {
            "events_24h": events_24h,
            "events_7d": events_7d,
            "latest_event_at": ar.get("latest_event_at"),
            "latest_subject": ar.get("latest_subject") or "",
            "top_agent_types": ar.get("top_agent_types") or [],
            "distinct_contact_count": int(ar.get("distinct_contact_count") or 0),
        }
        d["last_call_age_hours"] = last_call_age_hours
        rows.append(d)

    # Blocklist — Precise Imaging + imaging-vendor partners must never
    # appear in any call queue. See app/services/firm_blocklist.py.
    from app.services.firm_blocklist import filter_blocked
    rows = filter_blocked(rows)
    rows.sort(key=lambda r: r["priority_score"], reverse=True)
    return {"items": rows[:max(1, min(limit, 200))], "total": len(rows)}


@router.get("/autorespond-summary")
async def cadence_autorespond_summary():
    """Pass-through to PIF Stats /autorespond-events/summary.

    Surfaces aggregate stats on the Now / cadence pages: events_today,
    events_this_week, by_agent_type breakdown, by_day sparkline,
    top_firms.
    """
    from app.services.autorespond_signals import fetch_summary
    data = await fetch_summary()
    return data or {"error": "upstream unavailable"}


@router.get("/{pif_id}/autorespond-events")
async def cadence_firm_autorespond_events(
    pif_id: str,
    page: int = 1,
    page_size: int = 50,
):
    """Pass-through: events for a specific firm. Used by firm-detail page."""
    from app.services.autorespond_signals import fetch_events_for_firm
    data = await fetch_events_for_firm(pif_id, page=page, page_size=page_size)
    return data or {"items": [], "total": 0, "page": page, "page_size": page_size}


def _row_to_dict(e: CadenceEntryRow) -> dict:
    return {
        "id": e.id,
        "pif_id": e.pif_id,
        "firm_name": e.firm_name,
        "cadence_stage": e.cadence_stage,
        "stage_entered_at": e.stage_entered_at.isoformat() if e.stage_entered_at else None,
        "next_action": e.next_action,
        "next_action_due": e.next_action_due.isoformat() if e.next_action_due else None,
        "owner": e.owner,
        "outcome": e.outcome,
        "call_ids": e.call_ids or [],
        "contacts_tried": e.contacts_tried or [],
        "available_contacts": getattr(e, "available_contacts", None) or [],
        "intel": e.intel or {},
        "icp_tier": e.icp_tier,
        "icp_score": e.icp_score,
        "notes": e.notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }
