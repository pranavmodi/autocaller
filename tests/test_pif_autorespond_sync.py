from datetime import timezone

from app.services.pif_autorespond_sync import _parse_dt, _session_cookie


def test_session_cookie_has_expected_signed_shape():
    parts = _session_cookie().split(":")

    assert parts[:2] == ["admin", "v2"]
    assert len(parts) == 4
    assert len(parts[3]) == 64


def test_parse_dt_treats_naive_remote_timestamp_as_utc():
    parsed = _parse_dt("2026-08-20T05:45:45.302415")

    assert parsed.tzinfo == timezone.utc
