import asyncio
from types import SimpleNamespace

from app.db.models import PifFirmRow
from app.services import pif_local_enrichment as service
from app.services.firm_intel_sync import _apply_extraction


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
