"""Autorespond-events signals from PIF Stats.

Wraps the three new /autorespond-events endpoints from the PIF Stats
API and aggregates them into per-firm signal summaries we can use to
prioritise the call queue.

The key insight: a firm with autorespond events in the last 24-48 hours
has had real humans at that firm interact with our Precise Imaging
system *just now*. That's a far sharper signal than ICP tier or
"recently researched" for "should we call this firm next."

Signal aggregates we compute per pif_id:
    events_24h         — count in last 24 hours
    events_7d          — count in last 7 days
    latest_event_at    — most recent created_at (ISO string)
    latest_subject     — most recent email_subject (truncated 200 chars)
    top_agent_types    — agent_types sorted by frequency, top 3
    distinct_contacts  — list of {name, email} pairs from events
    distinct_contact_count
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


PIF_BASE = os.getenv(
    "PIFSTATS_BASE_URL",
    "https://emailprocessing.mediflow360.com/api/v1/pif-info",
)
HTTP_TIMEOUT = 30.0
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 50  # 5000 events ceiling per fetch — generous; events <100/day in practice


async def _get_json(path: str, params: Optional[dict] = None) -> Optional[dict]:
    url = f"{PIF_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params or None)
        if resp.status_code != 200:
            logger.warning(
                "[autorespond] %s HTTP %s: %s",
                path, resp.status_code, resp.text[:300],
            )
            return None
        return resp.json()
    except Exception as e:
        logger.warning("[autorespond] %s raised %s", path, e)
        return None


async def fetch_recent_events(days: int = 7) -> list[dict]:
    """Fetch autorespond events from PIF Stats for the last `days` days.

    Paginates automatically. Returns the raw event dicts. Each dict has:
        id, pif_id, firm_name, agent_type, contact_email, contact_name,
        conversation_id, email_subject, tags[], response_sent,
        test_mode, details, created_at
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    out: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        data = await _get_json(
            "/autorespond-events",
            params={
                "date_from": cutoff,
                "page": page,
                "page_size": DEFAULT_PAGE_SIZE,
            },
        )
        if not data:
            break
        items = data.get("items") or []
        out.extend(items)
        total_pages = int(data.get("total_pages") or 1)
        if page >= total_pages:
            break
        page += 1
    return out


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (ValueError, AttributeError):
        return None


async def fetch_recent_events_grouped(
    days: int = 7,
    *,
    include_test_mode: bool = False,
) -> dict[str, dict]:
    """Fetch + group events by pif_id into a per-firm signal summary.

    Returns map of pif_id → {
        events_24h, events_7d,
        latest_event_at,            # ISO string or None
        latest_subject,             # str (≤200 chars) or ""
        top_agent_types,            # list[str] of up to 3
        distinct_contacts,          # list[{name, email}]
        distinct_contact_count,
        firm_name,                  # for display
    }

    Filters out test-mode events by default — they're sandbox traffic
    and shouldn't drive call prioritisation.
    """
    events = await fetch_recent_events(days=days)
    if not events:
        return {}

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    by_pif: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        if not include_test_mode and ev.get("test_mode"):
            continue
        pif_id = ev.get("pif_id")
        if pif_id:
            by_pif[pif_id].append(ev)

    summary: dict[str, dict] = {}
    for pif_id, evs in by_pif.items():
        events_24h = 0
        latest_dt: Optional[datetime] = None
        latest_subject = ""
        agent_counter: Counter[str] = Counter()
        contacts: dict[str, dict] = {}
        firm_name = ""
        for ev in evs:
            created_at = _parse_iso(ev.get("created_at"))
            if created_at and created_at >= cutoff_24h:
                events_24h += 1
            if created_at and (latest_dt is None or created_at > latest_dt):
                latest_dt = created_at
                latest_subject = (ev.get("email_subject") or "")[:200]
            agent = (ev.get("agent_type") or "").strip()
            if agent:
                agent_counter[agent] += 1
            email = (ev.get("contact_email") or "").strip().lower()
            name = (ev.get("contact_name") or "").strip()
            if email and email not in contacts:
                contacts[email] = {"name": name, "email": email}
            if not firm_name:
                firm_name = ev.get("firm_name") or ""

        summary[pif_id] = {
            "events_24h": events_24h,
            "events_7d": len(evs),
            "latest_event_at": latest_dt.isoformat() if latest_dt else None,
            "latest_subject": latest_subject,
            "top_agent_types": [a for a, _ in agent_counter.most_common(3)],
            "agent_type_counts": dict(agent_counter),
            "distinct_contacts": list(contacts.values()),
            "distinct_contact_count": len(contacts),
            "firm_name": firm_name,
        }
    return summary


async def fetch_summary() -> Optional[dict]:
    """Pass-through: GET /autorespond-events/summary."""
    return await _get_json("/autorespond-events/summary")


async def fetch_events_for_firm(
    pif_id: str, *, page: int = 1, page_size: int = 50,
) -> Optional[dict]:
    """Pass-through: GET /{pif_id}/autorespond-events."""
    return await _get_json(
        f"/{pif_id}/autorespond-events",
        params={"page": page, "page_size": page_size},
    )


# ---------------------------------------------------------------------------
# Priority scoring — used by /api/cadence/next-up
# ---------------------------------------------------------------------------

def priority_score(
    *,
    events_24h: int = 0,
    events_7d: int = 0,
    icp_tier: Optional[str] = None,
    has_dm_phone: bool = False,
    cadence_stage: str = "",
    last_call_age_hours: Optional[float] = None,
) -> int:
    """Compute the call-queue priority score for a cadence entry.

    Higher = call sooner. Components, in order of weight:

      Recent autorespond activity (the new signal):
        events_24h × 8   — strongest signal: real humans interacted
                            with our system today
        events_7d  × 2

      ICP tier — partner-quality lead bias:
        A → +20, B → +10, C → +3

      DM phone known: +10  — actually callable

      Cadence stage:
        signal_detected → +5  (fresh, ready to dial)
        call_1          → +0
        call_retry      → -5  (already attempted, less urgent)
        callback_pending → +15 (DM asked for callback, time-sensitive)
        completed/exhausted/dnc → -1000 (filter, never call)

      Recent-call-age penalty:
        last_call < 6h  → -50
        last_call < 24h → -10
    """
    score = 0
    score += events_24h * 8
    score += events_7d * 2
    tier_weight = {"A": 20, "B": 10, "C": 3}
    score += tier_weight.get((icp_tier or "").upper(), 0)
    if has_dm_phone:
        score += 10
    stage_weight = {
        "signal_detected": 5,
        "call_1": 0,
        "call_1_alt": 0,
        "callback_pending": 15,
        "email_intro": -2,
        "linkedin": -3,
        "call_retry": -5,
        "completed": -1000,
        "exhausted": -1000,
        "dnc": -1000,
    }
    score += stage_weight.get(cadence_stage, 0)
    if last_call_age_hours is not None:
        if last_call_age_hours < 6:
            score -= 50
        elif last_call_age_hours < 24:
            score -= 10
    return score
