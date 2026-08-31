from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import or_

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
        if "count(" in rendered and "FROM pif_directory_firms" in rendered:
            return FakeResult(scalar=len(self.store.firms))
        if "count(" in rendered and "FROM firm_intel_aliases" in rendered:
            return FakeResult(scalar=len(self.store.aliases))
        if "pif_directory_firms.synced_at" in rendered:
            last_synced_at = next(
                (state.last_synced_at for state in self.store.states.values() if state.last_synced_at),
                None,
            )
            rows = [
                (
                    row.id,
                    row.firm_name,
                    row.canonical_website,
                    row.website,
                    row.source_updated_at,
                    row.contacts,
                )
                for row in self.store.firms.values()
                if row.synced_at == last_synced_at
            ]
            return FakeResult(rows=rows)
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
            "job_postings_research_status": "completed",
            "last_job_postings_researched_at": "2026-08-22T04:00:00Z",
            "job_postings": {
                "has_recent_openings": True,
                "window_days": 30,
                "window_start": "2026-07-24",
                "window_end": "2026-08-22",
                "researched_at": "2026-08-22T04:00:00Z",
                "postings": [{
                    "title": "Intake Specialist",
                    "location": "Los Angeles, CA",
                    "employment_type": "Full-time",
                    "posted_date": "2026-08-15",
                    "description_summary": "Handles prospective-client intake.",
                    "responsibilities": ["Answer prospective-client calls"],
                    "qualifications": ["One year of intake experience"],
                    "source_name": "Firm careers page",
                    "source_url": "https://smithlaw.com/careers/intake-specialist",
                }],
            },
        },
        "source_record": {
            "id": firm_id,
            "firm_name": f"Firm {firm_id}",
            "entity_type": "pi_law_firm",
            "fax": "310-999-0000",
            "staff_research_status": "completed",
            "first_contacted_precise_at": "2026-01-22T17:17:14.831612Z",
            "created_at": "2026-01-20T00:00:00Z",
            "icp_scored_at": "2026-06-29T00:00:00Z",
            "merge_status": "active",
            "conversation_ids": ["cnv_123"],
        },
        "provenance": {"refined_at": refined_at, "source": "emailtag"},
    }


def extraction(firm_id: str = "raw-1"):
    return {
        "extraction_id": firm_id,
        "firm_name": "Raw Example Law",
        "entity_type": "pi_law_firm",
        "observed_website": "rawexample.com/contact",
        "emails": ["intake@rawexample.com"],
        "phones": ["+13105551212"],
        "fax": None,
        "addresses": ["Los Angeles, CA"],
        "contacts": [{"name": "Intake", "email": "intake@rawexample.com"}],
        "conversation_ids": ["cnv_1"],
        "extraction_notes": "signature extraction",
        "first_contacted_precise_at": "2026-08-20T00:00:00Z",
        "merge_status": "active",
        "merged_into": None,
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-26T09:00:00Z",
        "source": "emailtag_pif_extraction",
    }


def test_raw_extraction_sync_queues_local_enrichment(monkeypatch):
    store, calls = install_fakes(monkeypatch, [{
        "items": [extraction()],
        "next_cursor": None,
        "total": 1,
    }])
    queued = []

    async def fake_queue(ids, *, limit):
        queued.extend(ids)
        return {"queued": list(ids), "skipped": []}

    from app.services import pif_local_enrichment
    monkeypatch.setattr(pif_local_enrichment, "queue_dirty_firm_enrichment", fake_queue)

    result = asyncio.run(svc.sync_firm_intel())

    row = store.firms["raw-1"]
    assert calls[0]["path"] == "/extractions"
    assert row.profile_source == "raw"
    assert row.source_json["source"] == "emailtag_pif_extraction"
    assert row.research_data["local_enrichment"]["dirty"] is True
    assert queued == ["raw-1"]
    assert result["local_enrichment"]["queued"] == ["raw-1"]


def test_linked_extraction_updates_existing_canonical_firm(monkeypatch):
    store, _calls = install_fakes(monkeypatch, [])
    canonical = PifFirmRow(
        id="canonical-1",
        firm_name="Canonical Law Group",
        canonical_website="canonical.example",
        website="canonical.example",
        emails=["owner@canonical.example"],
        phones=[],
        addresses=[],
        contacts=[],
        leadership=[],
        staff=[],
        conversation_ids=[],
        research_data={},
        source_json={},
    )
    store.firms[canonical.id] = canonical
    store.aliases[("legacy_pif_id", "raw-1")] = FirmAliasRow(
        alias_type="legacy_pif_id",
        alias_value="raw-1",
        firm_id=canonical.id,
        synced_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )

    status, _aliases, local_id = asyncio.run(svc._upsert_profile(
        FakeSession(store),
        extraction(),
        now=datetime(2026, 8, 31, tzinfo=timezone.utc),
    ))

    assert status == "updated"
    assert local_id == canonical.id
    assert canonical.firm_name == "Canonical Law Group"
    assert canonical.canonical_website == "canonical.example"
    assert canonical.emails == ["owner@canonical.example", "intake@rawexample.com"]
    assert canonical.conversation_ids == ["cnv_1"]
    assert canonical.source_json["_linked_extraction_ids"] == ["raw-1"]
    assert "raw-1" not in store.firms


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
    assert [item["firm_id"] for item in result["items"]] == ["firm-1", "firm-2", "firm-3"]
    assert all(item["status"] == "created" for item in result["items"])
    assert result["items"][0]["people_count"] == 2
    assert result["items_truncated"] is False


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
    assert row.research_data["job_postings_research_status"] == "completed"
    assert row.research_data["job_postings"]["postings"][0]["title"] == "Intake Specialist"
    assert row.research_data["job_postings"]["postings"][0]["source_url"] == "https://smithlaw.com/careers/intake-specialist"
    assert row.raw_json is fixture
    assert row.source_json is fixture["source_record"]
    assert row.first_contacted_precise_at == datetime(2026, 1, 22, 17, 17, 14, 831612, tzinfo=timezone.utc)
    assert row.source_json["merge_status"] == "active"
    assert row.entity_type == "pi_law_firm"
    assert row.fax == "310-999-0000"
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
    assert second["items"][0]["status"] == "updated"
    assert len(store.aliases) == alias_count


def test_incidental_domain_alias_cannot_steal_canonical_owner():
    store = FakeStore()
    store.firms["dk-law"] = PifFirmRow(
        id="dk-law",
        firm_name="DK Law",
        website="dklaw.com",
        canonical_website="dklaw.com",
    )
    store.firms["vendor"] = PifFirmRow(
        id="vendor",
        firm_name="Vendor",
        website="vendor.example",
        canonical_website="vendor.example",
    )
    store.aliases[("domain", "dklaw.com")] = FirmAliasRow(
        alias_type="domain",
        alias_value="dklaw.com",
        firm_id="dk-law",
    )
    incoming = profile("vendor", canonical="vendor.example", domains=["vendor.example", "dklaw.com"])

    asyncio.run(svc._upsert_aliases(FakeSession(store), incoming, now=datetime.now(timezone.utc)))

    assert store.aliases[("domain", "dklaw.com")].firm_id == "dk-law"


def test_canonical_domain_reclaims_alias_from_incidental_owner():
    store = FakeStore()
    store.firms["dk-law"] = PifFirmRow(
        id="dk-law",
        firm_name="DK Law",
        website="dklaw.com",
        canonical_website="dklaw.com",
    )
    store.firms["vendor"] = PifFirmRow(
        id="vendor",
        firm_name="Vendor",
        website="vendor.example",
        canonical_website="vendor.example",
    )
    store.aliases[("domain", "dklaw.com")] = FirmAliasRow(
        alias_type="domain",
        alias_value="dklaw.com",
        firm_id="vendor",
    )
    incoming = profile("dk-law", canonical="dklaw.com", domains=["dklaw.com"])

    asyncio.run(svc._upsert_aliases(FakeSession(store), incoming, now=datetime.now(timezone.utc)))

    assert store.aliases[("domain", "dklaw.com")].firm_id == "dk-law"


def test_sync_reapplies_operator_vendor_overrides(monkeypatch):
    fixture = profile("firm-1")
    store, _calls = install_fakes(monkeypatch, [
        {"items": [fixture], "next_cursor": None, "total": 1},
    ])
    store.firms["firm-1"] = PifFirmRow(
        id="firm-1",
        firm_name="Old Firm",
        website="smithlaw.com",
        canonical_website="smithlaw.com",
        profile_source="v2",
        source_json={
            "_possibleos_manual_overrides": {
                "vendor_stack": {
                    "other": {"intaker": {"confidence": 0.99, "grade": "A"}}
                }
            }
        },
        raw_json={},
        contacts=[],
        leadership=[],
        staff=[],
        emails=[],
        phones=[],
    )

    asyncio.run(svc.sync_firm_intel(full=True))

    row = store.firms["firm-1"]
    assert row.vendor_stack["other"]["intaker"]["confidence"] == 0.99
    assert row.source_json["_possibleos_manual_overrides"]["vendor_stack"] == row.vendor_stack
    assert row.raw_json["provenance"]["source"] == "emailtag"
    assert row.raw_json["provenance"]["operator_updated_at"]


def test_operator_vendor_evidence_takes_precedence_over_synced_signal():
    row = PifFirmRow(
        id="firm-1",
        source_json={
            "vendor_stack": [
                {
                    "vendor": "filevine",
                    "source": "email_domain",
                    "confidence": "high",
                }
            ],
            "_possibleos_manual_overrides": {
                "vendor_stack": {
                    "case_mgmt": "filevine",
                    "other": {
                        "filevine": {
                            "source": "public_technographic_research",
                            "confidence": 0.98,
                            "grade": "A",
                        },
                        "callrail": {
                            "confidence": 0.97,
                            "grade": "A",
                        },
                    },
                }
            },
        },
        vendor_stack={"case_mgmt": "filevine"},
        raw_json={},
    )

    entries = svc._vendor_entries_for_row(row)

    assert [entry["vendor"] for entry in entries] == ["filevine", "callrail"]
    assert entries[0]["confidence"] == 0.98
    assert entries[0]["grade"] == "A"


def test_operator_vendor_stack_replaces_stale_synced_vendors():
    row = PifFirmRow(
        id="firm-1",
        source_json={
            "vendor_stack": [
                {"vendor": "clio", "source": "stale_sync"},
                {"vendor": "filevine", "source": "stale_sync"},
            ],
            "_possibleos_manual_overrides": {
                "vendor_stack": {
                    "case_mgmt": "litify",
                    "other": {"salesforce": {"confidence": 0.98, "grade": "A"}},
                }
            },
        },
        vendor_stack={"case_mgmt": "litify"},
        raw_json={"vendor_stack": {"case_mgmt": "clio"}},
    )

    entries = svc._vendor_entries_for_row(row)

    assert [entry["vendor"] for entry in entries] == ["litify", "salesforce"]


def test_sync_reconciles_upstream_profile_into_manual_domain_record(monkeypatch):
    fixture = profile("upstream-1", canonical="sterncohenlaw.com", domains=["sterncohenlaw.com"])
    store, _calls = install_fakes(monkeypatch, [
        {"items": [fixture], "next_cursor": None, "total": 1},
    ])
    store.firms["manual-1"] = PifFirmRow(
        id="manual-1",
        firm_name="Stern & Cohen, P.C.",
        website="sterncohenlaw.com",
        canonical_website="sterncohenlaw.com",
        profile_source="manual",
        manually_added=True,
        source_json={
            "_possibleos_manual_overrides": {
                "firm_name": "Stern & Cohen, P.C.",
                "website": "sterncohenlaw.com",
                "vendor_stack": {"other": {"intaker": {"confidence": 0.99}}},
            }
        },
        raw_json={"aliases": {"domains": ["sterncohenlaw.com"]}},
        contacts=[],
        leadership=[],
        staff=[],
        emails=[],
        phones=[],
    )

    result = asyncio.run(svc.sync_firm_intel(full=True))

    assert set(store.firms) == {"manual-1"}
    assert store.firms["manual-1"].profile_source == "v2"
    assert store.firms["manual-1"].manually_added is True
    assert store.firms["manual-1"].vendor_stack["other"]["intaker"]["confidence"] == 0.99
    assert store.aliases[("legacy_pif_id", "upstream-1")].firm_id == "manual-1"
    assert result["items"][0]["firm_id"] == "manual-1"
    assert result["items"][0]["source_firm_id"] == "upstream-1"


def test_sync_uses_manual_alias_override_instead_of_readding_contaminated_domains(monkeypatch):
    fixture = profile(
        "firm-1",
        canonical="wrong-vendor.example",
        domains=["wrong-vendor.example", "rightfirm.com"],
    )
    store, _calls = install_fakes(monkeypatch, [
        {"items": [fixture], "next_cursor": None, "total": 1},
    ])
    store.firms["firm-1"] = PifFirmRow(
        id="firm-1",
        firm_name="Right Firm",
        website="rightfirm.com",
        canonical_website="rightfirm.com",
        profile_source="v2",
        source_json={
            "_possibleos_manual_overrides": {
                "canonical_website": "rightfirm.com",
                "aliases": {
                    "domains": ["rightfirm.com"],
                    "vanity_domains": [],
                    "legacy_pif_ids": ["firm-1"],
                },
            }
        },
        raw_json={},
        contacts=[],
        leadership=[],
        staff=[],
        emails=[],
        phones=[],
    )

    asyncio.run(svc.sync_firm_intel(full=True))

    assert ("domain", "rightfirm.com") in store.aliases
    assert ("domain", "wrong-vendor.example") not in store.aliases


def test_sync_status_reconstructs_legacy_run_firm_details(monkeypatch):
    store, _calls = install_fakes(monkeypatch, [])
    synced_at = datetime(2026, 7, 20, 7, 21, 27, tzinfo=timezone.utc)
    source_updated_at = datetime(2026, 7, 20, 6, 45, 2, tzinfo=timezone.utc)
    row = PifFirmRow(
        id="firm-legacy",
        firm_name="Legacy Firm",
        website="legacy.example",
        canonical_website="legacy.example",
        contacts=[{"name": "A"}, {"name": "B"}],
        synced_at=synced_at,
        source_updated_at=source_updated_at,
    )
    store.firms[row.id] = row
    store.states[1] = FirmIntelSyncStateRow(
        id=1,
        last_updated_since=source_updated_at,
        last_synced_at=synced_at,
        last_result={"fetched": 1, "created": 0, "updated": 1},
    )

    result = asyncio.run(svc.firm_intel_sync_status())

    assert result["last_result"]["items_inferred"] is True
    assert result["last_result"]["items_truncated"] is False
    assert result["last_result"]["items"] == [{
        "firm_id": "firm-legacy",
        "firm_name": "Legacy Firm",
        "status": "updated",
        "canonical_website": "legacy.example",
        "source_updated_at": "2026-07-20T06:45:02+00:00",
        "people_count": 2,
        "aliases_touched": None,
    }]


@pytest.mark.parametrize("status", ["done", "completed", "enriched"])
def test_research_presence_treats_finished_statuses_as_completed(status):
    row = PifFirmRow(id="firm-1", research_status=status)

    assert svc._row_matches_presence(row, "research_presence", "completed") is True
    assert svc._row_matches_presence(row, "research_presence", "missing") is False


@pytest.mark.parametrize("status", ["failed", "pending"])
def test_research_presence_does_not_treat_failed_or_pending_as_missing(status):
    row = PifFirmRow(id="firm-1", research_status=status)

    assert svc._row_matches_presence(row, "research_presence", "missing") is False


def test_job_postings_presence_distinguishes_openings_from_completed_empty_results():
    with_opening = PifFirmRow(id="firm-open", research_data={
        "job_postings_research_status": "completed",
        "job_postings": {"has_recent_openings": True, "postings": [{"title": "Intake Specialist"}]},
    })
    without_opening = PifFirmRow(id="firm-empty", research_data={
        "job_postings_research_status": "completed",
        "job_postings": {"has_recent_openings": False, "postings": []},
    })
    untouched = PifFirmRow(id="firm-new", research_data={})

    assert svc._row_matches_presence(with_opening, "job_postings_presence", "has") is True
    assert svc._row_matches_presence(without_opening, "job_postings_presence", "none") is True
    assert svc._row_matches_presence(untouched, "job_postings_presence", "not_researched") is True


def test_active_firm_condition_excludes_rows_with_merge_target():
    merged_into = PifFirmRow.source_json["merged_into"].astext
    condition = or_(merged_into.is_(None), merged_into == "")
    rendered = str(condition.compile(compile_kwargs={"literal_binds": True}))

    assert "merged_into" in rendered
    assert "IS NULL" in rendered


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
