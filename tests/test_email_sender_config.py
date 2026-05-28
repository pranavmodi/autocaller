import pytest

from app.services.email_notification_service import _resolve_sender_address


def test_resolve_sender_address_uses_default_precedence(monkeypatch):
    monkeypatch.setenv("SMTP_FROM_EMAIL", "Possible Minds <consult@getpossibleminds.com>")
    monkeypatch.setenv("SMTP_USERNAME", "pranav@possiblemindshq.com")
    monkeypatch.setenv("RESEND_FALLBACK_FROM", "fallback@example.com")
    monkeypatch.delenv("EMAIL_ALLOWED_FROM_ADDRESSES", raising=False)

    assert _resolve_sender_address() == "Possible Minds <consult@getpossibleminds.com>"


def test_resolve_sender_address_allows_configured_email_with_new_display_name(monkeypatch):
    monkeypatch.setenv("SMTP_FROM_EMAIL", "Possible Minds <consult@getpossibleminds.com>")
    monkeypatch.setenv("SMTP_USERNAME", "pranav@possiblemindshq.com")
    monkeypatch.delenv("RESEND_FALLBACK_FROM", raising=False)
    monkeypatch.delenv("EMAIL_ALLOWED_FROM_ADDRESSES", raising=False)

    assert (
        _resolve_sender_address("Pranav Modi <pranav@possiblemindshq.com>")
        == "Pranav Modi <pranav@possiblemindshq.com>"
    )


def test_resolve_sender_address_allows_explicit_whitelist(monkeypatch):
    monkeypatch.setenv("SMTP_FROM_EMAIL", "Possible Minds <consult@getpossibleminds.com>")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("RESEND_FALLBACK_FROM", raising=False)
    monkeypatch.setenv("EMAIL_ALLOWED_FROM_ADDRESSES", "ops@example.com, reply@example.com")

    assert _resolve_sender_address("Ops <ops@example.com>") == "Ops <ops@example.com>"


def test_resolve_sender_address_allows_call_site_extra_sender(monkeypatch):
    monkeypatch.setenv("SMTP_FROM_EMAIL", "Possible Minds <consult@getpossibleminds.com>")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("RESEND_FALLBACK_FROM", raising=False)
    monkeypatch.delenv("EMAIL_ALLOWED_FROM_ADDRESSES", raising=False)

    assert (
        _resolve_sender_address(
            "Lead Replies <lead-replies@example.com>",
            extra_allowed=["lead-replies@example.com"],
        )
        == "Lead Replies <lead-replies@example.com>"
    )


def test_resolve_sender_address_rejects_unconfigured_override(monkeypatch):
    monkeypatch.setenv("SMTP_FROM_EMAIL", "Possible Minds <consult@getpossibleminds.com>")
    monkeypatch.setenv("SMTP_USERNAME", "pranav@possiblemindshq.com")
    monkeypatch.delenv("RESEND_FALLBACK_FROM", raising=False)
    monkeypatch.delenv("EMAIL_ALLOWED_FROM_ADDRESSES", raising=False)

    with pytest.raises(RuntimeError, match="not allowed"):
        _resolve_sender_address("Other <other@example.com>")
