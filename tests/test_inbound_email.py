from datetime import timezone

from app.services.inbound_email import (
    _draft_reply_body,
    _imap_search_criteria,
    _reply_subject,
    parse_inbound_message,
)


def test_parse_inbound_message_extracts_text_headers_and_addresses():
    raw = (
        b"Message-ID: <reply-1@example.com>\r\n"
        b"In-Reply-To: <orig@example.com>\r\n"
        b"References: <orig@example.com>\r\n"
        b"Date: Wed, 27 May 2026 10:15:00 -0700\r\n"
        b"From: James Doyle <contact@doyleattorneys.com>\r\n"
        b"To: Possible Minds <consult@getpossibleminds.com>\r\n"
        b"Cc: Ops <ops@example.com>\r\n"
        b"Subject: Re: Precise Imaging -- quick records question\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Pranav,\r\n\r\nThis is interesting. Can you send a few times?\r\n"
    )

    parsed = parse_inbound_message(
        raw_message=raw,
        account_email="consult@getpossibleminds.com",
        mailbox="INBOX",
        uid="42",
    )

    assert parsed.uid == "42"
    assert parsed.message_id == "<reply-1@example.com>"
    assert parsed.in_reply_to == "<orig@example.com>"
    assert parsed.from_email == "contact@doyleattorneys.com"
    assert parsed.from_name == "James Doyle"
    assert parsed.to == [{"name": "Possible Minds", "email": "consult@getpossibleminds.com"}]
    assert parsed.cc == [{"name": "Ops", "email": "ops@example.com"}]
    assert parsed.subject == "Re: Precise Imaging -- quick records question"
    assert "send a few times" in parsed.body_text
    assert parsed.received_at is not None
    assert parsed.received_at.tzinfo == timezone.utc
    assert parsed.received_at.isoformat() == "2026-05-27T17:15:00+00:00"


def test_parse_inbound_message_falls_back_to_html_body():
    raw = (
        b"Date: Wed, 27 May 2026 10:15:00 -0700\r\n"
        b"From: Contact <contact@example.com>\r\n"
        b"To: consult@getpossibleminds.com\r\n"
        b"Subject: HTML only\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>Hello<br>there</p><script>ignore()</script></body></html>"
    )

    parsed = parse_inbound_message(
        raw_message=raw,
        account_email="consult@getpossibleminds.com",
        mailbox="INBOX",
        uid="43",
    )

    assert "Hello" in parsed.body_text
    assert "there" in parsed.body_text
    assert "ignore" not in parsed.body_text


def test_imap_search_criteria_defaults_to_unseen_recent():
    assert _imap_search_criteria(unseen_only=True, since_days=None) == "UNSEEN"
    assert _imap_search_criteria(unseen_only=False, since_days=None) == "ALL"
    assert 'SINCE "' in _imap_search_criteria(unseen_only=True, since_days=14)


def test_reply_notification_helpers_prepare_human_action_copy():
    assert _reply_subject("Precise Imaging -- quick records question") == (
        "Re: Precise Imaging -- quick records question"
    )
    assert _reply_subject("Re: Precise Imaging -- quick records question") == (
        "Re: Precise Imaging -- quick records question"
    )

    draft = _draft_reply_body(contact_name="Nayeli Pacheco", firm_name="Aghabi Law")

    assert draft.startswith("Hi Nayeli,")
    assert "Aghabi Law" in draft
    assert "highest-return one for your actual workflow" in draft
    assert "What part of the process are you trying to improve most right now" in draft
    assert "Precise Imaging" not in draft
    assert "20 minutes" not in draft
