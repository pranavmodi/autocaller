"""Cadence tracking service — manages multi-day outreach sequences for firms.

Daily scan (6 AM Eastern):
  Phase A: Ingest new signals from PIF Stats (recently-active firms)
  Phase B: Advance existing entries based on time + call outcomes

Stage flow:
  signal_detected → call_1 → [call_1_alt] → [callback_pending] →
  email_intro → linkedin → call_retry → completed / exhausted / dnc
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, func, or_

from app.db import AsyncSessionLocal
from app.db.models import CadenceEntryRow, CallLogRow

logger = logging.getLogger(__name__)

PIF_BASE = "https://emailprocessing.mediflow360.com/api/v1/pif-info"
SCAN_HOUR = 6  # 6 AM
SCAN_TZ = ZoneInfo("America/New_York")
RECENT_RESEARCH_DAYS = int(os.getenv("CADENCE_RECENT_RESEARCH_DAYS", "7"))


def _is_recent(iso_ts: Optional[str], days: int) -> bool:
    if not iso_ts:
        return False
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts) <= timedelta(days=days)


async def run_daily_scan() -> dict:
    """Run the full cadence scan. Returns {new: N, advanced: M}."""
    new = await _ingest_signals()
    advanced = await _advance_entries()
    await _link_recent_calls()
    logger.info("Cadence scan complete: new=%d advanced=%d", new, advanced)
    return {"new": new, "advanced": advanced}


async def _ingest_signals() -> int:
    """Phase A: fetch recently-active firms from PIF Stats, create entries."""
    created = 0
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            page = 1
            firms = []
            while True:
                resp = await client.get(
                    f"{PIF_BASE}/",
                    params={
                        "research_status": "completed",
                        "recently_researched": RECENT_RESEARCH_DAYS,
                        "page": page,
                        "page_size": 100,
                    },
                )
                if resp.status_code != 200:
                    break
                data = resp.json()
                for f in data.get("items", []):
                    beh = f.get("behavioral_data")
                    recently_active = bool(
                        beh and beh.get("days_since_last_contact", 999) <= 2
                    )
                    recently_researched = _is_recent(
                        f.get("last_researched_at"), RECENT_RESEARCH_DAYS
                    )
                    if recently_active or recently_researched:
                        firms.append(f)
                if page >= data.get("total_pages", 1):
                    break
                page += 1
                if page > 30:
                    break

        logger.info(
            "PIF Stats signal scan: %d firms (recent activity or researched <=%dd)",
            len(firms),
            RECENT_RESEARCH_DAYS,
        )

        async with AsyncSessionLocal() as session:
            existing_pifs = set()
            result = await session.execute(
                select(CadenceEntryRow.pif_id).where(
                    CadenceEntryRow.outcome == "in_progress"
                )
            )
            existing_pifs = {r[0] for r in result.all()}

            for firm in firms:
                pif_id = firm.get("id", "")
                if pif_id in existing_pifs:
                    continue

                now = datetime.now(timezone.utc)
                tomorrow_8am = (
                    datetime.now(SCAN_TZ)
                    .replace(hour=8, minute=0, second=0, microsecond=0)
                    + timedelta(days=1)
                ).astimezone(timezone.utc)

                # Collect all callable contacts from leadership + contacts
                contacts = []
                for l in (firm.get("leadership") or []):
                    phone = (l.get("phone") or "").replace("\u2011", "-").strip()
                    if phone:
                        contacts.append({
                            "name": l.get("name", ""),
                            "title": l.get("title", ""),
                            "phone": phone,
                            "email": l.get("email"),
                            "source": "leadership",
                        })
                for c in (firm.get("contacts") or []):
                    phone = (c.get("phone") or "").strip()
                    if phone:
                        contacts.append({
                            "name": c.get("name", ""),
                            "title": c.get("title", ""),
                            "phone": phone,
                            "email": c.get("email"),
                            "source": "contacts",
                        })

                entry = CadenceEntryRow(
                    id=str(uuid.uuid4()),
                    pif_id=pif_id,
                    firm_name=firm.get("firm_name", ""),
                    cadence_stage="signal_detected",
                    stage_entered_at=now,
                    next_action="Call managing partner",
                    next_action_due=tomorrow_8am,
                    owner="autocaller",
                    available_contacts=contacts,
                    outcome="in_progress",
                    icp_tier=firm.get("icp_tier"),
                    icp_score=firm.get("icp_score"),
                )
                session.add(entry)
                created += 1

            if created:
                await session.commit()

    except Exception as e:
        logger.warning("Cadence signal ingest failed: %s", e)

    return created


async def _advance_entries() -> int:
    """Phase B: advance stages based on time + call outcomes."""
    advanced = 0
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CadenceEntryRow).where(
                CadenceEntryRow.outcome == "in_progress"
            )
        )
        entries = list(result.scalars().all())

        for entry in entries:
            elapsed = (now - entry.stage_entered_at).total_seconds() / 3600  # hours
            old_stage = entry.cadence_stage

            if entry.cadence_stage == "signal_detected" and elapsed > 24:
                _transition(entry, "call_1", "AI call managing partner", now, "autocaller")
                advanced += 1

            elif entry.cadence_stage == "callback_pending" and elapsed > 48:
                _transition(entry, "email_intro", "Send intro email from Pranav", now + timedelta(hours=24), "pranav")
                advanced += 1

            elif entry.cadence_stage == "email_intro" and elapsed > 96:  # 4 days
                _transition(entry, "linkedin", "LinkedIn connection request from Pranav", now + timedelta(days=3), "pranav")
                advanced += 1

            elif entry.cadence_stage == "linkedin" and elapsed > 168:  # 7 days
                _transition(entry, "call_retry", "Second call attempt (different contact)", now, "autocaller")
                advanced += 1

        if advanced:
            await session.commit()

    return advanced


async def _link_recent_calls():
    """Link recent call_logs to cadence entries by firm_name."""
    async with AsyncSessionLocal() as session:
        # Get all active cadence entries
        result = await session.execute(
            select(CadenceEntryRow).where(
                CadenceEntryRow.outcome == "in_progress"
            )
        )
        entries = {e.firm_name.lower(): e for e in result.scalars().all()}
        if not entries:
            return

        # Get recent calls (last 48h)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        result = await session.execute(
            select(CallLogRow).where(
                CallLogRow.started_at >= cutoff,
                CallLogRow.outcome != "in_progress",
            )
        )
        calls = list(result.scalars().all())

        updated = False
        for call in calls:
            firm_key = (call.firm_name or "").lower()
            entry = entries.get(firm_key)
            if not entry:
                continue

            # Already linked?
            if call.call_id in (entry.call_ids or []):
                continue

            # Link the call
            entry.call_ids = list(entry.call_ids or []) + [call.call_id]

            # Update contacts_tried
            contact = {"name": call.patient_name, "phone": call.phone}
            tried = list(entry.contacts_tried or [])
            if contact not in tried:
                tried.append(contact)
                entry.contacts_tried = tried

            # Update intel from call
            intel = dict(entry.intel or {})
            if call.gatekeeper_contact:
                intel["gatekeeper"] = call.gatekeeper_contact
            if call.captured_contacts:
                intel["captured"] = call.captured_contacts
            entry.intel = intel

            # Advance stage based on call outcome
            outcome = call.outcome
            now = datetime.now(timezone.utc)

            if outcome == "demo_scheduled":
                entry.cadence_stage = "completed"
                entry.outcome = "demo_booked"
                entry.next_action = None
                entry.next_action_due = None
                entry.owner = None

            elif outcome == "not_interested":
                entry.cadence_stage = "dnc"
                entry.outcome = "dnc"
                entry.next_action = None
                entry.next_action_due = None
                entry.owner = None

            elif outcome == "callback_requested":
                _transition(entry, "callback_pending", "Send calendar invite to DM", now + timedelta(hours=4), "pranav")

            elif outcome == "gatekeeper_only":
                # Check if we got an email
                has_email = bool(
                    (call.gatekeeper_contact or {}).get("best_contact_email")
                    or any(c.get("email") for c in (call.captured_contacts or []))
                )
                if has_email:
                    _transition(entry, "email_intro", "Send intro email from Pranav", now + timedelta(days=1), "pranav")
                elif entry.cadence_stage in ("call_1", "signal_detected"):
                    _transition(entry, "call_1_alt", "Call different contact at firm", now + timedelta(hours=4), "autocaller")

            elif outcome in ("completed", "disconnected") and entry.cadence_stage == "call_retry":
                entry.cadence_stage = "exhausted"
                entry.outcome = "exhausted"
                entry.next_action = None
                entry.owner = None

            updated = True

        if updated:
            await session.commit()


def _transition(
    entry: CadenceEntryRow,
    stage: str,
    action: str,
    due: Optional[datetime],
    owner: str,
):
    entry.cadence_stage = stage
    entry.stage_entered_at = datetime.now(timezone.utc)
    entry.next_action = action
    entry.next_action_due = due
    entry.owner = owner


async def get_cadence_stats() -> dict:
    """Summary stats for the dashboard."""
    now = datetime.now(timezone.utc)
    today_end = now.replace(hour=23, minute=59, second=59)

    async with AsyncSessionLocal() as session:
        # By stage
        result = await session.execute(
            select(
                CadenceEntryRow.cadence_stage,
                func.count(),
            )
            .where(CadenceEntryRow.outcome == "in_progress")
            .group_by(CadenceEntryRow.cadence_stage)
        )
        by_stage = {r[0]: r[1] for r in result.all()}

        # By outcome
        result = await session.execute(
            select(
                CadenceEntryRow.outcome,
                func.count(),
            ).group_by(CadenceEntryRow.outcome)
        )
        by_outcome = {r[0]: r[1] for r in result.all()}

        # Due today
        result = await session.execute(
            select(func.count()).where(
                CadenceEntryRow.outcome == "in_progress",
                CadenceEntryRow.next_action_due <= today_end,
                CadenceEntryRow.next_action_due.isnot(None),
            )
        )
        due_today = result.scalar() or 0

        # Overdue
        result = await session.execute(
            select(func.count()).where(
                CadenceEntryRow.outcome == "in_progress",
                CadenceEntryRow.next_action_due < now,
                CadenceEntryRow.next_action_due.isnot(None),
            )
        )
        overdue = result.scalar() or 0

        total_active = sum(by_stage.values())

    return {
        "by_stage": by_stage,
        "by_outcome": by_outcome,
        "actions_due_today": due_today,
        "overdue": overdue,
        "total_active": total_active,
    }


async def cadence_scan_loop():
    """Background task: run the daily scan at SCAN_HOUR Eastern."""
    logger.info("Cadence scan loop started (hour=%d %s)", SCAN_HOUR, SCAN_TZ)
    last_scan_date: Optional[str] = None

    while True:
        try:
            now_local = datetime.now(SCAN_TZ)
            today_str = now_local.strftime("%Y-%m-%d")

            if now_local.hour == SCAN_HOUR and last_scan_date != today_str:
                logger.info("Cadence daily scan triggered for %s", today_str)
                result = await run_daily_scan()
                last_scan_date = today_str
                logger.info("Cadence scan result: %s", result)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Cadence scan loop error: %s", e)

        await asyncio.sleep(3600)  # check hourly
