"""Tests for Twilio SMS helper behavior that does not hit Twilio."""
from app.services import twilio_sms_service as sms


def test_normalize_phone_number_keeps_digits_and_plus():
    assert sms.normalize_phone_number(" +1 (555) 123-4567 ") == "+15551234567"


def test_get_opted_out_numbers_from_env(monkeypatch):
    monkeypatch.setenv("SMS_OPTOUT_NUMBERS", " +1 (555) 123-4567, 555.000.1111 ")

    assert sms.get_opted_out_numbers() == {"+15551234567", "5550001111"}
    assert sms.is_number_opted_out("+1 555 123 4567")
    assert not sms.is_number_opted_out("+1 555 999 9999")


def test_callback_number_precedence(monkeypatch):
    monkeypatch.setenv("SMS_CALLBACK_NUMBER", "+10000000001")
    monkeypatch.setenv("TELNYX_FROM_NUMBER", "+10000000002")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+10000000003")

    assert sms.get_callback_number() == "+10000000001"

    monkeypatch.delenv("SMS_CALLBACK_NUMBER")
    assert sms.get_callback_number() == "+10000000002"


def test_build_sms_message_uses_context_and_booking_link(monkeypatch):
    monkeypatch.setenv("SALES_REP_NAME", "Alex")
    monkeypatch.setenv("SALES_REP_COMPANY", "Possible Minds")
    monkeypatch.setenv("CALCOM_PUBLIC_BOOKING_URL", "https://cal.example/demo")
    monkeypatch.setenv("SMS_CALLBACK_NUMBER", "+15550001111")

    msg = sms.build_sms_message("callback_info", lead_first_name="Jordan")

    assert msg.startswith("Hi Jordan,")
    assert "Possible Minds" in msg
    assert "https://cal.example/demo" in msg
    assert "+15550001111" in msg


def test_build_demo_confirmation_includes_meeting_url(monkeypatch):
    monkeypatch.setenv("SALES_REP_NAME", "Alex")
    monkeypatch.setenv("SALES_REP_COMPANY", "Possible Minds")

    msg = sms.build_sms_message(
        "demo_confirmation",
        demo_meeting_url="https://meet.example/abc",
    )

    assert "thanks for booking" in msg
    assert "https://meet.example/abc" in msg


def test_twilio_opt_out_error_detection():
    class TwilioLikeError(Exception):
        code = sms.TWILIO_OPTOUT_ERROR_CODE

    assert sms.is_twilio_opt_out_error(TwilioLikeError("blocked"))
    assert sms.is_twilio_opt_out_error(Exception("Recipient has opted out with STOP 21610"))
    assert not sms.is_twilio_opt_out_error(Exception("temporary carrier failure"))
