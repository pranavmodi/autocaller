"""Inbound email ingestion via Zoho IMAP.

This is the mailbox sensor for lead generation. It reads messages from Zoho,
stores normalized inbound rows, matches replies to firm contacts / lead-gen
batch items, and creates feedback observations.
"""
from __future__ import annotations

import asyncio
import html
import imaplib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any

from sqlalchemy import desc, func, select

from app.db import AsyncSessionLocal
from app.db.models import (
    EmailSequenceRow,
    FirmContactRow,
    InboundEmailRow,
    LeadGenBatchItemRow,
)
from app.services.lead_gen_cybernetic import record_observation
from app.services.lead_feedback_classifier import FeedbackClassification, classify_feedback_event
from app.services.operator_notifications import create_operator_notification


PROVIDER = "zoho_imap"


@dataclass(frozen=True)
class InboundEmailConfig:
    host: str
    port: int
    user: str
    password: str
    mailbox: str
    mark_seen: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)


@dataclass(frozen=True)
class ParsedInboundEmail:
    account_email: str
    mailbox: str
    uid: str
    message_id: str | None
    in_reply_to: str | None
    references_text: str | None
    from_email: str
    from_name: str | None
    to: list[dict[str, str]]
    cc: list[dict[str, str]]
    subject: str
    body_text: str
    text_excerpt: str
    raw_headers: dict[str, str]
    received_at: datetime | None


def inbound_email_config() -> InboundEmailConfig:
    return InboundEmailConfig(
        host=os.getenv("ZOHO_IMAP_HOST", "imap.zoho.com").strip(),
        port=int(os.getenv("ZOHO_IMAP_PORT", "993") or "993"),
        user=os.getenv("ZOHO_IMAP_USER", "").strip(),
        password=os.getenv("ZOHO_IMAP_PASSWORD", "").strip(),
        mailbox=os.getenv("ZOHO_IMAP_MAILBOX", "INBOX").strip() or "INBOX",
        mark_seen=os.getenv("ZOHO_IMAP_MARK_SEEN", "").lower() in {"1", "true", "yes"},
    )


def masked_inbound_config() -> dict[str, Any]:
    cfg = inbound_email_config()
    return {
        "provider": PROVIDER,
        "configured": cfg.configured,
        "host": cfg.host,
        "port": cfg.port,
        "user": _mask_email(cfg.user),
        "mailbox": cfg.mailbox,
        "mark_seen_default": cfg.mark_seen,
    }


def _mask_email(value: str) -> str:
    if not value or "@" not in value:
        return "configured" if value else ""
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        return f"{local[0:1]}***@{domain}"
    return f"{local[:2]}***@{domain}"


def _decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return str(value).strip()


def _addr_list(value: str | None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name, email_addr in getaddresses([value or ""]):
        email_addr = (email_addr or "").strip().lower()
        if not email_addr:
            continue
        out.append({"name": _decode_mime(name), "email": email_addr})
    return out


def _received_at(msg: Message) -> datetime | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return html.unescape(text)


def _body_text(msg: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain_parts.append(_part_text(part))
            elif content_type == "text/html":
                html_parts.append(_html_to_text(_part_text(part)))
    else:
        content_type = msg.get_content_type()
        if content_type == "text/html":
            html_parts.append(_html_to_text(_part_text(msg)))
        else:
            plain_parts.append(_part_text(msg))
    text = "\n".join(p for p in plain_parts if p.strip())
    if not text.strip():
        text = "\n".join(p for p in html_parts if p.strip())
    return _normalize_body(text)


def _normalize_body(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


def parse_inbound_message(
    *,
    raw_message: bytes,
    account_email: str,
    mailbox: str,
    uid: str,
) -> ParsedInboundEmail:
    msg = BytesParser(policy=policy.default).parsebytes(raw_message)
    from_addr = _addr_list(msg.get("From"))
    body = _body_text(msg)
    headers = {
        k: _decode_mime(v)
        for k, v in msg.items()
        if k.lower()
        in {
            "message-id",
            "in-reply-to",
            "references",
            "from",
            "to",
            "cc",
            "date",
            "subject",
            "reply-to",
        }
    }
    return ParsedInboundEmail(
        account_email=account_email.strip().lower(),
        mailbox=mailbox,
        uid=str(uid),
        message_id=(msg.get("Message-ID") or "").strip() or None,
        in_reply_to=(msg.get("In-Reply-To") or "").strip() or None,
        references_text=(msg.get("References") or "").strip() or None,
        from_email=from_addr[0]["email"] if from_addr else "",
        from_name=from_addr[0].get("name") if from_addr else None,
        to=_addr_list(msg.get("To")),
        cc=_addr_list(msg.get("Cc")),
        subject=_decode_mime(msg.get("Subject")),
        body_text=body,
        text_excerpt=body[:500],
        raw_headers=headers,
        received_at=_received_at(msg),
    )


def _imap_search_criteria(*, unseen_only: bool, since_days: int | None) -> str:
    terms = ["UNSEEN" if unseen_only else "ALL"]
    if since_days and since_days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        terms.append(f'SINCE "{since.strftime("%d-%b-%Y")}"')
    return " ".join(terms)


def _sent_mailbox() -> str:
    return os.getenv("ZOHO_IMAP_SENT_MAILBOX", "Sent").strip() or "Sent"


def _sent_search_criteria(*, recipient_email: str, since_days: int | None) -> str:
    terms = [f'TO "{recipient_email.strip().lower()}"']
    if since_days and since_days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        terms.append(f'SINCE "{since.strftime("%d-%b-%Y")}"')
    return " ".join(terms)


def _fetch_from_zoho_sync(
    *,
    cfg: InboundEmailConfig,
    limit: int,
    unseen_only: bool,
    since_days: int | None,
    mark_seen: bool,
) -> list[tuple[str, bytes]]:
    if not cfg.configured:
        raise RuntimeError("ZOHO_IMAP_USER and ZOHO_IMAP_PASSWORD must be configured")
    imap = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    try:
        imap.login(cfg.user, cfg.password)
        typ, _ = imap.select(cfg.mailbox)
        if typ != "OK":
            raise RuntimeError(f"unable to select mailbox {cfg.mailbox!r}")
        typ, data = imap.uid("SEARCH", None, _imap_search_criteria(
            unseen_only=unseen_only,
            since_days=since_days,
        ))
        if typ != "OK":
            raise RuntimeError("imap search failed")
        uids = (data[0] or b"").split()
        selected = list(reversed(uids))[: max(1, limit)]
        out: list[tuple[str, bytes]] = []
        for uid_b in reversed(selected):
            uid = uid_b.decode("ascii", errors="replace")
            fetch_mode = "(RFC822)" if mark_seen else "(BODY.PEEK[])"
            typ, fetched = imap.uid("FETCH", uid, fetch_mode)
            if typ != "OK":
                continue
            raw = b""
            for part in fetched:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
                    raw = part[1]
                    break
            if raw:
                out.append((uid, raw))
        return out
    finally:
        try:
            imap.close()
        except Exception:
            pass
        try:
            imap.logout()
        except Exception:
            pass


async def fetch_zoho_messages(
    *,
    limit: int = 20,
    unseen_only: bool = True,
    since_days: int | None = 14,
    mark_seen: bool | None = None,
) -> list[ParsedInboundEmail]:
    cfg = inbound_email_config()
    raw_rows = await asyncio.to_thread(
        _fetch_from_zoho_sync,
        cfg=cfg,
        limit=max(1, min(limit, 200)),
        unseen_only=unseen_only,
        since_days=since_days,
        mark_seen=cfg.mark_seen if mark_seen is None else mark_seen,
    )
    return [
        parse_inbound_message(
            raw_message=raw,
            account_email=cfg.user,
            mailbox=cfg.mailbox,
            uid=uid,
        )
        for uid, raw in raw_rows
    ]


def _fetch_sent_for_recipient_sync(
    *,
    cfg: InboundEmailConfig,
    recipient_email: str,
    mailbox: str,
    limit: int,
    since_days: int | None,
) -> list[tuple[str, bytes]]:
    if not cfg.configured:
        raise RuntimeError("ZOHO_IMAP_USER and ZOHO_IMAP_PASSWORD must be configured")
    imap = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    try:
        imap.login(cfg.user, cfg.password)
        typ, _ = imap.select(mailbox, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"unable to select mailbox {mailbox!r}")
        typ, data = imap.uid("SEARCH", None, _sent_search_criteria(
            recipient_email=recipient_email,
            since_days=since_days,
        ))
        if typ != "OK":
            raise RuntimeError("imap sent search failed")
        uids = (data[0] or b"").split()
        selected = list(reversed(uids))[: max(1, limit)]
        out: list[tuple[str, bytes]] = []
        for uid_b in reversed(selected):
            uid = uid_b.decode("ascii", errors="replace")
            typ, fetched = imap.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = b""
            for part in fetched:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes):
                    raw = part[1]
                    break
            if raw:
                out.append((uid, raw))
        return out
    finally:
        try:
            imap.close()
        except Exception:
            pass
        try:
            imap.logout()
        except Exception:
            pass


async def fetch_zoho_sent_messages_for_recipient(
    recipient_email: str,
    *,
    limit: int = 5,
    since_days: int | None = 365,
    mailbox: str | None = None,
) -> list[ParsedInboundEmail]:
    cfg = inbound_email_config()
    sent_mailbox = mailbox or _sent_mailbox()
    raw_rows = await asyncio.to_thread(
        _fetch_sent_for_recipient_sync,
        cfg=cfg,
        recipient_email=recipient_email,
        mailbox=sent_mailbox,
        limit=max(1, min(limit, 50)),
        since_days=since_days,
    )
    return [
        parse_inbound_message(
            raw_message=raw,
            account_email=cfg.user,
            mailbox=sent_mailbox,
            uid=uid,
        )
        for uid, raw in raw_rows
    ]


async def ingest_zoho_inbox(
    *,
    limit: int = 20,
    unseen_only: bool = True,
    since_days: int | None = 14,
    classify: bool = False,
    mark_seen: bool | None = None,
) -> dict[str, Any]:
    parsed_messages = await fetch_zoho_messages(
        limit=limit,
        unseen_only=unseen_only,
        since_days=since_days,
        mark_seen=mark_seen,
    )
    saved = []
    skipped_existing = 0
    matched = 0
    observations = 0
    for parsed in parsed_messages:
        result = await store_inbound_email(parsed, classify=classify)
        saved.append(result)
        skipped_existing += 1 if result.get("existing") else 0
        matched += 1 if result.get("matched_contact_id") else 0
        observations += 1 if result.get("lead_gen_observation_id") else 0
    return {
        "status": "ok",
        "provider": PROVIDER,
        "fetched": len(parsed_messages),
        "stored": len(saved) - skipped_existing,
        "existing": skipped_existing,
        "matched": matched,
        "observations": observations,
        "messages": saved,
    }


async def store_inbound_email(
    parsed: ParsedInboundEmail,
    *,
    classify: bool = False,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(InboundEmailRow).where(
                InboundEmailRow.provider == PROVIDER,
                InboundEmailRow.account_email == parsed.account_email,
                InboundEmailRow.mailbox == parsed.mailbox,
                InboundEmailRow.uid == parsed.uid,
            )
        )).scalar_one_or_none()
        if existing:
            return _inbound_row_to_dict(existing, existing=True)

        contact, item, seq = await _match_reply(session, parsed)

        def _nul_free(value):
            # Postgres rejects NUL (0x00) in UTF8 text; some NDRs carry them.
            if isinstance(value, str):
                return value.replace("\x00", "")
            if isinstance(value, list):
                return [_nul_free(v) for v in value]
            if isinstance(value, dict):
                return {k: _nul_free(v) for k, v in value.items()}
            return value

        row = InboundEmailRow(
            id=uuid.uuid4().hex,
            provider=PROVIDER,
            account_email=parsed.account_email,
            mailbox=parsed.mailbox,
            uid=parsed.uid,
            message_id=_nul_free(parsed.message_id),
            in_reply_to=_nul_free(parsed.in_reply_to),
            references_text=_nul_free(parsed.references_text),
            from_email=_nul_free(parsed.from_email),
            from_name=_nul_free(parsed.from_name),
            to_json=_nul_free(parsed.to),
            cc_json=_nul_free(parsed.cc),
            subject=_nul_free(parsed.subject),
            text_excerpt=_nul_free(parsed.text_excerpt),
            body_text=_nul_free(parsed.body_text),
            raw_headers_json=_nul_free(parsed.raw_headers),
            matched_contact_id=contact.id if contact else None,
            matched_pif_id=(item.pif_id if item else (contact.pif_id if contact else None)),
            matched_batch_item_id=item.id if item else None,
            matched_sequence_id=seq.id if seq else None,
            classification_status="matched" if item else "unmatched",
            received_at=parsed.received_at,
        )
        session.add(row)
        await session.flush()

        obs = None
        if item:
            classification = await _classify_reply(parsed, contact, item, classify=True)
            obs = await record_observation(
                "email_reply_received",
                {
                    "dedupe_key": f"inbound_email:{row.id}",
                    "provider": PROVIDER,
                    "inbound_email_id": row.id,
                    "account_email": parsed.account_email,
                    "mailbox": parsed.mailbox,
                    "uid": parsed.uid,
                    "message_id": parsed.message_id,
                    "in_reply_to": parsed.in_reply_to,
                    "references": parsed.references_text,
                    "from_email": parsed.from_email,
                    "from_name": parsed.from_name,
                    "subject": parsed.subject,
                    "body_text": parsed.body_text,
                    "received_at": parsed.received_at.isoformat() if parsed.received_at else None,
                },
                batch_id=item.batch_id,
                batch_item_id=item.id,
                contact_id=item.contact_id,
                classification=classification,
            )
            row.lead_gen_observation_id = obs["id"]
            row.classification_status = "classified"
            item.outcome = classification.outcome
            item.outcome_confidence = classification.confidence
            if seq and seq.status == "active":
                seq.status = "paused"
                seq.paused_reason = f"zoho_email_reply:{row.id}"
            await _create_lead_reply_notification(
                session=session,
                row=row,
                parsed=parsed,
                contact=contact,
                item=item,
                seq=seq,
                obs_id=obs["id"],
                classification=classification,
            )

        await session.commit()
        await session.refresh(row)
        return _inbound_row_to_dict(row, existing=False)


async def _create_lead_reply_notification(
    *,
    session,
    row: InboundEmailRow,
    parsed: ParsedInboundEmail,
    contact: FirmContactRow,
    item: LeadGenBatchItemRow,
    seq: EmailSequenceRow | None,
    obs_id: str,
    classification: FeedbackClassification,
) -> None:
    firm_name = item.firm_name or "lead"
    contact_name = item.contact_name or contact.full_name or item.contact_email
    outcome_label = (classification.outcome or "email_reply").replace("_", " ")
    title = f"{outcome_label.title()} from {firm_name}"
    if classification.outcome in {"positive_reply", "booked_qualified_conversation", "referral"}:
        priority = "high"
    elif classification.outcome in {"do_not_contact", "bounce"}:
        priority = "high"
    else:
        priority = "normal"

    suggested_action = {
        "kind": classification.next_action or "human_reply",
        "label": _action_label(classification.next_action),
        "outcome": classification.outcome,
        "confidence": classification.confidence,
        "reasoning": classification.reasoning,
        "signals": classification.signals,
        "requires_human_review": classification.requires_human_review,
        "draft_subject": _reply_subject(parsed.subject),
        "draft_body": _draft_reply_body(contact_name=contact_name, firm_name=firm_name),
        "href": "/lead-gen",
    }
    await create_operator_notification(
        session,
        notification_type="lead_email_reply",
        priority=priority,
        title=title,
        body=parsed.text_excerpt,
        source_type="inbound_email",
        source_id=row.id,
        stimulus={
            "provider": PROVIDER,
            "inbound_email_id": row.id,
            "from_email": parsed.from_email,
            "from_name": parsed.from_name,
            "subject": parsed.subject,
            "text_excerpt": parsed.text_excerpt,
            "body_text": parsed.body_text,
            "received_at": parsed.received_at.isoformat() if parsed.received_at else None,
        },
        context={
            "firm_name": firm_name,
            "contact_name": contact_name,
            "contact_email": item.contact_email or contact.email,
            "contact_title": item.contact_title or contact.title,
            "pif_id": item.pif_id,
            "batch_id": item.batch_id,
            "batch_item_id": item.id,
            "sequence_id": item.sequence_id,
            "sequence_status": seq.status if seq else None,
            "sequence_paused_reason": seq.paused_reason if seq else None,
            "lead_gen_observation_id": obs_id,
        },
        suggested_action=suggested_action,
    )


def _reply_subject(subject: str) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject or 'quick records question'}"


def _draft_reply_body(*, contact_name: str, firm_name: str) -> str:
    first_name = (contact_name or "").strip().split(" ", 1)[0] or "there"
    return (
        f"Hi {first_name},\n\n"
        "Thanks for getting back to me. The short version is that we help PI firms "
        "turn messy operational follow-up loops into tracked workflows: what was "
        "requested, what is missing, who owns the next step, and what needs a staff "
        "follow-up.\n\n"
        f"For {firm_name}, we would first map where staff time is leaking today, then "
        "rank the possible automations by leverage, feasibility, and impact so the "
        "first system we build is the highest-return one for your actual workflow.\n\n"
        "What part of the process are you trying to improve most right now: records "
        "requests, status updates, missing-doc follow-up, client communication, or "
        "something else?"
    )


def _action_label(next_action: str | None) -> str:
    labels = {
        "confirm_booking": "Confirm booking",
        "human_reply": "Review suggested response",
        "ask_for_referral_contact": "Ask for referral contact",
        "find_better_contact": "Find better contact",
        "continue_sequence": "Continue sequence",
        "pause_sequence": "Pause sequence",
        "mark_do_not_contact": "Mark do not contact",
        "suppress_email": "Suppress email",
        "no_action": "No action",
        "needs_human_review": "Review manually",
    }
    return labels.get(next_action or "", "Review manually")


async def _match_reply(
    session,
    parsed: ParsedInboundEmail,
) -> tuple[FirmContactRow | None, LeadGenBatchItemRow | None, EmailSequenceRow | None]:
    sender = parsed.from_email.strip().lower()
    if not sender:
        return None, None, None
    contacts = list((await session.execute(
        select(FirmContactRow)
        .where(func.lower(FirmContactRow.email) == sender)
        .order_by(desc(FirmContactRow.updated_at))
    )).scalars().all())
    for contact in contacts:
        item = (await session.execute(
            select(LeadGenBatchItemRow)
            .where(LeadGenBatchItemRow.contact_id == contact.id)
            .order_by(desc(LeadGenBatchItemRow.updated_at))
        )).scalars().first()
        if item:
            seq = await session.get(EmailSequenceRow, item.sequence_id) if item.sequence_id else None
            return contact, item, seq
    return (contacts[0], None, None) if contacts else (None, None, None)


async def _classify_reply(
    parsed: ParsedInboundEmail,
    contact: FirmContactRow,
    item: LeadGenBatchItemRow,
    *,
    classify: bool,
) -> FeedbackClassification:
    if not classify:
        return FeedbackClassification(
            outcome="needs_human_review",
            confidence=50,
            next_action="human_reply",
            reasoning="Zoho inbound reply matched to a lead-gen contact; LLM classification was not requested.",
            signals=["zoho_inbound_reply"],
            requires_human_review=True,
            model="manual",
        )
    try:
        return await classify_feedback_event(
            event_type="email_reply",
            raw_event={
                "subject": parsed.subject,
                "body_text": parsed.body_text,
                "from_email": parsed.from_email,
                "received_at": parsed.received_at.isoformat() if parsed.received_at else None,
            },
            contact={
                "id": contact.id,
                "name": contact.full_name,
                "email": contact.email,
                "title": contact.title,
                "source": contact.source,
            },
            firm={"pif_id": item.pif_id, "firm_name": item.firm_name},
            sequence={
                "batch_id": item.batch_id,
                "batch_item_id": item.id,
                "template_key": item.template_key,
            },
            target_metric="booked_qualified_conversations",
        )
    except Exception as e:
        return FeedbackClassification(
            outcome="needs_human_review",
            confidence=40,
            next_action="human_reply",
            reasoning=f"Zoho reply matched, but LLM classification failed: {type(e).__name__}: {str(e)[:200]}",
            signals=["zoho_inbound_reply", "classification_failed"],
            requires_human_review=True,
            model="manual-fallback",
        )


def _inbound_row_to_dict(row: InboundEmailRow, *, existing: bool = False) -> dict[str, Any]:
    return {
        "id": row.id,
        "existing": existing,
        "provider": row.provider,
        "account_email": row.account_email,
        "mailbox": row.mailbox,
        "uid": row.uid,
        "message_id": row.message_id,
        "from_email": row.from_email,
        "from_name": row.from_name,
        "subject": row.subject,
        "text_excerpt": row.text_excerpt,
        "matched_contact_id": row.matched_contact_id,
        "matched_pif_id": row.matched_pif_id,
        "matched_batch_item_id": row.matched_batch_item_id,
        "matched_sequence_id": row.matched_sequence_id,
        "lead_gen_observation_id": row.lead_gen_observation_id,
        "classification_status": row.classification_status,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "ingested_at": row.ingested_at.isoformat() if row.ingested_at else None,
    }


async def list_inbound_emails(limit: int = 50, matched: bool | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    async with AsyncSessionLocal() as session:
        q = select(InboundEmailRow).order_by(desc(InboundEmailRow.received_at), desc(InboundEmailRow.ingested_at)).limit(limit)
        if matched is True:
            q = q.where(InboundEmailRow.matched_contact_id.isnot(None))
        elif matched is False:
            q = q.where(InboundEmailRow.matched_contact_id.is_(None))
        rows = (await session.execute(q)).scalars().all()
    return [_inbound_row_to_dict(row) for row in rows]
