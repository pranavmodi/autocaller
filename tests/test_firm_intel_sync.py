from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.db.models import FirmAliasRow, FirmIntelSyncStateRow, PifFirmRow
from app.services import firm_intel_sync as svc


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def scalar_one(self):
        return self._scalar


class FakeStore:
    def __init__(self):
        self.firms: dict[str, PifFirmRow] = {}
        self.aliases: dict[tuple[str, str], FirmAliasRow] = {}
        self.states: dict[int, FirmIntelSyncStateRow] = {}
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
        if model is FirmIntelSyncStateRow:
            return self.store.states.get(int(key))
        if model is FirmAliasRow:
            if isinstance(key, dict):
                alias_key = (key["alias_type"], key["alias_value"])
            else:
                alias_key = tuple(key)
            return self.store.aliases.get(alias_key)
        raise AssertionError(f"unexpected model get: {model}")

    def add(self, row):
        if isinstance(row, PifFirmRow):
            self.store.firms[row.id] = row
            return
        if isinstance(row, FirmIntelSyncStateRow):
            self.store.states[row.id] = row
            return
        if isinstance(row, FirmAliasRow):
            self.store.aliases[(row.alias_type, row.alias_value)] = row
            return
        raise AssertionError(f"unexpected add: {row!r}")

    async def commit(self):
        self.store.commits += 1

    async def execute(self, stmt):
        rendered = str(stmt)
        if "pif_directory_firms" in rendered and "canonical_website" in rendered:
            return FakeResult(
                rows=[
                    (row.id, row.canonical_website, row.website)
                    for row in self.store.firms.values()
                ]
            )
        raise AssertionError(f"unexpected execute: {rendered}")


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def install_fakes(monkeypatch, responses):
    store = FakeStore()
    calls = []

    async def noop_ensure():
        return None

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, path, params=None):
            calls.append({"path": path, "params": dict(params or {})})
            if not responses:
                raise AssertionError("no fake HTTP response queued")
            next_response = responses.pop(0)
            if isinstance(next_response, Exception):
                raise next_response
            return FakeResponse(next_response)

    monkeypatch.setattr(svc, "ensure_firm_intel_tables", noop_ensure)
    monkeypatch.setattr(svc, "AsyncSessionLocal", lambda: FakeSession(store))
    monkeypatch.setattr(svc.httpx, "AsyncClient", FakeClient)
    return store, calls


def profile(
    firm_id: str,
    *,
    canonical="smithlaw.com",
    domains=None,
    legacy_ids=None,
    refined_at="2026-07-01T12:00:00Z",
    decision_email="owner@smithlaw.com",
):
    domains = domains if domains is not None else ["smithlaw.com", "smith-law.com"]
    legacy_ids = legacy_ids if legacy_ids is not None else ["legacy-1"]
    return {
        "firm_id": firm_id,
        "canonical_website": canonical,
        "website_status": "resolved",
        "firm_name": f"Firm {firm_id}",
        "aliases": {
            "legacy_pif_ids": legacy_ids,
            "domains": domains,
            "vanity_domains": ["smithlaw.filevineapp.com"],
        },
        "identity": {
            "metro": "los-angeles",
            "city": "Los Angeles",
            "state": "CA",
            "size_hint": "5-30",
            "icp_tier": "A",
        },
        "people": [
            {
                "person_id": f"{firm_id}-dm",
                "name": "Avery Owner",
                "title": "Managing Partner",
                "email": decision_email,
                "phone": "310-111-2222",
                "persona": "owner",
                "is_decision_maker": True,
                "confidence": 0.9,
            },
            {
                "person_id": f"{firm_id}-staff",
                "name": "Sam Staff",
                "title": "Intake",
                "email": f"intake@{domains[0] if domains else 'fallbackfirm.com'}",
                "phone": "310-333-4444",
                "persona": "intake",
                "is_decision_maker": False,
                "confidence": 0.7,
            },
        ],
        "relationship": {
            "warm_score_neutral": 42.5,
            "total_email_count": 12,
            "last_seen_at": "2026-07-01T10:00:00Z",
            "monthly_email_volume": [1, 4, 7],
            "inbox_breakdown": {"inb_qfq9": {"count": 8}},
        },
        "behavior": {
            "primary_pain_point": "intake",
            "topic_distribution": {"intake": 10},
            "sender_roles": {"intake": 4},
            "after_hours_ratio": 0.25,
        },
        "vendor_stack": {"case_mgmt": "filevine", "evidence": [{"signal": "domain"}]},
        "icp": {"score": 87, "tier": "A", "score_breakdown": {"fit": 50}},
        "research": {
            "practice_areas": ["PI"],
            "sources": ["https://smithlaw.com"],
            "research_status": "done",
            "last_researched_at": "2026-06-30T00:00:00Z",
        },
        "provenance": {"refined_at": refined_at, "source": "emailtag"},
    }


def test_delta_sync_two_pages_upserts_and_advances_watermark(monkeypatch):
    p1 = profile("firm-1", refined_at="2026-07-01T12:00:00Z")
    p2 = profile("firm-2", canonical="joneslaw.com", domains=["joneslaw.com"], legacy_ids=["legacy-2"], refined_at="2026-07-02T12:00:00Z", decision_email="owner@joneslaw.com")
    p3 = profile("firm-3", canonical="raylaw.com", domains=["raylaw.com"], legacy_ids=["legacy-3"], refined_at="2026-07-03T12:00:00Z", decision_email="owner@raylaw.com")
    store, calls = install_fakes(monkeypatch, [
        {"items": [p1, p2], "next_cursor": "cursor-2", "total": 3},
        {"items": [p3], "next_cursor": None, "total": 3},
    ])
    store.states[1] = FirmIntelSyncStateRow(
        id=1,
        last_updated_since=datetime(2026, 6, 30, tzinfo=timezone.utc),
        last_result={},
    )

    result = asyncio.run(svc.sync_firm_intel())

    assert result["fetched"] == 3
    assert result["created"] == 3
    assert result["pages"] == 2
    assert calls[0]["params"]["updated_since"] == "2026-06-30T00:00:00+00:00"
    assert calls[1]["params"]["cursor"] == "cursor-2"
    assert store.states[1].last_updated_since == datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    assert set(store.firms) == {"firm-1", "firm-2", "firm-3"}
    assert ("domain", "smithlaw.com") in store.aliases


def test_full_sync_ignores_watermark(monkeypatch):
    store, calls = install_fakes(monkeypatch, [
        {"items": [profile("firm-1")], "next_cursor": None, "total": 1},
    ])
    store.states[1] = FirmIntelSyncStateRow(
        id=1,
        last_updated_since=datetime(2026, 6, 30, tzinfo=timezone.utc),
        last_result={},
    )

    asyncio.run(svc.sync_firm_intel(full=True, limit=1))

    assert "updated_since" not in calls[0]["params"]
    assert calls[0]["params"]["limit"] == 1


def test_limited_smoke_sync_does_not_advance_watermark_when_more_pages_exist(monkeypatch):
    old_watermark = datetime(2026, 6, 30, tzinfo=timezone.utc)
    store, _calls = install_fakes(monkeypatch, [
        {"items": [profile("firm-1")], "next_cursor": "cursor-2", "total": 2},
    ])
    store.states[1] = FirmIntelSyncStateRow(
        id=1,
        last_updated_since=old_watermark,
        last_result={},
    )

    result = asyncio.run(svc.sync_firm_intel(limit=1))

    assert result["fetched"] == 1
    assert result["stopped_by_limit_with_more"] is True
    assert result["watermark_advanced"] is False
    assert store.states[1].last_updated_since == old_watermark


def test_mapping_profile_to_pif_row_fields(monkeypatch):
    fixture = profile(
        "firm-fallback",
        canonical=None,
        domains=["fallbackfirm.com"],
        legacy_ids=["legacy-fallback"],
        decision_email="boss@fallbackfirm.com",
    )
    store, _calls = install_fakes(monkeypatch, [
        {"items": [fixture], "next_cursor": None, "total": 1},
    ])

    asyncio.run(svc.sync_firm_intel(full=True))

    row = store.firms["firm-fallback"]
    assert row.website == "fallbackfirm.com"
    assert row.canonical_website == "fallbackfirm.com"
    assert row.icp_score == 87
    assert row.icp_tier == "A"
    assert row.score_breakdown == {"fit": 50}
    assert row.research_status == "done"
    assert row.last_researched_at == datetime(2026, 6, 30, tzinfo=timezone.utc)
    assert row.leadership[0]["email"] == "boss@fallbackfirm.com"
    assert row.staff[0]["title"] == "Intake"
    assert row.emails == ["boss@fallbackfirm.com", "intake@fallbackfirm.com"]
    assert row.phones == ["310-111-2222", "310-333-4444"]
    assert row.behavioral_data["primary_pain_point"] == "intake"
    assert row.behavioral_data["total_email_count"] == 12
    assert row.research_data["city"] == "Los Angeles"
    assert row.raw_json is fixture
    assert row.source_updated_at == datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert row.metro == "los-angeles"
    assert row.warm_score == 42.5
    assert row.vendor_stack["case_mgmt"] == "filevine"
    assert row.profile_source == "v2"


def test_alias_upsert_idempotent_on_rerun(monkeypatch):
    fixture = profile("firm-1")
    store, _calls = install_fakes(monkeypatch, [
        {"items": [fixture], "next_cursor": None, "total": 1},
        {"items": [fixture], "next_cursor": None, "total": 1},
    ])

    first = asyncio.run(svc.sync_firm_intel(full=True))
    alias_count = len(store.aliases)
    second = asyncio.run(svc.sync_firm_intel(full=True))

    assert first["created"] == 1
    assert second["updated"] == 1
    assert len(store.aliases) == alias_count


def test_resolve_firm_local_hits_domain_email_and_legacy_id(monkeypatch):
    fixture = profile("firm-1")
    store, _calls = install_fakes(monkeypatch, [
        {"items": [fixture], "next_cursor": None, "total": 1},
    ])
    asyncio.run(svc.sync_firm_intel(full=True))

    assert asyncio.run(svc.resolve_firm_local("https://www.smithlaw.com/about")) == "firm-1"
    assert asyncio.run(svc.resolve_firm_local("person@smithlaw.com")) == "firm-1"
    assert asyncio.run(svc.resolve_firm_local("legacy-1")) == "firm-1"
    assert len(store.aliases) > 0


def test_watermark_not_advanced_when_later_page_raises(monkeypatch):
    old_watermark = datetime(2026, 6, 30, tzinfo=timezone.utc)
    store, _calls = install_fakes(monkeypatch, [
        {"items": [profile("firm-1")], "next_cursor": "cursor-2", "total": 2},
        RuntimeError("boom"),
    ])
    store.states[1] = FirmIntelSyncStateRow(
        id=1,
        last_updated_since=old_watermark,
        last_result={},
    )

    with pytest.raises(RuntimeError):
        asyncio.run(svc.sync_firm_intel())

    assert store.states[1].last_updated_since == old_watermark


def test_failed_full_crawl_saves_resume_point_and_next_run_resumes(monkeypatch):
    store, _calls = install_fakes(monkeypatch, [
        {"items": [profile("firm-1", refined_at="2026-07-01T12:00:00Z")], "next_cursor": "cursor-2", "total": 2},
        RuntimeError("boom"),
    ])

    with pytest.raises(RuntimeError):
        asyncio.run(svc.sync_firm_intel(full=True))

    saved = store.states[1].last_result
    assert saved["resume_cursor"] == "cursor-2"
    assert saved["resume_watermark"] is not None

    # Second full run resumes from the saved cursor and completes.
    store2, calls2 = install_fakes(monkeypatch, [
        {"items": [profile("firm-2", refined_at="2026-07-02T12:00:00Z")], "next_cursor": None, "total": 2},
    ])
    store2.states[1] = store.states[1]

    result = asyncio.run(svc.sync_firm_intel(full=True))

    assert calls2[0]["params"].get("cursor") == "cursor-2"
    assert result["resumed_from"] == "cursor-2"
    assert result["watermark_advanced"] is True
    # Watermark covers both partial runs (max of resumed + newly seen).
    assert store2.states[1].last_updated_since == datetime(2026, 7, 2, 12, tzinfo=timezone.utc)
    # Completed full crawl clears the resume point.
    assert "resume_cursor" not in store2.states[1].last_result


def test_limited_run_preserves_saved_resume_point(monkeypatch):
    store, _calls = install_fakes(monkeypatch, [
        {"items": [profile("firm-1")], "next_cursor": "cursor-2", "total": 2},
        RuntimeError("boom"),
    ])
    with pytest.raises(RuntimeError):
        asyncio.run(svc.sync_firm_intel(full=True))
    assert store.states[1].last_result["resume_cursor"] == "cursor-2"

    store2, calls2 = install_fakes(monkeypatch, [
        {"items": [profile("firm-3")], "next_cursor": "cursor-x", "total": 2},
    ])
    store2.states[1] = store.states[1]

    result = asyncio.run(svc.sync_firm_intel(limit=1))

    # Limited run starts from page 0 (no resume) but must not wipe the point.
    assert calls2[0]["params"].get("cursor") is None
    assert store2.states[1].last_result["resume_cursor"] == "cursor-2"

    # restart=True discards the resume point.
    store3, calls3 = install_fakes(monkeypatch, [
        {"items": [profile("firm-4")], "next_cursor": None, "total": 1},
    ])
    store3.states[1] = store2.states[1]
    asyncio.run(svc.sync_firm_intel(full=True, restart=True))
    assert calls3[0]["params"].get("cursor") is None
    assert "resume_cursor" not in store3.states[1].last_result
