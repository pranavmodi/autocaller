from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import pif as pif_api
from app.services import pif_change_detection as service


def _event_types(events):
    return {event["event_type"] for event in events}


def test_vendor_snapshot_normalizes_supported_stack_shapes():
    normalized = service.normalize_vendor_snapshot({
        "case_mgmt": "Filevine",
        "other": {
            "call_tracking": "CallRail",
            "intaker": {"confidence": 0.91, "source_url": "https://example.com/privacy"},
        },
        "evidence": [{
            "vendor": "Lead Docket",
            "source": "job_posting",
            "source_url": "https://example.com/jobs/intake",
            "confidence": 0.96,
        }],
    })

    assert {row["vendor"] for row in normalized.values()} == {
        "filevine", "callrail", "intaker", "lead_docket",
    }
    lead_docket = next(row for row in normalized.values() if row["vendor"] == "lead_docket")
    assert lead_docket["product"] == "Lead Docket"
    assert lead_docket["evidence"][0]["source_url"] == "https://example.com/jobs/intake"


def test_profile_diff_detects_practice_office_leadership_and_size_changes():
    previous = service.normalize_profile_snapshot({
        "practice_areas": ["Personal injury"],
        "office_locations": ["Los Angeles, CA"],
        "leadership": [{"name": "Avery Owner", "title": "Partner"}],
        "firm_size": "11-25",
    })
    current = service.normalize_profile_snapshot({
        "practice_areas": ["Personal injury", "Truck accidents"],
        "office_locations": ["Los Angeles, CA", "San Diego, CA"],
        "leadership": [
            {"name": "Avery Owner", "title": "Partner"},
            {"name": "Morgan Leader", "title": "COO"},
        ],
        "firm_size": "26-50",
    })

    assert _event_types(service.diff_profile_snapshots(previous, current)) == {
        "practice_area_added", "office_added", "leadership_added", "firm_size_changed",
    }


def test_sitemap_diff_detects_high_value_business_location_and_intake_pages():
    previous = service.normalize_sitemap_snapshot({
        "website": "example.com",
        "urls": ["https://example.com/"],
    })
    current = service.normalize_sitemap_snapshot({
        "website": "example.com",
        "urls": [
            "https://example.com/",
            "https://example.com/practice-areas/truck-accidents",
            "https://example.com/locations/san-diego",
            "https://example.com/free-case-evaluation",
        ],
    })

    assert _event_types(service.diff_sitemap_snapshots(previous, current)) == {
        "sitemap_pages_added",
        "high_value_practice_page_added",
        "location_page_added",
        "intake_surface_added",
    }


def test_job_diff_uses_classified_role_as_gtm_signal():
    previous = service.normalize_jobs_snapshot({"postings": []})
    current = service.normalize_jobs_snapshot({
        "postings": [{
            "title": "Intake Manager",
            "posted_date": "2026-09-08",
            "source_url": "https://example.com/jobs/intake-manager",
            "role_category": "intake_conversion",
            "classification_confidence": 0.93,
        }],
    })

    events = service.diff_job_snapshots(previous, current)

    assert _event_types(events) == {"intake_job_posted"}
    assert events[0]["source_date"].isoformat().startswith("2026-09-08")
    assert events[0]["evidence"][0]["source_url"] == "https://example.com/jobs/intake-manager"


def test_review_diff_detects_new_negative_review_and_operational_pain():
    previous = service.normalize_reviews_snapshot({"sources": []})
    current = service.normalize_reviews_snapshot({
        "sources": [{
            "source": "google",
            "listing_url": "https://example.com/google-listing",
            "reviews": [{
                "review_id": "review-1",
                "review_date": "2026-09-07",
                "rating": 1,
                "text": "Nobody returned my calls and I never knew what was happening.",
                "classification": {
                    "overall_sentiment": "negative",
                    "themes": [{"theme": "communication"}],
                    "failure_modes": ["unreturned_calls", "unclear_case_status"],
                    "confidence": 0.9,
                },
            }],
        }],
    })

    assert _event_types(service.diff_review_snapshots(
        previous,
        current,
        reference_time=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )) == {
        "reviews_added", "negative_reviews_added", "review_pain_detected",
    }


def test_review_diff_ignores_undated_and_stale_reviews_as_triggers():
    current = service.normalize_reviews_snapshot({
        "sources": [{
            "source": "google",
            "reviews": [
                {"review_id": "old", "review_date": "2025-01-01", "rating": 1, "text": "Old complaint"},
                {"review_id": "unknown", "review_date": None, "rating": 1, "text": "Undated complaint"},
            ],
        }],
    })

    events = service.diff_review_snapshots(
        {"reviews": {}},
        current,
        reference_time=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert events == []


@pytest.mark.asyncio
async def test_llm_detector_batches_related_false_positive_candidates(monkeypatch):
    previous = service.normalize_profile_snapshot({
        "office_locations": ["17547 Ventura Blvd, Encino, CA 91316"],
        "leadership": [{
            "name": "Michael Sabzevar",
            "title": "Principal Attorney",
            "source_url": "https://apps.calbar.ca.gov/attorney/Licensee/Detail/172312",
        }],
    })
    current = service.normalize_profile_snapshot({
        "office_locations": ["Encino, CA"],
        "leadership": [{
            "name": "Farzad Michael Sabzevar",
            "title": "Principal Attorney and Owner",
            "source_url": "https://apps.calbar.ca.gov/attorney/Licensee/Detail/172312",
        }],
    })
    candidates = service._candidate_specs(
        service.MODULE_PROFILE,
        previous,
        current,
        reference_time=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    captured = {}

    async def fake_call_trigger_detector(**kwargs):
        captured.update(kwargs)
        return {
            "parsed": {"decisions": [{
                "candidate_id": candidate["candidate_id"],
                "decision": "same_entity_or_restatement",
                "emit_trigger": False,
                "event_type": None,
                "title": "Same existing fact",
                "summary": "The before and after values describe the same entity.",
                "source_date": None,
                "confidence": 0.98,
                "score": 0,
                "severity": 1,
                "reason": "Equivalent address or matching California Bar profile.",
            } for candidate in candidates]},
            "model": "gpt-5.6-luna",
            "provider": "openai_responses",
            "usage": {"input_tokens": 900, "cached_tokens": 600},
        }

    monkeypatch.setattr(service, "_call_trigger_detector", fake_call_trigger_detector)
    accepted, summary = await service.evaluate_trigger_candidates(
        firm={"id": "firm-1", "name": "Law Offices of F. Michael Sabzevar"},
        module=service.MODULE_PROFILE,
        previous=previous,
        current=current,
        candidates=candidates,
        captured_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert len(candidates) == 2
    assert len(captured["payload"]["candidates"]) == 2
    assert captured["batch_id"]
    assert accepted == []
    assert summary["calls"] == 1
    assert summary["decision_counts"] == {"same_entity_or_restatement": 2}


@pytest.mark.asyncio
async def test_llm_detector_can_correct_a_rule_proposed_job_type(monkeypatch):
    candidate = service._event(
        "technology_job_posted",
        "New opening: PRN X-Ray Technologist Float",
        new_value={
            "title": "PRN X-Ray Technologist Float",
            "source_url": "https://example.com/jobs/xray-technologist",
        },
        evidence=[{
            "source": "job_posting",
            "source_url": "https://example.com/jobs/xray-technologist",
            "published_at": "2026-09-08",
        }],
    )
    candidate["candidate_id"] = "cand_001"

    async def fake_call_trigger_detector(**_kwargs):
        return {
            "parsed": {"decisions": [{
                "candidate_id": "cand_001",
                "decision": "not_gtm_relevant",
                "emit_trigger": False,
                "event_type": None,
                "title": "Clinical radiology opening",
                "summary": "This is a patient-care role, not a software or data role.",
                "source_date": None,
                "confidence": 0.99,
                "score": 0,
                "severity": 1,
                "reason": "Technologist refers to the clinical occupation.",
            }]},
            "model": "gpt-5.6-luna",
            "provider": "openai_responses",
            "usage": {},
        }

    monkeypatch.setattr(service, "_call_trigger_detector", fake_call_trigger_detector)
    accepted, summary = await service.evaluate_trigger_candidates(
        firm={"id": "akumin", "name": "Akumin"},
        module=service.MODULE_JOBS,
        previous={"postings": {}},
        current={"postings": {"job-1": candidate["new_value"]}},
        candidates=[candidate],
        captured_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert accepted == []
    assert summary["status"] == "completed"
    assert summary["decision_counts"] == {"not_gtm_relevant": 1}


@pytest.mark.asyncio
async def test_llm_detector_fails_closed_on_incomplete_output(monkeypatch):
    candidates = []
    for index in range(2):
        candidate = service._event(
            "practice_area_added",
            f"Candidate {index}",
            new_value={"practice_area": f"Area {index}"},
        )
        candidate["candidate_id"] = f"cand_{index + 1:03d}"
        candidates.append(candidate)

    async def fake_call_trigger_detector(**_kwargs):
        return {
            "parsed": {"decisions": []},
            "model": "gpt-5.6-luna",
            "provider": "openai_responses",
            "usage": {},
        }

    monkeypatch.setattr(service, "_call_trigger_detector", fake_call_trigger_detector)
    accepted, summary = await service.evaluate_trigger_candidates(
        firm={"id": "firm-1", "name": "Example Firm"},
        module=service.MODULE_PROFILE,
        previous={},
        current={},
        candidates=candidates,
        captured_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert accepted == []
    assert summary["status"] == "failed"
    assert summary["calls"] == 1
    assert "omitted candidates" in summary["errors"][0]


def test_candidate_batching_bounds_item_count_and_prompt_size():
    candidates = []
    for index in range(5):
        candidate = service._event(
            "sitemap_pages_added",
            f"Candidate {index}",
            new_value={"urls": [f"https://example.com/{index}/" + ("x" * 600)]},
        )
        candidate["candidate_id"] = f"cand_{index + 1:03d}"
        candidates.append(candidate)

    batches = service._candidate_batches(candidates, max_items=3, max_chars=4_000)

    assert [len(batch) for batch in batches] == [3, 2]


def test_high_icp_signal_research_uses_shorter_freshness(monkeypatch):
    monkeypatch.setenv("PIF_HIGH_ICP_SIGNAL_REFRESH_DAYS", "5")
    monkeypatch.setenv("PIF_FIRM_PROFILE_REFRESH_DAYS", "31")

    assert service.refresh_days_for(service.MODULE_JOBS, "A") == 5
    assert service.refresh_days_for(service.MODULE_REVIEWS, "B") == 5
    assert service.refresh_days_for(service.MODULE_PROFILE, "A") == 31
    assert service.refresh_days_for(service.MODULE_JOBS, "C") == 30


def test_priority_endpoint_passes_repeated_trigger_filters(monkeypatch):
    captured = {}

    async def fake_list_priority_firms(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "page": 1, "page_size": 25, "total_pages": 0}

    monkeypatch.setattr(pif_api, "list_priority_firms", fake_list_priority_firms)
    app = FastAPI()
    app.include_router(pif_api.router)
    response = TestClient(app).get(
        "/api/pif/priority-firms"
        "?event_type=vendor_added&event_type=intake_job_posted"
        "&category=technology&within_days=14&min_score=70&match_mode=all"
        "&staff_count_range=1-5&staff_count_range=26-50"
        "&icp_tier=A&icp_tier=B&entity_type=pi_law_firm&entity_type=law_firm"
        "&vendor=filevine&vendor=clio"
    )

    assert response.status_code == 200
    assert captured["event_types"] == ["vendor_added", "intake_job_posted"]
    assert captured["categories"] == ["technology"]
    assert captured["within_days"] == 14
    assert captured["min_score"] == 70
    assert captured["match_mode"] == "all"
    assert captured["staff_count_ranges"] == ["1-5", "26-50"]
    assert captured["icp_tiers"] == ["A", "B"]
    assert captured["entity_types"] == ["pi_law_firm", "law_firm"]
    assert captured["vendors"] == ["filevine", "clio"]


def test_trigger_revalidation_endpoint_passes_scope_and_limit(monkeypatch):
    captured = {}

    async def fake_revalidate_active_trigger_events(**kwargs):
        captured.update(kwargs)
        return {"considered": 3, "confirmed": 0, "deactivated": 3}

    monkeypatch.setattr(
        pif_api,
        "revalidate_active_trigger_events",
        fake_revalidate_active_trigger_events,
    )
    app = FastAPI()
    app.include_router(pif_api.router)
    response = TestClient(app).post(
        "/api/pif/triggers/revalidate?firm_id=firm-1&limit=30"
    )

    assert response.status_code == 200
    assert captured == {"pif_id": "firm-1", "limit": 30}
