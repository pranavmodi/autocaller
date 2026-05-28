from app.db.models import InboundEmailRow
from app.services import operator_notifications
from app.services.operator_notifications import _reply_subject, _send_thread_reply, _thread_references


def test_reply_subject_preserves_existing_re_prefix():
    assert _reply_subject("Quick question") == "Re: Quick question"
    assert _reply_subject("Re: Quick question") == "Re: Quick question"


def test_thread_references_deduplicates_inbound_headers():
    inbound = InboundEmailRow(
        id="in_1",
        provider="zoho_imap",
        account_email="pranav@example.com",
        mailbox="INBOX",
        uid="42",
        from_email="lead@example.com",
        subject="Re: Quick question",
        references_text="<orig@example.com> <middle@example.com>",
        in_reply_to="<middle@example.com>",
        message_id="<reply@example.com>",
    )

    assert _thread_references(inbound) == (
        "<orig@example.com> <middle@example.com> <reply@example.com>"
    )


def test_send_thread_reply_defaults_to_resend_when_configured(monkeypatch):
    inbound = InboundEmailRow(
        id="in_2",
        provider="zoho_imap",
        account_email="pranav@example.com",
        mailbox="INBOX",
        uid="43",
        from_email="lead@example.com",
        subject="Re: Quick question",
        message_id="<reply@example.com>",
    )
    notification = type("Notification", (), {"id": 7})()

    monkeypatch.delenv("THREAD_REPLY_TRANSPORT", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setattr(
        operator_notifications,
        "_send_thread_reply_resend_sync",
        lambda **kwargs: "resend-id",
    )

    message_id, transport = _send_thread_reply(
        inbound=inbound,
        notification=notification,
        subject="Quick question",
        body="Thanks",
    )

    assert message_id == "resend-id"
    assert transport == "resend_thread"
