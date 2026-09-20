"""Focused contracts for operator-triggered Job Agent discovery."""
from datetime import date

import pytest

from app.services import daily_career_search as service


def candidate():
    return service.Candidate(
        firm_name="Example Legal Tech",
        canonical_domain="example.com",
        source_url="https://example.com/jobs/1",
        employer_evidence_url="https://example.com/about",
        title="AI Agent Engineer",
    )


def pages():
    return [
        {"requested_url": "https://example.com/about", "content": "Legal technology company"},
        {"requested_url": "https://example.com/jobs/1", "content": "Build AI agents. Apply for Engineer."},
    ]


def profile():
    return service.SearchProfile(
        target_roles="AI agent engineering",
        preferred_industries="Legal technology",
        location_preferences="Remote from Colombia",
    )


def test_configured_profile_accepts_legal_tech_without_weakening_legacy_seed_validation():
    value = service.Decision(
        candidate_id="0", status="active", reason="Primary sources",
        direct_pi_employer=False, legal_domain_employer=True, legal_domain_kind="legal_tech",
        target_role_match=True, matched_target_role="AI agent engineering",
        technology_role=True, title="AI Agent Engineer",
        employer_evidence={"source_url": "https://example.com/about", "text": "Legal technology company"},
        role_evidence={"source_url": "https://example.com/jobs/1", "text": "Build AI agents"},
        status_evidence={"source_url": "https://example.com/jobs/1", "text": "Apply for Engineer"},
    )
    service.validate_decision(value, pages(), today=date(2026, 9, 20), search_profile=profile())
    with pytest.raises(ValueError, match="direct PI"):
        service.validate_decision(value, pages(), today=date(2026, 9, 20))


@pytest.mark.asyncio
async def test_manual_search_skips_an_exact_job_found_in_an_earlier_run(monkeypatch):
    raw = candidate().model_dump(mode="json")
    calls = []

    async def llm(*args, **kwargs):
        calls.append(args[0])
        return {"candidates": [raw]}

    async def known():
        return {service.source_identity(raw["source_url"])}

    async def checkpoint(*args):
        pass

    async def no_fetch(*args, **kwargs):
        pytest.fail("a known source must be skipped before live verification")

    monkeypatch.setattr(service, "llm", llm)
    monkeypatch.setattr(service, "known_source_identities", known)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(service, "fetch_page", no_fetch)
    audit = {
        "new_jobs": 0, "verified": 0, "closed": 0, "rejected": 0,
        "candidates": 0, "duplicates_skipped": 0, "llm_calls": 0,
        "errors": [], "attempt_errors": [], "stored": [], "decisions": [], "usage": [],
    }
    await service.execute("manual", service.SearchConfig(), seed_only=False, audit=audit,
                          search_profile=profile())
    assert len(calls) == 1
    assert audit["candidates"] == 0
    assert audit["duplicates_skipped"] == 1
