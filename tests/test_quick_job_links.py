import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import quick_job_links as quick_job_links_api


def test_quick_job_link_request_requires_public_http_url():
    with pytest.raises(ValidationError):
        quick_job_links_api.QuickJobLinkCreateRequest(
            company_name="Acme Legal",
            job_url="not-a-url",
        )


def test_post_quick_job_link_serializes_validated_url(monkeypatch):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return {"id": 7, **kwargs}

    monkeypatch.setattr(quick_job_links_api, "create_quick_job_link", create)
    result = asyncio.run(quick_job_links_api.post_quick_job_link(
        quick_job_links_api.QuickJobLinkCreateRequest(
            company_name="Acme Legal",
            job_url="https://jobs.example.com/roles/123",
        )
    ))

    assert result["link"]["id"] == 7
    assert captured == {
        "company_name": "Acme Legal",
        "job_url": "https://jobs.example.com/roles/123",
        "link_type": "job",
        "actor": "operator",
    }


def test_post_quick_job_portal_preserves_type(monkeypatch):
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return {"id": 8, **kwargs}

    monkeypatch.setattr(quick_job_links_api, "create_quick_job_link", create)
    asyncio.run(quick_job_links_api.post_quick_job_link(
        quick_job_links_api.QuickJobLinkCreateRequest(
            company_name="Acme Careers",
            job_url="https://jobs.example.com/",
            link_type="portal",
        )
    ))

    assert captured["link_type"] == "portal"


def test_list_quick_job_links_forwards_type_filter(monkeypatch):
    captured = {}

    async def list_links(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(quick_job_links_api, "list_quick_job_links", list_links)
    result = asyncio.run(quick_job_links_api.get_quick_job_links(link_type="portal", limit=25))

    assert result == {"links": [], "count": 0}
    assert captured == {"link_type": "portal", "limit": 25}


def test_post_quick_job_link_reports_duplicate(monkeypatch):
    async def create(**_kwargs):
        raise ValueError("job_link_already_saved")

    monkeypatch.setattr(quick_job_links_api, "create_quick_job_link", create)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(quick_job_links_api.post_quick_job_link(
            quick_job_links_api.QuickJobLinkCreateRequest(
                company_name="Acme Legal",
                job_url="https://jobs.example.com/roles/123",
            )
        ))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "job_link_already_saved"


def test_delete_quick_job_link_reports_missing_row(monkeypatch):
    async def delete(_link_id):
        return False

    monkeypatch.setattr(quick_job_links_api, "delete_quick_job_link", delete)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(quick_job_links_api.remove_quick_job_link(404))

    assert exc_info.value.status_code == 404
