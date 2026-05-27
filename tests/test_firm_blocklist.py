"""Tests for firm blocklist matching."""
from app.services.firm_blocklist import filter_blocked, is_blocked


def test_builtin_pif_id_is_blocked(monkeypatch):
    monkeypatch.delenv("CALL_FIRM_BLOCKLIST", raising=False)

    assert is_blocked("ca3dae0e-f252-489a-b093-9032eae6bdeb", "Any Name")


def test_builtin_name_substring_is_blocked(monkeypatch):
    monkeypatch.delenv("CALL_FIRM_BLOCKLIST", raising=False)

    assert is_blocked(None, "The Precise Imaging Group")


def test_env_blocklist_supports_uuid_and_name_tokens(monkeypatch):
    blocked_uuid = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setenv("CALL_FIRM_BLOCKLIST", f"{blocked_uuid}, Do Not Call LLP")

    assert is_blocked(blocked_uuid, "Other Firm")
    assert is_blocked(None, "Regional Do Not Call LLP")
    assert not is_blocked("pif-2", "Allowed Firm")


def test_filter_blocked_removes_matching_rows(monkeypatch):
    monkeypatch.setenv("CALL_FIRM_BLOCKLIST", "Blocked Firm")
    rows = [
        {"pif_id": "1", "firm_name": "Allowed Firm"},
        {"pif_id": "2", "firm_name": "Blocked Firm PLLC"},
        {"pif_id": "3", "firm_name": "Precise MRI"},
    ]

    assert filter_blocked(rows) == [{"pif_id": "1", "firm_name": "Allowed Firm"}]
