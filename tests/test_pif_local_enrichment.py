import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.db.models import FirmAliasRow, PifEnrichmentTaskRow, PifFirmRow
from app.services import pif_local_enrichment as service
from app.services.firm_intel_sync import _apply_extraction


def test_local_research_is_due_after_30_days():
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)

    assert service._research_is_due(None, now=now, refresh_days=30) is True
    assert service._research_is_due(now - timedelta(days=29), now=now, refresh_days=30) is False
    assert service._research_is_due(now - timedelta(days=30), now=now, refresh_days=30) is True


def test_local_research_due_accepts_legacy_naive_timestamp():
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)

    assert service._research_is_due(
        datetime(2026, 8, 1),
        now=now,
        refresh_days=30,
    ) is True


def test_attach_extraction_to_recent_canonical_firm_preserves_research(monkeypatch):
    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    canonical = PifFirmRow(
        id="canonical-1",
        firm_name="Canonical Law Group",
        canonical_website="canonical.example",
        website="canonical.example",
        emails=["owner@canonical.example"],
        phones=[],
        addresses=[],
        contacts=[],
        conversation_ids=["cnv_old"],
        research_data={"summary": "Existing researched summary"},
        source_json={},
        last_researched_at=now - timedelta(days=5),
    )
    source = PifFirmRow(
        id="raw-1",
        firm_name="Canonical Law",
        emails=["intake@canonical.example"],
        phones=["+13105550100"],
        addresses=["Los Angeles, CA"],
        contacts=[{"name": "Intake", "email": "intake@canonical.example"}],
        conversation_ids=["cnv_new"],
        research_data={},
        source_json={"extraction_id": "raw-1", "merge_status": "active"},
        source_updated_at=now,
    )
    aliases = {}

    class Session:
        async def get(self, model, key):
            assert model is FirmAliasRow
            return aliases.get((key["alias_type"], key["alias_value"]))

        def add(self, row):
            aliases[(row.alias_type, row.alias_value)] = row

    asyncio.run(service._attach_extraction_to_canonical(
        Session(),
        source,
        canonical,
        now=now,
        reuse_recent_research=True,
    ))

    assert canonical.research_data["summary"] == "Existing researched summary"
    assert canonical.research_data["local_enrichment"]["dirty"] is False
    assert canonical.emails == ["owner@canonical.example", "intake@canonical.example"]
    assert canonical.conversation_ids == ["cnv_old", "cnv_new"]
    assert source.source_json["merged_into"] == canonical.id
    assert aliases[("legacy_pif_id", "raw-1")].firm_id == canonical.id


def test_persist_reconciles_domain_owner_without_review_conflict(monkeypatch):
    now = datetime.now(timezone.utc)
    canonical = PifFirmRow(
        id="canonical-1",
        firm_name="Canonical Law Group",
        canonical_website="canonical.example",
        website="canonical.example",
        emails=[],
        phones=[],
        addresses=[],
        contacts=[],
        conversation_ids=[],
        research_data={"summary": "Recent canonical research"},
        source_json={},
        last_researched_at=now - timedelta(days=5),
    )
    source = PifFirmRow(
        id="raw-1",
        firm_name="Canonical Law",
        emails=["intake@canonical.example"],
        phones=[],
        addresses=[],
        contacts=[],
        conversation_ids=["cnv_new"],
        research_data={"local_enrichment": {"dirty": True}},
        source_json={"extraction_id": "raw-1"},
    )
    task = PifEnrichmentTaskRow(
        task_id="task-1",
        pif_id=source.id,
        status="in_progress",
        requested_at=now,
        result_summary={},
    )
    aliases = {
        ("domain", "canonical.example"): FirmAliasRow(
            alias_type="domain",
            alias_value="canonical.example",
            firm_id=canonical.id,
            synced_at=now,
        ),
    }

    class Result:
        def scalar_one_or_none(self):
            return canonical.id

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, _stmt):
            return Result()

        async def get(self, model, key):
            if model is PifEnrichmentTaskRow:
                return task
            if model is PifFirmRow:
                return {source.id: source, canonical.id: canonical}.get(str(key))
            if model is FirmAliasRow:
                return aliases.get((key["alias_type"], key["alias_value"]))
            raise AssertionError(model)

        def add(self, row):
            aliases[(row.alias_type, row.alias_value)] = row

        async def commit(self):
            return None

    monkeypatch.setattr(service, "AsyncSessionLocal", lambda: Session())

    result = asyncio.run(service._persist_research_result("task-1", {
        "canonical_website": "canonical.example",
        "summary": "New duplicate research",
    }))

    assert result["pif_id"] == canonical.id
    assert result["reused_recent_research"] is True
    assert canonical.research_data["summary"] == "Recent canonical research"
    assert "canonical_domain_review" not in source.research_data.get("local_enrichment", {})
    assert source.source_json["merged_into"] == canonical.id
    assert aliases[("legacy_pif_id", source.id)].firm_id == canonical.id


def test_raw_extraction_preserves_local_derived_fields_and_marks_dirty():
    firm = PifFirmRow(
        id="firm-1",
        firm_name="Old Name",
        canonical_website="canonical.example",
        website="canonical.example",
        leadership=[{"name": "Owner", "email": "owner@canonical.example"}],
        staff=[{"name": "Staff", "phone": "+13105550100"}],
        vendor_stack={"case_mgmt": "filevine"},
        research_data={
            "summary": "Local summary",
            "local_enrichment": {"enriched_source_updated_at": "2026-08-25T00:00:00+00:00"},
        },
        source_json={},
    )
    extraction = {
        "extraction_id": "firm-1",
        "firm_name": "Example Injury Law",
        "entity_type": "pi_law_firm",
        "observed_website": "observed.example/path",
        "emails": ["intake@observed.example"],
        "phones": [],
        "addresses": ["Los Angeles, CA"],
        "contacts": [],
        "conversation_ids": ["cnv_1"],
        "created_at": "2026-08-20T00:00:00Z",
        "updated_at": "2026-08-26T00:00:00Z",
        "merge_status": "active",
    }

    service_now = service._utcnow()
    _apply_extraction(firm, extraction, now=service_now)

    assert firm.canonical_website == "canonical.example"
    assert firm.vendor_stack == {"case_mgmt": "filevine"}
    assert firm.research_data["summary"] == "Local summary"
    assert firm.research_data["local_enrichment"]["dirty"] is True
    assert firm.source_json["extraction_id"] == "firm-1"


def test_local_gateway_receives_identity_hints_not_extraction_notes(monkeypatch):
    captured = {}

    async def fake_call_skill_json(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(parsed={
            "canonical_website": "examplelaw.com",
            "website_confidence": 0.9,
            "website_sources": ["https://examplelaw.com"],
            "summary": "PI firm",
            "practice_areas": ["Personal injury"],
            "founded_year": None,
            "firm_size": "15-50",
            "office_locations": ["Los Angeles, CA"],
            "social_media": {},
            "sources": ["https://examplelaw.com"],
            "leadership": [],
            "staff": [],
            "vendor_stack": {"case_mgmt": None, "other": {}, "evidence": []},
        })

    monkeypatch.setattr(service, "call_skill_json", fake_call_skill_json)
    firm = PifFirmRow(
        id="firm-1",
        firm_name="Example Injury Law",
        entity_type="pi_law_firm",
        website="examplelaw.com",
        source_json={
            "emails": ["intake@examplelaw.com"],
            "phones": ["+13105551212"],
            "addresses": ["Los Angeles, CA"],
            "extraction_notes": "Patient-sensitive source text",
            "conversation_ids": ["cnv_secret"],
        },
    )

    result = asyncio.run(service.research_firm_locally(firm))

    assert captured["model"] == "openclaw/main"
    assert captured["payload"]["observed_domains"] == ["examplelaw.com"]
    assert "extraction_notes" not in captured["payload"]
    assert "conversation_ids" not in captured["payload"]
    assert result["canonical_website"] == "examplelaw.com"


def test_normalize_enrichment_rejects_unsourced_people_and_consumer_domain():
    normalized = service.normalize_enrichment({
        "canonical_website": "gmail.com",
        "website_confidence": 2,
        "leadership": [
            {"name": "No Source"},
            {"name": "Avery Owner", "source_url": "https://example.com/team/avery"},
        ],
        "staff": [],
        "vendor_stack": {"evidence": [{"vendor": "filevine"}]},
    })

    assert normalized["canonical_website"] is None
    assert [person["name"] for person in normalized["leadership"]] == ["Avery Owner"]
    assert normalized["vendor_stack"]["evidence"] == []


def test_merge_people_never_replaces_existing_operator_facts_with_empty_values():
    merged = service._merge_people(
        [{"name": "Avery Owner", "title": "Managing Partner", "email": "avery@example.com"}],
        [
            {
                "name": "Avery Owner",
                "title": None,
                "email": "avery@example.com",
                "phone": "+13105550100",
                "source_url": "https://example.com/avery",
            },
            {"name": "New Staff", "title": "Case Manager", "source_url": "https://example.com/staff"},
        ],
    )

    assert merged[0]["title"] == "Managing Partner"
    assert merged[0]["phone"] == "+13105550100"
    assert merged[0]["source_url"] == "https://example.com/avery"
    assert [person["name"] for person in merged] == ["Avery Owner", "New Staff"]


def test_merge_vendor_stack_preserves_existing_values_and_unions_evidence():
    merged = service._merge_vendor_stack(
        {
            "case_mgmt": "filevine",
            "evidence": [{"vendor": "filevine", "source_url": "https://example.com/jobs"}],
        },
        {
            "case_mgmt": None,
            "other": {"call_tracking": "callrail"},
            "evidence": [
                {"vendor": "filevine", "source_url": "https://example.com/jobs"},
                {"vendor": "callrail", "source_url": "https://example.com/privacy"},
            ],
        },
    )

    assert merged["case_mgmt"] == "filevine"
    assert merged["other"] == {"call_tracking": "callrail"}
    assert len(merged["evidence"]) == 2


def test_progress_summary_counts_completed_failed_and_skipped_stages():
    stages = service._stage_list()
    stages[0]["status"] = "completed"
    stages[1]["status"] = "failed"
    stages[2]["status"] = "skipped"

    summary = service._progress_summary("Example Law", current_stage="behavior", stages=stages)

    assert summary["progress_percent"] == 38
    assert summary["warning_count"] == 1
    assert summary["current_stage"] == "behavior"


def test_full_pipeline_reports_every_stage_before_finalizing(monkeypatch):
    firm = PifFirmRow(id="firm-1", firm_name="Example Law")
    events = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, key):
            return firm

    async def fake_set_stage(task_id, key, status, **kwargs):
        events.append((key, status))

    async def fake_research(_firm):
        return {"leadership": [], "staff": [], "vendor_stack": {}}

    async def fake_persist(task_id, result):
        return {"leadership_count": 0}

    async def fake_optional(task_id, key, operation):
        events.append((key, "in_progress"))
        events.append((key, "completed"))
        return {}

    async def fake_finalize(task_id, status, **kwargs):
        events.append(("final", status))

    monkeypatch.setattr(service, "AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr(service, "_set_stage", fake_set_stage)
    monkeypatch.setattr(service, "research_firm_locally", fake_research)
    monkeypatch.setattr(service, "_persist_research_result", fake_persist)
    monkeypatch.setattr(service, "_run_optional_stage", fake_optional)
    monkeypatch.setattr(service, "_finalize_task", fake_finalize)

    asyncio.run(service._run_task("task-1", "firm-1"))

    assert events == [
        ("web_research", "in_progress"),
        ("web_research", "completed"),
        ("persist_research", "in_progress"),
        ("persist_research", "completed"),
        ("sitemap", "in_progress"),
        ("sitemap", "completed"),
        ("behavior", "in_progress"),
        ("behavior", "completed"),
        ("contact_intelligence", "in_progress"),
        ("contact_intelligence", "completed"),
        ("contacts", "in_progress"),
        ("contacts", "completed"),
        ("job_postings", "in_progress"),
        ("job_postings", "completed"),
        ("score", "in_progress"),
        ("score", "completed"),
        ("final", "completed"),
    ]
