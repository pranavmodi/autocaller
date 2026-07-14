import asyncio
from datetime import datetime, timezone

import pytest

from app.db.models import LeadGenBatchRow, LeadGenObservationRow
from app.services.inbound_email import ParsedInboundEmail, _reply_reference_message_ids
from app.services.lead_gen_experiments import (
    assert_batch_experiment_send_gate,
    classify_page_sessions,
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
    assert signal_quality("page_session", {"time_on_page_ms": 12000, "user_agent": ""}) == "suspect"
    assert signal_quality(
        "page_session",
        {"time_on_page_ms": 12000, "user_agent": "Mozilla/5.0 Chrome/120 Safari/537.36"},
    ) == "human"
    assert signal_quality("link_clicked", user_agent="Proofpoint URL Defense") == "scanner"


def test_signal_quality_short_dwell_browser_session_is_suspect():
    # Email-security scanners execute JS: session_ready + ~4s dwell + browser UA.
    assert signal_quality(
        "page_session",
        {"time_on_page_ms": 4000, "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120 Safari/537.36"},
    ) == "suspect"


BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def _obs(obs_id, event, *, session_id, time_ms=None, minutes=0, batch_item_id="item_1", ua=BROWSER_UA):
    return LeadGenObservationRow(
        id=obs_id,
        batch_id="batch_1",
        batch_item_id=batch_item_id,
        event_type="page_session",
        raw_event_json={
            "event": event,
            "session_id": session_id,
            "time_on_page_ms": time_ms,
            "user_agent": ua,
        },
        created_at=datetime(2026, 7, 13, 16, minutes, tzinfo=timezone.utc),
    )


def test_classify_page_sessions_requires_interaction_evidence():
    sent_at = {"item_1": datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)}
    observations = [
        # Scanner-shaped: session_ready + short-dwell page_leave right after send.
        _obs("o1", "session_ready", session_id="s_scanner", time_ms=0, minutes=2),
        _obs("o2", "page_leave", session_id="s_scanner", time_ms=4000, minutes=2),
        # Long dwell counts as human.
        _obs("o3", "session_ready", session_id="s_dwell", time_ms=0, minutes=3),
        _obs("o4", "page_leave", session_id="s_dwell", time_ms=14000, minutes=3),
        # On-page click counts as human even with a short dwell.
        _obs("o5", "session_ready", session_id="s_click", time_ms=0, minutes=4),
        _obs("o6", "click", session_id="s_click", time_ms=2000, minutes=4),
        # Arrival well after the send counts as human.
        _obs("o7", "session_ready", session_id="s_late", time_ms=0, minutes=40),
        # Scanner UA is never human, whatever the dwell.
        _obs("o8", "page_leave", session_id="s_ua", time_ms=20000, minutes=50, ua="python-requests/2.31"),
    ]

    records = classify_page_sessions(observations, sent_at)
    quality = {sid: rec["quality"] for sid, rec in records.items()}

    assert quality == {
        "s_scanner": "suspect",
        "s_dwell": "human",
        "s_click": "human",
        "s_late": "human",
        "s_ua": "scanner",
    }


def test_classify_page_sessions_scores_progressive_funnel_gestures():
    sent_at = {"item_1": datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc)}
    observations = [
        # Bare beacon fired seconds after send, no gesture -> suspect.
        _obs("g1", "session_ready", session_id="s_bare", time_ms=0, minutes=2),
        _obs("g2", "page_leave", session_id="s_bare", time_ms=4000, minutes=2),
        # A pointer gesture (short dwell, no click) is high-confidence human.
        _obs("g3", "session_ready", session_id="s_pointer", time_ms=0, minutes=2),
        _obs("g4", "first_pointer", session_id="s_pointer", time_ms=1200, minutes=2),
        # Tap-to-reveal is the strongest pre-conversion signal.
        _obs("g5", "session_ready", session_id="s_reveal", time_ms=0, minutes=3),
        _obs("g6", "content_revealed", session_id="s_reveal", time_ms=6000, minutes=3),
    ]

    records = classify_page_sessions(observations, sent_at)

    assert records["s_bare"]["quality"] == "suspect"
    assert records["s_bare"]["has_gesture"] is False
    assert records["s_pointer"]["quality"] == "human"
    assert records["s_pointer"]["has_gesture"] is True
    assert records["s_pointer"]["reached_reveal"] is False
    assert records["s_reveal"]["quality"] == "human"
    assert records["s_reveal"]["reached_reveal"] is True


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
