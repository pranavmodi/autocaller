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


def test_front_client_handles_429_with_retry_after(monkeypatch):
    import asyncio

    import httpx

    from app.services.front_sync import FrontClient, FrontRateBudget

    monkeypatch.setenv("FRONT_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("FRONT_API_BASE_URL", "https://front.test")

    calls = {"n": 0}

    async def fake_get(self, url, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "1"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200,
            json={"_results": []},
            request=httpx.Request("GET", url),
        )

    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def run():
        budget = FrontRateBudget(max_calls=10)
        async with FrontClient(budget=budget) as client:
            result = await client.get("/contacts")
        return budget, result

    budget, result = asyncio.run(run())
    assert result == {"_results": []}
    assert budget.rate_limited_count == 1
    assert budget.calls_made == 2  # retry consumed budget
    assert budget.min_interval_seconds == 3.0  # pacing widened from 1.5
    assert 1.0 in sleeps  # honored Retry-After


def test_front_client_raises_after_persistent_429(monkeypatch):
    import asyncio

    import httpx
    import pytest

    from app.services.front_sync import FrontClient, FrontRateBudget

    monkeypatch.setenv("FRONT_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("FRONT_API_BASE_URL", "https://front.test")

    async def always_429(self, url, params=None):
        return httpx.Response(
            429,
            headers={"Retry-After": "1"},
            request=httpx.Request("GET", url),
        )

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "get", always_429)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def run():
        budget = FrontRateBudget(max_calls=10)
        async with FrontClient(budget=budget) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get("/contacts")
        return budget

    budget = asyncio.run(run())
    assert budget.rate_limited_count == 2  # both retries counted before raising
