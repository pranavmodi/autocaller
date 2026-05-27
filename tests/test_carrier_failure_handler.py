"""Tests for CarrierFailureHandler callback behavior."""
from unittest.mock import AsyncMock, patch

import pytest

from app.models import CallLog, CallOutcome, Patient
from app.services.carrier_failure_service import CarrierFailureHandler


@pytest.mark.asyncio
async def test_ignores_status_for_other_sid():
    end_call = AsyncMock()
    handler = CarrierFailureHandler(
        lambda: CallLog(call_id="call-1"),
        lambda: None,
        lambda: "CA-current",
        end_call,
    )

    await handler.handle_twilio_call_status("CA-other", "failed", "32009", "")

    end_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_carrier_status_is_logged_only_when_verbose(capsys):
    end_call = AsyncMock()
    handler = CarrierFailureHandler(
        lambda: CallLog(call_id="call-1"),
        lambda: None,
        lambda: "CA-current",
        end_call,
    )
    handler.verbose = True

    await handler.handle_twilio_call_status("CA-current", "completed", "", "200")

    assert "[TwilioStatus]" in capsys.readouterr().out
    end_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_carrier_failure_updates_call_flags_patient_and_ends():
    call = CallLog(call_id="call-1", patient_id="p1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    end_call = AsyncMock()
    status_update = AsyncMock()
    call_provider = AsyncMock()
    patient_provider = AsyncMock()
    handler = CarrierFailureHandler(
        lambda: call,
        lambda: patient,
        lambda: "CA-current",
        end_call,
    )
    handler.on_status_update = status_update

    with patch("app.services.carrier_failure_service.get_call_log_provider", return_value=call_provider):
        with patch("app.services.carrier_failure_service.get_patient_provider", return_value=patient_provider):
            await handler.handle_twilio_call_status("CA-current", "failed", "32009", "404")

    assert call.error_code == "32009"
    assert "invalid number" in call.error_message
    call_provider.update_call.assert_awaited()
    patient_provider.mark_patient_invalid_number.assert_awaited_with("p1", call.error_message)
    end_call.assert_awaited_with(CallOutcome.FAILED, ended_by="carrier_failure")
    status_update.assert_awaited()
