"""Workshop-only click and on-page engagement analytics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select

from app.db import AsyncSessionLocal
from app.db.models import (
    AuditLinkClickRow,
    AuditLinkRow,
    FirmContactRow,
    LeadGenObservationRow,
    PifFirmRow,
)


TRACKED_WORKSHOP_SOURCE = "workshop_linkedin"
SCANNER_UA_MARKERS = (
    "linkedinbot",
    "proofpoint",
    "mimecast",
    "barracuda",
    "safelinks",
    "urlprotect",
    "defender",
    "microsoft office",
    "microsoft preview",
    "googleimageproxy",
    "google web preview",
    "headlesschrome",
    "curl/",
    "python-requests",
)
REVEAL_EVENTS = {"content_revealed"}


def _clean(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _workshop_page_key(value: Any) -> str:
    page = _clean(value, 128).lower().strip("/")
    if page.startswith("workshops/"):
        page = page.split("/", 1)[1]
    if page.startswith("ai-for-"):
        page = page[7:]
    if page.startswith("workshop-"):
        page = page[9:]
    return page or "workshop"


def _is_workshop_page(value: Any) -> bool:
    page = _clean(value, 128).lower().strip("/")
    return page.startswith("workshop-") or page.startswith("workshops/")


def _is_scanner_ua(value: Any) -> bool:
    ua = _clean(value, 512).lower()
    return any(marker in ua for marker in SCANNER_UA_MARKERS)


def _is_reveal_event(event: str) -> bool:
    return event in REVEAL_EVENTS or event.endswith("_revealed")


def _dedupe_page_events(rows: list[Any]) -> list[Any]:
    """Collapse the duplicate global/page beacon events already in storage."""
    kept: list[Any] = []
    last_seen: dict[tuple[str, ...], datetime] = {}
    for row in sorted(rows, key=lambda item: item.created_at):
        raw = row.raw_event_json or {}
        event = _clean(raw.get("event"), 64) or "session_ready"
        key = (
            _clean(row.contact_id, 64),
            _clean(raw.get("session_id"), 64),
            _workshop_page_key(raw.get("page")),
            event,
            _clean(raw.get("click_text"), 180),
            _clean(raw.get("click_href"), 512),
        )
        previous = last_seen.get(key)
        if previous and abs((row.created_at - previous).total_seconds()) <= 1:
            continue
        last_seen[key] = row.created_at
        kept.append(row)
    return kept


def _session_quality(rows: list[Any]) -> str:
    raws = [row.raw_event_json or {} for row in rows]
    if any(_is_scanner_ua(raw.get("user_agent")) for raw in raws):
        return "scanner"
    events = {_clean(raw.get("event"), 64) or "session_ready" for raw in raws}
    if any(_is_reveal_event(event) for event in events) or events.intersection({"click", "scroll_50"}):
        return "human"
    max_time = max((int(raw.get("time_on_page_ms") or 0) for raw in raws), default=0)
    if max_time <= 6_000 and events.issubset({"session_ready", "first_pointer", "page_leave"}):
        return "scanner"
    return "suspect"


def _event_label(event: str, raw: dict[str, Any], quality: str) -> tuple[str, str]:
    if event == "redirect_click":
        if quality == "scanner":
            return "Link preview / scanner", "The tracked link was fetched automatically"
        return "Raw link open", "A browser-like client opened the tracked link"
    if _is_reveal_event(event):
        return "Prompt revealed", "The hidden workshop instruction was revealed"
    if event == "click":
        text = _clean(raw.get("click_text"), 180) or "Button or link"
        href = _clean(raw.get("click_href"), 512)
        return "Page click", f"{text}{f' -> {href}' if href else ''}"
    if event == "scroll_50":
        return "Scrolled 50%", "Reached at least halfway down the workshop page"
    if event == "session_ready":
        return "Workshop page loaded", "The landing-page tracking script ran"
    if event == "first_pointer":
        return "Pointer activity", "Pointer, touch, keyboard, or wheel activity detected"
    if event == "page_leave":
        ms = int(raw.get("time_on_page_ms") or 0)
        return "Left workshop page", f"Time on page: {round(ms / 1000, 1)} seconds"
    return event.replace("_", " ").title(), "Workshop funnel event"


def _firm_name(contact: FirmContactRow, firm: PifFirmRow | None) -> str:
    if firm and _clean(firm.firm_name):
        return _clean(firm.firm_name, 255)
    signals = contact.tech_signals or {}
    linkedin = signals.get("linkedin_workshop") if isinstance(signals, dict) else {}
    if isinstance(linkedin, dict) and _clean(linkedin.get("firm_name")):
        return _clean(linkedin.get("firm_name"), 255)
    return "Unknown firm"


def _contacts_with_activity(contacts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (item for item in contacts.values() if item.get("last_activity_at")),
        key=lambda item: (item["last_activity_at"], item["contact_name"]),
        reverse=True,
    )


async def workshop_click_analytics(*, since_days: int = 30, limit: int = 250) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days > 0 else None

    tracked_stmt = (
        select(AuditLinkRow, FirmContactRow, PifFirmRow)
        .join(FirmContactRow, FirmContactRow.id == AuditLinkRow.contact_id)
        .outerjoin(PifFirmRow, PifFirmRow.id == FirmContactRow.pif_id)
        .where(
            AuditLinkRow.kind == "workshop",
            AuditLinkRow.source == TRACKED_WORKSHOP_SOURCE,
        )
        .order_by(desc(AuditLinkRow.created_at))
    )
    click_stmt = (
        select(AuditLinkClickRow)
        .where(AuditLinkClickRow.source == TRACKED_WORKSHOP_SOURCE)
        .order_by(AuditLinkClickRow.clicked_at)
    )
    event_stmt = (
        select(LeadGenObservationRow)
        .where(
            LeadGenObservationRow.event_type == "page_session",
            LeadGenObservationRow.contact_id.is_not(None),
            LeadGenObservationRow.raw_event_json["page"].astext.like("workshop%"),
        )
        .order_by(LeadGenObservationRow.created_at)
    )
    if cutoff:
        click_stmt = click_stmt.where(AuditLinkClickRow.clicked_at >= cutoff)
        event_stmt = event_stmt.where(LeadGenObservationRow.created_at >= cutoff)

    async with AsyncSessionLocal() as session:
        tracked_rows = (await session.execute(tracked_stmt)).all()
        clicks = list((await session.execute(click_stmt)).scalars().all())
        raw_events = list((await session.execute(event_stmt)).scalars().all())

    contacts: dict[str, dict[str, Any]] = {}
    for link, contact, firm in tracked_rows:
        item = contacts.setdefault(contact.id, {
            "contact_id": contact.id,
            "contact_name": contact.full_name or contact.email or "Unknown contact",
            "contact_email": contact.email or "",
            "title": contact.title or "",
            "linkedin_url": contact.linkedin_url or "",
            "firm_name": _firm_name(contact, firm),
            "source": link.source,
            "tracking_link_created_at": _iso(link.created_at),
            "raw_link_clicks": 0,
            "scanner_link_clicks": 0,
            "sessions": 0,
            "confirmed_sessions": 0,
            "scanner_or_suspect_sessions": 0,
            "prompt_reveals": 0,
            "on_page_clicks": 0,
            "scroll_50": 0,
            "max_time_on_page_ms": 0,
            "last_activity_at": None,
        })
        if link.source == "workshop_linkedin":
            item["source"] = link.source

    activities: list[dict[str, Any]] = []
    for click in clicks:
        item = contacts.get(click.contact_id)
        if item is None:
            continue
        quality = "scanner" if _is_scanner_ua(click.user_agent) else "suspect"
        item["raw_link_clicks"] += 1
        if quality == "scanner":
            item["scanner_link_clicks"] += 1
        item["last_activity_at"] = _iso(click.clicked_at)
        label, detail = _event_label("redirect_click", {}, quality)
        activities.append({
            "id": click.id,
            "contact_id": click.contact_id,
            "contact_name": item["contact_name"],
            "firm_name": item["firm_name"],
            "occurred_at": _iso(click.clicked_at),
            "event": "redirect_click",
            "label": label,
            "detail": detail,
            "quality": quality,
            "page": "workshop redirect",
            "session_id": None,
            "time_on_page_ms": None,
            "user_agent": click.user_agent,
        })

    events = _dedupe_page_events([row for row in raw_events if _is_workshop_page((row.raw_event_json or {}).get("page"))])
    sessions: dict[str, list[Any]] = defaultdict(list)
    for row in events:
        raw = row.raw_event_json or {}
        session_id = _clean(raw.get("session_id"), 64) or row.id
        sessions[session_id].append(row)

    session_quality = {session_id: _session_quality(rows) for session_id, rows in sessions.items()}
    for session_id, rows in sessions.items():
        contact_ids = {_clean(row.contact_id, 64) for row in rows if _clean(row.contact_id, 64)}
        for contact_id in contact_ids:
            item = contacts.get(contact_id)
            if item is None:
                continue
            quality = session_quality[session_id]
            item["sessions"] += 1
            if quality == "human":
                item["confirmed_sessions"] += 1
            else:
                item["scanner_or_suspect_sessions"] += 1

    for row in events:
        item = contacts.get(row.contact_id or "")
        if item is None:
            continue
        raw = row.raw_event_json or {}
        event = _clean(raw.get("event"), 64) or "session_ready"
        session_id = _clean(raw.get("session_id"), 64) or row.id
        quality = session_quality.get(session_id, "suspect")
        time_ms = int(raw.get("time_on_page_ms") or 0)
        if _is_reveal_event(event):
            item["prompt_reveals"] += 1
        elif event == "click":
            item["on_page_clicks"] += 1
        elif event == "scroll_50":
            item["scroll_50"] += 1
        item["max_time_on_page_ms"] = max(item["max_time_on_page_ms"], time_ms)
        if not item["last_activity_at"] or row.created_at.isoformat() > item["last_activity_at"]:
            item["last_activity_at"] = _iso(row.created_at)
        label, detail = _event_label(event, raw, quality)
        activities.append({
            "id": row.id,
            "contact_id": row.contact_id,
            "contact_name": item["contact_name"],
            "firm_name": item["firm_name"],
            "occurred_at": _iso(row.created_at),
            "event": event,
            "label": label,
            "detail": detail,
            "quality": quality,
            "page": _workshop_page_key(raw.get("page")),
            "session_id": session_id,
            "time_on_page_ms": time_ms,
            "user_agent": _clean(raw.get("user_agent"), 512) or None,
        })

    for item in contacts.values():
        if item["prompt_reveals"]:
            item["status"] = "Prompt revealed"
        elif item["on_page_clicks"] or item["scroll_50"]:
            item["status"] = "Engaged"
        elif item["confirmed_sessions"]:
            item["status"] = "Visited"
        elif item["raw_link_clicks"] or item["sessions"]:
            item["status"] = "Scanner / suspect only"
        else:
            item["status"] = "No activity"

    contact_rows = _contacts_with_activity(contacts)
    activities.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
    all_last_activity = [item["last_activity_at"] for item in contact_rows if item["last_activity_at"]]
    return {
        "since_days": since_days,
        "summary": {
            "tracked_contacts": len(contact_rows),
            "raw_link_clicks": sum(item["raw_link_clicks"] for item in contact_rows),
            "scanner_link_clicks": sum(item["scanner_link_clicks"] for item in contact_rows),
            "confirmed_visitors": sum(item["confirmed_sessions"] for item in contact_rows),
            "scanner_or_suspect_sessions": sum(item["scanner_or_suspect_sessions"] for item in contact_rows),
            "prompt_reveals": sum(item["prompt_reveals"] for item in contact_rows),
            "on_page_clicks": sum(item["on_page_clicks"] for item in contact_rows),
            "last_activity_at": max(all_last_activity) if all_last_activity else None,
        },
        "contacts": contact_rows[:limit],
        "activities": activities[:limit],
    }
