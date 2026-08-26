from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.engagement_campaigns import (
    _approved_vendor_stack,
    _observed_time_on_page_ms,
    _tracking_codes_from_text,
    EngagementCampaignError,
    tracked_destination,
    validate_destination_url,
)


def test_observed_time_on_page_uses_largest_valid_sample():
    rows = [
        SimpleNamespace(raw_event_json={"time_on_page_ms": 0}),
        SimpleNamespace(raw_event_json={"time_on_page_ms": "17124"}),
        SimpleNamespace(raw_event_json={"time_on_page_ms": "invalid"}),
    ]
    assert _observed_time_on_page_ms(rows) == 17124


def test_tracking_codes_from_text_finds_unique_possible_minds_links():
    body = """Read https://getpossibleminds.com/t/first_code
    or https://www.getpossibleminds.com/t/second-code?utm_source=email.
    Duplicate: https://getpossibleminds.com/t/first_code
    Ignore: https://example.com/t/not_ours
    """
    assert _tracking_codes_from_text(body) == ["first_code", "second-code"]


def test_advisor_vendor_stack_keeps_only_evidence_bearing_signals():
    stack = _approved_vendor_stack({
        "filevine": {"status": "confirmed", "evidence": "careers page"},
        "lead_docket": {"status": "suspected"},
        "casepeer": "verified",
    })
    assert set(stack) == {"filevine", "casepeer"}


def test_destination_accepts_possible_minds_pages_and_subdomains():
    assert validate_destination_url(
        "https://getpossibleminds.com/blog/personal-injury-marketing-attribution"
    ).endswith("/blog/personal-injury-marketing-attribution")
    assert validate_destination_url("https://intake.getpossibleminds.com/try") == (
        "https://intake.getpossibleminds.com/try"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://getpossibleminds.com/blog",
        "https://example.com/blog",
        "https://getpossibleminds.com.evil.example/blog",
        "https://user:password@getpossibleminds.com/blog",
    ],
)
def test_destination_rejects_unsafe_redirects(url):
    with pytest.raises(EngagementCampaignError):
        validate_destination_url(url)


def test_tracked_destination_preserves_query_and_adds_campaign_attribution():
    link = SimpleNamespace(
        destination_url="https://getpossibleminds.com/blog/test?utm_content=founder",
        code="abc123",
        channel="linkedin",
    )
    campaign = SimpleNamespace(id="cmp_today")
    destination = tracked_destination(link, campaign, "click_1")
    parsed = urlsplit(destination)
    params = parse_qs(parsed.query)
    assert params["utm_content"] == ["founder"]
    assert params["utm_source"] == ["possibleos"]
    assert params["utm_medium"] == ["linkedin_dm"]
    assert params["utm_campaign"] == ["cmp_today"]
    assert params["lc"] == ["abc123"]
    assert params["c"] == ["click_1"]
