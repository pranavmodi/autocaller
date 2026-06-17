"""Durable operator notifications for dashboard modals."""
from __future__ import annotations

import os
import smtplib
import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.db.models import EmailSequenceRow, FirmContactRow, InboundEmailRow, OperatorNotificationRow
from app.services.comms_log import log_email
from app.services.email_notification_service import _resolve_sender_address, _send_email
from app.services.lead_email_composer import _sanitize_email_copy
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY, cadence_for


def notification_to_dict(row: OperatorNotificationRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "notification_type": row.notification_type,
        "priority": row.priority,
        "title": row.title,
        "body": row.body,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "stimulus": row.stimulus_json or {},
        "context": row.context_json or {},
        "suggested_action": row.suggested_action_json or {},
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "acknowledged_by": row.acknowledged_by,
    }


# Notification types we intentionally do NOT surface in the operator action
# center. lead_sequence_email_approval duplicated the /lead-gen review surface
# and made the bottom-right action center noisy — drafts are reviewed on
# /lead-gen, not here.
_SUPPRESSED_NOTIFICATION_TYPES = {"lead_sequence_email_approval"}


async def create_operator_notification(
    session: AsyncSession,
    *,
    notification_type: str,
    title: str,
    body: str = "",
    source_type: str,
    source_id: str,
    priority: str = "normal",
    stimulus: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    suggested_action: dict[str, Any] | None = None,
) -> OperatorNotificationRow:
    if notification_type in _SUPPRESSED_NOTIFICATION_TYPES:
        # Transient, un-persisted row: callers that read `.id` (paused_reason
        # bookkeeping) keep working; nothing is written to the DB.
        return OperatorNotificationRow(
            notification_type=notification_type[:64],
            priority=(priority or "normal")[:16],
            title=title[:255],
            body=body or "",
            source_type=source_type[:64],
            source_id=source_id[:128],
            status="suppressed",
        )
    existing = (await session.execute(
        select(OperatorNotificationRow).where(
            OperatorNotificationRow.notification_type == notification_type,
            OperatorNotificationRow.source_type == source_type,
            OperatorNotificationRow.source_id == source_id,
        )
    )).scalar_one_or_none()
    if existing:
        return existing

    row = OperatorNotificationRow(
        notification_type=notification_type[:64],
        priority=(priority or "normal")[:16],
        title=title[:255],
        body=body or "",
        source_type=source_type[:64],
        source_id=source_id[:128],
        stimulus_json=stimulus or {},
        context_json=context or {},
        suggested_action_json=suggested_action or {},
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row


async def list_pending_notifications(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(OperatorNotificationRow)
            .where(
                OperatorNotificationRow.status == "pending",
                OperatorNotificationRow.acknowledged_at.is_(None),
            )
            .order_by(OperatorNotificationRow.created_at.desc(), OperatorNotificationRow.id.desc())
            .limit(limit)
        )).scalars().all())
    return [notification_to_dict(row) for row in rows]


async def acknowledge_notification(
    notification_id: int,
    *,
    acknowledged_by: str = "operator",
) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(OperatorNotificationRow, notification_id)
        if not row:
            return None
        if row.acknowledged_at is None:
            row.acknowledged_at = datetime.now(timezone.utc)
            row.acknowledged_by = acknowledged_by[:128] if acknowledged_by else "operator"
            row.status = "acknowledged"
            await session.commit()
            await session.refresh(row)
        return notification_to_dict(row)


async def resolve_notifications(
    *,
    notification_type: str,
    source_id: str,
    resolved_by: str = "system",
) -> int:
    """Mark all pending notifications of a type+source as resolved. Used to
    auto-clear a `yelp_review_needed` prompt once the firm has a usable quote.
    Returns the count resolved."""
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(OperatorNotificationRow).where(
                OperatorNotificationRow.notification_type == notification_type,
                OperatorNotificationRow.source_id == source_id,
                OperatorNotificationRow.status == "pending",
            )
        )).scalars().all())
        now = datetime.now(timezone.utc)
        for row in rows:
            row.status = "resolved"
            row.acknowledged_at = now
            row.acknowledged_by = resolved_by[:128]
        if rows:
            await session.commit()
        return len(rows)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _reply_subject(subject: str) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject or 'reply'}"


def _thread_references(inbound: InboundEmailRow) -> str:
    refs: list[str] = []
    for raw in (inbound.references_text, inbound.in_reply_to, inbound.message_id):
        for token in (raw or "").replace("\r", " ").replace("\n", " ").split():
            token = token.strip()
            if token and token not in refs:
                refs.append(token)
    return " ".join(refs)


def _send_thread_reply_sync(
    *,
    inbound: InboundEmailRow,
    notification: OperatorNotificationRow,
    subject: str,
    body: str,
) -> str:
    to_email = (inbound.from_email or "").strip().lower()
    if not to_email or "@" not in parseaddr(to_email)[1]:
        raise RuntimeError("inbound sender email is not usable")
    if not body.strip():
        raise RuntimeError("draft body is empty")

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    smtp_user = os.getenv("SMTP_USERNAME", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_use_ssl = _truthy(os.getenv("SMTP_USE_SSL", "")) or smtp_port == 465
    smtp_use_tls = _truthy(os.getenv("SMTP_USE_TLS", "true")) and not smtp_use_ssl
    thread_from = os.getenv("THREAD_REPLY_FROM_EMAIL", "").strip()
    from_addr = _resolve_sender_address(
        thread_from or None,
        extra_allowed=[thread_from] if thread_from else None,
    )
    reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()
    if not smtp_host:
        raise RuntimeError("SMTP_HOST not set")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = _reply_subject(subject)
    msg["Message-ID"] = make_msgid()
    if reply_to:
        msg["Reply-To"] = reply_to
    if inbound.message_id:
        msg["In-Reply-To"] = inbound.message_id
    references = _thread_references(inbound)
    if references:
        msg["References"] = references
    msg["X-Autocaller-Notification-ID"] = str(notification.id)
    msg["X-Autocaller-Inbound-Email-ID"] = inbound.id
    msg.set_content(body)

    if smtp_use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)

    return str(msg["Message-ID"])


def _send_thread_reply_resend_sync(
    *,
    inbound: InboundEmailRow,
    notification: OperatorNotificationRow,
    subject: str,
    body: str,
) -> str:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not set")
    to_email = (inbound.from_email or "").strip().lower()
    if not to_email or "@" not in parseaddr(to_email)[1]:
        raise RuntimeError("inbound sender email is not usable")
    if not body.strip():
        raise RuntimeError("draft body is empty")

    thread_from = os.getenv("THREAD_REPLY_FROM_EMAIL", "").strip()
    from_addr = _resolve_sender_address(
        thread_from or None,
        extra_allowed=[thread_from] if thread_from else None,
    )
    reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()

    headers: dict[str, str] = {
        "X-Autocaller-Notification-ID": str(notification.id),
        "X-Autocaller-Inbound-Email-ID": inbound.id,
    }
    if inbound.message_id:
        headers["In-Reply-To"] = inbound.message_id
    references = _thread_references(inbound)
    if references:
        headers["References"] = references

    payload: dict[str, Any] = {
        "from": from_addr,
        "to": [to_email],
        "subject": _reply_subject(subject),
        "text": body,
        "headers": headers,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    with httpx.Client(timeout=20.0) as client:
        resp = client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if resp.status_code >= 300:
        raise RuntimeError(f"Resend HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json() if resp.content else {}
    return str(data.get("id", ""))


def _send_thread_reply(
    *,
    inbound: InboundEmailRow,
    notification: OperatorNotificationRow,
    subject: str,
    body: str,
) -> tuple[str, str]:
    transport = os.getenv("THREAD_REPLY_TRANSPORT", "").strip().lower()
    if not transport:
        transport = "zoho_api" if os.getenv("ZOHO_MAIL_REFRESH_TOKEN", "").strip() else (
            "smtp" if os.getenv("SMTP_HOST", "").strip() else "resend"
        )
    if transport == "zoho_api":
        context = notification.context_json if isinstance(notification.context_json, dict) else {}
        return (
            _send_email(
                _reply_subject(subject),
                body,
                to=inbound.from_email,
                message_type="lead_reply_draft",
                pif_id=context.get("pif_id"),
                recipient_name=context.get("contact_name"),
                transport="zoho_api",
            ),
            "zoho_api_thread",
        )
    if transport == "resend":
        return (
            _send_thread_reply_resend_sync(
                inbound=inbound,
                notification=notification,
                subject=subject,
                body=body,
            ),
            "resend_thread",
        )
    if transport != "smtp":
        raise RuntimeError("THREAD_REPLY_TRANSPORT must be 'smtp', 'resend', or 'zoho_api'")
    return (
        _send_thread_reply_sync(
            inbound=inbound,
            notification=notification,
            subject=subject,
            body=body,
        ),
        "smtp_thread",
    )


async def send_notification_draft_reply(
    notification_id: int,
    *,
    subject: str | None = None,
    body: str | None = None,
    sent_by: str = "operator",
) -> dict[str, Any] | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(OperatorNotificationRow, notification_id)
        if not row:
            return None
        if row.notification_type == "lead_sequence_email_approval" and row.source_type == "email_sequence_step":
            return await _send_sequence_draft_notification(
                session,
                row,
                subject=subject,
                body=body,
                sent_by=sent_by,
            )
        if row.notification_type != "lead_email_reply" or row.source_type != "inbound_email":
            raise ValueError("notification is not a lead email reply")
        if row.status != "pending" or row.acknowledged_at is not None:
            raise ValueError("notification is no longer pending")

        inbound = await session.get(InboundEmailRow, row.source_id)
        if not inbound:
            raise ValueError("source inbound email not found")

        suggested = dict(row.suggested_action_json or {})
        draft_subject = subject if subject is not None else str(suggested.get("draft_subject") or inbound.subject)
        draft_body = body if body is not None else str(suggested.get("draft_body") or "")
        msg_id, transport = await asyncio.to_thread(
            _send_thread_reply,
            inbound=inbound,
            notification=row,
            subject=draft_subject,
            body=draft_body,
        )

        sent_at = datetime.now(timezone.utc)
        suggested.update({
            "sent_at": sent_at.isoformat(),
            "sent_by": sent_by or "operator",
            "sent_message_id": msg_id,
            "sent_transport": transport,
            "sent_to": inbound.from_email,
            "sent_subject": _reply_subject(draft_subject),
            "sent_body": draft_body,
        })
        row.suggested_action_json = suggested
        row.status = "actioned"
        row.acknowledged_at = sent_at
        row.acknowledged_by = sent_by[:128] if sent_by else "operator"
        await session.commit()
        await session.refresh(row)

        if not transport.startswith("zoho_api"):
            await asyncio.to_thread(
                log_email,
                recipient_email=inbound.from_email,
                subject=_reply_subject(draft_subject),
                body=draft_body,
                message_type="lead_reply_draft",
                transport="resend" if transport.startswith("resend") else "smtp",
                message_id=msg_id,
                status="sent",
                pif_id=row.context_json.get("pif_id") if isinstance(row.context_json, dict) else None,
                recipient_name=(row.context_json or {}).get("contact_name") if isinstance(row.context_json, dict) else None,
            )
        return notification_to_dict(row)


def _optional_int(value) -> int | None:  # noqa: ANN001
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _send_sequence_draft_notification(
    session: AsyncSession,
    row: OperatorNotificationRow,
    *,
    subject: str | None,
    body: str | None,
    sent_by: str,
) -> dict[str, Any]:
    if row.status != "pending" or row.acknowledged_at is not None:
        raise ValueError("notification is no longer pending")

    context = row.context_json or {}
    suggested = dict(row.suggested_action_json or {})
    sequence_id = str(context.get("sequence_id") or "")
    contact_id = str(context.get("contact_id") or "")
    step_num = int(context.get("step_num") or 0)
    if not sequence_id or not contact_id or step_num <= 0:
        raise ValueError("notification is missing sequence context")

    seq = await session.get(EmailSequenceRow, sequence_id)
    if not seq:
        raise ValueError("source sequence not found")
    if seq.template_key != DEFAULT_TEMPLATE_KEY:
        raise ValueError("legacy fixed sequence drafts are disabled")
    if seq.current_step + 1 != step_num:
        raise ValueError("sequence step has changed since this draft was created")

    contact = await session.get(FirmContactRow, contact_id)
    if not contact or not contact.email:
        raise ValueError("sequence contact email not found")

    draft_subject = _sanitize_email_copy(subject if subject is not None else str(suggested.get("draft_subject") or ""))
    draft_body = _sanitize_email_copy(body if body is not None else str(suggested.get("draft_body") or ""))
    if not draft_subject.strip():
        raise RuntimeError("draft subject is empty")
    if not draft_body.strip():
        raise RuntimeError("draft body is empty")

    msg_id = await asyncio.to_thread(
        _send_email,
        draft_subject,
        draft_body,
        to=contact.email,
        message_type=str(suggested.get("message_type") or "dynamic_lead_email"),
        pif_id=contact.pif_id,
        recipient_name=contact.full_name,
        transport="zoho_api",
        brief_version=_optional_int(suggested.get("brief_version")),
    )

    sent_at = datetime.now(timezone.utc)
    seq.current_step = step_num
    seq.last_sent_at = sent_at
    if step_num >= seq.steps_total:
        seq.status = "completed"
        seq.next_step_due_at = None
    else:
        cadence = cadence_for(seq.template_key, seq.variant)
        gap_days = cadence[step_num] - cadence[step_num - 1]
        seq.status = "active"
        seq.next_step_due_at = sent_at + timedelta(days=gap_days)
    seq.paused_reason = None

    suggested.update({
        "sent_at": sent_at.isoformat(),
        "sent_by": sent_by or "operator",
        "sent_message_id": msg_id,
        "sent_transport": "configured_email_transport",
        "sent_to": contact.email,
        "sent_subject": draft_subject,
        "sent_body": draft_body,
        "brief_version": suggested.get("brief_version"),
    })
    row.suggested_action_json = suggested
    row.status = "actioned"
    row.acknowledged_at = sent_at
    row.acknowledged_by = sent_by[:128] if sent_by else "operator"
    await session.commit()
    await session.refresh(row)
    return notification_to_dict(row)
