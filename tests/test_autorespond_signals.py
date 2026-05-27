"""Tests for autorespond signal aggregation and priority scoring."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import autorespond_signals as signals


def test_parse_iso_accepts_z_suffix_and_naive_values():
    assert signals._parse_iso("2026-05-13T03:00:00Z").tzinfo is not None

    parsed = signals._parse_iso("2026-05-13T03:00:00")
    assert parsed.tzinfo == timezone.utc


def test_parse_iso_rejects_invalid_values():
    assert signals._parse_iso("") is None
    assert signals._parse_iso("not-a-date") is None
    assert signals._parse_iso(None) is None


@pytest.mark.asyncio
async def test_fetch_recent_events_paginates(monkeypatch):
    calls = []

    async def fake_get_json(path, params=None):
        calls.append((path, params))
        if params["page"] == 1:
            return {"items": [{"id": "1"}], "total_pages": 2}
        return {"items": [{"id": "2"}], "total_pages": 2}

    monkeypatch.setattr(signals, "_get_json", fake_get_json)

    assert await signals.fetch_recent_events(days=3) == [{"id": "1"}, {"id": "2"}]
    assert [params["page"] for _, params in calls] == [1, 2]
    assert calls[0][1]["date_from"]


@pytest.mark.asyncio
async def test_fetch_recent_events_grouped_filters_tests_and_summarizes(monkeypatch):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=3)
    long_subject = "x" * 250

    async def fake_fetch_recent_events(days=7):
        return [
            {
                "pif_id": "pif-1",
                "firm_name": "Alpha Law",
                "agent_type": "records",
                "contact_email": "DM@Example.com",
                "contact_name": "Decision Maker",
                "email_subject": "Older subject",
                "created_at": old.isoformat(),
            },
            {
                "pif_id": "pif-1",
                "firm_name": "Alpha Law",
                "agent_type": "records",
                "contact_email": "dm@example.com",
                "contact_name": "Duplicate",
                "email_subject": long_subject,
                "created_at": now.isoformat(),
            },
            {
                "pif_id": "pif-2",
                "firm_name": "Test Firm",
                "test_mode": True,
                "created_at": now.isoformat(),
            },
        ]

    monkeypatch.setattr(signals, "fetch_recent_events", fake_fetch_recent_events)

    summary = await signals.fetch_recent_events_grouped()

    assert set(summary) == {"pif-1"}
    assert summary["pif-1"]["events_24h"] == 1
    assert summary["pif-1"]["events_7d"] == 2
    assert summary["pif-1"]["latest_subject"] == long_subject[:200]
    assert summary["pif-1"]["top_agent_types"] == ["records"]
    assert summary["pif-1"]["distinct_contact_count"] == 1
    assert summary["pif-1"]["distinct_contacts"] == [
        {"name": "Decision Maker", "email": "dm@example.com"}
    ]


def test_priority_score_weights_positive_and_negative_signals():
    score = signals.priority_score(
        events_24h=2,
        events_7d=4,
        icp_tier="A",
        has_dm_phone=True,
        cadence_stage="callback_pending",
        last_call_age_hours=12,
    )

    assert score == 59


@pytest.mark.parametrize("stage", ["completed", "exhausted", "dnc"])
def test_priority_score_suppresses_terminal_stages(stage):
    assert signals.priority_score(cadence_stage=stage) == -1000


def test_priority_score_penalizes_very_recent_calls():
    assert signals.priority_score(last_call_age_hours=5) == -50
