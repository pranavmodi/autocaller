"""Tests for carrier failure detection logic."""
import pytest
from app.services.carrier_failure_service import (
    parse_int_or_none,
    map_twilio_failure_reason,
    is_carrier_failure,
    is_known_invalid_number_code,
    is_known_invalid_number_sip_code,
    should_flag_invalid_number,
    looks_like_disconnected_or_invalid,
)


class TestParseIntOrNone:
    def test_valid_int(self):
        assert parse_int_or_none("32009") == 32009

    def test_padded_whitespace(self):
        assert parse_int_or_none("  404  ") == 404

    def test_empty_string(self):
        assert parse_int_or_none("") is None

    def test_non_numeric(self):
        assert parse_int_or_none("abc") is None

    def test_none_value(self):
        assert parse_int_or_none(None) is None


class TestMapTwilioFailureReason:
    def test_known_error_code_32009(self):
        result = map_twilio_failure_reason("failed", 32009, None)
        assert "invalid number" in result
        assert "error_code=32009" in result

    def test_known_error_code_32005(self):
        result = map_twilio_failure_reason("failed", 32005, None)
        assert "disconnected/unreachable" in result

    def test_generic_carrier_error(self):
        result = map_twilio_failure_reason("failed", 32100, None)
        assert "carrier failure" in result

    def test_no_error_code(self):
        result = map_twilio_failure_reason("failed", None, None)
        assert "call failed" in result
        assert "error_code" not in result

    def test_with_sip_code(self):
        result = map_twilio_failure_reason("failed", 32009, 404)
        assert "sip_response_code=404" in result

    def test_non_carrier_error_code(self):
        result = map_twilio_failure_reason("failed", 12345, None)
        assert "call failed" in result


class TestIsCarrierFailure:
    def test_failed_status(self):
        assert is_carrier_failure("failed", None, None) is True

    def test_busy_with_error_code(self):
        assert is_carrier_failure("busy", 32009, None) is True

    def test_no_answer_with_sip_code(self):
        assert is_carrier_failure("no-answer", None, 404) is True

    def test_busy_without_codes(self):
        assert is_carrier_failure("busy", None, None) is False

    def test_completed_status(self):
        assert is_carrier_failure("completed", None, None) is False

    def test_empty_status(self):
        assert is_carrier_failure("", None, None) is False

    def test_case_insensitive(self):
        assert is_carrier_failure("FAILED", None, None) is True


class TestIsKnownInvalidNumberCode:
    def test_32005(self):
        assert is_known_invalid_number_code(32005) is True

    def test_32009(self):
        assert is_known_invalid_number_code(32009) is True

    def test_other_code(self):
        assert is_known_invalid_number_code(32100) is False

    def test_none(self):
        assert is_known_invalid_number_code(None) is False


class TestIsKnownInvalidNumberSipCode:
    def test_404(self):
        assert is_known_invalid_number_sip_code(404) is True

    def test_410(self):
        assert is_known_invalid_number_sip_code(410) is True

    def test_484(self):
        assert is_known_invalid_number_sip_code(484) is True

    def test_604(self):
        assert is_known_invalid_number_sip_code(604) is True

    def test_200(self):
        assert is_known_invalid_number_sip_code(200) is False

    def test_none(self):
        assert is_known_invalid_number_sip_code(None) is False


class TestShouldFlagInvalidNumber:
    def test_known_error_code(self):
        assert should_flag_invalid_number(32009, None, "") is True

    def test_known_sip_code(self):
        assert should_flag_invalid_number(None, 404, "") is True

    def test_text_disconnected(self):
        assert should_flag_invalid_number(None, None, "Number is disconnected") is True

    def test_text_invalid(self):
        assert should_flag_invalid_number(None, None, "Invalid number format") is True

    def test_no_match(self):
        assert should_flag_invalid_number(None, None, "Call completed normally") is False


class TestLooksLikeDisconnectedOrInvalid:
    def test_disconnected(self):
        assert looks_like_disconnected_or_invalid("Number is disconnected") is True

    def test_invalid(self):
        assert looks_like_disconnected_or_invalid("invalid number") is True

    def test_not_in_service(self):
        assert looks_like_disconnected_or_invalid("the number is not in service") is True

    def test_unreachable(self):
        assert looks_like_disconnected_or_invalid("destination unreachable") is True

    def test_cannot_be_completed(self):
        assert looks_like_disconnected_or_invalid("call cannot be completed as dialed") is True

    def test_normal_text(self):
        assert looks_like_disconnected_or_invalid("call completed successfully") is False

    def test_empty(self):
        assert looks_like_disconnected_or_invalid("") is False

    def test_none(self):
        assert looks_like_disconnected_or_invalid(None) is False
