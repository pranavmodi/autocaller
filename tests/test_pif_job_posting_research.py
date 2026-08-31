import asyncio
from datetime import date
from types import SimpleNamespace

from app.services import pif_job_posting_research as service
from app.services.firm_intel_sync import _preserve_local_job_research


def test_normalize_job_postings_filters_dates_sources_and_duplicates():
    raw = [
        {
            "title": "Intake Specialist",
            "location": "Los Angeles, CA",
            "employment_type": "Full-time",
            "posted_date": "2026-08-15",
            "description_summary": "Handles new-client intake.",
            "responsibilities": ["Answer calls"],
            "qualifications": ["One year of experience"],
            "source_name": "Firm careers",
            "source_url": "https://example.com/jobs/intake",
        },
        {
            "title": "Intake Specialist",
            "posted_date": "2026-08-15",
            "source_url": "https://example.com/jobs/intake/",
        },
        {
            "title": "Old opening",
            "posted_date": "2026-06-01",
            "source_url": "https://example.com/jobs/old",
        },
        {
            "title": "No source",
            "posted_date": "2026-08-15",
            "source_url": "",
        },
    ]

    result = service.normalize_job_postings(
        raw,
        window_start=date(2026, 7, 28),
        window_end=date(2026, 8, 26),
    )

    assert [posting["title"] for posting in result] == ["Intake Specialist"]
    assert result[0]["posted_date"] == "2026-08-15"
    assert result[0]["source_url"] == "https://example.com/jobs/intake"
    assert result[0]["role_category"] == "intake_conversion"
    assert result[0]["classification_version"] == service.CLASSIFIER_VERSION


def test_classify_job_posting_adds_gtm_tags_and_technology_mentions():
    posting = {
        "title": "Intake Manager",
        "description_summary": "Own lead conversion and rapid follow-up for a high volume PI firm.",
        "responsibilities": ["Manage Lead Docket CRM KPIs and after-hours workflows"],
        "qualifications": ["Filevine experience preferred", "Spanish bilingual"],
        "source_url": "https://example.com/jobs/intake-manager",
    }

    result = service.classify_job_posting(posting)

    assert result["role_category"] == "intake_conversion"
    assert result["gtm_relevance"] == "high"
    assert set(result["technology_mentions"]) == {"Filevine", "Lead Docket"}
    assert {
        "rapid_lead_followup",
        "lead_conversion",
        "high_volume",
        "after_hours_or_24_7",
        "crm_management",
        "case_management_system",
        "kpi_reporting",
        "workflow_automation",
        "spanish_language_capacity",
    } <= set(result["trigger_tags"])
    assert result["classification_confidence"] == 0.95


def test_classify_job_posting_preserves_existing_source_fields():
    posting = {
        "title": "Bookkeeper",
        "posted_date": "2026-08-30",
        "source_url": "https://example.com/jobs/bookkeeper",
        "description_summary": "Manage accounting.",
        "responsibilities": [],
        "qualifications": [],
    }

    result = service.classify_job_posting(posting)

    assert result["title"] == posting["title"]
    assert result["source_url"] == posting["source_url"]
    assert result["posted_date"] == posting["posted_date"]
    assert result["role_category"] == "finance_billing"


def test_gateway_research_uses_main_agent_and_emailtag_result_shape(monkeypatch):
    captured = {}

    async def fake_call_skill_json(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(parsed={"postings": []})

    monkeypatch.setattr(service, "call_skill_json", fake_call_skill_json)

    result = asyncio.run(service.research_recent_job_postings(
        "Example Injury Law",
        "example.com",
        as_of_date=date(2026, 8, 26),
    ))

    assert captured["model"] == "openclaw/main"
    assert captured["required_fields"] == ["postings"]
    assert captured["payload"] == {
        "firm_name": "Example Injury Law",
        "official_website": "example.com",
        "window_start": "2026-07-28",
        "window_end": "2026-08-26",
    }
    assert result["has_recent_openings"] is False
    assert result["window_days"] == 30
    assert result["postings"] == []


def test_local_job_research_status_marks_possibleos_as_owner():
    firm = SimpleNamespace(research_data={"identity": {"state": "CA"}})

    updated = service._research_data_with_status(firm, "queued")

    assert updated["identity"] == {"state": "CA"}
    assert updated["job_postings_research_status"] == "queued"
    assert updated["job_postings_research_provider"] == "possibleos_openclaw"


def test_emailtag_sync_does_not_overwrite_possibleos_job_research():
    local = {
        "job_postings_research_provider": "possibleos_openclaw",
        "job_postings_research_status": "completed",
        "job_postings": {"postings": [{"title": "Intake Specialist"}]},
        "last_job_postings_researched_at": "2026-08-26T10:00:00+00:00",
    }

    merged = _preserve_local_job_research(local, {"identity": {"state": "CA"}})

    assert merged["identity"] == {"state": "CA"}
    assert merged["job_postings"] == local["job_postings"]
    assert merged["job_postings_research_status"] == "completed"
