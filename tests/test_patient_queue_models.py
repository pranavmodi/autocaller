"""Tests for lead and queue model helpers."""
from datetime import datetime

from app.models import GlobalQueueState, IntakeStatus, Language, Patient, QueueInfo


def test_patient_priority_for_never_called_decision_maker():
    lead = Patient(patient_id="p1", name="Jane", phone="+1555", title="Managing Partner")

    assert lead.is_decision_maker()
    assert lead.priority_bucket == 1


def test_patient_priority_for_non_dm_and_attempted_dm():
    assert Patient(patient_id="p1", name="Jane", phone="+1555").priority_bucket == 2
    assert Patient(
        patient_id="p2",
        name="Alex",
        phone="+1556",
        title="Partner",
        attempt_count=1,
    ).priority_bucket == 3
    assert Patient(patient_id="p3", name="Sam", phone="+1557", attempt_count=1).priority_bucket == 4


def test_patient_to_dict_serializes_datetimes_enums_and_lists():
    now = datetime.now()
    lead = Patient(
        patient_id="p1",
        name="Jane",
        phone="+1555",
        language=Language.SPANISH,
        intake_status=IntakeStatus.INCOMPLETE,
        order_created=now,
        last_attempt_at=now,
        due_by=now,
        tags=["pi", "ca"],
    )

    data = lead.to_dict()

    assert data["lead_id"] == "p1"
    assert data["language"] == "es"
    assert data["intake_status"] == "incomplete"
    assert data["order_created"] == now.isoformat()
    assert data["tags"] == ["pi", "ca"]


def test_global_queue_state_to_dict_serializes_queues_and_time():
    now = datetime.now()
    state = GlobalQueueState(
        global_calls_waiting=1,
        global_max_holdtime=2,
        global_agents_available=3,
        outbound_allowed=True,
        stable_polls_count=4,
        last_poll_time=now,
        queues=[QueueInfo(Queue="9006", AvailableAgents=2)],
    )

    data = state.to_dict()

    assert data["last_poll_time"] == now.isoformat()
    assert data["queues"][0]["Queue"] == "9006"
    assert data["queues"][0]["AvailableAgents"] == 2
