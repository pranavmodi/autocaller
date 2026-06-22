import pytest

from app.services.lead_gen_transport import (
    RESEND,
    ZOHO_API,
    choose_lead_gen_transport_from_counts,
    lead_gen_transport_snapshot_from_counts,
    provider_daily_caps_from_weights,
)


def test_provider_caps_default_zoho_to_20_and_resend_to_remaining_budget():
    caps = provider_daily_caps_from_weights({"daily_send_budget": 50})

    assert caps == {ZOHO_API: 20, RESEND: 30}


def test_provider_caps_allow_resend_override():
    caps = provider_daily_caps_from_weights({
        "daily_send_budget": 80,
        "provider_daily_caps": {ZOHO_API: 20, RESEND: 100},
    })

    assert caps == {ZOHO_API: 20, RESEND: 100}


def test_choose_transport_prefers_zoho_until_daily_cap():
    weights = {"daily_send_budget": 50}

    assert choose_lead_gen_transport_from_counts(
        weights,
        counts={ZOHO_API: 19, RESEND: 0},
        configured={ZOHO_API, RESEND},
    ) == ZOHO_API

    assert choose_lead_gen_transport_from_counts(
        weights,
        counts={ZOHO_API: 20, RESEND: 0},
        configured={ZOHO_API, RESEND},
    ) == RESEND


def test_choose_transport_respects_missing_resend_config():
    with pytest.raises(RuntimeError, match="lead_gen_email_transport_unavailable"):
        choose_lead_gen_transport_from_counts(
            {"daily_send_budget": 50},
            counts={ZOHO_API: 20, RESEND: 0},
            configured={ZOHO_API},
        )


def test_transport_snapshot_reports_remaining_capacity():
    snapshot = lead_gen_transport_snapshot_from_counts(
        {"daily_send_budget": 50},
        counts={ZOHO_API: 12, RESEND: 5},
        configured={ZOHO_API, RESEND},
    )

    providers = {provider["transport"]: provider for provider in snapshot["providers"]}
    assert providers[ZOHO_API]["remaining"] == 8
    assert providers[RESEND]["remaining"] == 25
    assert snapshot["available"] is True
