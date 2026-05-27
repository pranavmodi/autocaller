"""Additional TransferService branch coverage."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import CallLog, CallOutcome, Language, Patient
from app.services.transfer_service import TransferService, _load_json_object_env


async def immediate_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def queue_state(*, queue="9006", available=1, global_available=1, ami_connected=True):
    return SimpleNamespace(
        ami_connected=ami_connected,
        global_agents_available=global_available,
        outbound_allowed=True,
        queues=[SimpleNamespace(Queue=queue, AvailableAgents=available)],
    )


def test_load_json_object_env_rejects_invalid_and_non_dict(monkeypatch):
    monkeypatch.setenv("BAD_JSON", "{")
    assert _load_json_object_env("BAD_JSON") == {}

    monkeypatch.setenv("BAD_JSON", '["not", "a", "dict"]')
    assert _load_json_object_env("BAD_JSON") == {}


def test_check_capacity_requires_queue_agent_global_agent_and_ami():
    svc = TransferService()

    assert svc.check_capacity(queue_state(), "9006")[1] is True
    assert svc.check_capacity(queue_state(available=0), "9006")[1] is False
    assert svc.check_capacity(queue_state(global_available=0), "9006")[1] is False
    assert svc.check_capacity(queue_state(ami_connected=False), "9006")[1] is False
    assert svc.check_capacity(queue_state(), "9009") == (None, False)


@pytest.mark.asyncio
async def test_execute_transfer_missing_queue_sends_callback_sms():
    svc = TransferService()
    svc.on_status_update = AsyncMock()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555", language=Language.SPANISH)
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state(queue="9006")

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            outcome = await svc.execute_transfer(call, patient, "web", None, notification)

    assert outcome == CallOutcome.CALLBACK_REQUESTED
    notification.send_sms_for_call.assert_awaited()
    svc.on_status_update.assert_awaited()


@pytest.mark.asyncio
async def test_execute_transfer_no_capacity_sends_callback_sms():
    svc = TransferService()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state(available=0)

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            outcome = await svc.execute_transfer(call, patient, "web", None, notification)

    assert outcome == CallOutcome.CALLBACK_REQUESTED
    notification.send_sms_for_call.assert_awaited()


@pytest.mark.asyncio
async def test_execute_transfer_web_success_marks_transfer_success():
    svc = TransferService()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state()

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            outcome = await svc.execute_transfer(call, patient, "web", None, notification)

    assert outcome == CallOutcome.TRANSFERRED
    call_log_provider.update_call.assert_any_await("call-1", transfer_success=True)
    notification.send_sms_for_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_transfer_twilio_missing_destination_sends_callback_sms(monkeypatch):
    monkeypatch.delenv("TRANSFER_TARGET_9006", raising=False)
    monkeypatch.delenv("QUEUE_TRANSFER_TARGETS", raising=False)
    svc = TransferService()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state()

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            outcome = await svc.execute_transfer(call, patient, "twilio", "CA123", notification)

    assert outcome == CallOutcome.CALLBACK_REQUESTED
    notification.send_sms_for_call.assert_awaited()


@pytest.mark.asyncio
async def test_execute_transfer_twilio_missing_sid_sends_callback_sms(monkeypatch):
    monkeypatch.setenv("TRANSFER_TARGET_9006", "sip:9006@example.test")
    svc = TransferService()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state()

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            outcome = await svc.execute_transfer(call, patient, "twilio", None, notification)

    assert outcome == CallOutcome.CALLBACK_REQUESTED
    notification.send_sms_for_call.assert_awaited()


@pytest.mark.asyncio
async def test_execute_transfer_twilio_success(monkeypatch):
    monkeypatch.setenv("TRANSFER_TARGET_9006", "sip:9006@example.test")
    svc = TransferService()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state()

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            with patch("app.services.twilio_voice_service.transfer_call_to_destination") as transfer:
                with patch("app.services.transfer_service.asyncio.to_thread", immediate_to_thread):
                    outcome = await svc.execute_transfer(call, patient, "twilio", "CA123", notification)

    assert outcome == CallOutcome.TRANSFERRED
    transfer.assert_called_once_with("CA123", "sip:9006@example.test", "+1555")


@pytest.mark.asyncio
async def test_execute_transfer_twilio_failure_sends_callback_sms(monkeypatch):
    monkeypatch.setenv("TRANSFER_TARGET_9006", "sip:9006@example.test")
    svc = TransferService()
    call = CallLog(call_id="call-1")
    patient = Patient(patient_id="p1", name="Jane", phone="+1555")
    notification = AsyncMock()
    call_log_provider = AsyncMock()
    queue_provider = MagicMock()
    queue_provider.get_state.return_value = queue_state()

    with patch("app.services.transfer_service.get_call_log_provider", return_value=call_log_provider):
        with patch("app.services.transfer_service.get_queue_provider", return_value=queue_provider):
            with patch("app.services.twilio_voice_service.transfer_call_to_destination", side_effect=RuntimeError("pbx")):
                with patch("app.services.transfer_service.asyncio.to_thread", immediate_to_thread):
                    outcome = await svc.execute_transfer(call, patient, "twilio", "CA123", notification)

    assert outcome == CallOutcome.CALLBACK_REQUESTED
    notification.send_sms_for_call.assert_awaited()
