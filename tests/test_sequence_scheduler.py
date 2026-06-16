from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.sequence_scheduler import _apply_followup_send_to_sequence


def _sequence(**overrides):
    data = {
        "id": "seq-1",
        "contact_id": "contact-1",
        "template_key": "possible_minds_dynamic",
        "status": "paused",
        "current_step": 1,
        "steps_total": 3,
        "variant": "dynamic",
        "last_sent_at": None,
        "next_step_due_at": None,
        "paused_reason": "awaiting_operator_send_approval:daily_run:run-1",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_followup_send_advances_sequence_and_sets_next_due():
    sent_at = datetime(2026, 6, 16, 16, 0, tzinfo=timezone.utc)
    seq = _sequence(current_step=1)

    _apply_followup_send_to_sequence(seq, step_just_sent=2, sent_at=sent_at)

    assert seq.current_step == 2
    assert seq.last_sent_at == sent_at
    assert seq.status == "active"
    assert seq.paused_reason is None
    assert seq.next_step_due_at == sent_at + timedelta(days=4)


def test_last_followup_send_completes_sequence():
    sent_at = datetime(2026, 6, 16, 16, 0, tzinfo=timezone.utc)
    seq = _sequence(current_step=2)

    _apply_followup_send_to_sequence(seq, step_just_sent=3, sent_at=sent_at)

    assert seq.current_step == 3
    assert seq.last_sent_at == sent_at
    assert seq.status == "completed"
    assert seq.next_step_due_at is None
    assert seq.paused_reason is None


def test_followup_send_advancement_is_idempotent_for_already_sent_step():
    sent_at = datetime(2026, 6, 16, 16, 0, tzinfo=timezone.utc)
    original_due = datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc)
    seq = _sequence(current_step=2, status="active", next_step_due_at=original_due)

    _apply_followup_send_to_sequence(seq, step_just_sent=2, sent_at=sent_at)

    assert seq.current_step == 2
    assert seq.status == "active"
    assert seq.next_step_due_at == original_due
