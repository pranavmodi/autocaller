from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import pif as pif_api
from app.db.models import FirmAliasRow, PifFirmRow
from app.services import pif_firm_crud as svc


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class FakeStore:
    def __init__(self):
        self.firms: dict[str, PifFirmRow] = {}
        self.aliases: dict[tuple[str, str], FirmAliasRow] = {}
        self.commits = 0


class FakeSession:
    def __init__(self, store: FakeStore):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, key):
        if model is PifFirmRow:
            return self.store.firms.get(str(key))
        if model is FirmAliasRow:
            alias_key = (key["alias_type"], key["alias_value"])
            return self.store.aliases.get(alias_key)
        raise AssertionError(f"unexpected model: {model}")

    def add(self, row):
        if isinstance(row, PifFirmRow):
            self.store.firms[row.id] = row
            return
        if isinstance(row, FirmAliasRow):
            self.store.aliases[(row.alias_type, row.alias_value)] = row
            return
        raise AssertionError(f"unexpected row: {row!r}")

    async def execute(self, stmt):
        rendered = str(stmt)
        if rendered.startswith("DELETE FROM firm_intel_aliases"):
            self.store.aliases.clear()
            return FakeResult()
        return FakeResult()

    async def delete(self, row):
        self.store.firms.pop(row.id, None)

    async def commit(self):
        self.store.commits += 1


def install_store(monkeypatch) -> FakeStore:
    store = FakeStore()

    async def noop_ensure():
        return None

    monkeypatch.setattr(svc, "ensure_firm_intel_tables", noop_ensure)
    monkeypatch.setattr(svc, "AsyncSessionLocal", lambda: FakeSession(store))
    return store


def stern_payload() -> dict:
    return {
        "firm_name": "Stern & Cohen, P.C.",
        "website": "https://sterncohenlaw.com/",
        "entity_type": "law_firm",
        "metro": "philadelphia",
        "contacts": [
            {
                "name": "David F. Stern",
                "title": "Founding Partner",
                "email": "david@sterncohenlaw.com",
                "is_decision_maker": True,
            }
        ],
        "vendor_stack": {
            "other": {
                "intaker": {
                    "category": "intake",
                    "confidence": 0.99,
                    "evidence": [{"url": "https://sterncohenlaw.com/"}],
                },
                "callrail": {"category": "call_tracking", "confidence": 0.99},
            }
        },
        "research_data": {"sources": ["https://sterncohenlaw.com/"]},
        "aliases": {"domains": ["www.sterncohenlaw.com"]},
        "provenance": {"observed_at": "2026-07-22T00:00:00Z"},
    }


def test_normalize_firm_write_rejects_unknown_and_consumer_domains():
    with pytest.raises(svc.PifFirmCrudError, match="unsupported fields"):
        svc.normalize_firm_write({"firm_name": "Firm", "website": "firm.com", "mystery": 1}, creating=True)
    with pytest.raises(svc.PifFirmCrudError, match="non-consumer"):
        svc.normalize_firm_write({"firm_name": "Firm", "website": "gmail.com"}, creating=True)


def test_stored_manual_overrides_drop_legacy_consumer_aliases():
    now = datetime.now(timezone.utc)
    row = PifFirmRow(
        id="legacy-firm",
        firm_name="Legacy Firm",
        website="legacyfirm.com",
        canonical_website="legacyfirm.com",
        raw_json={"aliases": {"domains": ["legacyfirm.com", "yahoo.com"]}},
        source_json={},
        created_at=now,
        updated_at=now,
        synced_at=now,
    )

    svc.apply_stored_manual_overrides(
        row,
        {"vendor_stack": {"case_management": {"filevine": {"confidence": 1.0}}}},
        now=now,
    )

    assert row.raw_json["aliases"]["domains"] == ["legacyfirm.com"]
    assert row.source_json["_possibleos_manual_overrides"]["vendor_stack"] == row.vendor_stack


def test_create_manual_firm_derives_people_fields_and_aliases(monkeypatch):
    store = install_store(monkeypatch)

    async def no_owner(_session, _domain):
        return None

    monkeypatch.setattr(svc, "_domain_owner", no_owner)
    result = asyncio.run(svc.create_pif_firm(stern_payload()))

    row = store.firms[result["firm_id"]]
    assert result["status"] == "created"
    assert result["manually_added"] is True
    assert row.canonical_website == "sterncohenlaw.com"
    assert row.profile_source == "manual"
    assert row.manually_added is True
    assert row.emails == ["david@sterncohenlaw.com"]
    assert row.leadership[0]["name"] == "David F. Stern"
    assert row.vendor_stack["other"]["intaker"]["confidence"] == 0.99
    assert row.raw_json["provenance"]["source"] == "possibleos_manual"
    assert ("domain", "sterncohenlaw.com") in store.aliases
    assert result["aliases_touched"] == 1
    assert store.commits == 1


def test_create_conflicts_on_existing_domain(monkeypatch):
    install_store(monkeypatch)

    async def existing_owner(_session, _domain):
        return "existing-firm"

    monkeypatch.setattr(svc, "_domain_owner", existing_owner)
    with pytest.raises(svc.PifFirmConflictError) as exc:
        asyncio.run(svc.create_pif_firm(stern_payload()))
    assert exc.value.firm_id == "existing-firm"


def test_update_dry_run_does_not_mutate_existing_row(monkeypatch):
    store = install_store(monkeypatch)
    row = PifFirmRow(
        id="manual-1",
        firm_name="Stern & Cohen, P.C.",
        website="sterncohenlaw.com",
        canonical_website="sterncohenlaw.com",
        profile_source="manual",
        vendor_stack={},
        contacts=[],
        leadership=[],
        staff=[],
        emails=[],
        phones=[],
        raw_json={"aliases": {"domains": ["sterncohenlaw.com"]}},
        source_json={},
        created_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    store.firms[row.id] = row

    async def resolve(_session, _value):
        return row

    monkeypatch.setattr(svc, "_resolve_row", resolve)
    result = asyncio.run(svc.update_pif_firm(
        row.id,
        {"vendor_stack": {"other": {"intaker": {"confidence": 0.99}}}},
        dry_run=True,
    ))

    assert result["status"] == "would_update"
    assert result["vendor_stack"]["other"]["intaker"]["confidence"] == 0.99
    assert row.vendor_stack == {}
    assert store.commits == 0


def test_upsert_falls_back_to_domain_when_supplied_id_is_new(monkeypatch):
    store = install_store(monkeypatch)
    row = PifFirmRow(
        id="existing-1",
        firm_name="Stern & Cohen, P.C.",
        website="sterncohenlaw.com",
        canonical_website="sterncohenlaw.com",
        profile_source="manual",
        vendor_stack={},
        contacts=[],
        leadership=[],
        staff=[],
        emails=[],
        phones=[],
        raw_json={"aliases": {"domains": ["sterncohenlaw.com"]}},
        source_json={},
    )
    store.firms[row.id] = row

    async def resolve(_session, value):
        return row if value in {"sterncohenlaw.com", "existing-1"} else None

    async def no_other_owner(_session, _domain):
        return row.id

    monkeypatch.setattr(svc, "_resolve_row", resolve)
    monkeypatch.setattr(svc, "_domain_owner", no_other_owner)
    payload = stern_payload()
    payload["firm_id"] = "new-import-id"

    result = asyncio.run(svc.upsert_pif_firm(payload))

    assert result["status"] == "updated"
    assert result["firm_id"] == "existing-1"
    assert set(store.firms) == {"existing-1"}


def test_delete_requires_force_for_synced_firm(monkeypatch):
    install_store(monkeypatch)
    row = PifFirmRow(id="upstream-1", firm_name="Synced Firm", profile_source="v2")

    async def resolve(_session, _value):
        return row

    monkeypatch.setattr(svc, "_resolve_row", resolve)
    with pytest.raises(svc.PifFirmProtectedError, match="force=true"):
        asyncio.run(svc.delete_pif_firm(row.id))


def test_api_create_and_error_mapping(monkeypatch):
    captured = {}

    async def fake_create(payload, *, dry_run=False):
        captured.update({"payload": payload, "dry_run": dry_run})
        return {"status": "would_create", "firm_id": "manual-1", "dry_run": dry_run}

    monkeypatch.setattr(pif_api, "create_pif_firm", fake_create)
    app = FastAPI()
    app.include_router(pif_api.router)
    client = TestClient(app)
    response = client.post(
        "/api/pif/firms?dry_run=true",
        json={"firm_name": "Stern & Cohen, P.C.", "website": "sterncohenlaw.com"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "would_create"
    assert captured["dry_run"] is True
    assert captured["payload"]["firm_name"] == "Stern & Cohen, P.C."


def test_api_filters_firms_by_manually_added_boolean(monkeypatch):
    captured = {}

    async def fake_list(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "page": 1, "page_size": 25, "total_pages": 0}

    monkeypatch.setattr(pif_api, "list_mirrored_pif_firms", fake_list)
    app = FastAPI()
    app.include_router(pif_api.router)
    client = TestClient(app)

    response = client.get("/api/pif/firms?manually_added=true")

    assert response.status_code == 200
    assert captured["manually_added"] is True


def test_api_forwards_contact_email_and_staff_count_ranges(monkeypatch):
    captured = {}

    async def fake_list(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "page": 1, "page_size": 25, "total_pages": 0}

    monkeypatch.setattr(pif_api, "list_mirrored_pif_firms", fake_list)
    app = FastAPI()
    app.include_router(pif_api.router)
    client = TestClient(app)

    response = client.get(
        "/api/pif/firms?contact_email_min=6&contact_email_max=10&staff_count_min=26&staff_count_max=50"
    )

    assert response.status_code == 200
    assert captured["contact_email_min"] == 6
    assert captured["contact_email_max"] == 10
    assert captured["staff_count_min"] == 26
    assert captured["staff_count_max"] == 50


def test_api_forwards_job_trigger_filters(monkeypatch):
    captured = {}

    async def fake_list(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "page": 1, "page_size": 25, "total_pages": 0}

    monkeypatch.setattr(pif_api, "list_mirrored_pif_firms", fake_list)
    app = FastAPI()
    app.include_router(pif_api.router)
    client = TestClient(app)

    response = client.get(
        "/api/pif/firms?job_postings_presence=has&job_posting_role=intake"
        "&job_posting_query=lead%20conversion&job_posted_within_days=30"
    )

    assert response.status_code == 200
    assert captured["job_postings_presence"] == "has"
    assert captured["job_posting_role"] == "intake"
    assert captured["job_posting_query"] == "lead conversion"
    assert captured["job_posted_within_days"] == 30


def test_api_forwards_autorespond_filters(monkeypatch):
    captured = {}

    async def fake_list(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "page": 1, "page_size": 25, "total_pages": 0}

    monkeypatch.setattr(pif_api, "list_mirrored_pif_firms", fake_list)
    app = FastAPI()
    app.include_router(pif_api.router)
    client = TestClient(app)

    response = client.get("/api/pif/firms?autorespond_window=7d&autorespond_type=bill_offer")

    assert response.status_code == 200
    assert captured["autorespond_window"] == "7d"
    assert captured["autorespond_type"] == "bill_offer"
