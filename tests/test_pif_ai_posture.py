from datetime import datetime, timezone

import pytest

from app.services.pif_ai_posture import normalize_ai_posture, store_ai_posture
from app.services import pif_change_detection as detector
from app.services.firm_intel_sync import _preserve_local_job_research


def posture():
    return normalize_ai_posture({
        "adoption_stage": "piloting",
        "leadership_stance": "cautious",
        "summary": "The managing partner described a supervised intake pilot.",
        "confidence": 0.9,
        "statements": [{
            "speaker_name": "Alex Owner",
            "speaker_title": "Managing Partner",
            "source_url": "https://example.com/news/ai-pilot",
            "source_type": "firm_news",
            "published_at": "2026-09-09",
            "quote": "We are piloting supervised AI intake.",
            "summary": "A firm AI intake pilot with human review.",
            "scope": "firm_adoption",
            "tools": [],
            "use_cases": ["Intake"],
        }],
    })


def test_posture_requires_valid_sources_and_preserves_dates():
    value = posture()
    assert value["statements"][0]["published_at"] == "2026-09-09"
    value["statements"][0]["source_url"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="invalid_ai_adoption_research"):
        normalize_ai_posture(value)


def test_absence_of_evidence_is_unknown_not_opposed():
    value = normalize_ai_posture({"adoption_stage": "restricted", "leadership_stance": "opposed"})
    assert value["adoption_stage"] == value["leadership_stance"] == "unknown"
    assert value["confidence"] == 0


def test_changed_posture_archives_previous_evidence_and_missing_payload_preserves_it():
    first = datetime(2026, 9, 9, tzinfo=timezone.utc)
    second = datetime(2026, 9, 10, tzinfo=timezone.utc)
    data = {"summary": "Existing research"}
    store_ai_posture(data, posture(), first)
    store_ai_posture(data, None, second)
    assert data["ai_adoption"]["checked_at"] == first.isoformat()
    store_ai_posture(data, posture(), second)
    assert data["ai_adoption_history"] == []
    store_ai_posture(data, normalize_ai_posture({}), second)
    assert data["ai_adoption"]["adoption_stage"] == "unknown"
    assert data["ai_adoption_history"][0]["statements"] == posture()["statements"]
    assert data["summary"] == "Existing research"


def test_ai_snapshot_ignores_check_time_and_summary_rewording():
    first = {**posture(), "checked_at": "2026-09-09"}
    second = {**first, "checked_at": "2026-09-10", "summary": "Rephrased overall summary"}
    before = detector.normalize_profile_snapshot({"ai_adoption": first})
    after = detector.normalize_profile_snapshot({"ai_adoption": second})
    assert before == after
    assert detector.diff_profile_snapshots(before, after) == []


def test_new_ai_observations_become_candidates_not_automatic_triggers():
    after = detector.normalize_profile_snapshot({"ai_adoption": posture()})
    events = detector.diff_profile_snapshots({}, after)
    assert len(events) == 1
    assert events[0]["event_type"] == "ai_adoption_changed"
    assert events[0]["evidence"][0]["published_at"] == "2026-09-09"
    assert events[0]["new_value"]["leadership_stance"] == "cautious"
    assert detector.diff_profile_snapshots(after, {}) == []


def test_legacy_sync_preserves_local_ai_evidence_and_history():
    data = {"ai_adoption": posture(), "ai_adoption_history": [posture()]}
    result = _preserve_local_job_research(data, {"summary": "Remote profile"})
    assert result["ai_adoption"] == data["ai_adoption"]
    assert result["ai_adoption_history"] == data["ai_adoption_history"]
    assert result["summary"] == "Remote profile"


@pytest.mark.asyncio
@pytest.mark.parametrize("recent", [True, False])
async def test_ai_candidate_goes_through_batched_llm_judgment(monkeypatch, recent):
    value = posture()
    value["statements"][0]["published_at"] = "2026-09-09" if recent else "2024-01-01"
    current = detector.normalize_profile_snapshot({"ai_adoption": value})
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    candidates = detector._candidate_specs(detector.MODULE_PROFILE, {}, current, reference_time=now)
    calls = []

    async def fake_detector(**kwargs):
        calls.append(kwargs)
        return {"parsed": {"decisions": [{
            "candidate_id": candidates[0]["candidate_id"],
            "decision": "confirmed_change" if recent else "newly_discovered_existing_fact",
            "emit_trigger": recent,
            "event_type": "ai_adoption_changed" if recent else None,
            "title": "Supervised AI intake pilot",
            "summary": "Dated firm statement about a pilot.",
            "source_date": "2026-09-09" if recent else None,
            "confidence": 0.9,
            "score": 84 if recent else 0,
            "severity": 3 if recent else 1,
            "reason": "Recent source evidence" if recent else "Historical source",
        }]}, "model": "test", "provider": "test", "usage": {}}

    monkeypatch.setattr(detector, "_call_trigger_detector", fake_detector)
    accepted, metadata = await detector.evaluate_trigger_candidates(
        firm={"id": "test", "name": "Example Law"}, module=detector.MODULE_PROFILE,
        previous={}, current=current, candidates=candidates, captured_at=now,
    )
    assert len(calls) == 1
    assert bool(accepted) == recent
    assert metadata["calls"] == 1
