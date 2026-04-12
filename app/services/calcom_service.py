"""Cal.com v2 booking client.

Thin async wrapper around two Cal.com endpoints:
- GET /slots           — available time slots for a given event type
- POST /bookings       — book a specific slot for an invitee

Used by the AI `book_demo` tool during the cold-call discovery flow. The
service itself is stateless; the call orchestrator stamps the returned
booking_id onto the call log so future queries can surface the outcome.

Docs: https://cal.com/docs/api-reference/v2
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CALCOM_API_BASE = os.getenv("CALCOM_API_BASE", "https://api.cal.com/v2")
CALCOM_API_VERSION_HEADER = os.getenv("CALCOM_API_VERSION", "2024-08-13")


class CalComError(Exception):
    """Raised when a Cal.com request fails in a way callers should surface."""


@dataclass
class CalComSlot:
    """A single availability slot in a lead's local timezone."""
    start_iso: str     # ISO 8601 (e.g. "2026-04-14T14:00:00-04:00")
    end_iso: str
    attendees_count: int = 0

    def label(self) -> str:
        """Human-readable label the AI can speak to the lead."""
        try:
            dt = datetime.fromisoformat(self.start_iso)
            return dt.strftime("%A %B %-d at %-I:%M %p")
        except Exception:
            return self.start_iso


@dataclass
class CalComBooking:
    """Confirmed booking returned from Cal.com."""
    booking_id: str
    start_iso: str
    end_iso: str
    meeting_url: Optional[str] = None
    cancel_url: Optional[str] = None
    reschedule_url: Optional[str] = None


class CalComService:
    """Cal.com booking client. Single instance is fine; httpx is re-entrant."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = CALCOM_API_BASE,
        timeout: float = 15.0,
    ):
        self._api_key = api_key or os.getenv("CALCOM_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "cal-api-version": CALCOM_API_VERSION_HEADER,
                "Content-Type": "application/json",
            },
        )

    async def aclose(self):
        await self._client.aclose()

    def is_configured(self) -> bool:
        return bool(self._api_key)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    async def get_availability(
        self,
        event_type_id: int,
        timezone_name: str,
        days: int = 7,
        max_slots: int = 5,
    ) -> list[CalComSlot]:
        """Return up to `max_slots` upcoming slots within the next `days` days."""
        if not self.is_configured():
            raise CalComError("Cal.com is not configured (CALCOM_API_KEY missing)")

        now = datetime.now(timezone.utc)
        start = now.isoformat()
        end = (now + timedelta(days=days)).isoformat()

        params = {
            "eventTypeId": event_type_id,
            "startTime": start,
            "endTime": end,
            "timeZone": timezone_name,
        }
        url = f"{self._base_url}/slots"
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Cal.com slots request failed: %s", e)
            raise CalComError(f"slots request failed: {e}") from e

        data = resp.json() or {}
        # Cal.com v2 response shape: { "status": "success", "data": { "YYYY-MM-DD": [{"start": "..."}] } }
        by_date = (data.get("data") or {}) if isinstance(data.get("data"), dict) else {}
        slots: list[CalComSlot] = []
        for _, day_slots in sorted(by_date.items()):
            for s in day_slots or []:
                start_iso = s.get("start") or s.get("time")
                if not start_iso:
                    continue
                end_iso = s.get("end", "")
                slots.append(CalComSlot(
                    start_iso=start_iso,
                    end_iso=end_iso,
                    attendees_count=int(s.get("attendees", 0) or 0),
                ))
                if len(slots) >= max_slots:
                    return slots
        return slots

    # ------------------------------------------------------------------
    # Booking
    # ------------------------------------------------------------------
    async def book_slot(
        self,
        event_type_id: int,
        slot_iso: str,
        invitee_name: str,
        invitee_email: str,
        timezone_name: str,
        metadata: Optional[dict] = None,
        notes: Optional[str] = None,
    ) -> CalComBooking:
        """Book a specific slot. Returns the created booking record."""
        if not self.is_configured():
            raise CalComError("Cal.com is not configured (CALCOM_API_KEY missing)")

        payload: dict = {
            "eventTypeId": event_type_id,
            "start": slot_iso,
            "attendee": {
                "name": invitee_name,
                "email": invitee_email,
                "timeZone": timezone_name,
                "language": "en",
            },
        }
        if metadata:
            payload["metadata"] = {str(k): str(v) for k, v in metadata.items()}
        if notes:
            payload["bookingFieldsResponses"] = {"notes": notes}

        url = f"{self._base_url}/bookings"
        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            body = getattr(e, "response", None)
            detail = body.text if body is not None else ""
            logger.warning("Cal.com booking failed: %s — %s", e, detail[:500])
            raise CalComError(f"booking failed: {e}") from e

        data = (resp.json() or {}).get("data") or {}
        booking_id = str(data.get("id") or data.get("uid") or "")
        start_iso = data.get("start", slot_iso)
        end_iso = data.get("end", "")
        meeting_url = data.get("meetingUrl") or data.get("videoCallUrl")
        cancel_url = data.get("cancelUrl") or data.get("cancel_url")
        reschedule_url = data.get("rescheduleUrl") or data.get("reschedule_url")

        if not booking_id:
            raise CalComError("booking succeeded but no booking id returned")

        logger.info(
            "Cal.com booking created: id=%s start=%s invitee=%s",
            booking_id, start_iso, invitee_email,
        )
        return CalComBooking(
            booking_id=booking_id,
            start_iso=start_iso,
            end_iso=end_iso,
            meeting_url=meeting_url,
            cancel_url=cancel_url,
            reschedule_url=reschedule_url,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_service: Optional[CalComService] = None


def get_calcom_service() -> CalComService:
    global _service
    if _service is None:
        _service = CalComService()
    return _service
