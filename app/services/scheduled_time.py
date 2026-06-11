"""Shared parsing and formatting for operator-scheduled action times."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

_PT_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s+(PDT|PST|PT)\s*$", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduled time must include a timezone offset")
    return value.astimezone(UTC)


def parse_scheduled_time(value: str, *, now: datetime | None = None) -> datetime:
    """Parse CLI scheduling input and return an aware UTC datetime.

    Supported forms:
    - ISO-8601 with offset, e.g. ``2026-06-11T09:30:00-07:00``
    - ``HH:MM PDT|PST|PT`` for today in America/Los_Angeles
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("scheduled time is required")

    now_utc = _aware_utc(now or _utcnow())
    match = _PT_TIME_RE.match(raw)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("scheduled time must be HH:MM in 24-hour time")
        local_now = now_utc.astimezone(PACIFIC_TZ)
        scheduled_local = local_now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if scheduled_local <= local_now:
            raise ValueError("scheduled time is already past today in PT")
        return scheduled_local.astimezone(UTC)

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            'scheduled time must be ISO-8601 with offset or "HH:MM PT"'
        ) from exc
    scheduled_utc = _aware_utc(parsed)
    if scheduled_utc <= now_utc:
        raise ValueError("scheduled time is already in the past")
    return scheduled_utc


def format_pt(value: datetime | str | None) -> str:
    if value is None:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return _aware_utc(parsed).astimezone(PACIFIC_TZ).strftime("%Y-%m-%d %H:%M %Z")


def format_utc(value: datetime | str | None) -> str:
    if value is None:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return _aware_utc(parsed).strftime("%Y-%m-%d %H:%M:%S UTC")
