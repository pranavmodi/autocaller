from datetime import datetime, timezone

from app.db.models import ProductTraceRow
from app.services.product_traces import (
    current_request_id,
    current_trace_id,
    request_id_var,
    trace_id_var,
    trace_to_dict,
)


def test_trace_to_dict_exposes_ai_legible_payload_fields():
    row = ProductTraceRow(
        id=12,
        trace_id="trace-1",
        session_id="session-1",
        request_id="request-1",
        actor_type="user",
        actor_id="operator",
        event_type="email_draft_edited",
        surface="actions",
        entity_type="operator_notification",
        entity_id="7",
        parent_trace_id="parent-1",
        input_json={"subject": "before"},
        output_json={"subject": "after"},
        diff_json={"subject_changed": True},
        context_json={"firm_name": "Example Law"},
        metadata_json={"source": "unit-test"},
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )

    assert trace_to_dict(row) == {
        "id": 12,
        "trace_id": "trace-1",
        "session_id": "session-1",
        "request_id": "request-1",
        "actor_type": "user",
        "actor_id": "operator",
        "event_type": "email_draft_edited",
        "surface": "actions",
        "entity_type": "operator_notification",
        "entity_id": "7",
        "parent_trace_id": "parent-1",
        "input": {"subject": "before"},
        "output": {"subject": "after"},
        "diff": {"subject_changed": True},
        "context": {"firm_name": "Example Law"},
        "metadata": {"source": "unit-test"},
        "created_at": "2026-05-30T00:00:00+00:00",
    }


def test_trace_contextvars_hold_request_and_trace_ids():
    request_token = request_id_var.set("request-2")
    trace_token = trace_id_var.set("trace-2")
    try:
        assert current_request_id() == "request-2"
        assert current_trace_id() == "trace-2"
    finally:
        request_id_var.reset(request_token)
        trace_id_var.reset(trace_token)
