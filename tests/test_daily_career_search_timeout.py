from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.services import daily_career_search as service


def candidate():
    return service.Candidate(
        firm_name="Example Law",
        canonical_domain="example.com",
        source_url="https://example.com/jobs/analyst",
        employer_evidence_url="https://example.com/about",
        title="Data Analyst",
    )


@pytest.mark.asyncio
async def test_llm_skips_call_when_run_budget_is_exhausted(monkeypatch):
    gateway = AsyncMock()
    monkeypatch.setattr(service, "call_skill_json", gateway)
    monkeypatch.setattr(service, "checkpoint", AsyncMock())
    audit = {"llm_calls": 0, "usage": [], "attempt_errors": []}
    deadline = service.asyncio.get_running_loop().time() + 1

    with pytest.raises(service.CareerSearchBudgetExceeded, match="budget was exhausted"):
        await service.llm(
            {"mode": "discovery"}, "candidates", service.SearchConfig(),
            audit, "run-1", deadline=deadline,
        )

    gateway.assert_not_awaited()
    assert audit["llm_calls"] == 0


@pytest.mark.asyncio
async def test_verification_timeout_is_recorded_per_candidate(monkeypatch):
    async def timed_out(*_args, **_kwargs):
        raise service.CareerSearchBudgetExceeded(
            "verification exceeded its remaining 45-second run budget")

    checkpoint = AsyncMock()
    monkeypatch.setattr(service, "llm", timed_out)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    audit = {"errors": [], "verification_rejections": []}
    batch = [{
        "candidate_id": "0",
        "candidate": candidate(),
        "pages": [],
    }]

    results = [pair async for pair in service.verified_decisions(
        batch, service.SearchConfig(), audit, "run-1", today=date(2026, 9, 21),
    )]

    assert results == []
    assert audit["errors"] == [{
        "candidate_id": "0",
        "source_url": "https://example.com/jobs/analyst",
        "phase": "verification",
        "status": "unverified",
        "error": "verification exceeded its remaining 45-second run budget",
    }]
    assert audit["verification_rejections"][0]["phase"] == "initial_transport"
    checkpoint.assert_awaited()
