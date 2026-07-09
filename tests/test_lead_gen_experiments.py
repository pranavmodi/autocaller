import asyncio
from datetime import datetime, timezone

import pytest

from app.db.models import LeadGenBatchRow
from app.services.inbound_email import ParsedInboundEmail, _reply_reference_message_ids
from app.services.lead_gen_experiments import (
    assert_batch_experiment_send_gate,
    experiment_card_summary,
    signal_quality,
)


class _GateSession:
    def __init__(self):
        self.flushed = False

    async def flush(self):
        self.flushed = True


def _batch(*, name="Wave 7 test", status="none", card=None):
    return LeadGenBatchRow(
        id="batch_1",
        name=name,
        target_metric="human_reply",
        template_key="possible_minds_dynamic",
        policy_version="lead-gen-v1",
        status="approved",
        counts_json={"returned": 30},
        experiment_status=status,
        experiment_json=card or {},
    )


def _complete_card():
    return {
        "wave_id": "wave-7",
        "goal": "Get one qualified reply",
        "primary_metric": "human_reply",
        "hypothesis": "Fewer stronger recipients improve reply quality.",
        "changed_vs_previous": "Reduced recipient padding.",
        "prediction": "At least one strong reply within 72h.",
        "success_threshold": "1 strong reply",
        "measurement_window_hours": 72,
        "minimum_n": 30,
        "confidence_note": "directional at this N",
        "invalidation_criteria": "report error or bounce rate above 20%",
        "owner": "operator",
    }


def test_wave_batch_requires_complete_card_before_send():
    session = _GateSession()
    batch = _batch(card={"wave_id": "wave-7"})

    with pytest.raises(ValueError, match="experiment_card_required"):
        asyncio.run(assert_batch_experiment_send_gate(session, batch))

    summary = experiment_card_summary(batch)
    assert "goal" in summary["missing_fields"]
    assert session.flushed is False


def test_complete_card_promotes_wave_to_ready():
    session = _GateSession()
    batch = _batch(card=_complete_card())

    asyncio.run(assert_batch_experiment_send_gate(session, batch))

    assert batch.experiment_status == "ready"
    assert session.flushed is True
    assert experiment_card_summary(batch)["is_ready"] is True


def test_signal_quality_does_not_treat_blank_page_session_as_human():
    assert signal_quality("page_session", {"time_on_page_ms": 9000, "user_agent": ""}) == "suspect"
    assert signal_quality(
        "page_session",
        {"time_on_page_ms": 9000, "user_agent": "Mozilla/5.0 Chrome/120 Safari/537.36"},
    ) == "human"
    assert signal_quality("link_clicked", user_agent="Proofpoint URL Defense") == "scanner"


def test_reply_reference_message_ids_extracts_thread_headers():
    parsed = ParsedInboundEmail(
        account_email="inbox@example.test",
        mailbox="INBOX",
        uid="uid-1",
        message_id="<reply@example.test>",
        in_reply_to="<sent-1@example.test>",
        references_text="<root@example.test> <sent-1@example.test>",
        from_email="lead@example.test",
        from_name="Lead",
        to=[],
        cc=[],
        subject="Re: hello",
        body_text="Interested",
        text_excerpt="Interested",
        raw_headers={},
        received_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )

    ids = _reply_reference_message_ids(parsed)

    assert "<sent-1@example.test>" in ids
    assert "sent-1@example.test" in ids
    assert "<root@example.test>" in ids
