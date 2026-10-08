from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import job_search_relevance as relevance
from app.services import job_search_source_adapters as adapters


def target(provider="remoteok", **kwargs):
    return adapters.SourceTarget(
        source_key=f"catalog:{provider}", source_name=provider.title(),
        source_url=f"https://example.com/{provider}", adapter_type="structured",
        provider=provider, **kwargs,
    )


def profile(**kwargs):
    values = dict(target_roles="AI agents", preferred_industries="Legal technology",
                  industry_mode="preferred", location_preferences="Remote Colombia",
                  location_mode="required", employment_type="any", employment_mode="preferred",
                  exclusions="Attorney roles", additional_preferences="Small teams",
                  posted_within_days=14)
    values.update(kwargs)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_remoteok_adapter_preserves_recent_transport_facts(monkeypatch):
    recent = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    monkeypatch.setattr(adapters, "_fetch_json", AsyncMock(return_value=[
        {"legal": "metadata"},
        {"id": "1", "position": "Agent Engineer", "company": "Acme", "location": "Worldwide",
         "url": "https://remoteok.com/remote-jobs/1", "description": "Build agents", "date": recent},
        {"id": "2", "position": "Old Engineer", "company": "Old", "location": "Worldwide",
         "url": "https://remoteok.com/remote-jobs/2", "description": "Old", "date": old},
    ]))
    result = await adapters._collect_remoteok(target(), datetime.now(timezone.utc) - timedelta(days=14), profile())
    assert result.pages_checked == 1
    assert [item.native_id for item in result.listings] == ["1"]
    assert result.listings[0].title == "Agent Engineer"


@pytest.mark.asyncio
async def test_lever_adapter_follows_pagination_until_exhausted(monkeypatch):
    rows = [{"id": str(index), "text": f"Role {index}", "hostedUrl": f"https://jobs.lever.co/acme/{index}",
             "descriptionPlain": "Build systems", "categories": {"location": "Remote"}}
            for index in range(101)]
    fetch = AsyncMock(side_effect=[rows[:100], rows[100:]])
    monkeypatch.setattr(adapters, "_fetch_json", fetch)
    result = await adapters._collect_lever(target("lever", board_key="acme"),
                                            datetime.now(timezone.utc) - timedelta(days=14), profile())
    assert result.pages_checked == 2
    assert len(result.listings) == 101
    assert "skip=100" in fetch.await_args_list[1].args[0]


@pytest.mark.asyncio
async def test_old_job_still_on_ats_board_is_not_marked_closed(monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp() * 1000
    monkeypatch.setattr(adapters, "_fetch_json", AsyncMock(return_value=[{
        "id": "old-open", "text": "Older open role",
        "hostedUrl": "https://jobs.lever.co/acme/old-open",
        "descriptionPlain": "Still open", "createdAt": old,
    }]))
    board = target("lever", board_key="acme", cursor={"open_jobs": {
        "old-open": {"url": "https://jobs.lever.co/acme/old-open", "sha256": "previous"},
    }})
    result = await adapters._collect_lever(
        board, datetime.now(timezone.utc) - timedelta(days=14), profile(),
    )
    assert result.listings == []
    assert "old-open" in result.cursor["open_jobs"]
    assert result.details["closed_native_ids"] == []


def test_ats_board_reference_is_mechanical():
    assert adapters._board_reference("https://jobs.ashbyhq.com/oyster/00000000-0000-0000-0000-000000000000") == (
        "ashby", "oyster", "https://jobs.ashbyhq.com/oyster")
    assert adapters._board_reference("https://jobs.lever.co/acme/role-id") == (
        "lever", "acme", "https://jobs.lever.co/acme")
    assert adapters._board_reference("https://example.com/jobs/role") is None


def listing(identity: str, title: str) -> adapters.SourceListing:
    return adapters.SourceListing(source_key="catalog:remoteok", provider="remoteok", native_id=identity,
        job_url=f"https://example.com/jobs/{identity}", title=title, employer_name="Acme",
        description="Build production systems", raw_fingerprint=identity * 8)


def choice(selected, match, possible, unrelated):
    return {"type": "choice", "choice": selected, "confidence": max(match, possible, unrelated),
            "probabilities": {"match": match, "possible": possible, "unrelated": unrelated}}


def test_jev_relevance_preserves_probabilities_and_input_hash():
    rows = [listing("a", "Agent Engineer")]
    parsed = relevance._parse({"model": "jev-test", "usage": {"input_tokens": 10},
        "answers": {"job_0": choice("match", .8, .15, .05)}}, rows, profile())
    judgment = parsed[0].relevance
    assert judgment["provider"] == "typesafe" and judgment["model"] == "jev-test"
    assert judgment["probabilities"] == {"match": .8, "possible": .15, "unrelated": .05}
    assert len(judgment["input_sha256"]) == 64


@pytest.mark.asyncio
async def test_relevance_ranking_keeps_possible_items_for_research(monkeypatch):
    rows = [listing("a", "Strong"), listing("b", "Unclear"), listing("c", "Unrelated")]
    async def classify(batch, current_profile):
        answers = {
            "job_0": choice("match", .8, .15, .05),
            "job_1": choice("possible", .25, .55, .2),
            "job_2": choice("unrelated", .05, .1, .85),
        }
        return relevance._parse({"model": "jev-test", "answers": answers}, batch, current_profile)
    monkeypatch.setattr(relevance, "_classify_batch", classify)
    selected, metadata = await relevance.rank_source_listings(rows, profile(), max_selected=5)
    assert [item.native_id for item in selected] == ["a", "b"]
    assert metadata == {"state": "completed", "version": relevance.CLASSIFICATION_VERSION,
                        "model": "jev-test", "checked": 3, "eligible": 2, "selected": 2,
                        "failed_batches": 0, "errors": [], "threshold": .35}


@pytest.mark.asyncio
async def test_relevance_failure_does_not_fall_back_to_string_matching(monkeypatch):
    monkeypatch.setattr(relevance, "_classify_batch", AsyncMock(side_effect=RuntimeError("offline")))
    selected, metadata = await relevance.rank_source_listings([listing("a", "AI Agent Engineer")],
                                                               profile(), max_selected=5)
    assert selected == []
    assert metadata["state"] == "error" and "offline" in metadata["error"]


@pytest.mark.asyncio
async def test_relevance_keeps_successful_batches_and_reports_partial_failure(monkeypatch):
    rows = [listing("a", "Strong"), listing("b", "Unclear")]
    monkeypatch.setenv("JOB_SEARCH_RELEVANCE_BATCH_SIZE", "1")

    async def classify(batch, current_profile):
        if batch[0].native_id == "b":
            raise RuntimeError("second batch offline")
        return relevance._parse({
            "model": "jev-test",
            "answers": {"job_0": choice("match", .8, .15, .05)},
        }, batch, current_profile)

    monkeypatch.setattr(relevance, "_classify_batch", classify)
    selected, metadata = await relevance.rank_source_listings(rows, profile(), max_selected=5)
    assert [item.native_id for item in selected] == ["a"]
    assert metadata["state"] == "partial"
    assert metadata["failed_batches"] == 1
    assert metadata["errors"] == ["second batch offline"]
