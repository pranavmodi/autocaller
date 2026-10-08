from unittest.mock import AsyncMock

import pytest

from app.services import job_search_sources as sources


def test_remote_talent_networks_are_in_the_always_on_catalog():
    expected = {
        "turing", "andela", "arc", "braintrust", "g2i", "proxify",
        "gunio", "ateam", "contra", "crossover",
    }

    assert expected <= set(sources.ALL_SOURCE_IDS)
    assert all(sources.SOURCES_BY_ID[source_id].enabled_by_default for source_id in expected)
    assert len(sources.ALL_SOURCE_IDS) == len(set(sources.ALL_SOURCE_IDS))
    assert len(sources.source_urls(sources.ALL_SOURCE_IDS)) == len(sources.ALL_SOURCE_IDS)


@pytest.mark.asyncio
async def test_quick_save_portals_are_exposed_as_public_search_sources(monkeypatch):
    monkeypatch.setattr(sources, "list_quick_job_links", AsyncMock(return_value=[{
        "id": 41,
        "company_name": "VC JOB BOARD · Example",
        "job_url": "https://jobs.example.com/jobs",
    }]))

    payload = await sources.quick_save_catalog(True)

    assert payload["total_count"] == payload["enabled_count"] == 1
    assert payload["items"][0] == {
        "id": "quick_save:41",
        "name": "Example",
        "url": "https://jobs.example.com/jobs",
        "method": "web_search",
        "enabled_by_default": True,
        "note": "Saved in Quick Save; search public pages without signing in.",
        "aliases": [],
        "available": True,
        "enabled": True,
        "origin": "quick_save",
    }


@pytest.mark.asyncio
async def test_resolved_urls_include_all_quick_save_portals_without_duplicates(monkeypatch):
    monkeypatch.setattr(sources, "quick_save_catalog", AsyncMock(return_value={
        "items": [
            {"url": "https://remotive.com/api/remote-jobs/"},
            {"url": "https://jobs.example.com/jobs"},
        ],
    }))

    urls = await sources.resolved_source_urls(["remotive"], include_quick_save=True)

    assert urls[:len(sources.ALL_SOURCE_IDS)] == sources.source_urls(sources.ALL_SOURCE_IDS)
    assert urls[-1] == "https://jobs.example.com/jobs"
    assert urls.count("https://remotive.com/api/remote-jobs") == 1
