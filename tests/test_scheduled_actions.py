from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.action_scheduler import classify_scheduled_action_rows, tick_scheduled_actions
from app.services.scheduled_time import parse_scheduled_time


def test_parse_scheduled_time_iso_with_offset():
    parsed = parse_scheduled_time(
        "2026-06-11T09:30:00-07:00",
        now=datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc),
    )

    assert parsed == datetime(2026, 6, 11, 16, 30, tzinfo=timezone.utc)


def test_parse_scheduled_time_pt_today():
    parsed = parse_scheduled_time(
        "9:30 PDT",
        now=datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc),
    )

    assert parsed == datetime(2026, 6, 11, 16, 30, tzinfo=timezone.utc)


def test_parse_scheduled_time_pt_past_errors():
    with pytest.raises(ValueError, match="already past"):
        parse_scheduled_time(
            "7:30 PT",
            now=datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc),
        )


def test_parse_scheduled_time_iso_past_errors():
    with pytest.raises(ValueError, match="already in the past"):
        parse_scheduled_time(
            "2026-06-11T07:30:00Z",
            now=datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc),
        )


def test_due_selection_classifies_due_future_and_expired():
    now = datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(id="expired", scheduled_for=now - timedelta(hours=25)),
        SimpleNamespace(id="due", scheduled_for=now - timedelta(minutes=5)),
        SimpleNamespace(id="future", scheduled_for=now + timedelta(minutes=5)),
    ]

    result = classify_scheduled_action_rows(rows, now=now)

    assert result == {"due_ids": ["due"], "expired_ids": ["expired"]}


@pytest.mark.asyncio
async def test_scheduler_tick_executes_due_action(monkeypatch):
    calls = []

    async def fake_candidates(*, now=None, limit=25):
        return {"due_ids": ["action_due"], "expired_ids": []}

    async def fake_execute(action_id, *, actor):
        calls.append((action_id, actor))
        return {"action": {"id": action_id, "status": "succeeded"}, "executed": True}

    monkeypatch.setattr("app.services.action_scheduler.get_due_scheduled_action_candidates", fake_candidates)
    monkeypatch.setattr("app.services.action_scheduler.execute_action", fake_execute)

    result = await tick_scheduled_actions(
        now=datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc),
        actor="test-scheduler",
    )

    assert calls == [("action_due", "test-scheduler")]
    assert result["executed"] == 1
    assert result["due_action_ids"] == ["action_due"]
