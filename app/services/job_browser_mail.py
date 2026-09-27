"""Bounded, read-only Zoho inbox search for website applications."""
from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.inbound_email import fetch_zoho_messages, inbound_email_config


class MailboxSearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=4, max_length=200)
    since_hours: int = Field(default=48, ge=1, le=168)
    limit: int = Field(default=5, ge=1, le=5)

    @field_validator('query')
    @classmethod
    def specific_query(cls, value: str) -> str:
        query = ' '.join(value.split())
        terms = query.casefold().split()
        if not terms or not any(len(term.strip('.,:;()[]{}')) >= 4 for term in terms):
            raise ValueError('Use at least one specific search term with four or more characters.')
        return query


def _normalized(value: str) -> str:
    return ' '.join((value or '').split()).casefold()


def _matches(query: str, *, sender: str, subject: str, body: str) -> bool:
    """Mechanical text lookup only; relevance is decided by the action audit."""
    haystack = _normalized('\n'.join((sender, subject, body)))
    terms = [term for term in _normalized(query).split() if term]
    return bool(terms) and all(term in haystack for term in terms)


def application_mailboxes() -> list[str]:
    """Return the bounded inbox-like folders allowed for application mail."""
    primary = inbound_email_config().mailbox
    configured = os.getenv('ZOHO_JOB_APPLICATION_MAILBOXES', '').strip()
    requested = [item.strip() for item in configured.split(',') if item.strip()]
    folders = requested or [primary, 'Notification']
    blocked = {'sent', 'drafts', 'templates', 'trash', 'archive'}
    return list(dict.fromkeys(folder for folder in folders if folder.casefold() not in blocked))[:4]


async def search_zoho_inbox(request: MailboxSearchRequest) -> dict:
    """Search recent inbox-like messages without changing mailbox state."""
    since_days = max(1, math.ceil(request.since_hours / 24))
    mailboxes = application_mailboxes()
    batches = await asyncio.wait_for(asyncio.gather(*(
        fetch_zoho_messages(limit=100, unseen_only=False, since_days=since_days,
                            mark_seen=False, mailbox=mailbox)
        for mailbox in mailboxes
    )), timeout=50)
    messages = [message for batch in batches for message in batch]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=request.since_hours)
    matched = []
    for message in messages:
        if message.received_at is None or message.received_at < cutoff:
            continue
        sender = ' '.join(part for part in (message.from_name or '', message.from_email) if part)
        if not _matches(request.query, sender=sender, subject=message.subject, body=message.body_text):
            continue
        matched.append({
            'mailbox': message.mailbox,
            'from_name': message.from_name,
            'from_email': message.from_email,
            'subject': message.subject,
            'received_at': message.received_at.isoformat(),
            'excerpt': message.body_text[:3000],
        })
    matched.sort(key=lambda item: item['received_at'], reverse=True)
    items = matched[:request.limit]
    return {
        'query': request.query,
        'mailbox': inbound_email_config().mailbox,
        'mailboxes': mailboxes,
        'read_only': True,
        'since_hours': request.since_hours,
        'matched': len(items),
        'items': items,
    }
