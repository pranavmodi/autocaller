"""Additional notification-service branch coverage."""
from unittest.mock import AsyncMock, patch

import pytest

from app.models import CallLog, Patient
from app.services.notification_service import CallNotificationService


async def immediate_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


@pytest.fixture
def service():
    svc = CallNotificationService()
    svc.on_status_update = AsyncMock()
    return svc


@pytest.fixture
def call():
    return CallLog(call_id="call-1", patient_id="p1", patient_name="Jane")


@pytest.fixture
def patient():
    return Patient(patient_id="p1", name="Jane", phone="+15551234567")


@pytest.mark.asyncio
async def test_twilio_sms_success_updates_call_and_logs(service, call, patient):
    provider = AsyncMock()
    provider.get_call.return_value = None

    with patch("app.services.notification_service.get_call_log_provider", return_value=provider):
        with patch("app.services.notification_service.is_number_opted_out", return_value=False):
            with patch("app.services.notification_service.send_sms", return_value="SM123") as send_sms:
                with patch("app.services.notification_service.log_sms") as log_sms:
                    with patch("app.services.notification_service.asyncio.to_thread", immediate_to_thread):
                        result = await service.send_sms_for_call(
                            call,
                            patient,
                            call_mode="twilio",
                            reason="unit",
                        )

    assert result is True
    assert call.sms_sent is True
    send_sms.assert_called_once()
    log_sms.assert_called_once()
    provider.update_call.assert_awaited_with("call-1", sms_sent=True)


@pytest.mark.asyncio
async def test_twilio_sms_failure_logs_and_reports(service, call, patient):
    provider = AsyncMock()
    provider.get_call.return_value = None

    with patch("app.services.notification_service.get_call_log_provider", return_value=provider):
        with patch("app.services.notification_service.is_number_opted_out", return_value=False):
            with patch("app.services.notification_service.send_sms", side_effect=RuntimeError("boom")):
                with patch("app.services.notification_service.log_sms") as log_sms:
                    with patch("app.services.notification_service.asyncio.to_thread", immediate_to_thread):
                        result = await service.send_sms_for_call(
                            call,
                            patient,
                            call_mode="twilio",
                            reason="unit",
                        )

    assert result is False
    assert call.sms_sent is False
    log_sms.assert_called_once()
    service.on_status_update.assert_awaited()


@pytest.mark.asyncio
async def test_twilio_sms_opt_out_exception_returns_false(service, call, patient):
    provider = AsyncMock()
    provider.get_call.return_value = None

    with patch("app.services.notification_service.get_call_log_provider", return_value=provider):
        with patch("app.services.notification_service.is_number_opted_out", return_value=False):
            with patch("app.services.notification_service.send_sms", side_effect=Exception("21610 opted out")):
                with patch("app.services.notification_service.log_sms"):
                    with patch("app.services.notification_service.asyncio.to_thread", immediate_to_thread):
                        result = await service.send_sms_for_call(
                            call,
                            patient,
                            call_mode="twilio",
                            reason="unit",
                        )

    assert result is False
    assert service.on_status_update.await_args.args[0] == "SMS blocked (unit): recipient opted out"


@pytest.mark.asyncio
async def test_issue_email_failure_is_logged(service, call):
    provider = AsyncMock()

    with patch("app.services.notification_service.get_call_log_provider", return_value=provider):
        with patch("app.services.notification_service.send_wrong_number_email", side_effect=RuntimeError("smtp")):
            with patch("app.services.notification_service.asyncio.to_thread", immediate_to_thread):
                from app.models import CallOutcome

                await service.maybe_send_issue_email(call, CallOutcome.WRONG_NUMBER)

    provider.add_transcript.assert_awaited()
    service.on_status_update.assert_awaited_with("Email failed: smtp")


def test_cleanup_call_removes_idempotency_state(service):
    service._sms_sent_call_ids.add("call-1")
    service._email_sent_call_ids.add("call-1")
    service._sms_locks["call-1"] = object()

    service.cleanup_call("call-1")

    assert "call-1" not in service._sms_sent_call_ids
    assert "call-1" not in service._email_sent_call_ids
    assert "call-1" not in service._sms_locks
