"""Tests for TransferService routing logic."""
import os
import pytest
from unittest.mock import patch, MagicMock

from app.services.transfer_service import (
    normalize_language_code,
    resolve_transfer_queue_for_language,
    resolve_transfer_destination_for_queue,
    find_queue_by_name,
)
from app.models import Language


class TestNormalizeLanguageCode:
    def test_none(self):
        assert normalize_language_code(None) == "en"

    def test_empty_string(self):
        assert normalize_language_code("") == "en"

    def test_english_enum(self):
        assert normalize_language_code(Language.ENGLISH) == "en"

    def test_spanish_enum(self):
        assert normalize_language_code(Language.SPANISH) == "es"

    def test_chinese_enum(self):
        assert normalize_language_code(Language.CHINESE) == "zh"

    def test_string_en(self):
        assert normalize_language_code("en") == "en"

    def test_string_uppercase(self):
        assert normalize_language_code("ES") == "es"

    def test_whitespace_padded(self):
        assert normalize_language_code("  zh  ") == "zh"


class TestResolveTransferQueueForLanguage:
    def test_english(self):
        assert resolve_transfer_queue_for_language(Language.ENGLISH) == "9006"

    def test_spanish(self):
        assert resolve_transfer_queue_for_language(Language.SPANISH) == "9009"

    def test_chinese(self):
        assert resolve_transfer_queue_for_language(Language.CHINESE) == "9012"

    def test_unknown_language(self):
        assert resolve_transfer_queue_for_language("fr") == "9006"

    def test_none_defaults_to_en(self):
        assert resolve_transfer_queue_for_language(None) == "9006"

    def test_env_override(self):
        with patch.dict(os.environ, {"LANGUAGE_QUEUE_MAP": '{"fr": "9099"}'}):
            assert resolve_transfer_queue_for_language("fr") == "9099"

    def test_env_override_replaces_default(self):
        with patch.dict(os.environ, {"LANGUAGE_QUEUE_MAP": '{"es": "9099"}'}):
            assert resolve_transfer_queue_for_language(Language.SPANISH) == "9099"


class TestResolveTransferDestinationForQueue:
    def test_env_var_override(self):
        with patch.dict(os.environ, {"TRANSFER_TARGET_9006": "sip:9006@pbx.local", "QUEUE_TRANSFER_TARGETS": ""}):
            result = resolve_transfer_destination_for_queue("9006")
            assert result == "sip:9006@pbx.local"

    def test_json_env_override(self):
        with patch.dict(os.environ, {"QUEUE_TRANSFER_TARGETS": '{"9006": "sip:9006@pbx.radflow360.com;transport=TLS"}'}):
            result = resolve_transfer_destination_for_queue("9006")
            assert result == "sip:9006@pbx.radflow360.com;transport=TLS"

    def test_no_config_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            # Clear relevant env vars
            for k in list(os.environ):
                if k.startswith("TRANSFER_TARGET_") or k == "QUEUE_TRANSFER_TARGETS":
                    del os.environ[k]
            result = resolve_transfer_destination_for_queue("9006")
            assert result is None

    def test_json_takes_precedence(self):
        with patch.dict(os.environ, {
            "QUEUE_TRANSFER_TARGETS": '{"9006": "from_json"}',
            "TRANSFER_TARGET_9006": "from_env",
        }):
            result = resolve_transfer_destination_for_queue("9006")
            assert result == "from_json"


class TestFindQueueByName:
    def test_found(self):
        q = MagicMock()
        q.Queue = "9006"
        state = MagicMock()
        state.queues = [q]
        assert find_queue_by_name(state, "9006") == q

    def test_case_insensitive(self):
        q = MagicMock()
        q.Queue = "Scheduling_EN"
        state = MagicMock()
        state.queues = [q]
        assert find_queue_by_name(state, "scheduling_en") == q

    def test_not_found(self):
        q = MagicMock()
        q.Queue = "9006"
        state = MagicMock()
        state.queues = [q]
        assert find_queue_by_name(state, "9009") is None

    def test_empty_queues(self):
        state = MagicMock()
        state.queues = []
        assert find_queue_by_name(state, "9006") is None
