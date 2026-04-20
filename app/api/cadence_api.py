"""Cadence tracking API — manage multi-day outreach sequences."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func, desc

from app.db import AsyncSessionLocal
from app.db.models import CadenceEntryRow

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


@router.post("/refresh")
async def refresh_cadence():
    """Manually trigger the daily cadence scan."""
    from app.services.cadence_service import run_daily_scan
    result = await run_daily_scan()
    return {"status": "ok", **result}


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
        "intel": e.intel or {},
        "icp_tier": e.icp_tier,
        "icp_score": e.icp_score,
        "notes": e.notes,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }
