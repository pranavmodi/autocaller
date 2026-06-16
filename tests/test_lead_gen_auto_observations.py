from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import AgentActionRow, EmailSequenceRow, LeadGenObservationRow
from app.services.action_execution import SEND_EMAIL, execute_action
from app.services.lead_feedback_classifier import FeedbackClassification
from app.services.lead_gen_cybernetic import record_observation
from app.services.inbound_email import ParsedInboundEmail, _classify_reply


class _ScalarResult:
    def __init__(self, row=None):
        self.row = row

    def scalar_one_or_none(self):
        return self.row

    def scalar_one(self):
        return self.row


class _ObservationSession:
    def __init__(self, store):
        self.store = store
        self.pending = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _stmt):
        return _ScalarResult(next(iter(self.store.values()), None))

    async def get(self, _model, _row_id):
        return None

    def add(self, row):
        self.pending.append(row)

    async def commit(self):
        for row in self.pending:
            self.store[(row.event_type, row.dedupe_key)] = row
        self.pending.clear()

    async def rollback(self):
        self.pending.clear()

    async def refresh(self, _row):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "classification"),
    [
        ("email_sent", None),
        ("email_send_failed", None),
        ("email_reply_received", {
            "outcome": "positive_reply",
            "confidence": 90,
            "next_action": "human_reply",
            "reasoning": "mocked reply classification",
            "model": "test",
        }),
        ("link_clicked", None),
        ("consult_booked", None),
        ("call_disposition", None),
        ("email_action_cancelled", None),
        ("email_rescheduled", None),
    ],
)
async def test_record_observation_is_idempotent_for_auto_event_types(monkeypatch, event_type, classification):
    store = {}
    monkeypatch.setattr(
        "app.services.lead_gen_cybernetic.AsyncSessionLocal",
        lambda: _ObservationSession(store),
    )

    raw_event = {"dedupe_key": f"{event_type}:one", "source": "test"}
    first = await record_observation(event_type, raw_event, classification=classification)
    second = await record_observation(event_type, raw_event, classification=classification)

    assert first["event_type"] == event_type
    assert first["existing"] is False
    assert second["id"] == first["id"]
    assert second["existing"] is True
    assert len(store) == 1


@pytest.mark.asyncio
async def test_reply_classification_uses_existing_classifier_path(monkeypatch):
    calls = []

    async def fake_classifier(**kwargs):
        calls.append(kwargs)
        return FeedbackClassification(
            outcome="positive_reply",
            confidence=91,
            next_action="human_reply",
            reasoning="mocked",
            model="test-model",
        )

    monkeypatch.setattr("app.services.inbound_email.classify_feedback_event", fake_classifier)
    parsed = ParsedInboundEmail(
        account_email="inbox@example.test",
        mailbox="INBOX",
        uid="uid-1",
        message_id="msg-1",
        in_reply_to=None,
        references_text=None,
        from_email="lead@example.test",
        from_name="Lead",
        to=[],
        cc=[],
        subject="Re: quick question",
        body_text="Sounds interesting.",
        text_excerpt="Sounds interesting.",
        raw_headers={},
        received_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    contact = SimpleNamespace(
        id="contact_1",
        full_name="Lead Example",
        email="lead@example.test",
        title="COO",
        source="manual",
    )
    item = SimpleNamespace(
        batch_id="batch_1",
        id="item_1",
        pif_id="pif_1",
        firm_name="Example Law",
        template_key="possible_minds_dynamic",
    )

    result = await _classify_reply(parsed, contact, item, classify=True)

    assert result.outcome == "positive_reply"
    assert calls[0]["event_type"] == "email_reply"
    assert calls[0]["sequence"]["batch_item_id"] == "item_1"


class _ActionSession:
    def __init__(self, action):
        self.action = action
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, row_id):
        if model is AgentActionRow and row_id == self.action.id:
            return self.action
        return None

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        return None


class _SequenceScalarResult:
    def __init__(self, row=None):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _SequenceSession:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _stmt):
        return _SequenceScalarResult(self.rows[0] if self.rows else None)

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        return None

    async def refresh(self, _row):
        return None


@pytest.mark.asyncio
async def test_scheduled_execute_action_records_email_sent_observation(monkeypatch):
    scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=5)
    action = SimpleNamespace(
        id="action_scheduled",
        action_type=SEND_EMAIL,
        status="approved",
        risk_level="high",
        requested_by="operator",
        approved_by="operator",
        entity_type="lead_gen_email",
        entity_id="item_1",
        input_json={
            "mode": "lead_gen",
            "to": "lead@example.test",
            "subject": "Subject",
            "body": "Body with https://getpossibleminds.com/consult",
            "contact_id": "contact_1",
            "batch_item_id": "item_1",
            "brief_version": 4,
        },
        policy_result_json={},
        execution_result_json={},
        error=None,
        trace_id=None,
        scheduled_for=scheduled_for,
        started_at=None,
        completed_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    observations = []

    async def noop(*args, **kwargs):
        return None

    async def fake_policy(*args, **kwargs):
        return {"allowed": True, "action_type": SEND_EMAIL}

    async def fake_send(payload):
        assert payload["mode"] == "lead_gen"
        return {
            "sent_message_id": "msg_1",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "email_log_id": 12,
            "transport": "zoho_api",
            "email_log_status": "sent",
        }

    async def fake_record(event_type, raw_event, **kwargs):
        observations.append((event_type, raw_event, kwargs))
        return {"id": "obs_1", "existing": False}

    async def fake_get_action(action_id):
        return {"action": {"id": action_id, "status": action.status}, "events": []}

    monkeypatch.setattr("app.services.action_execution.AsyncSessionLocal", lambda: _ActionSession(action))
    monkeypatch.setattr("app.services.action_execution.ensure_agent_tables", noop)
    monkeypatch.setattr("app.services.action_execution.check_action_policy", fake_policy)
    monkeypatch.setattr("app.services.action_execution._execute_send_email", fake_send)
    monkeypatch.setattr("app.services.action_execution.safe_record_product_trace", noop)
    monkeypatch.setattr("app.services.action_execution.record_observation", fake_record)
    monkeypatch.setattr("app.services.action_execution.get_action", fake_get_action)

    result = await execute_action("action_scheduled", actor="scheduler")

    assert result["executed"] is True
    assert action.status == "succeeded"
    assert observations == [
        (
            "email_sent",
            observations[0][1],
            {"contact_id": "contact_1", "batch_item_id": "item_1"},
        )
    ]
    assert observations[0][1]["action_id"] == "action_scheduled"
    assert observations[0][1]["brief_version"] == 4


@pytest.mark.asyncio
async def test_successful_first_touch_send_starts_sequence_when_flag_enabled(monkeypatch):
    sent_at = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    action = SimpleNamespace(
        id="action_sequence_seed",
        action_type=SEND_EMAIL,
        status="approved",
        risk_level="high",
        requested_by="operator",
        approved_by="operator",
        entity_type="lead_gen_email",
        entity_id="item_1",
        input_json={
            "mode": "lead_gen",
            "to": "lead@example.test",
            "subject": "Subject",
            "body": "Body with https://getpossibleminds.com/consult",
            "contact_id": "contact_1",
            "batch_item_id": "item_1",
            "composer_variant_key": "subject-pain-led",
            "brief_version": 4,
        },
        policy_result_json={},
        execution_result_json={},
        error=None,
        trace_id=None,
        scheduled_for=None,
        started_at=None,
        completed_at=None,
        created_at=sent_at,
        updated_at=sent_at,
    )
    sequence_rows = []

    async def noop(*args, **kwargs):
        return None

    async def fake_policy(*args, **kwargs):
        return {"allowed": True, "action_type": SEND_EMAIL}

    async def fake_send(payload):
        assert payload["mode"] == "lead_gen"
        return {
            "sent_message_id": "msg_1",
            "sent_at": sent_at.isoformat(),
            "email_log_id": 12,
            "transport": "zoho_api",
            "email_log_status": "sent",
        }

    async def fake_record(*args, **kwargs):
        return {"id": "obs_1", "existing": False}

    async def fake_get_action(action_id):
        return {"action": {"id": action_id, "status": action.status}, "events": []}

    monkeypatch.setenv("SEQUENCES_ENABLED", "1")
    monkeypatch.delenv("SEQUENCE_STEPS", raising=False)
    monkeypatch.delenv("SEQUENCE_CADENCE_DAYS", raising=False)
    monkeypatch.setattr("app.services.action_execution.AsyncSessionLocal", lambda: _ActionSession(action))
    monkeypatch.setattr("app.services.sequence_scheduler.AsyncSessionLocal", lambda: _SequenceSession(sequence_rows))
    monkeypatch.setattr("app.services.action_execution.ensure_agent_tables", noop)
    monkeypatch.setattr("app.services.action_execution.check_action_policy", fake_policy)
    monkeypatch.setattr("app.services.action_execution._execute_send_email", fake_send)
    monkeypatch.setattr("app.services.action_execution.safe_record_product_trace", noop)
    monkeypatch.setattr("app.services.action_execution.record_observation", fake_record)
    monkeypatch.setattr("app.services.action_execution.get_action", fake_get_action)

    first = await execute_action("action_sequence_seed", actor="scheduler")
    second = await execute_action("action_sequence_seed", actor="scheduler")

    assert first["executed"] is True
    assert second["executed"] is True
    assert len(sequence_rows) == 1
    row = sequence_rows[0]
    assert isinstance(row, EmailSequenceRow)
    assert row.contact_id == "contact_1"
    assert row.template_key == "possible_minds_dynamic"
    assert row.current_step == 1
    assert row.steps_total == 3
    assert row.status == "active"
    assert row.started_by == "lead_gen_daily"
    assert row.variant == "subject-pain-led"
    assert row.last_sent_at == sent_at
    assert row.next_step_due_at == sent_at + timedelta(days=3)

    sequence_rows = []
    monkeypatch.delenv("SEQUENCES_ENABLED", raising=False)
    await execute_action("action_sequence_seed", actor="scheduler")

    assert sequence_rows == []
