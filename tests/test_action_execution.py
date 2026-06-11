from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import AgentActionRow, LeadGenBatchItemRow
from app.services.action_execution import (
    SEND_EMAIL,
    _sync_lead_gen_scheduled_draft_fields,
    _terminal_policy_block_reason,
    cancel_action,
    save_edited_lead_gen_draft,
)


def test_terminal_policy_block_reason_detects_duplicate_send_failures():
    policy = {
        "reason": "batch_item_not_already_started",
        "checks": [
            {"name": "daily_budget_available", "passed": True},
            {"name": "no_prior_successful_lead_gen_action_for_item", "passed": False},
        ],
    }

    assert _terminal_policy_block_reason(policy) == "batch_item_not_already_started"


def test_terminal_policy_block_reason_ignores_retryable_failures():
    policy = {
        "reason": "daily_budget_available",
        "checks": [
            {"name": "daily_budget_available", "passed": False},
            {"name": "email_transport_configured", "passed": True},
        ],
    }

    assert _terminal_policy_block_reason(policy) == ""


def _action(**overrides):
    now = datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc)
    data = {
        "id": "action_1",
        "action_type": SEND_EMAIL,
        "status": "approved",
        "risk_level": "high",
        "requested_by": "operator",
        "approved_by": "operator",
        "entity_type": "lead_gen_batch_item",
        "entity_id": "item_1",
        "input_json": {
            "to": "lead@example.com",
            "subject": "Old subject",
            "body": "Old body",
            "mode": "lead_gen",
            "approval": {
                "approved_by": "operator",
                "recipient": "lead@example.com",
                "subject_sha256": "old",
                "body_sha256": "old",
            },
        },
        "policy_result_json": {},
        "execution_result_json": {},
        "error": None,
        "trace_id": None,
        "scheduled_for": now + timedelta(days=30),
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _item(**overrides):
    data = {
        "id": "item_1",
        "reason_json": {
            "agent_draft": {"subject": "Old subject", "body": "Old body"},
            "send_email_action_id": "action_1",
        },
        "approval_status": "pending",
        "updated_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, row_id):
        return self.rows.get((model, row_id)) or self.rows.get(row_id)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def refresh(self, row):
        return None


@pytest.mark.asyncio
async def test_cancel_action_happy_path(monkeypatch):
    action = _action(status="approved")
    session = _FakeSession({(AgentActionRow, "action_1"): action})
    monkeypatch.setattr("app.services.action_execution.AsyncSessionLocal", lambda: session)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.action_execution.ensure_agent_tables", noop)
    monkeypatch.setattr("app.services.action_execution.safe_record_product_trace", noop)

    result = await cancel_action("action_1", actor="operator", reason="test cleanup")

    assert result["cancelled"] is True
    assert action.status == "cancelled"
    assert "test cleanup" in action.error
    assert session.added[-1].event_type == "action_cancelled"


@pytest.mark.asyncio
async def test_cancel_action_refuses_terminal_status(monkeypatch):
    action = _action(status="succeeded")
    session = _FakeSession({(AgentActionRow, "action_1"): action})
    monkeypatch.setattr("app.services.action_execution.AsyncSessionLocal", lambda: session)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.action_execution.ensure_agent_tables", noop)

    with pytest.raises(ValueError, match="action_cannot_be_cancelled_from_status:succeeded"):
        await cancel_action("action_1", actor="operator")


def test_sync_lead_gen_scheduled_draft_fields_keeps_ui_consistent():
    action = _action()
    item = _item()

    reason = _sync_lead_gen_scheduled_draft_fields(
        item,
        action=action,
        subject="Edited subject",
        body="Edited body",
        actor="operator",
    )

    draft = reason["agent_draft"]
    assert item.approval_status == "approved"
    assert draft["subject"] == "Edited subject"
    assert draft["body"] == "Edited body"
    assert draft["operator_edited"] is True
    assert draft["scheduled_for_pt"]
    assert draft["scheduled_for_utc"]
    assert reason["send_email_action_id"] == "action_1"


@pytest.mark.asyncio
async def test_edit_draft_updates_live_scheduled_action_instead_of_creating(monkeypatch):
    action = _action()
    item = _item()
    session = _FakeSession({
        (LeadGenBatchItemRow, "item_1"): item,
        (AgentActionRow, "action_1"): action,
    })
    monkeypatch.setattr("app.services.action_execution.AsyncSessionLocal", lambda: session)

    async def noop(*args, **kwargs):
        return None

    async def fail_create(*args, **kwargs):
        raise AssertionError("should not create duplicate action")

    monkeypatch.setattr("app.services.action_execution.ensure_agent_tables", noop)
    monkeypatch.setattr("app.services.action_execution.create_send_approved_lead_gen_draft_action", fail_create)

    result = await save_edited_lead_gen_draft(
        batch_item_id="item_1",
        subject="New subject",
        body="New body",
        actor="operator",
        scheduled_for=action.scheduled_for + timedelta(days=1),
    )

    assert result["updated_existing"] is True
    assert result["created"] is False
    assert action.input_json["subject"] == "New subject"
    assert action.input_json["body"] == "New body"
    assert item.reason_json["agent_draft"]["subject"] == "New subject"
    assert session.added[-2].event_type == "action_draft_edited"
    assert session.added[-1].event_type == "action_rescheduled"
