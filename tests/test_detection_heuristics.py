"""Tests for voicemail and disconnected-number detection heuristics."""
import pytest
from app.services.transfer_service import (
    looks_like_voicemail_signal,
)
from app.services.carrier_failure_service import looks_like_disconnected_or_invalid


class TestLooksLikeVoicemailSignal:
    """Test voicemail detection from transcript text."""

    def test_leave_a_message(self):
        assert looks_like_voicemail_signal("Please leave a message after the beep") is True

    def test_at_the_tone(self):
        assert looks_like_voicemail_signal("Please record your message at the tone") is True

    def test_after_the_beep(self):
        assert looks_like_voicemail_signal("Leave your message after the beep") is True

    def test_cannot_take_call(self):
        assert looks_like_voicemail_signal("I cannot take your call right now") is True

    def test_not_available(self):
        assert looks_like_voicemail_signal("I'm not available right now") is True

    def test_im_not_available(self):
        assert looks_like_voicemail_signal("im not available, leave a message") is True

    def test_leave_your_name(self):
        assert looks_like_voicemail_signal("Please leave your name and number") is True

    def test_leave_your_number_and_name(self):
        assert looks_like_voicemail_signal("Leave your number and name") is True

    def test_voicemail_word(self):
        assert looks_like_voicemail_signal("You have reached the voicemail of...") is True

    def test_voice_mail_two_words(self):
        assert looks_like_voicemail_signal("This is the voice mail box for...") is True

    def test_normal_conversation(self):
        assert looks_like_voicemail_signal("Hello, yes this is Jane speaking") is False

    def test_empty(self):
        assert looks_like_voicemail_signal("") is False

    def test_none(self):
        assert looks_like_voicemail_signal(None) is False


class TestLooksLikeDisconnectedOrInvalid:
    """Test disconnected/invalid number keyword detection."""

    def test_disconnected(self):
        assert looks_like_disconnected_or_invalid("number disconnected") is True

    def test_not_in_service(self):
        assert looks_like_disconnected_or_invalid("the number is not in service") is True

    def test_does_not_exist(self):
        assert looks_like_disconnected_or_invalid("this number does not exist") is True

    def test_failed_to_route(self):
        assert looks_like_disconnected_or_invalid("failed to route call") is True

    def test_normal_completion(self):
        assert looks_like_disconnected_or_invalid("call completed") is False
