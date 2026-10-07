from unittest.mock import AsyncMock

import pytest

from app.services import job_search_sources as sources


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
        "name": "VC JOB BOARD · Example",
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
            {"url": "https://remotive.com/feed/"},
            {"url": "https://jobs.example.com/jobs"},
        ],
    }))

    urls = await sources.resolved_source_urls(["remotive"], include_quick_save=True)

    assert urls == ["https://remotive.com/feed", "https://jobs.example.com/jobs"]
