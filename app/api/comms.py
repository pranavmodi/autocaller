"""Outbound-communications dashboard endpoints.

Reads from three independent tables and unions them by `sent_at`:
  - call_logs                (channel = 'call' or 'voicemail')
  - email_logs               (channel = 'email')
  - sms_logs                 (channel = 'sms')

Two routes:
  GET /api/communications                   — global feed, filterable
  GET /api/firms/{pif_id}/communications    — per-firm timeline

The shape returned is intentionally flat so the frontend can render
everything in a single table without per-channel branches.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_, func

from app.db import AsyncSessionLocal
from app.db.models import (
    CallLogRow, EmailLogRow, ProductTraceRow, SmsLogRow,
)


router = APIRouter(tags=["communications"])


def _patient_id_from_pif(pif_id: str) -> str:
    """`pifstats_sync` keys patient rows as `pif-{pif_id}`. The reverse
    map needs the same convention so the comms feed can link calls (which
    only know patient_id) back to the firm."""
    return f"pif-{pif_id}"


def _pif_from_patient_id(patient_id: str) -> Optional[str]:
    if patient_id and patient_id.startswith("pif-"):
        return patient_id[4:]
    return None


class CommItem(BaseModel):
    id: str                        # channel-prefixed (call:..., email:..., sms:...)
    channel: str                   # 'call' | 'voicemail' | 'email' | 'sms'
    occurred_at: str               # ISO8601 UTC
    pif_id: Optional[str] = None
    firm_name: Optional[str] = None
    contact_name: Optional[str] = None
    recipient: Optional[str] = None  # email address or phone number
    summary: str = ""              # one-line, channel-appropriate
    status: str = ""               # 'sent' | 'failed' | call outcome
    body_excerpt: Optional[str] = None
    call_id: Optional[str] = None
    duration_seconds: Optional[int] = None
    message_type: Optional[str] = None


class CommsResponse(BaseModel):
    items: list[CommItem]
    total: int


# ---------------------------------------------------------------------------
# Assemblers — each returns a list[CommItem] from one source table.
# Filters that don't apply to a source (e.g. message_type for calls) are
# applied at the union level below.
# ---------------------------------------------------------------------------

async def _calls_to_items(
    *, pif_id: Optional[str], since: Optional[datetime],
    until: Optional[datetime], limit: int,
) -> list[CommItem]:
    """Pull rows from call_logs. The pif_id ↔ patient_id mapping is the
    `pif-{pif_id}` convention from `pifstats_sync` — no DB join needed."""
    async with AsyncSessionLocal() as session:
        q = select(CallLogRow).order_by(CallLogRow.started_at.desc()).limit(limit)
        if pif_id:
            q = q.where(CallLogRow.patient_id == _patient_id_from_pif(pif_id))
        if since:
            q = q.where(CallLogRow.started_at >= since)
        if until:
            q = q.where(CallLogRow.started_at <= until)
        rows = (await session.execute(q)).scalars().all()

    items: list[CommItem] = []
    for r in rows:
        channel = "voicemail" if r.voicemail_left else "call"
        outcome = r.outcome or r.call_status or "in_progress"
        # Summary: prefer the human-readable one-liners we already have.
        summary = (
            (r.call_summary or "").strip()
            or (r.pain_point_summary or "").strip()
            or f"{outcome.replace('_', ' ')} · {r.duration_seconds or 0}s"
        )
        items.append(
            CommItem(
                id=f"call:{r.call_id}",
                channel=channel,
                occurred_at=r.started_at.astimezone(timezone.utc).isoformat(),
                pif_id=pif_id or _pif_from_patient_id(r.patient_id),
                firm_name=r.firm_name,
                contact_name=r.patient_name or None,
                recipient=r.phone or None,
                summary=summary[:300],
                status=outcome,
                call_id=r.call_id,
                duration_seconds=r.duration_seconds or None,
                message_type=None,
            )
        )
    return items


async def _emails_to_items(
    *, pif_id: Optional[str], since: Optional[datetime],
    until: Optional[datetime], limit: int,
) -> list[CommItem]:
    async with AsyncSessionLocal() as session:
        q = select(EmailLogRow).order_by(EmailLogRow.sent_at.desc()).limit(limit)
        if pif_id:
            q = q.where(EmailLogRow.pif_id == pif_id)
        if since:
            q = q.where(EmailLogRow.sent_at >= since)
        if until:
            q = q.where(EmailLogRow.sent_at <= until)
        rows = (await session.execute(q)).scalars().all()

        # If we have call_ids, look up firm_name for those rows so the
        # cross-firm feed has a label even when pif_id is null on the
        # email row (e.g. test sends, follow-ups predating instrumented pif_id).
        firm_map: dict[str, str] = {}
        call_ids = [r.call_id for r in rows if r.call_id]
        if call_ids:
            firm_rows = (await session.execute(
                select(CallLogRow.call_id, CallLogRow.firm_name)
                .where(CallLogRow.call_id.in_(call_ids))
            )).all()
            firm_map = {cid: name for cid, name in firm_rows if name}

        # Older email_logs rows stored only the first 500 body characters.
        # Lead-gen sends also carry the exact body keyed by provider message ID
        # in the append-only product trace, so recover it in one batched query.
        trace_map: dict[str, ProductTraceRow] = {}
        message_ids = [r.message_id for r in rows if r.message_id]
        if message_ids:
            trace_rows = (await session.execute(
                select(ProductTraceRow)
                .where(
                    ProductTraceRow.event_type == "email_sent",
                    ProductTraceRow.output_json["message_id"].astext.in_(message_ids),
                )
                .order_by(ProductTraceRow.created_at.desc())
            )).scalars().all()
            for trace in trace_rows:
                message_id = str((trace.output_json or {}).get("message_id") or "")
                if message_id and message_id not in trace_map:
                    trace_map[message_id] = trace

    items: list[CommItem] = []
    for r in rows:
        trace = trace_map.get(r.message_id or "")
        trace_input = trace.input_json if trace and isinstance(trace.input_json, dict) else {}
        trace_context = trace.context_json if trace and isinstance(trace.context_json, dict) else {}
        traced_body = trace_input.get("body")
        body = traced_body if isinstance(traced_body, str) and traced_body else r.body_excerpt
        items.append(CommItem(
            id=f"email:{r.id}",
            channel="email",
            occurred_at=r.sent_at.astimezone(timezone.utc).isoformat(),
            pif_id=r.pif_id,
            firm_name=(firm_map.get(r.call_id or "") or str(trace_context.get("firm_name") or "") or None),
            contact_name=r.recipient_name,
            recipient=r.recipient_email,
            summary=(r.subject or r.body_excerpt or "")[:300],
            status=r.status,
            body_excerpt=body,
            call_id=r.call_id,
            message_type=r.message_type,
        ))
    return items


async def _sms_to_items(
    *, pif_id: Optional[str], since: Optional[datetime],
    until: Optional[datetime], limit: int,
) -> list[CommItem]:
    async with AsyncSessionLocal() as session:
        q = select(SmsLogRow).order_by(SmsLogRow.sent_at.desc()).limit(limit)
        if pif_id:
            q = q.where(SmsLogRow.pif_id == pif_id)
        if since:
            q = q.where(SmsLogRow.sent_at >= since)
        if until:
            q = q.where(SmsLogRow.sent_at <= until)
        rows = (await session.execute(q)).scalars().all()

        firm_map: dict[str, str] = {}
        call_ids = [r.call_id for r in rows if r.call_id]
        if call_ids:
            firm_rows = (await session.execute(
                select(CallLogRow.call_id, CallLogRow.firm_name)
                .where(CallLogRow.call_id.in_(call_ids))
            )).all()
            firm_map = {cid: name for cid, name in firm_rows if name}

    return [
        CommItem(
            id=f"sms:{r.id}",
            channel="sms",
            occurred_at=r.sent_at.astimezone(timezone.utc).isoformat(),
            pif_id=r.pif_id,
            firm_name=firm_map.get(r.call_id or ""),
            contact_name=r.recipient_name,
            recipient=r.recipient_phone,
            summary=(r.body or "")[:300],
            status=r.status,
            body_excerpt=r.body or None,
            call_id=r.call_id,
        )
        for r in rows
    ]


def _parse_since(since: Optional[str]) -> Optional[datetime]:
    """Accept '7d' / '24h' / ISO8601. None disables the filter."""
    if not since:
        return None
    s = since.strip().lower()
    if s.endswith("d") and s[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    if s.endswith("h") and s[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(hours=int(s[:-1]))
    try:
        dt = datetime.fromisoformat(since)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid `since` value {since!r} (use Nd / Nh / ISO8601)",
        )


async def _assemble(
    *, pif_id: Optional[str], channel: Optional[str],
    since: Optional[datetime], until: Optional[datetime],
    status: Optional[str], q_text: Optional[str], limit: int,
) -> CommsResponse:
    # Per-source budget: ask each source for `limit` rows, then sort
    # and trim the union. With 4 channels this is at most 4x over-fetch.
    chans = {channel} if channel else {"call", "voicemail", "email", "sms"}
    items: list[CommItem] = []
    if "call" in chans or "voicemail" in chans:
        items.extend(await _calls_to_items(
            pif_id=pif_id, since=since, until=until, limit=limit,
        ))
    if "email" in chans:
        items.extend(await _emails_to_items(
            pif_id=pif_id, since=since, until=until, limit=limit,
        ))
    if "sms" in chans:
        items.extend(await _sms_to_items(
            pif_id=pif_id, since=since, until=until, limit=limit,
        ))

    # Channel filter for the call/voicemail split (which both come
    # from call_logs).
    if channel:
        items = [i for i in items if i.channel == channel]

    if status:
        s = status.strip().lower()
        items = [i for i in items if (i.status or "").lower() == s]

    if q_text:
        needle = q_text.strip().lower()
        if needle:
            items = [
                i for i in items
                if needle in (i.summary or "").lower()
                or needle in (i.recipient or "").lower()
                or needle in (i.contact_name or "").lower()
                or needle in (i.firm_name or "").lower()
            ]

    items.sort(key=lambda i: i.occurred_at, reverse=True)
    items = items[:limit]
    return CommsResponse(items=items, total=len(items))


@router.get("/api/communications", response_model=CommsResponse)
async def list_communications(
    channel: Optional[str] = Query(None, regex="^(call|voicemail|email|sms)$"),
    status: Optional[str] = None,
    since: Optional[str] = Query(None, description="Nd / Nh / ISO8601"),
    until: Optional[str] = Query(None, description="ISO8601 cutoff"),
    q: Optional[str] = Query(None, description="Free-text over summary/recipient/firm"),
    limit: int = Query(50, ge=1, le=500),
) -> CommsResponse:
    """Cross-firm outbound comms feed."""
    return await _assemble(
        pif_id=None,
        channel=channel,
        since=_parse_since(since),
        until=_parse_since(until),
        status=status,
        q_text=q,
        limit=limit,
    )


@router.get("/api/firms/{pif_id}/communications", response_model=CommsResponse)
async def list_firm_communications(
    pif_id: str,
    channel: Optional[str] = Query(None, regex="^(call|voicemail|email|sms)$"),
    since: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> CommsResponse:
    """Per-firm outbound comms timeline."""
    return await _assemble(
        pif_id=pif_id,
        channel=channel,
        since=_parse_since(since),
        until=None,
        status=None,
        q_text=None,
        limit=limit,
    )
