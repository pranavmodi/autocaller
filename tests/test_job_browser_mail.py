from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.services.inbound_email import ParsedInboundEmail
from app.services import job_browser_mail as mailbox


def message(*, sender='verify@ats.example', subject='Fixture verification code',
            body='Your code is Ab12Cd34.', hours_ago=1, folder='INBOX'):
    return ParsedInboundEmail(
        account_email='applicant@example.com', mailbox=folder, uid='1',
        message_id='<fixture>', in_reply_to=None, references_text=None,
        from_email=sender, from_name='Fixture ATS', to=[], cc=[], subject=subject,
        body_text=body, text_excerpt=body, raw_headers={},
        received_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago))


def test_mailbox_query_must_be_specific_and_bounded():
    with pytest.raises(ValidationError):
        mailbox.MailboxSearchRequest(query='job')
    with pytest.raises(ValidationError):
        mailbox.MailboxSearchRequest(query='verification', limit=6)


@pytest.mark.asyncio
async def test_search_is_recent_bounded_and_read_only(monkeypatch):
    async def fetched(**kwargs):
        if kwargs['mailbox'] == 'Notification':
            return [message(folder='Notification')]
        return [message(subject='Unrelated newsletter', body='No application content.'),
                message(subject='Fixture verification code', hours_ago=72)]
    fetch = AsyncMock(side_effect=fetched)
    monkeypatch.setattr(mailbox, 'fetch_zoho_messages', fetch)

    result = await mailbox.search_zoho_inbox(
        mailbox.MailboxSearchRequest(query='Fixture verification', since_hours=48))

    assert result['read_only'] is True
    assert result['mailbox'] == 'INBOX'
    assert result['mailboxes'] == ['INBOX', 'Notification']
    assert result['matched'] == 1
    assert result['items'][0]['mailbox'] == 'Notification'
    assert result['items'][0]['excerpt'] == 'Your code is Ab12Cd34.'
    assert fetch.await_count == 2
    fetch.assert_any_await(limit=100, unseen_only=False, since_days=2,
                           mark_seen=False, mailbox='INBOX')
    fetch.assert_any_await(limit=100, unseen_only=False, since_days=2,
                           mark_seen=False, mailbox='Notification')


def test_application_mailbox_configuration_excludes_non_inbox_folders(monkeypatch):
    monkeypatch.setenv('ZOHO_JOB_APPLICATION_MAILBOXES',
                       'INBOX, Notification, Sent, Trash, Custom Applications')
    assert mailbox.application_mailboxes() == ['INBOX', 'Notification', 'Custom Applications']
