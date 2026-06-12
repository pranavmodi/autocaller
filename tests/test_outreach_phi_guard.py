import pytest

from app.services.outreach_phi_guard import (
    check_no_patient_data_in_outreach,
    deterministic_phi_findings,
    outreach_body_hash,
)


@pytest.mark.asyncio
async def test_phi_guard_blocks_seeded_phi_without_llm(monkeypatch):
    async def fail_llm(*args, **kwargs):
        raise AssertionError("deterministic PHI should not call the LLM")

    monkeypatch.setattr("app.services.outreach_phi_guard.call_skill_json", fail_llm)

    result = await check_no_patient_data_in_outreach(
        subject="Records for DOB 03/14/1982",
        body="Patient name John Smith, DOL 04/01/2026, MRN AB-12345.",
        cache={},
    )

    assert result["passed"] is False
    assert "dob_pattern" in result["detail"]
    assert result["llm_checked"] is False


@pytest.mark.asyncio
async def test_phi_guard_clean_draft_passes_with_mocked_llm(monkeypatch):
    class _Result:
        parsed = {"contains_phi": False, "reason": "general workflow outreach only"}
        model = "openclaw"

    async def mock_llm(*args, **kwargs):
        return _Result()

    monkeypatch.setattr("app.services.outreach_phi_guard.call_skill_json", mock_llm)

    result = await check_no_patient_data_in_outreach(
        subject="Records workflow idea for your team",
        body=(
            "Hi Jane,\n\n"
            "We run intake, records, and follow-up automation for Precise Imaging. "
            "Would it be useful to compare notes for your PI operations?\n\n"
            "https://getpossibleminds.com/consult"
        ),
        cache={},
    )

    assert result["passed"] is True
    assert result["llm_checked"] is True


@pytest.mark.asyncio
async def test_phi_guard_llm_error_fails_closed_but_never_caches(monkeypatch):
    calls = 0

    async def mock_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("gateway down")

    monkeypatch.setattr("app.services.outreach_phi_guard.call_skill_json", mock_llm)
    subject = "Quick question"
    body = "General operational note with no patient-specific details."
    cache = {}

    first = await check_no_patient_data_in_outreach(subject=subject, body=body, cache=cache)
    second = await check_no_patient_data_in_outreach(subject=subject, body=body, cache=cache)

    # Fails closed on each attempt...
    assert first["passed"] is False
    assert first["detail"].startswith("llm_error:")
    assert second["passed"] is False
    # ...but a transport error is retried, never cached as a verdict.
    assert calls == 2
    assert outreach_body_hash(subject, body) not in cache


def test_deterministic_phi_patterns_cover_case_shapes():
    findings = deterministic_phi_findings(
        "Case # PI-998877",
        "Date of birth: 1/2/1990. Claim number ZXCV-123456.",
    )

    assert "dob_pattern" in findings
    assert "case_number_pattern" in findings
