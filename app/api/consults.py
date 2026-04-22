"""Consult-booking endpoints.

Public (unauth'd) POST /api/consults/book + GET /api/consults/slots power
the getpossibleminds.com/consult page. Authenticated GET /api/consults
lists bookings for the autocaller admin UI.

Slot model: fixed 30-minute slots during business hours (weekdays, 9am-
5pm local). Booked slots are excluded from the picker. No overlap
allowed. Times stored as UTC.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone, date, time
from typing import List, Optional

import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, and_

from app.db import AsyncSessionLocal
from app.db.models import ConsultBookingRow
from app.services.phone_normalize import normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/consults", tags=["consults"])

# Slot schedule — 30-minute windows on weekdays, business hours in the
# booking timezone. Keep this boring: no timezone negotiation, no
# holiday calendar for v1. If we ever need per-firm TZ or a holiday
# table we can add them; for now a simple fixed grid.
BOOKING_TZ_OFFSET_HOURS = int(os.getenv("CONSULT_TZ_OFFSET", "-7"))  # PT default
SLOT_MINUTES = 30
# Four 30-min slots per weekday, spread across morning / midday / afternoon.
# Each entry is (hour, minute) in the booking timezone (PT by default).
SLOT_TIMES: List[tuple[int, int]] = [
    (9, 0),    # 9:00 AM PT
    (11, 0),   # 11:00 AM PT
    (13, 30),  # 1:30 PM PT
    (16, 0),   # 4:00 PM PT
]
# Kept for backward-compat with any external callers; derived from SLOT_TIMES.
SLOT_START_HOUR = SLOT_TIMES[0][0] if SLOT_TIMES else 9
SLOT_END_HOUR = (SLOT_TIMES[-1][0] + 1) if SLOT_TIMES else 17


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BookingRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    firm: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=64)
    notes: Optional[str] = Field(None, max_length=4000)
    slot_start: str  # ISO-8601 UTC

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = (v or "").strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v


class BookingResponse(BaseModel):
    id: int
    slot_start: str
    slot_end: str
    message: str


def _generate_slots_for_date(d: date) -> List[datetime]:
    """Return the naive-UTC datetimes representing all 30-min slot
    starts for the given calendar date, expressed in business hours of
    BOOKING_TZ_OFFSET."""
    # Skip weekends.
    if d.weekday() >= 5:
        return []
    tz = timezone(timedelta(hours=BOOKING_TZ_OFFSET_HOURS))
    slots: List[datetime] = []
    for hour, minute in SLOT_TIMES:
        local = datetime.combine(d, time(hour, minute, tzinfo=tz))
        slots.append(local.astimezone(timezone.utc))
    return slots


@router.get("/slots")
async def list_slots(date_str: str = "", days: int = 7):
    """Return available 30-minute slots.

    `date_str` (YYYY-MM-DD) — returns slots for that date only.
    Otherwise returns the next `days` weekdays starting today (cap 21).
    """
    tz = timezone(timedelta(hours=BOOKING_TZ_OFFSET_HOURS))
    today = datetime.now(tz).date()

    dates: List[date] = []
    if date_str:
        try:
            dates = [date.fromisoformat(date_str)]
        except ValueError:
            raise HTTPException(status_code=400, detail="bad date format (YYYY-MM-DD)")
    else:
        days = max(1, min(21, days))
        d = today
        while len(dates) < days and (d - today).days <= 60:
            if d.weekday() < 5:
                dates.append(d)
            d += timedelta(days=1)

    candidate_slots: List[datetime] = []
    for d in dates:
        candidate_slots.extend(_generate_slots_for_date(d))

    if not candidate_slots:
        return {"slots": []}

    # Hide slots already in the past (plus a 30-min buffer — no same-second booking).
    now_utc = datetime.now(timezone.utc)
    candidate_slots = [s for s in candidate_slots if s > now_utc + timedelta(minutes=30)]

    if not candidate_slots:
        return {"slots": []}

    # Real bookings → definitively unavailable.
    window_start = min(candidate_slots)
    window_end = max(candidate_slots) + timedelta(minutes=SLOT_MINUTES)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConsultBookingRow.slot_start).where(
                and_(
                    ConsultBookingRow.slot_start >= window_start,
                    ConsultBookingRow.slot_start < window_end,
                    ConsultBookingRow.status == "booked",
                )
            )
        )
        real_booked = {row[0].replace(microsecond=0) for row in result.all()}

    # Light social-proof overlay: show a small fraction of slots as
    # "taken" even when unbooked so the calendar doesn't look deserted.
    # ~25% with the salt rotating daily — on average 1 of 4 per day.
    # Real bookings always win (a booked slot is always unavailable).
    salt = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _looks_busy(s: datetime) -> bool:
        import hashlib
        h = hashlib.sha256((salt + "|" + s.isoformat()).encode()).digest()[0]
        return h < 64  # ~25%

    slots_out: list[dict] = []
    for s in candidate_slots:
        key = s.replace(microsecond=0)
        iso = key.isoformat()
        available = key not in real_booked and not _looks_busy(key)
        slots_out.append({"iso": iso, "available": available})

    return {
        "slots": slots_out,
        "slot_minutes": SLOT_MINUTES,
        "tz_offset_hours": BOOKING_TZ_OFFSET_HOURS,
    }


def _parse_slot(slot_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(slot_str.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="bad slot_start format (ISO-8601)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _notify_booking(row: ConsultBookingRow) -> None:
    """Send an SMS to NOTIFY_NUMBER via Telnyx when a new booking comes in."""
    from app.services.twilio_sms_service import get_notify_number
    notify = get_notify_number()
    api_key = os.getenv("TELNYX_API_KEY", "").strip()
    frm = os.getenv("TELNYX_FROM_NUMBER", "").strip()
    if not (notify and api_key and frm):
        logger.info("[consults] notify skipped — NOTIFY_NUMBER/TELNYX_* not set")
        return
    slot_local = row.slot_start.astimezone(
        timezone(timedelta(hours=BOOKING_TZ_OFFSET_HOURS))
    ).strftime("%a %b %d, %-I:%M %p")
    parts = [
        f"New consult booking: {row.name}",
        f"Firm: {row.firm_name}" if row.firm_name else None,
        f"Email: {row.email}",
        f"Phone: {row.phone}" if row.phone else None,
        f"Slot: {slot_local} (PT)",
        f"Notes: {row.notes}" if row.notes else None,
    ]
    body = "\n".join(p for p in parts if p)[:1500]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.telnyx.com/v2/messages",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"from": frm, "to": notify, "text": body, "type": "SMS"},
            )
        if resp.status_code >= 300:
            logger.warning(
                "[consults] notify Telnyx HTTP %s: %s", resp.status_code, resp.text[:200]
            )
        else:
            logger.info("[consults] notify sent to %s", notify)
    except Exception as e:
        logger.warning("[consults] notify send failed: %s", type(e).__name__)


@router.post("/book", response_model=BookingResponse)
async def create_booking(request: Request, payload: BookingRequest):
    """Create a consult booking. Public endpoint — no auth, but
    CORS-gated to the marketing site origin.
    """
    slot_start = _parse_slot(payload.slot_start)
    slot_end = slot_start + timedelta(minutes=SLOT_MINUTES)

    # Sanity: must match an actual published slot (weekday + one of
    # SLOT_TIMES in the booking timezone). Catches tampering or stale
    # client state trying to book an arbitrary time.
    tz = timezone(timedelta(hours=BOOKING_TZ_OFFSET_HOURS))
    local = slot_start.astimezone(tz)
    if local.weekday() >= 5 or (local.hour, local.minute) not in SLOT_TIMES:
        raise HTTPException(status_code=400, detail="slot outside bookable window")
    if slot_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="slot in the past")

    # Conflict protection: the pre-insert SELECT is a best-effort
    # friendly-error path. The ACTUAL guarantee comes from the unique
    # partial index uq_consult_bookings_slot_booked (slot_start)
    # WHERE status='booked' — two concurrent inserts can both pass the
    # SELECT but only one survives COMMIT; the second raises
    # IntegrityError which we translate to 409.
    from sqlalchemy.exc import IntegrityError
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConsultBookingRow.id).where(
                and_(
                    ConsultBookingRow.slot_start == slot_start,
                    ConsultBookingRow.status == "booked",
                )
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="slot already booked")

        row = ConsultBookingRow(
            name=payload.name.strip(),
            firm_name=(payload.firm or "").strip() or None,
            email=str(payload.email).lower(),
            phone=normalize_phone(payload.phone or "") or None,
            slot_start=slot_start,
            slot_end=slot_end,
            notes=(payload.notes or "").strip() or None,
            status="booked",
            source="website",
            user_agent=(request.headers.get("user-agent") or "")[:512] or None,
            ip_address=(request.client.host if request.client else None),
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="slot already booked")
        await session.refresh(row)
        booking_id = row.id
        # Capture values before session closes.
        notify_row = row

    # Fire-and-forget SMS notification to the operator.
    try:
        await _notify_booking(notify_row)
    except Exception as e:
        logger.warning("[consults] notify outer fail: %s", e)

    # Confirmation email to the booker (includes the Google Meet link).
    # If SMTP isn't configured, log and continue — the booking still
    # succeeds and the operator was already SMS'd.
    try:
        tz = timezone(timedelta(hours=BOOKING_TZ_OFFSET_HOURS))
        slot_local_str = notify_row.slot_start.astimezone(tz).strftime(
            "%A, %B %-d at %-I:%M %p PT"
        )
        import asyncio as _asyncio
        from app.services.email_notification_service import send_consult_confirmation
        # Run in a thread — smtplib is blocking.
        await _asyncio.to_thread(
            send_consult_confirmation,
            to_email=notify_row.email,
            name=notify_row.name,
            firm_name=notify_row.firm_name,
            slot_local_str=slot_local_str,
            notes=notify_row.notes,
        )
        logger.info("[consults] confirmation email sent to %s", notify_row.email)
    except Exception as e:
        logger.warning(
            "[consults] confirmation email skipped: %s", e
        )

    return BookingResponse(
        id=booking_id,
        slot_start=slot_start.isoformat(),
        slot_end=slot_end.isoformat(),
        message="Booked. Check your email for the confirmation.",
    )


@router.get("/pending")
async def list_pending_bookings():
    """Return bookings that haven't been acknowledged yet.

    Drives the dashboard popup: the frontend polls this every few
    seconds, shows the first unacked booking as a modal, and calls
    POST /api/consults/{id}/acknowledge when the operator dismisses it.
    Once acked, the booking drops off this list permanently.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConsultBookingRow)
            .where(ConsultBookingRow.acknowledged_at.is_(None))
            .order_by(ConsultBookingRow.created_at.asc())
        )
        rows = result.scalars().all()
    return {
        "pending": [
            {
                "id": r.id,
                "name": r.name,
                "firm_name": r.firm_name,
                "email": r.email,
                "phone": r.phone,
                "slot_start": r.slot_start.isoformat(),
                "slot_end": r.slot_end.isoformat(),
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/{booking_id}/acknowledge")
async def acknowledge_booking(booking_id: int):
    """Mark a booking as acknowledged so the popup stops firing."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConsultBookingRow).where(ConsultBookingRow.id == booking_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="booking not found")
        if row.acknowledged_at is None:
            row.acknowledged_at = datetime.now(timezone.utc)
            await session.commit()
    return {"id": booking_id, "acknowledged": True}


@router.get("")
async def list_bookings(limit: int = 100):
    """Admin: list bookings (newest first). Auth-gated by the
    AuthMiddleware unless running in dev without AUTH_PASSWORD.
    """
    limit = max(1, min(500, limit))
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConsultBookingRow)
            .order_by(ConsultBookingRow.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
    return {
        "bookings": [
            {
                "id": r.id,
                "name": r.name,
                "firm_name": r.firm_name,
                "email": r.email,
                "phone": r.phone,
                "slot_start": r.slot_start.isoformat(),
                "slot_end": r.slot_end.isoformat(),
                "notes": r.notes,
                "status": r.status,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
                "acknowledged_at": (
                    r.acknowledged_at.isoformat() if r.acknowledged_at else None
                ),
            }
            for r in rows
        ]
    }
