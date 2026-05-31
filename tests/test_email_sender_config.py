import pytest

from app.services.email_notification_service import (
    _choose_email_transport,
    _resolve_sender_address,
    _zoho_account_id,
)


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


def test_choose_email_transport_prefers_smtp_when_zoho_is_configured(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtppro.zoho.in")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.delenv("EMAIL_TRANSPORT", raising=False)
    monkeypatch.delenv("ZOHO_MAIL_REFRESH_TOKEN", raising=False)

    assert _choose_email_transport() == "smtp"


def test_choose_email_transport_allows_explicit_resend(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtppro.zoho.in")
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_TRANSPORT", "resend")

    assert _choose_email_transport() == "resend"


def test_choose_email_transport_prefers_zoho_api_when_refresh_token_exists(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtppro.zoho.in")
    monkeypatch.setenv("ZOHO_MAIL_REFRESH_TOKEN", "refresh-token")
    monkeypatch.delenv("EMAIL_TRANSPORT", raising=False)

    assert _choose_email_transport() == "zoho_api"


def test_choose_email_transport_allows_explicit_zoho_api(monkeypatch):
    monkeypatch.setenv("EMAIL_TRANSPORT", "zoho_api")

    assert _choose_email_transport() == "zoho_api"


def test_zoho_account_id_uses_configured_value(monkeypatch):
    monkeypatch.setenv("ZOHO_MAIL_ACCOUNT_ID", "12345")

    assert _zoho_account_id() == "12345"
