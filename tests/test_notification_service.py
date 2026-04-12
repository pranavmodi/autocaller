"""Tests for CallNotificationService."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.models import CallLog, CallOutcome, Patient, Language
from app.services.notification_service import CallNotificationService


@pytest.fixture
def notification_service():
    svc = CallNotificationService()
    svc.on_status_update = AsyncMock()
    return svc


@pytest.fixture
def call():
    return CallLog(
        call_id="test-call-001",
        patient_id="PAT-001",
        patient_name="Jane Doe",
        phone="+15551234567",
    )


@pytest.fixture
def patient():
    return Patient(
        patient_id="PAT-001",
        name="Jane Doe",
        phone="+15551234567",
        language=Language.ENGLISH,
    )


class TestSmsIdempotency:
    """SMS should not be sent twice for the same call."""

    @pytest.mark.asyncio
    async def test_second_send_is_skipped(self, notification_service, call, patient):
        """Once sms_sent is True, subsequent sends are no-ops."""
        call.sms_sent = True
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_clp.return_value = AsyncMock()
            result = await notification_service.send_sms_for_call(call, patient, reason="test")
        assert result is True

    @pytest.mark.asyncio
    async def test_in_memory_guard(self, notification_service, call, patient):
        """After first send, call_id is added to _sms_sent_call_ids."""
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_provider = AsyncMock()
            mock_provider.get_call.return_value = None
            mock_clp.return_value = mock_provider

            # First send in web mode (simulated)
            await notification_service.send_sms_for_call(call, patient, call_mode="web", reason="test")
            assert call.call_id in notification_service._sms_sent_call_ids

            # Second send should be skipped
            result = await notification_service.send_sms_for_call(call, patient, call_mode="web", reason="test2")
            assert result is True

    @pytest.mark.asyncio
    async def test_persisted_check(self, notification_service, call, patient):
        """If DB shows sms_sent=True, skip."""
        db_call = MagicMock()
        db_call.sms_sent = True
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_provider = AsyncMock()
            mock_provider.get_call.return_value = db_call
            mock_clp.return_value = mock_provider

            result = await notification_service.send_sms_for_call(call, patient, reason="test")
        assert result is True


class TestSmsOptOutBlocking:
    """SMS should be blocked for opted-out numbers."""

    @pytest.mark.asyncio
    async def test_opted_out_blocks_send(self, notification_service, call, patient):
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_provider = AsyncMock()
            mock_provider.get_call.return_value = None
            mock_clp.return_value = mock_provider

            with patch("app.services.notification_service.is_number_opted_out", return_value=True):
                result = await notification_service.send_sms_for_call(call, patient, reason="test")
        assert result is False


class TestEmailDispatch:
    """Email dispatch for wrong_number and disconnected outcomes."""

    @pytest.mark.asyncio
    async def test_wrong_number_email(self, notification_service, call):
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_clp.return_value = AsyncMock()
            with patch("app.services.notification_service.send_wrong_number_email", return_value="msg-1"):
                await notification_service.maybe_send_issue_email(call, CallOutcome.WRONG_NUMBER)
        assert call.call_id in notification_service._email_sent_call_ids

    @pytest.mark.asyncio
    async def test_disconnected_email(self, notification_service, call):
        """Carrier failure (FAILED + disconnected error text) should trigger email."""
        call.error_message = "Number is disconnected"
        call.error_code = "32005"
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_clp.return_value = AsyncMock()
            with patch("app.services.notification_service.send_disconnected_number_email", return_value="msg-2"):
                await notification_service.maybe_send_issue_email(call, CallOutcome.FAILED)
        assert call.call_id in notification_service._email_sent_call_ids

    @pytest.mark.asyncio
    async def test_idempotent_email(self, notification_service, call):
        """Second email send for same call_id should be skipped."""
        notification_service._email_sent_call_ids.add(call.call_id)
        with patch("app.services.notification_service.send_wrong_number_email") as mock_email:
            await notification_service.maybe_send_issue_email(call, CallOutcome.WRONG_NUMBER)
        mock_email.assert_not_called()


class TestBuildSmsMessage:
    """Test SMS message building."""

    def test_appointment_reminder(self):
        from app.services.twilio_sms_service import build_sms_message
        msg = build_sms_message("appointment_reminder")
        assert "Precise Imaging" in msg
        assert "reminder" in msg.lower()

    def test_callback_info(self):
        from app.services.twilio_sms_service import build_sms_message
        msg = build_sms_message("callback_info")
        assert "Precise Imaging" in msg
        assert "imaging order" in msg.lower()

    def test_unknown_type_defaults(self):
        from app.services.twilio_sms_service import build_sms_message
        msg = build_sms_message("unknown_type")
        assert "Precise Imaging" in msg


class TestNoPatientPhone:
    """SMS should be skipped if patient has no phone."""

    @pytest.mark.asyncio
    async def test_no_patient(self, notification_service, call):
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_clp.return_value = AsyncMock()
            result = await notification_service.send_sms_for_call(call, None, reason="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_phone(self, notification_service, call):
        patient = Patient(patient_id="PAT-X", name="No Phone", phone="")
        with patch("app.services.notification_service.get_call_log_provider") as mock_clp:
            mock_clp.return_value = AsyncMock()
            result = await notification_service.send_sms_for_call(call, patient, reason="test")
        assert result is False
