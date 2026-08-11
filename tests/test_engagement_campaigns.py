from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.engagement_campaigns import (
    EngagementCampaignError,
    tracked_destination,
    validate_destination_url,
)


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
