from datetime import datetime, timedelta, timezone

from app.services.front_sync import (
    compute_warm_score,
    derive_contact_fields,
    is_consumer_domain,
    is_filevine_domain,
    normalize_domain,
    parse_front_datetime,
    seniority_multiplier,
)


def test_front_contact_domain_derivation_and_consumer_skip():
    contact = {
        "id": "crd_123",
        "name": "Jane Owner",
        "handles": [{"handle": "Jane.Owner@ExampleLaw.com", "source": "email"}],
        "updated_at": "2026-06-11T12:30:00Z",
    }

    fields = derive_contact_fields(contact)

    assert fields["front_id"] == "crd_123"
    assert fields["primary_email"] == "jane.owner@examplelaw.com"
    assert fields["domain"] == "examplelaw.com"
    assert fields["front_updated_at"] == datetime(2026, 6, 11, 12, 30, tzinfo=timezone.utc)
    assert normalize_domain("https://www.examplelaw.com/path") == "examplelaw.com"
    assert is_consumer_domain("gmail.com")
    assert not is_consumer_domain("examplelaw.com")


def test_filevine_tech_signal_detection():
    assert is_filevine_domain("notifications.firm.filevineapp.com")
    assert is_filevine_domain("filevineapp.com")
    assert not is_filevine_domain("filevine.examplelaw.com")


def test_warm_score_math_prefers_recent_referrals_and_seniority():
    now = datetime(2026, 6, 11, tzinfo=timezone.utc)
    recent = compute_warm_score(
        contact_count=9,
        last_referral_at=now - timedelta(days=2),
        last_seen_at=now - timedelta(days=1),
        max_seniority=seniority_multiplier("Managing Partner"),
        tech_signals={"case_mgmt": "filevine"},
        now=now,
    )
    old = compute_warm_score(
        contact_count=9,
        last_referral_at=now - timedelta(days=120),
        last_seen_at=now - timedelta(days=120),
        max_seniority=1.0,
        tech_signals={},
        now=now,
    )

    assert recent > old
    assert recent > 200
    assert old > 0


def test_parse_front_datetime_accepts_epoch_seconds_and_millis():
    seconds = parse_front_datetime(1_780_000_000)
    millis = parse_front_datetime(1_780_000_000_000)

    assert seconds == millis
    assert seconds.tzinfo is timezone.utc
