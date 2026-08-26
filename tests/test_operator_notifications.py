from app.db.models import InboundEmailRow
from app.services import operator_notifications
from app.services.operator_notifications import (
    _notification_is_suppressed,
    _reply_subject,
    _send_thread_reply,
    _thread_references,
)


def test_needs_human_review_reply_notifications_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPERATOR_NOTIFY_NEEDS_HUMAN_REVIEW", raising=False)

    assert _notification_is_suppressed(
        "lead_email_reply",
        {"kind": "needs_human_review"},
    ) is True
    assert _notification_is_suppressed(
        "lead_email_reply",
        {"kind": "human_reply", "outcome": "positive_reply"},
    ) is False


def test_needs_human_review_reply_notifications_can_be_reenabled(monkeypatch):
    monkeypatch.setenv("OPERATOR_NOTIFY_NEEDS_HUMAN_REVIEW", "true")

    assert _notification_is_suppressed(
        "lead_email_reply",
        {"kind": "needs_human_review"},
    ) is False


def test_yelp_review_needed_notifications_are_suppressed():
    assert _notification_is_suppressed("yelp_review_needed") is True


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
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("ZOHO_MAIL_REFRESH_TOKEN", raising=False)
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


def test_send_thread_reply_prefers_smtp_when_zoho_is_configured(monkeypatch):
    inbound = InboundEmailRow(
        id="in_3",
        provider="zoho_imap",
        account_email="pranav@example.com",
        mailbox="INBOX",
        uid="44",
        from_email="lead@example.com",
        subject="Re: Quick question",
        message_id="<reply@example.com>",
    )
    notification = type("Notification", (), {"id": 8})()

    monkeypatch.delenv("THREAD_REPLY_TRANSPORT", raising=False)
    monkeypatch.delenv("ZOHO_MAIL_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtppro.zoho.in")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setattr(
        operator_notifications,
        "_send_thread_reply_sync",
        lambda **kwargs: "smtp-id",
    )

    message_id, transport = _send_thread_reply(
        inbound=inbound,
        notification=notification,
        subject="Quick question",
        body="Thanks",
    )

    assert message_id == "smtp-id"
    assert transport == "smtp_thread"


def test_send_thread_reply_prefers_zoho_api_when_configured(monkeypatch):
    inbound = InboundEmailRow(
        id="in_4",
        provider="zoho_imap",
        account_email="pranav@example.com",
        mailbox="INBOX",
        uid="45",
        from_email="lead@example.com",
        subject="Re: Quick question",
        message_id="<reply@example.com>",
    )
    notification = type("Notification", (), {"id": 9, "context_json": {"pif_id": "p1", "contact_name": "Lead"}})()

    monkeypatch.delenv("THREAD_REPLY_TRANSPORT", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtppro.zoho.in")
    monkeypatch.setenv("ZOHO_MAIL_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setattr(
        operator_notifications,
        "_send_email",
        lambda *args, **kwargs: "zoho-id",
    )

    message_id, transport = _send_thread_reply(
        inbound=inbound,
        notification=notification,
        subject="Quick question",
        body="Thanks",
    )

    assert message_id == "zoho-id"
    assert transport == "zoho_api_thread"
