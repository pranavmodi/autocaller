"""Resend webhook ingestion for outbound email feedback.

Resend signs webhooks using Svix headers. The public route verifies the raw
request body, then this service converts provider events into local email-log
state and lead-generation observations.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    EmailLogRow,
    EmailSequenceRow,
    FirmContactRow,
    LeadGenBatchItemRow,
    LeadGenObservationRow,
)


class ResendWebhookVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class ResendEventClassification:
    log_status: str
    observation_type: str | None = None
    outcome: str | None = None
    confidence: int | None = None
    next_action: str | None = None
    pause_sequence: bool = False
    update_batch_item: bool = False


EVENT_CLASSIFICATIONS: dict[str, ResendEventClassification] = {
    "email.sent": ResendEventClassification("sent"),
    "email.delivered": ResendEventClassification(
        "delivered",
        observation_type="email_delivered",
        outcome="neutral",
        confidence=50,
        next_action="no_action",
    ),
    "email.delivery_delayed": ResendEventClassification(
        "delayed",
        observation_type="email_delivery_delayed",
        outcome="neutral",
        confidence=75,
        next_action="pause_sequence",
        pause_sequence=True,
    ),
    "email.bounced": ResendEventClassification(
        "bounced",
        observation_type="email_bounce",
        outcome="bounce",
        confidence=95,
        next_action="suppress_email",
        pause_sequence=True,
        update_batch_item=True,
    ),
    "email.failed": ResendEventClassification(
        "failed",
        observation_type="email_failed",
        outcome="bounce",
        confidence=80,
        next_action="pause_sequence",
        pause_sequence=True,
        update_batch_item=True,
    ),
    "email.complained": ResendEventClassification(
        "complained",
        observation_type="email_complaint",
        outcome="do_not_contact",
        confidence=100,
        next_action="mark_do_not_contact",
        pause_sequence=True,
        update_batch_item=True,
    ),
    "email.suppressed": ResendEventClassification(
        "suppressed",
        observation_type="email_suppressed",
        outcome="bounce",
        confidence=95,
        next_action="suppress_email",
        pause_sequence=True,
        update_batch_item=True,
    ),
    "email.opened": ResendEventClassification(
        "opened",
        observation_type="email_open",
        outcome="opened_or_clicked",
        confidence=60,
        next_action="continue_sequence",
        update_batch_item=True,
    ),
    "email.clicked": ResendEventClassification(
        "clicked",
        observation_type="email_click",
        outcome="opened_or_clicked",
        confidence=70,
        next_action="continue_sequence",
        update_batch_item=True,
    ),
}


def _get_header(headers: Mapping[str, str], name: str) -> str:
    needle = name.lower()
    for key, value in headers.items():
        if key.lower() == needle:
            return value
    return ""


def _secret_bytes(secret: str) -> bytes:
    raw = secret.strip()
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_") :]
    try:
        padding = "=" * (-len(raw) % 4)
        return base64.b64decode(raw + padding, validate=True)
    except Exception:
        return raw.encode("utf-8")


def verify_svix_signature(
    *,
    payload: bytes,
    headers: Mapping[str, str],
    secret: str,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    """Verify Svix-style HMAC signature headers used by Resend."""
    webhook_id = _get_header(headers, "svix-id") or _get_header(headers, "webhook-id")
    timestamp = _get_header(headers, "svix-timestamp") or _get_header(
        headers, "webhook-timestamp"
    )
    signature = _get_header(headers, "svix-signature") or _get_header(
        headers, "webhook-signature"
    )
    if not webhook_id or not timestamp or not signature:
        raise ResendWebhookVerificationError("missing_svix_headers")
    try:
        ts = int(timestamp)
    except ValueError as e:
        raise ResendWebhookVerificationError("invalid_svix_timestamp") from e
    clock = int(time.time()) if now is None else now
    if tolerance_seconds > 0 and abs(clock - ts) > tolerance_seconds:
        raise ResendWebhookVerificationError("stale_svix_timestamp")

    signed = f"{webhook_id}.{timestamp}.".encode("utf-8") + payload
    expected = base64.b64encode(
        hmac.new(_secret_bytes(secret), signed, hashlib.sha256).digest()
    ).decode("ascii")
    for part in signature.split():
        version, _, value = part.partition(",")
        if version == "v1" and value and hmac.compare_digest(value, expected):
            return
    raise ResendWebhookVerificationError("invalid_svix_signature")


def parse_resend_event(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError("invalid_json") from e
    if not isinstance(payload, dict):
        raise ValueError("invalid_payload")
    if not isinstance(payload.get("data"), dict):
        raise ValueError("missing_data")
    return payload


def classify_resend_event(event_type: str) -> ResendEventClassification:
    return EVENT_CLASSIFICATIONS.get(
        event_type,
        ResendEventClassification("event"),
    )


def _first_recipient(data: dict[str, Any]) -> str:
    to = data.get("to")
    if isinstance(to, list) and to:
        return str(to[0]).strip().lower()
    if isinstance(to, str):
        return to.strip().lower()
    return ""


def _provider_error(event_type: str, data: dict[str, Any]) -> str | None:
    if event_type == "email.bounced":
        bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
        parts = [
            str(bounce.get("type") or "").strip(),
            str(bounce.get("subType") or "").strip(),
            str(bounce.get("message") or "").strip(),
        ]
        msg = " | ".join(p for p in parts if p)
        return msg or "Resend reported email.bounced"
    if event_type == "email.delivery_delayed":
        return "Resend reported email.delivery_delayed"
    if event_type == "email.failed":
        error = data.get("error")
        if isinstance(error, dict):
            return json.dumps(error, sort_keys=True)[:500]
        return str(error or "Resend reported email.failed")[:500]
    if event_type == "email.suppressed":
        return "Resend reported email.suppressed"
    if event_type == "email.complained":
        return "Resend reported email.complained"
    return None


def _template_from_message_type(message_type: str | None) -> str | None:
    if not message_type:
        return None
    if message_type.startswith("records_audit_"):
        return "precise_records_audit"
    if message_type.startswith("pain_") or message_type.startswith("precise_pain"):
        return "precise_pain_4step"
    return None


async def _find_lead_item(
    session,
    *,
    log: EmailLogRow,
    recipient_email: str,
) -> tuple[LeadGenBatchItemRow | None, EmailSequenceRow | None, FirmContactRow | None]:
    email = (recipient_email or log.recipient_email or "").strip().lower()
    if not email:
        return None, None, None

    contact_query = select(FirmContactRow).where(func.lower(FirmContactRow.email) == email)
    if log.pif_id:
        contact_query = contact_query.where(FirmContactRow.pif_id == log.pif_id)
    contacts = list((await session.execute(contact_query)).scalars().all())
    if not contacts and log.pif_id:
        contacts = list((
            await session.execute(
                select(FirmContactRow).where(func.lower(FirmContactRow.email) == email)
            )
        ).scalars().all())

    template_key = _template_from_message_type(log.message_type)
    for contact in contacts:
        seq_query = select(EmailSequenceRow).where(EmailSequenceRow.contact_id == contact.id)
        if template_key:
            seq_query = seq_query.where(EmailSequenceRow.template_key == template_key)
        seqs = list((await session.execute(seq_query)).scalars().all())
        for seq in seqs:
            item = (await session.execute(
                select(LeadGenBatchItemRow)
                .where(LeadGenBatchItemRow.sequence_id == seq.id)
                .order_by(desc(LeadGenBatchItemRow.updated_at))
            )).scalars().first()
            if item:
                return item, seq, contact

        item_query = (
            select(LeadGenBatchItemRow)
            .where(LeadGenBatchItemRow.contact_id == contact.id)
            .order_by(desc(LeadGenBatchItemRow.updated_at))
        )
        if template_key:
            item_query = item_query.where(LeadGenBatchItemRow.template_key == template_key)
        item = (await session.execute(item_query)).scalars().first()
        if item:
            seq = None
            if item.sequence_id:
                seq = await session.get(EmailSequenceRow, item.sequence_id)
            return item, seq, contact

    return None, None, contacts[0] if contacts else None


async def ingest_resend_webhook(
    payload: dict[str, Any],
    *,
    provider_event_id: str | None = None,
) -> dict[str, Any]:
    event_type = str(payload.get("type") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    classification = classify_resend_event(event_type)
    email_id = str(data.get("email_id") or data.get("id") or "").strip()
    recipient_email = _first_recipient(data)
    status = classification.log_status[:16]
    error = _provider_error(event_type, data)

    async with AsyncSessionLocal() as session:
        logs: list[EmailLogRow] = []
        if email_id:
            logs = list((
                await session.execute(
                    select(EmailLogRow).where(EmailLogRow.message_id == email_id)
                )
            ).scalars().all())
        if not logs and recipient_email:
            subject = str(data.get("subject") or "")
            fallback_query = select(EmailLogRow).where(
                func.lower(EmailLogRow.recipient_email) == recipient_email,
            )
            if subject:
                fallback_query = fallback_query.where(EmailLogRow.subject == subject)
            logs = list((
                await session.execute(
                    fallback_query.order_by(desc(EmailLogRow.sent_at)).limit(3)
                )
            ).scalars().all())

        for log in logs:
            log.status = status
            if error:
                log.error = error

        item = None
        seq = None
        contact = None
        if logs:
            item, seq, contact = await _find_lead_item(
                session,
                log=logs[0],
                recipient_email=recipient_email,
            )

        observation_created = False
        if item and classification.observation_type:
            raw_event = {
                "provider": "resend",
                "provider_event_id": provider_event_id,
                "event_type": event_type,
                "email_id": email_id,
                "payload": payload,
            }
            existing = list((
                await session.execute(
                    select(LeadGenObservationRow).where(
                        LeadGenObservationRow.batch_item_id == item.id,
                        LeadGenObservationRow.event_type == classification.observation_type,
                    )
                )
            ).scalars().all())
            duplicate = any(
                (obs.raw_event_json or {}).get("provider_event_id") == provider_event_id
                or (obs.raw_event_json or {}).get("email_id") == email_id
                for obs in existing
            )
            if not duplicate:
                session.add(LeadGenObservationRow(
                    id=uuid.uuid4().hex,
                    batch_id=item.batch_id,
                    batch_item_id=item.id,
                    contact_id=item.contact_id,
                    pif_id=item.pif_id,
                    event_type=classification.observation_type,
                    raw_event_json=raw_event,
                    classified_outcome=classification.outcome,
                    confidence=classification.confidence,
                    next_action=classification.next_action,
                    llm_reasoning=(
                        f"Deterministic classification from Resend {event_type} webhook."
                    ),
                    llm_model="resend-webhook",
                ))
                observation_created = True
            if classification.update_batch_item:
                item.outcome = classification.outcome
                item.outcome_confidence = classification.confidence

        sequence_paused = False
        if classification.pause_sequence and seq and seq.status not in ("paused", "completed"):
            seq.status = "paused"
            seq.paused_reason = (
                f"resend_{event_type}:{provider_event_id or email_id or 'unknown'}"
            )[:500]
            sequence_paused = True

        await session.commit()

    return {
        "status": "ok",
        "event_type": event_type,
        "email_id": email_id or None,
        "logs_matched": len(logs),
        "log_status": status,
        "lead_gen_item_id": item.id if item else None,
        "sequence_id": seq.id if seq else None,
        "sequence_paused": sequence_paused,
        "observation_created": observation_created,
        "contact_id": contact.id if contact else None,
    }
