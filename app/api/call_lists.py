"""Call-list endpoints — named cohorts of calls the operator wants to
revisit (e.g. re-dial for a VM blast, requeue gatekeepers).

For now: just the "went to VM" list. As we add more cohorts (callback
requested, hung up during pitch, etc.) they get their own route here.
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select, func

from app.db import AsyncSessionLocal
from app.db.models import CallLogRow


router = APIRouter(prefix="/api/call-lists", tags=["call-lists"])


@router.get("/voicemail")
async def voicemail_recipients(limit: int = 500):
    """Calls whose outcome was voicemail — candidates for a VM blast.

    Returns the MOST RECENT call per (patient_id, phone) pair so we
    don't list the same lead multiple times if we've attempted them
    more than once. `voicemail_left` tells the operator whether we
    already delivered our VM on that attempt — unblasted leads are
    usually the priority to re-dial.
    """
    limit = max(1, min(2000, limit))
    async with AsyncSessionLocal() as session:
        # Latest call per (patient_id, phone) where outcome went to VM.
        # A subquery picks the max started_at per lead; then we join back
        # to CallLogRow to get the full row for that latest attempt.
        latest_per_lead = (
            select(
                CallLogRow.patient_id,
                CallLogRow.phone,
                func.max(CallLogRow.started_at).label("latest_started_at"),
            )
            .where(CallLogRow.outcome == "voicemail")
            .group_by(CallLogRow.patient_id, CallLogRow.phone)
            .subquery()
        )
        result = await session.execute(
            select(CallLogRow)
            .join(
                latest_per_lead,
                (CallLogRow.patient_id == latest_per_lead.c.patient_id)
                & (CallLogRow.phone == latest_per_lead.c.phone)
                & (CallLogRow.started_at == latest_per_lead.c.latest_started_at),
            )
            .where(CallLogRow.outcome == "voicemail")
            .order_by(CallLogRow.started_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()

    return {
        "rows": [
            {
                "call_id": r.call_id,
                "patient_id": r.patient_id,
                "patient_name": r.patient_name,
                "firm_name": r.firm_name,
                "phone": r.phone,
                "lead_state": r.lead_state,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "duration_seconds": r.duration_seconds,
                "voicemail_left": bool(r.voicemail_left),
                "prompt_version": r.prompt_version,
            }
            for r in rows
        ],
        "count": len(rows),
    }
