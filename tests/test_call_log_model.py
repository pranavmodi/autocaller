"""Tests for call-log model derivations and serialization."""
from datetime import datetime, timedelta

import pytest

from app.models.call_log import (
    CallDisposition,
    CallLog,
    CallOutcome,
    CallStatus,
    TranscriptEntry,
    derive_status_and_disposition,
)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (CallOutcome.TRANSFERRED, (CallStatus.CALLED, CallDisposition.TRANSFERRED)),
        (CallOutcome.DEMO_SCHEDULED, (CallStatus.CALLED, CallDisposition.DEMO_SCHEDULED)),
        (CallOutcome.NOT_INTERESTED, (CallStatus.CALLED, CallDisposition.NOT_INTERESTED)),
        (CallOutcome.GATEKEEPER_ONLY, (CallStatus.CALLED, CallDisposition.GATEKEEPER_ONLY)),
        (CallOutcome.VOICEMAIL, (CallStatus.CALLED, CallDisposition.VOICEMAIL_LEFT)),
        (CallOutcome.CALLBACK_REQUESTED, (CallStatus.CALLED, CallDisposition.CALLBACK_REQUESTED)),
        (CallOutcome.WRONG_NUMBER, (CallStatus.CALLED, CallDisposition.WRONG_NUMBER)),
        (CallOutcome.NO_ANSWER, (CallStatus.CALLED, CallDisposition.NO_ANSWER)),
        (CallOutcome.COMPLETED, (CallStatus.CALLED, CallDisposition.COMPLETED)),
        (CallOutcome.IN_PROGRESS, (CallStatus.IN_PROGRESS, CallDisposition.IN_PROGRESS)),
    ],
)
def test_derive_status_and_disposition_for_standard_outcomes(outcome, expected):
    assert derive_status_and_disposition(outcome) == expected


@pytest.mark.parametrize("error_code", ["media_stream_timeout", "twilio_no-answer", "twilio_busy"])
def test_failed_no_answer_codes_are_called_no_answer(error_code):
    assert derive_status_and_disposition(CallOutcome.FAILED, error_code=error_code) == (
        CallStatus.CALLED,
        CallDisposition.NO_ANSWER,
    )


@pytest.mark.parametrize("error_code", ["32005", "32009"])
def test_failed_invalid_number_codes_are_failed_disconnected(error_code):
    assert derive_status_and_disposition(CallOutcome.FAILED, error_code=error_code) == (
        CallStatus.FAILED,
        CallDisposition.DISCONNECTED_NUMBER,
    )


def test_failed_unknown_error_is_technical_error():
    assert derive_status_and_disposition(CallOutcome.FAILED, error_code="openai_connect_failed") == (
        CallStatus.FAILED,
        CallDisposition.TECHNICAL_ERROR,
    )


def test_disconnected_after_speech_is_hung_up():
    assert derive_status_and_disposition(CallOutcome.DISCONNECTED, had_patient_speech=True) == (
        CallStatus.CALLED,
        CallDisposition.HUNG_UP,
    )


def test_disconnected_after_duration_is_hung_up():
    assert derive_status_and_disposition(CallOutcome.DISCONNECTED, duration_seconds=5) == (
        CallStatus.CALLED,
        CallDisposition.HUNG_UP,
    )


def test_disconnected_without_answer_is_bad_number():
    assert derive_status_and_disposition(CallOutcome.DISCONNECTED) == (
        CallStatus.FAILED,
        CallDisposition.DISCONNECTED_NUMBER,
    )


@pytest.mark.parametrize("ivr_outcome", ["reached_human", "queue_wait"])
def test_ivr_reached_human_overrides_disposition(ivr_outcome):
    assert derive_status_and_disposition(
        CallOutcome.NO_ANSWER,
        ivr_detected=True,
        ivr_outcome=ivr_outcome,
    ) == (CallStatus.CALLED, CallDisposition.IVR_NAVIGATED)


@pytest.mark.parametrize("ivr_outcome", ["skipped", "dead_end", "timed_out"])
def test_ivr_unreached_overrides_disposition(ivr_outcome):
    assert derive_status_and_disposition(
        CallOutcome.COMPLETED,
        ivr_detected=True,
        ivr_outcome=ivr_outcome,
    ) == (CallStatus.CALLED, CallDisposition.IVR_UNREACHED)


def test_transcript_entry_serializes_timestamp():
    entry = TranscriptEntry("ai", "hello")

    assert entry.to_dict()["speaker"] == "ai"
    assert entry.to_dict()["text"] == "hello"
    assert "T" in entry.to_dict()["timestamp"]


def test_call_log_end_call_updates_duration_and_outcome():
    call = CallLog(call_id="call-1", started_at=datetime.now() - timedelta(seconds=3))

    call.end_call(CallOutcome.COMPLETED)

    assert call.ended_at is not None
    assert call.outcome == CallOutcome.COMPLETED
    assert call.duration_seconds >= 2


def test_call_log_to_dict_includes_nested_and_optional_fields():
    call = CallLog(
        call_id="call-1",
        patient_id="p1",
        patient_name="Jane",
        phone="+15551234567",
        outcome=CallOutcome.COMPLETED,
        call_status=CallStatus.CALLED,
        call_disposition=CallDisposition.COMPLETED,
        recording_path="/tmp/call.wav",
    )
    call.add_transcript("ai", "hello")

    data = call.to_dict()

    assert data["call_id"] == "call-1"
    assert data["outcome"] == "completed"
    assert data["call_status"] == "called"
    assert data["call_disposition"] == "completed"
    assert data["has_recording"] is True
    assert data["transcript"][0]["text"] == "hello"
