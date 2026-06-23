from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import visibility_links as visibility_api
from app.api.visibility_links import router as visibility_router
from app.db.models import AuditLinkClickRow, VisibilityLinkRow
from app.services import visibility_links


class _VisibilityStore:
    def __init__(self):
        self.rows = {}


class _VisibilitySession:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def add(self, row):
        self.store.rows[row.code] = row

    async def get(self, _model, key):
        return self.store.rows.get(key)

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.mark.asyncio
async def test_build_short_visibility_link_stores_and_resolves(monkeypatch):
    store = _VisibilityStore()
    monkeypatch.setenv("VISIBILITY_LINK_BASE_URL", "https://possible.example")
    monkeypatch.setenv("OUTREACH_PUBLIC_BASE_URL", "https://fallback.example")
    monkeypatch.setattr(visibility_links, "AsyncSessionLocal", lambda: _VisibilitySession(store))

    contact = SimpleNamespace(id="contact-1", pif_id="pif-1")
    url = await visibility_links.build_short_visibility_link(
        contact,
        scan_id="scan-123",
        batch_item_id="item-1",
        source="visibility_report_email",
    )

    parsed = urlparse(url)
    code = parsed.path.rsplit("/", 1)[-1]
    assert parsed.netloc == "possible.example"
    assert parsed.path == f"/v/{code}"
    assert isinstance(store.rows[code], VisibilityLinkRow)
    assert store.rows[code].contact_id == "contact-1"
    assert store.rows[code].scan_id == "scan-123"

    resolved = await visibility_links.resolve_visibility_code(code)
    assert resolved == {
        "contact_id": "contact-1",
        "batch_item_id": "item-1",
        "pif_id": "pif-1",
        "scan_id": "scan-123",
        "source": "visibility_report_email",
        "link_code": code,
    }


class _ClickSession:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        return None


def test_visibility_redirect_records_click_and_observation(monkeypatch):
    click_rows = []
    observations = []
    monkeypatch.setenv("AIVIS_REPORT_BASE_URL", "https://visibility.example")

    async def fake_resolve(code):
        assert code == "abc123"
        return {
            "contact_id": "contact-1",
            "batch_item_id": "item-1",
            "pif_id": "pif-1",
            "scan_id": "scan-123",
            "source": "visibility_report_email",
            "link_code": code,
        }

    async def fake_record_observation(**kwargs):
        observations.append(kwargs)
        return {"id": "obs-1"}

    monkeypatch.setattr(visibility_api, "resolve_visibility_code", fake_resolve)
    monkeypatch.setattr(visibility_api, "AsyncSessionLocal", lambda: _ClickSession(click_rows))
    monkeypatch.setattr(visibility_api, "record_observation", fake_record_observation)

    app = FastAPI()
    app.include_router(visibility_router)
    client = TestClient(app)
    response = client.get(
        "/v/abc123",
        headers={"user-agent": "pytest-agent", "referer": "https://mail.example/message"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert location.startswith("https://visibility.example/r/scan-123?")
    assert query["src"] == ["visibility_report_email"]
    assert query["c"][0].startswith("visibilityclick_")

    assert len(click_rows) == 1
    click = click_rows[0]
    assert isinstance(click, AuditLinkClickRow)
    assert click.id == query["c"][0]
    assert click.contact_id == "contact-1"
    assert click.batch_item_id == "item-1"
    assert click.pif_id == "pif-1"
    assert click.source == "visibility_report_email"
    assert click.user_agent == "pytest-agent"
    assert click.referer == "https://mail.example/message"

    assert observations == [{
        "event_type": "link_clicked",
        "raw_event": {
            "source": "visibility_report_email",
            "channel": "ai_visibility",
            "click_id": query["c"][0],
            "scan_id": "scan-123",
            "link_code": "abc123",
        },
        "contact_id": "contact-1",
        "batch_item_id": "item-1",
    }]
