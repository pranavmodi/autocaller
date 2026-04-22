"""Voicemail / no-reach follow-up emailer.

Background loop that picks completed calls which (a) left a voicemail or
(b) hit voicemail/no-answer/disconnected without leaving a message, and
sends the post-call "free consult" email when we have an address on file
or captured during the call.

Safety gate: `ALLOW_VOICEMAIL_EMAIL=true` must be set. Without it the
loop runs but skips every row (and returns that note). The underlying
send function also enforces the gate as a belt-and-suspenders.

Source-of-truth priority for the recipient address:
  1. captured_contacts entries on this call (most specific)
  2. patients.email (per-lead on-file address)
Neither present → skip, leave followup_email_sent=False.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, and_, or_, text

from app.db import AsyncSessionLocal
from app.db.models import CallLogRow, PatientRow
from app.providers.call_log_provider import get_call_log_provider
from app.services.email_notification_service import send_voicemail_followup_email

logger = logging.getLogger(__name__)

# Calls that never reached a human but we still want to follow up on.
_NO_REACH_OUTCOMES = ("voicemail", "no_answer", "disconnected")

# Don't email the same address more than once in this rolling window.
_DEDUP_WINDOW_DAYS = int(os.getenv("VOICEMAIL_EMAIL_DEDUP_DAYS", "7"))

# Strict recipient validator — rejects the junk we've seen in captured_contacts
# (placeholder strings like "[email protected]", "X and Y@z.com" joins, multi-@,
# embedded whitespace, markup brackets).
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _looks_like_valid_email(email: str) -> bool:
    if not email:
        return False
    e = email.strip()
    if len(e) > 254:
        return False
    if any(c in e for c in " \t\n\r[]()<>,"):
        return False
    if e.count("@") != 1:
        return False
    return bool(_EMAIL_RE.match(e))


def _is_truthy(v: str) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def _pick_email_from_captured(captured: Any) -> tuple[Optional[str], Optional[str]]:
    """Scan captured_contacts list for the first valid email + name pair."""
    if not captured:
        return None, None
    if isinstance(captured, str):
        try:
            captured = json.loads(captured)
        except Exception:
            return None, None
    if not isinstance(captured, list):
        return None, None
    for entry in captured:
        if not isinstance(entry, dict):
            continue
        # Avoid sending twice by skipping our own prior delivery records.
        if entry.get("source") == "voicemail_followup":
            continue
        email = (entry.get("email") or "").strip()
        if _looks_like_valid_email(email):
            return email, (entry.get("name") or "").strip() or None
    return None, None


async def _pick_pending(limit: int = 10, since_days: int = 30) -> list[CallLogRow]:
    """Find calls eligible for the follow-up email."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(CallLogRow)
            .where(CallLogRow.ended_at.is_not(None))
            .where(CallLogRow.followup_email_sent.is_(False))
            .where(
                or_(
                    CallLogRow.voicemail_left.is_(True),
                    and_(
                        CallLogRow.voicemail_left.is_(False),
                        CallLogRow.outcome.in_(_NO_REACH_OUTCOMES),
                    ),
                )
            )
            .where(
                CallLogRow.ended_at
                > datetime.now(timezone.utc).replace(microsecond=0)
                - _interval(days=since_days)
            )
            .order_by(CallLogRow.ended_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _interval(days: int):
    from datetime import timedelta
    return timedelta(days=days)


async def _lookup_patient_email(patient_id: str) -> tuple[Optional[str], Optional[str]]:
    if not patient_id:
        return None, None
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PatientRow.email, PatientRow.name).where(PatientRow.patient_id == patient_id)
        )
        row = result.first()
        if not row:
            return None, None
        email = (row[0] or "").strip() or None
        name = (row[1] or "").strip() or None
        return email, name


async def _patient_recently_emailed(
    patient_id: str, exclude_call_id: str, days: int = _DEDUP_WINDOW_DAYS
) -> bool:
    """True if any OTHER call for this patient already has
    followup_email_sent=True within the last N days. Uses the
    per-call boolean (reliably persisted) instead of the jsonb
    audit trail, so it catches duplicates even if the audit
    records were missed.
    """
    if not patient_id:
        return False
    sql = text(
        """
        SELECT 1
        FROM call_logs
        WHERE patient_id = :pid
          AND call_id <> :cid
          AND followup_email_sent = true
          AND ended_at > now() - make_interval(days => :days)
        LIMIT 1
        """
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sql, {"pid": patient_id, "cid": exclude_call_id, "days": days}
        )
        return result.first() is not None


async def _recently_emailed(email: str, days: int = _DEDUP_WINDOW_DAYS) -> bool:
    """True if this email address has a delivered voicemail_followup record
    in any call's captured_contacts within the last N days. Case-insensitive
    match on the email value.
    """
    if not email:
        return False
    sql = text(
        """
        SELECT 1
        FROM call_logs,
             jsonb_array_elements(
               COALESCE(captured_contacts, '[]'::jsonb)
             ) AS elem
        WHERE elem->>'source' = 'voicemail_followup'
          AND (elem->>'delivered')::boolean = true
          AND lower(elem->>'email') = lower(:email)
          AND (elem->>'captured_at')::timestamptz
              > now() - make_interval(days => :days)
        LIMIT 1
        """
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(sql, {"email": email, "days": days})
        return result.first() is not None


async def process_call(call: CallLogRow, dry_run: bool = False) -> dict:
    """Process one call. Returns a result dict for caller/CLI visibility."""
    call_id = call.call_id
    captured_email, captured_name = _pick_email_from_captured(call.captured_contacts)
    patient_email, patient_name = await _lookup_patient_email(call.patient_id)

    if captured_email and _looks_like_valid_email(captured_email):
        recipient = captured_email
        recipient_name = captured_name or patient_name or (call.firm_name or "")
        source = "captured_contact"
    elif patient_email and _looks_like_valid_email(patient_email):
        recipient = patient_email
        recipient_name = patient_name or ""
        source = "patients_db"
    else:
        return {
            "call_id": call_id, "skipped": True, "reason": "no_valid_email",
            "voicemail_left": bool(call.voicemail_left),
        }

    # DB-level dedup — two checks, either triggers a skip:
    #   (a) any prior call for the same patient with followup_email_sent=true
    #       in the window (belt: uses the reliably-persisted boolean)
    #   (b) any prior captured_contacts audit record for the same address
    #       in the window (suspenders: catches cross-patient dupes too)
    if await _patient_recently_emailed(call.patient_id, call_id, days=_DEDUP_WINDOW_DAYS):
        return {
            "call_id": call_id, "skipped": True,
            "reason": f"patient_already_emailed_within_{_DEDUP_WINDOW_DAYS}d",
            "recipient": recipient, "source": source,
            "voicemail_left": bool(call.voicemail_left),
        }
    if await _recently_emailed(recipient, days=_DEDUP_WINDOW_DAYS):
        return {
            "call_id": call_id, "skipped": True,
            "reason": f"email_already_sent_within_{_DEDUP_WINDOW_DAYS}d",
            "recipient": recipient, "source": source,
            "voicemail_left": bool(call.voicemail_left),
        }

    if dry_run:
        return {
            "call_id": call_id, "dry_run": True, "would_send_to": recipient,
            "source": source, "voicemail_left": bool(call.voicemail_left),
        }

    delivered, note = send_voicemail_followup_email(
        to_email=recipient,
        first_name=recipient_name,
        voicemail_left=bool(call.voicemail_left),
    )

    # Append delivery record to captured_contacts + flip followup_email_sent
    new_entry = {
        "name": recipient_name,
        "email": recipient,
        "phone": None,
        "source": "voicemail_followup",
        "voicemail_left_at_call": bool(call.voicemail_left),
        "delivered": delivered,
        "delivery_note": note,
        "resolved_from": source,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    existing = call.captured_contacts
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except Exception:
            existing = []
    if not isinstance(existing, list):
        existing = []
    updated = list(existing) + [new_entry]

    provider = get_call_log_provider()
    await provider.update_call(
        call_id,
        followup_email_sent=delivered,
        captured_contacts=updated,
    )
    logger.info(
        "voicemail_followup: call=%s → %s (delivered=%s, source=%s)",
        call_id, recipient, delivered, source,
    )
    return {
        "call_id": call_id, "delivered": delivered, "recipient": recipient,
        "source": source, "note": note,
        "voicemail_left": bool(call.voicemail_left),
    }


async def tick(limit: int = 10, since_days: int = 30, dry_run: bool = False) -> list[dict]:
    # Fetch a bit wider than `limit` so that within-batch dedup by recipient
    # still leaves `limit` unique addresses to actually process.
    fetch_limit = min(max(limit * 3, limit), 500)
    rows = await _pick_pending(limit=fetch_limit, since_days=since_days)

    # Within-batch dedup: for each unique resolved recipient email, keep
    # only the most recent call. Prevents a single invocation from emailing
    # the same firm twice even before the DB-level window check.
    seen_recipients: set[str] = set()
    deduped: list[CallLogRow] = []
    batch_skips: list[dict] = []
    for row in rows:
        captured_email, _ = _pick_email_from_captured(row.captured_contacts)
        if captured_email and _looks_like_valid_email(captured_email):
            recipient = captured_email
        else:
            pemail, _ = await _lookup_patient_email(row.patient_id)
            recipient = pemail if _looks_like_valid_email(pemail or "") else None
        if recipient:
            key = recipient.strip().lower()
            if key in seen_recipients:
                batch_skips.append({
                    "call_id": row.call_id, "skipped": True,
                    "reason": "duplicate_in_batch", "recipient": recipient,
                    "voicemail_left": bool(row.voicemail_left),
                })
                continue
            seen_recipients.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break

    out: list[dict] = list(batch_skips)
    for row in deduped:
        try:
            out.append(await process_call(row, dry_run=dry_run))
        except Exception as e:
            logger.exception("voicemail_followup failed for %s: %s", row.call_id, e)
            out.append({"call_id": row.call_id, "error": str(e)[:300]})
    return out


async def voicemail_followup_loop(interval_seconds: int = 120):
    """Poll loop for the daemon. Mirrors judge_loop structure."""
    logger.info("Voicemail-followup loop started (interval=%ds)", interval_seconds)
    while True:
        try:
            if not _is_truthy(os.getenv("ALLOW_VOICEMAIL_EMAIL", "false")):
                # Gate closed — no-op tick.
                await asyncio.sleep(interval_seconds)
                continue
            results = await tick(limit=10)
            sent = sum(1 for r in results if r.get("delivered"))
            skipped = sum(1 for r in results if r.get("skipped"))
            if sent or skipped:
                logger.info("voicemail_followup tick: sent=%d skipped=%d total=%d",
                            sent, skipped, len(results))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("voicemail_followup_loop tick failed: %s", e)
        await asyncio.sleep(interval_seconds)


async def process_one_by_id(call_id: str, dry_run: bool = False) -> dict:
    """Programmatic single-call entry point for CLI."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CallLogRow).where(CallLogRow.call_id == call_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return {"call_id": call_id, "error": "call_not_found"}
    return await process_call(row, dry_run=dry_run)
