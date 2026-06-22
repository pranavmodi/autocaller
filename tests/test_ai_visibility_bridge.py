from __future__ import annotations

from app.services import ai_visibility_bridge as bridge
from app.services.lead_email_composer_variants import get_composer_skill_variant


def test_visibility_report_reuses_existing_by_domain(monkeypatch):
    existing = {
        "scan_id": "scan-existing",
        "meta": {
            "firm_name": "Rezvani Law Firm",
            "domain": "rezvanilawfirm.com",
            "report_url": "https://aiscan.example/r/scan-existing",
        },
    }

    def fake_json(_cli, args, *, timeout):
        assert args == ["report-for-domain", "rezvanilawfirm.com"]
        return existing

    def fail_text(*_args, **_kwargs):
        raise AssertionError("scan should not run when a report already exists")

    monkeypatch.setattr(bridge, "_run_aivis_json", fake_json)
    monkeypatch.setattr(bridge, "_run_aivis_text", fail_text)

    result = bridge.ensure_visibility_report(
        firm_name="Rezvani Law Firm",
        domain="https://www.rezvanilawfirm.com/path",
        market="Los Angeles, CA",
        aivis_cli="/fake/aivis",
    )

    assert result["status"] == "existing"
    assert result["report"]["scan_id"] == "scan-existing"


def test_visibility_report_generates_when_missing(monkeypatch):
    calls = []

    def fake_json(_cli, args, *, timeout):
        calls.append(tuple(args))
        if args and args[0] == "report-for-domain":
            raise RuntimeError("No scanned report found for domain: example.com")
        if args and args[0] == "reports":
            return {"reports": []}
        if args == ["report", "abc123abc123abc123abc123abc123ab"]:
            return {
                "scan_id": "abc123abc123abc123abc123abc123ab",
                "meta": {"firm_name": "Example Firm", "domain": "example.com"},
                "email_variants": [{"subject": "s", "body": "b"}],
            }
        raise AssertionError(args)

    def fake_text(_cli, args, *, timeout):
        calls.append(tuple(args))
        assert args[0] == "scan"
        return "Created scan: abc123abc123abc123abc123abc123ab\n"

    monkeypatch.setattr(bridge, "_run_aivis_json", fake_json)
    monkeypatch.setattr(bridge, "_run_aivis_text", fake_text)

    result = bridge.ensure_visibility_report(
        firm_name="Example Firm",
        domain="example.com",
        market="Los Angeles, CA",
        dry_run=True,
        aivis_cli="/fake/aivis",
    )

    assert result["status"] == "generated"
    assert result["scan_id"] == "abc123abc123abc123abc123abc123ab"
    assert any(call[0] == "scan" and "--dry-run" in call for call in calls)


def test_compact_visibility_report_keeps_email_package():
    compact = bridge.compact_visibility_report(
        {
            "scan_id": "scan-1",
            "meta": {
                "scan_id": "scan-1",
                "firm_name": "Example Firm",
                "domain": "example.com",
                "market": "Los Angeles, CA",
                "practice": "auto accidents",
                "report_url": "https://aiscan.example/r/scan-1",
            },
            "email_variants": [
                {"name": "canonical", "subject": "Subject", "body": "Body", "merge_fields": {"x": 1}},
            ],
            "ranked_email_facts": [{"type": "absence"}],
            "estimate": {"email_case_band": {"low": {"display": "1"}, "high": {"display": "2"}}},
            "one_pager": {"measured_inputs": [{"display": "5"}], "modeled_inputs": [{"display": "1-2"}]},
        }
    )

    assert compact["scan_id"] == "scan-1"
    assert compact["report_url"] == "https://aiscan.example/r/scan-1"
    assert compact["email_variants"][0]["subject"] == "Subject"
    assert compact["estimate"]["email_case_band"]["low"]["display"] == "1"


def test_visibility_report_status_by_domain(monkeypatch):
    def fake_json(_cli, args, *, timeout):
        assert args == [
            "trace-status-for-domain",
            "example.com",
            "--stale-after-seconds",
            "120",
        ]
        assert timeout == 60
        return {
            "scan_id": "scan-1",
            "phase": "running",
            "is_stuck": False,
            "progress": {"queries_done": 2, "queries_total": 13},
        }

    monkeypatch.setattr(bridge, "_run_aivis_json", fake_json)

    result = bridge.visibility_report_status(
        domain="https://www.example.com/path",
        stale_after_seconds=120,
        aivis_cli="/fake/aivis",
    )

    assert result["phase"] == "running"
    assert result["progress"]["queries_done"] == 2


def test_ai_visibility_report_variant_is_forced_only_active():
    variant = get_composer_skill_variant("ai-visibility-report")

    assert variant is not None
    assert variant.active
    assert variant.allocation_weight == 0
