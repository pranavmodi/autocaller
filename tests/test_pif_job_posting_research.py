import asyncio
from datetime import date, datetime, timedelta, timezone
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


def test_classify_job_posting_marks_explicit_worldwide_remote_role():
    result = service.classify_job_posting({
        "title": "Remote Intake Specialist",
        "location": "Worldwide",
        "remote_eligibility": "Work from anywhere in the world",
        "description_summary": "Support prospective clients remotely.",
    })

    assert result["work_arrangement"] == "remote"
    assert result["remote_scope"] == "global"
    assert result["global_remote"] is True
    assert "anywhere in the world" in result["global_remote_evidence"]


def test_classify_job_posting_does_not_mark_country_restricted_remote_as_global():
    result = service.classify_job_posting({
        "title": "Remote Case Manager",
        "remote_eligibility": "Remote within the United States",
        "description_summary": "Must reside in California.",
    })

    assert result["work_arrangement"] == "remote"
    assert result["remote_scope"] == "country_restricted"
    assert result["global_remote"] is False


def test_classify_job_posting_treats_plain_remote_scope_as_unclear():
    result = service.classify_job_posting({
        "title": "Remote Marketing Manager",
        "description_summary": "This is a fully remote role.",
    })

    assert result["work_arrangement"] == "remote"
    assert result["remote_scope"] == "unclear"
    assert result["global_remote"] is False


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
    assert captured["timeout_s"] == 420
    assert captured["retries"] == 1
    assert captured["schema_repair_retries"] == 1
    assert captured["payload"] == {
        "firm_name": "Example Injury Law",
        "official_website": "example.com",
        "window_start": "2026-07-28",
        "window_end": "2026-08-26",
    }
    assert result["has_recent_openings"] is False
    assert result["window_days"] == 30
    assert result["postings"] == []


def test_retry_plan_uses_exponential_backoff_and_stops_at_budget(monkeypatch):
    monkeypatch.setenv("PIF_JOB_RESEARCH_BACKOFF_SECONDS", "60")
    monkeypatch.setenv("PIF_JOB_RESEARCH_MAX_BACKOFF_SECONDS", "600")
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    first = service._retry_plan(
        "job-1",
        {"attempt_count": 1, "max_attempts": 4},
        now=now,
    )
    second = service._retry_plan(
        "job-1",
        {"attempt_count": 2, "max_attempts": 4},
        now=now,
    )

    assert first is not None
    assert second is not None
    assert 60 <= first["retry_delay_seconds"] <= 72
    assert 120 <= second["retry_delay_seconds"] <= 144
    assert first["retry_at"] == now + timedelta(seconds=first["retry_delay_seconds"])
    assert service._retry_plan(
        "job-1",
        {"attempt_count": 4, "max_attempts": 4},
        now=now,
    ) is None


def test_gateway_failure_is_requeued_with_persisted_retry_state(monkeypatch):
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    task = SimpleNamespace(
        task_id="job-1",
        pif_id="firm-1",
        kind="research",
        status="in_progress",
        requested_at=now,
        started_at=now,
        completed_at=None,
        result_summary={"attempt_count": 1, "max_attempts": 4},
    )
    firm = SimpleNamespace(research_data={}, updated_at=now)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, model, key):
            return task if model is service.PifJobResearchTaskRow else firm

        async def commit(self):
            return None

    monkeypatch.setattr(service, "AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr(service, "_utcnow", lambda: now)
    monkeypatch.setenv("PIF_JOB_RESEARCH_BACKOFF_SECONDS", "60")
    monkeypatch.setenv("PIF_JOB_RESEARCH_MAX_BACKOFF_SECONDS", "600")

    retried = asyncio.run(service._schedule_job_research_retry(
        task.task_id,
        TimeoutError(),
    ))

    assert retried is True
    assert task.status == "queued"
    assert task.started_at is None
    assert task.requested_at > now
    assert task.result_summary["last_error"] == "TimeoutError"
    assert task.result_summary["attempt_count"] == 1
    assert firm.research_data["job_postings_research_status"] == "queued"
    assert firm.research_data["job_postings_research_retry"]["retry_at"] == task.requested_at.isoformat()


def test_local_job_research_status_marks_possibleos_as_owner():
    firm = SimpleNamespace(research_data={"identity": {"state": "CA"}})

    updated = service._research_data_with_status(firm, "queued")

    assert updated["identity"] == {"state": "CA"}
    assert updated["job_postings_research_status"] == "queued"
    assert updated["job_postings_research_provider"] == "possibleos_openclaw"


def test_terminal_job_research_status_clears_retry_metadata():
    firm = SimpleNamespace(research_data={
        "job_postings_research_retry": {
            "attempt_count": 2,
            "retry_at": "2026-09-01T12:10:00+00:00",
        },
    })

    updated = service._research_data_with_status(
        firm,
        "completed",
        checked_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert "job_postings_research_retry" not in updated


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


def test_daily_stats_deduplicate_firm_and_use_latest_result():
    rows = [
        SimpleNamespace(
            pif_id="firm-1",
            status="completed",
            completed_at=datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
            result_summary={"has_recent_openings": True, "posting_count": 2},
        ),
        SimpleNamespace(
            pif_id="firm-1",
            status="completed",
            completed_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
            result_summary={"has_recent_openings": True, "posting_count": 3},
        ),
        SimpleNamespace(
            pif_id="firm-2",
            status="failed",
            completed_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
            result_summary={"message": "timeout"},
        ),
    ]

    result = service._aggregate_job_research_daily_stats(
        rows,
        days=2,
        now=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        open_counts={"queued": 7, "in_progress": 2},
    )

    assert result["today"] == {
        "date": "2026-09-01",
        "firms_processed": 2,
        "firms_completed": 1,
        "firms_failed": 1,
        "firms_with_openings": 1,
        "job_postings_found": 3,
        "research_attempts": 3,
    }
    assert result["queue"] == {"queued": 7, "in_progress": 2}
