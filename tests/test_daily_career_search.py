import asyncio
import json
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from app import cli
from app.services import daily_career_search as service
from app.services.career_job_store import PROVIDER, merge_career_postings, preserve_career_postings, same_job
from app.services.career_search_web import extract_page, public_url
from app.services.pif_job_posting_research import _research_data_with_status, classify_job_posting, _finish_task
from app.services.firm_intel_sync import _preserve_local_job_research


@pytest.fixture(autouse=True)
def isolate_contract_model(monkeypatch):
    # Contract inference has its own tests. This suite tests discovery and evidence,
    # and must never call a paid external model or wait for network access.
    from app.services import job_contract_classification
    async def classify(rows):
        return rows, None
    monkeypatch.setattr(job_contract_classification, 'classify_extracted_postings', classify)


def daily_job(**changes):
    return {"id": "career_1", "title": "AI Engineer", "source_url": "https://example.com/jobs/1",
        "source_name": "Verified employer", "posted_date": "2026-08-27", "employer_posted_date": "2026-08-27",
        "first_seen_at": "2026-09-01T00:00:00+00:00", "last_checked_at": "2026-09-09T00:00:00+00:00",
        "status": "closed", "closed_at": "2026-09-09T00:00:00+00:00", "discovery_provider": PROVIDER,
        "classification_provider": PROVIDER, "remote_scope": "country_restricted", "global_remote": False,
        "colombia_eligibility": "restricted", **changes}


def test_broad_refresh_cannot_replace_verified_dates_sources_or_closed_status():
    protected = daily_job()
    broad = {"source_url": protected["source_url"], "posted_date": "2026-09-10", "first_seen_at": "2026-09-10",
             "source_name": "Search snippet", "status": "active", "global_remote": True}
    unrelated = {"title": "Paralegal", "source_url": "https://example.com/jobs/2"}
    original = deepcopy(protected)
    merged = preserve_career_postings([protected], [broad, unrelated])
    assert merged[0] == {**broad, **protected}
    assert merged[1] == unrelated
    assert protected == original
    assert preserve_career_postings([protected], []) == [protected]


def test_rerun_dedup_preserves_first_seen_and_original_date():
    first = daily_job(status="active")
    first["date_evidence"] = {"text": "Posted August 27", "source_url": first["source_url"]}
    next_check = daily_job(posted_date="2026-09-10", first_seen_at="2026-09-10", last_checked_at="2026-09-10")
    merged, count = merge_career_postings([first], [next_check, next_check])
    assert count == 0
    assert len(merged) == 1
    assert merged[0]["first_seen_at"] == first["first_seen_at"]
    assert merged[0]["posted_date"] == "2026-08-27"
    assert merged[0]["date_evidence"] == first["date_evidence"]
    assert merged[0]["last_checked_at"] == "2026-09-10"


def test_source_and_requisition_dedup_without_title_only_matching():
    assert same_job({"source_url": "https://jobs.jobvite.com/firm/job/abc/apply?utm_source=email"},
                    {"source_url": "https://jobs.jobvite.com/firm/job/abc"})
    assert same_job({"source_url": "https://a.com/1", "ats_provider": "Rippling", "requisition_id": "123"},
                    {"source_url": "https://b.com/2", "ats_provider": "rippling", "requisition_id": "123"})
    assert not same_job({"title": "Engineer", "source_url": "https://a.com/1"},
                        {"title": "Engineer", "source_url": "https://a.com/2"})


def test_routine_research_sync_and_classification_preserve_daily_rows():
    job = daily_job()
    firm = SimpleNamespace(research_data={"summary": "Do not erase", "job_postings": {"postings": [job]}})
    result = _research_data_with_status(firm, "completed", result={"postings": [], "has_recent_openings": False})
    assert result["summary"] == "Do not erase"
    assert result["job_postings"]["postings"] == [job]
    assert result["job_postings"]["has_recent_openings"] is False
    assert classify_job_posting(job) == job
    assert _preserve_local_job_research(firm.research_data, {})["job_postings"]["postings"] == [job]


def test_default_schedule_bogota_and_completed_day():
    config = service.SearchConfig()
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    assert service.next_due(config, set(), now=now).isoformat() == "2026-09-10T13:00:00+00:00"
    assert service.next_due(config, {"2026-09-10"}, now=now).isoformat() == "2026-09-11T13:00:00+00:00"
    assert not config.enabled
    with pytest.raises(ValueError):
        service.SearchConfig(local_time="25:00")


def test_partial_scheduled_run_consumes_daily_slot():
    row = SimpleNamespace(status="partial", result={"search_trigger": "scheduled"})
    assert service.run_consumes_daily_slot(row)
    row.result = {"search_trigger": "manual", "manual_search": True}
    assert not service.run_consumes_daily_slot(row)


def test_legacy_unverified_decision_is_presented_as_candidate_rejection():
    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    reason = "The current source does not verify this requisition."
    row = SimpleNamespace(
        id="run", scheduled_day="2026-09-21", status="partial", started_at=now, completed_at=now,
        result={
            "errors": [{"source_url": "https://example.com/job", "error": reason}],
            "decisions": [{
                "candidate": {"source_url": "https://example.com/job"},
                "decision": {"status": "unverified", "reason": reason},
            }],
        },
    )
    serialized = service.serialize_run(row)
    assert serialized["status"] == "completed"
    assert serialized["result"]["errors"] == []
    assert serialized["result"]["candidate_rejections"] == [{
        "source_url": "https://example.com/job", "reason": reason,
    }]


def candidate():
    return service.Candidate(firm_name="Example PI", canonical_domain="example.com", source_url="https://example.com/jobs/1",
                             employer_evidence_url="https://example.com/about", title="Engineer")


def decision(**kwargs):
    return service.Decision(candidate_id="0", status="active", reason="Primary source", direct_pi_employer=True,
        target_role_match=True, matched_target_role="AI agent engineering",
        technology_role=True, title="Engineer", employer_evidence={"source_url": "https://example.com/about", "text": "Personal injury firm"},
        role_evidence={"source_url": "https://example.com/jobs/1", "text": "Build software"},
        status_evidence={"source_url": "https://example.com/jobs/1", "text": "Apply for Engineer"}, **kwargs)


def pages():
    return [{"requested_url": "https://example.com/about", "content": "Personal injury firm"},
            {"requested_url": "https://example.com/jobs/1", "content": "Build software. Apply for Engineer. Remote (United States). Based in Latin America."}]


def test_unknown_publication_remains_unknown_not_ats_created_date():
    result = service.to_posting(candidate(), decision(ats_created_at="2026-09-01T00:00:00Z"), checked_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert result["posted_date"] is None
    assert result["ats_created_at"] == "2026-09-01T00:00:00Z"
    assert result["recency_label"] == "publication_date_unknown"


@pytest.mark.parametrize("scope,eligibility,quote", [
    ("country_restricted", "restricted", "Remote (United States)"),
    ("location_restricted", "conditional_latam", "Based in Latin America"),
    ("unclear", "unknown", None),
])
def test_llm_geography_is_preserved_not_promoted_to_global(scope, eligibility, quote):
    evidence = {"source_url": "https://example.com/jobs/1", "text": quote} if quote else None
    value = decision(work_arrangement="remote", remote_scope=scope, colombia_eligibility=eligibility, geography_evidence=evidence)
    service.validate_decision(value, pages(), today=date(2026, 9, 10))
    result = service.to_posting(candidate(), value, checked_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert result["global_remote"] is False
    assert result["remote_scope"] == scope
    assert result["colombia_eligibility"] == eligibility


def test_missing_or_fabricated_evidence_prevents_ingest():
    value = decision(posted_date="2026-09-01")
    with pytest.raises(ValueError, match="publication date lacks evidence"):
        service.validate_decision(value, pages(), today=date(2026, 9, 10))
    value = decision()
    value.status_evidence.text = "Invented active application"
    with pytest.raises(ValueError, match="excerpt not found"):
        service.validate_decision(value, pages(), today=date(2026, 9, 10))
    value = decision()
    value.direct_pi_employer = False
    with pytest.raises(ValueError, match="not a direct PI"):
        service.validate_decision(value, pages(), today=date(2026, 9, 10))


def test_direct_import_downgrades_only_unverified_optional_claims():
    value = decision(
        legal_domain_employer=False, legal_domain_kind="unclear",
        work_arrangement="remote", remote_scope="global", colombia_eligibility="explicit",
        geography_evidence={"source_url": "https://example.com/jobs/1", "text": "Worldwide"},
        posted_date="2026-09-01",
        date_evidence={"source_url": "https://example.com/jobs/1", "text": "Posted September 1"},
    )
    with pytest.raises(ValueError, match="geography_evidence"):
        service.validate_decision(value, pages(), today=date(2026, 9, 10), direct_import=True)
    downgraded = service.downgrade_unverified_optional_evidence(value, pages())
    assert downgraded.work_arrangement == "unclear"
    assert downgraded.direct_pi_employer is False
    assert downgraded.remote_scope == "unclear"
    assert downgraded.colombia_eligibility == "unknown"
    assert downgraded.geography_evidence is None
    assert downgraded.posted_date is None and downgraded.date_evidence is None
    service.validate_decision(downgraded, pages(), today=date(2026, 9, 10), direct_import=True)


def test_application_contact_normalizes_missing_optional_labels():
    contact = service.ApplicationContact.model_validate({
        "email": "jobs@example.com", "name": None, "title": None, "kind": "recruiting",
        "evidence": {"source_url": "https://example.com/careers", "text": "jobs@example.com"},
    })
    assert contact.name == "" and contact.title == ""


@pytest.mark.asyncio
async def test_url_import_retry_replays_fresh_required_evidence_without_model(monkeypatch):
    raw_decision = decision(
        work_arrangement="remote", remote_scope="global", colombia_eligibility="explicit",
        geography_evidence={"source_url": "https://example.com/jobs/1", "text": "Worldwide"},
        posted_date="2026-09-01",
        date_evidence={"source_url": "https://example.com/jobs/1", "text": "Posted September 1"},
    ).model_dump(mode="json")
    prior = [("old-run", {"verification_rejections": [{
        "candidate": candidate().model_dump(mode="json"),
        "original_decision": raw_decision,
    }]})]

    async def fetch(url):
        content = "Personal injury firm" if url.endswith("/about") else "Build software. Apply for Engineer."
        return {"requested_url": url, "final_url": url, "http_status": 200, "content": content}

    async def ingest(_candidate, posting):
        assert posting["remote_scope"] == "unclear" and posting["posted_date"] is None
        return {"firm_id": "firm-1", "job_id": posting["id"], "added": 1,
                "source_url": posting["source_url"]}

    monkeypatch.setattr(service, "fetch_page", fetch)
    monkeypatch.setattr(service, "ingest", ingest)
    monkeypatch.setattr(service, "ingest_application_contacts", AsyncMock(return_value={
        "verified": 0, "inserted": 0, "updated": 0, "existing": 0,
    }))
    result = await service.replay_url_import_evidence(
        "https://example.com/jobs/1", prior,
        checked_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    assert result["replayed_from_run"] == "old-run"
    assert result["decision"]["colombia_eligibility"] == "unknown"
    assert result["stored"]["firm_id"] == "firm-1"


def test_manual_profile_accepts_verified_legal_tech_but_scheduled_search_does_not():
    value = decision()
    value.direct_pi_employer = False
    value.legal_domain_employer = True
    value.legal_domain_kind = "legal_tech"
    profile = service.SearchProfile(
        target_roles="AI agent engineering",
        preferred_industries="Legal technology",
        location_preferences="Remote from Colombia",
    )
    service.validate_decision(value, pages(), today=date(2026, 9, 10), search_profile=profile)
    with pytest.raises(ValueError, match="direct PI"):
        service.validate_decision(value, pages(), today=date(2026, 9, 10))


def test_application_contact_evidence_accepts_the_same_normalized_source_url():
    value = decision(application_contacts=[{
        "email": "jobs@example.com",
        "name": "Recruiting",
        "title": "Recruiting",
        "kind": "recruiting",
        "evidence": {
            "source_url": "https://example.com/contact#jobs",
            "text": "Recruiting jobs@example.com",
        },
    }])
    source_pages = pages() + [{
        "requested_url": "https://example.com/contact/?utm_source=careers",
        "content": "Recruiting jobs@example.com",
    }]

    service.validate_decision(value, source_pages, today=date(2026, 9, 10))


@pytest.mark.asyncio
async def test_manual_search_skips_an_exact_job_found_in_an_earlier_run(monkeypatch):
    profile = service.SearchProfile(
        target_roles="AI agent engineering",
        preferred_industries="Legal technology",
        location_preferences="Remote from Colombia",
        source_ids=["remotive", "remoteok"],
        source_urls=["https://remotive.com/feed", "https://remoteok.com/api"],
    )
    raw = candidate().model_dump(mode="json")
    calls = []
    async def llm(*args, **kwargs):
        calls.append(args[0])
        return {"candidates": [raw]}
    async def known():
        return {service.source_identity(raw["source_url"])}
    async def checkpoint(*args):
        pass
    async def no_fetch(*args, **kwargs):
        pytest.fail("a known source must be skipped before live verification")
    monkeypatch.setattr(service, "llm", llm)
    monkeypatch.setattr(service, "known_source_identities", known)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(service, "fetch_page", no_fetch)
    audit = {"new_jobs": 0, "verified": 0, "closed": 0, "rejected": 0, "candidates": 0,
             "duplicates_skipped": 0, "llm_calls": 0, "errors": [], "attempt_errors": [],
             "stored": [], "decisions": [], "usage": []}
    await service.execute("manual", service.SearchConfig(), seed_only=False, audit=audit,
                          search_profile=profile)
    assert len(calls) == 1
    assert set(calls[0]["career_sources"]) == {"https://remotive.com/feed", "https://remoteok.com/api"}
    assert audit["search_source_ids"] == ["remotive", "remoteok"]
    assert audit["candidates"] == 0
    assert audit["duplicates_skipped"] == 1


def test_page_extraction_keeps_ats_dates_and_application_metadata():
    content = extract_page('<h1>Engineer</h1><script id="__NEXT_DATA__">{"props":{"pageProps":{"apiData":{"jobPost":{"createdOn":"2026-09-01","active":true}}}}}</script>')
    assert "Engineer" in content and "createdOn" in content and '"active": true' in content


@pytest.mark.asyncio
async def test_private_source_is_rejected():
    with pytest.raises(ValueError, match="non-public"):
        await public_url("https://127.0.0.1/jobs")


@pytest.mark.asyncio
async def test_transient_failure_does_not_close_tracked_job(monkeypatch):
    item = {"candidate": candidate(), "tracked": daily_job(status="active"), "firm_id": "1"}
    checks = []
    async def tracked(_limit): return [item]
    async def fetch(_url): raise RuntimeError("HTTP 503")
    async def checked(item, **kwargs): checks.append(kwargs)
    async def checkpoint(*_args): pass
    async def llm(*_args): return {"candidates": []}
    monkeypatch.setattr(service, "tracked_candidates", tracked)
    monkeypatch.setattr(service, "fetch_page", fetch)
    monkeypatch.setattr(service, "mark_checked", checked)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(service, "llm", llm)
    audit = {"errors": [], "candidates": 0}
    await service.execute("test", service.SearchConfig(), seed_only=False, audit=audit)
    assert checks == [{"closed": False, "reason": "HTTP 503"}]
    assert audit["errors"]


def test_cli_configuration_and_quiet_zero_new(monkeypatch):
    seen = []
    async def config(changes):
        seen.append(changes)
        return service.SearchConfig(**changes)
    async def run(**kwargs):
        seen.append(kwargs)
        return {"status": "completed", "result": {"new_jobs": 0}}
    monkeypatch.setattr(service, "configuration", config)
    monkeypatch.setattr(service, "run", run)
    runner = CliRunner()
    result = runner.invoke(cli.app, ["pif", "career-search-config", "--enable"])
    assert result.exit_code == 0, result.exception
    assert seen[0] == {"enabled": True}
    result = runner.invoke(cli.app, ["pif", "career-search-run", "--due", "--quiet"])
    assert result.exit_code == 0 and result.stdout == ""


def test_cli_failure_is_not_success(monkeypatch):
    async def run(**kwargs): return {"status": "failed", "result": {"errors": ["Gateway unavailable"]}}
    monkeypatch.setattr(service, "run", run)
    result = CliRunner().invoke(cli.app, ["pif", "career-search-run", "--quiet"])
    assert result.exit_code == 1
    assert "Gateway unavailable" in result.stdout


@pytest.mark.asyncio
async def test_classification_finish_locks_and_preserves_concurrent_daily_insert(monkeypatch):
    from app.services import pif_job_posting_research as jobs
    normal = {"title": "Paralegal", "source_url": "https://example.com/old"}
    new_daily = daily_job()
    firm = SimpleNamespace(firm_name="Example", research_data={"summary": "Existing", "job_postings": {"postings": [normal, new_daily]}})
    task = SimpleNamespace(pif_id="firm1", result_summary={})

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, model, key, **kwargs):
            if model is jobs.PifFirmRow:
                assert kwargs.get("with_for_update") is True
                return firm
            return task
        async def commit(self): pass

    monkeypatch.setattr(jobs, "AsyncSessionLocal", Session)
    # This classifier started before the daily row was inserted.
    await _finish_task("task", kind="classify", status="completed", result={"postings": [{**normal, "role_category": "case_operations"}]})
    assert firm.research_data["summary"] == "Existing"
    assert firm.research_data["job_postings"]["postings"][1] == new_daily
    assert firm.research_data["job_postings"]["postings"][0]["role_category"] == "case_operations"


@pytest.mark.asyncio
async def test_ingest_uses_canonical_firm_and_locked_idempotent_merge(monkeypatch):
    firm = SimpleNamespace(research_data={"summary": "Keep", "job_postings": {"postings": [{"title": "Unrelated", "source_url": "https://example.com/2"}]}})
    async def resolve(domain):
        assert domain == "example.com"
        return {"id": "canonical-1"}
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, model, key, **kwargs):
            assert key == "canonical-1" and kwargs.get("with_for_update") is True
            return firm
        async def commit(self): pass
    monkeypatch.setattr(service, "get_pif_firm_for_crud", resolve)
    monkeypatch.setattr(service, "AsyncSessionLocal", Session)
    job = daily_job(status="active")
    first = await service.ingest(candidate(), job)
    second = await service.ingest(candidate(), job)
    assert (first["added"], second["added"]) == (1, 0)
    assert first["job_id"] == "career_1"
    assert len(firm.research_data["job_postings"]["postings"]) == 2
    assert firm.research_data["summary"] == "Keep"


@pytest.mark.asyncio
async def test_gateway_retries_have_backoff_and_audited_errors(monkeypatch):
    attempts = []
    delays = []
    async def call(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise TimeoutError("gateway timeout")
        return SimpleNamespace(parsed={"candidates": []}, usage={})
    async def checkpoint(*args): pass
    async def sleep(delay): delays.append(delay)
    monkeypatch.setattr(service, "call_skill_json", call)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    audit = {"llm_calls": 0, "usage": [], "attempt_errors": []}
    result = await service.llm({"mode": "discovery"}, "candidates", service.SearchConfig(), audit, "run1")
    assert result == {"candidates": []}
    assert audit["llm_calls"] == 2 and len(delays) == 1
    assert audit["attempt_errors"][0]["error"] == "gateway timeout"
    assert attempts[0]["prompt_cache_key"] == "possibleos:career-search:v4"
    assert attempts[0]["retries"] == 1
    assert attempts[0]["allow_tools"] is True
    assert audit["prompt_cache_metrics"][0]["status"] == "unreported"


@pytest.mark.asyncio
async def test_url_import_identity_uses_raw_interactive_model_run(monkeypatch):
    attempts = []

    async def call(**kwargs):
        attempts.append(kwargs)
        return SimpleNamespace(parsed={"candidates": []}, usage={})

    async def checkpoint(*_args):
        pass

    monkeypatch.setattr(service, "call_skill_json", call)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    audit = {"llm_calls": 0, "usage": [], "attempt_errors": []}
    await service.llm(
        {"mode": "url_import"}, "candidates", service.SearchConfig(), audit, "run1",
        lane="possibleos-interactive",
    )
    assert attempts[0]["allow_tools"] is False
    assert attempts[0]["lane"] == "possibleos-interactive"


@pytest.mark.asyncio
async def test_url_import_identity_enrichment_uses_raw_interactive_lane(monkeypatch):
    attempts = []

    async def call(**kwargs):
        attempts.append(kwargs)
        return SimpleNamespace(parsed={"candidates": []}, usage={})

    async def checkpoint(*_args):
        pass

    monkeypatch.setattr(service, "call_skill_json", call)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    audit = {"llm_calls": 0, "usage": [], "attempt_errors": []}
    await service.llm(
        {"mode": "url_import_enrichment"}, "candidates", service.SearchConfig(), audit, "run1",
        lane="possibleos-interactive",
    )
    assert attempts[0]["allow_tools"] is False
    assert attempts[0]["lane"] == "possibleos-interactive"


@pytest.mark.asyncio
async def test_url_import_enrichment_can_explicitly_use_provider_native_tools(monkeypatch):
    attempts = []

    async def call(**kwargs):
        attempts.append(kwargs)
        return SimpleNamespace(parsed={"candidates": []}, usage={})

    async def checkpoint(*_args):
        pass

    monkeypatch.setattr(service, "call_skill_json", call)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    audit = {"llm_calls": 0, "usage": [], "attempt_errors": []}
    await service.llm(
        {"mode": "url_import_enrichment"}, "candidates", service.SearchConfig(), audit, "run1",
        lane="possibleos-interactive", allow_tools=True,
    )
    assert attempts[0]["allow_tools"] is True
    assert attempts[0]["lane"] == "possibleos-interactive"


@pytest.mark.asyncio
async def test_direct_import_researches_official_identity_after_incomplete_extraction(monkeypatch):
    raw = {
        "firm_name": "Example PI",
        "canonical_domain": None,
        "source_url": "https://linkedin.com/jobs/view/123",
        "employer_evidence_url": None,
        "title": "AI Engineer",
        "contact_urls": [],
    }
    enriched = {
        "firm_name": "Example PI",
        "canonical_domain": "example.com",
        "source_url": "https://linkedin.com/jobs/view/123",
        "employer_evidence_url": "https://example.com/about",
        "title": "AI Engineer",
        "contact_urls": [],
    }
    calls = []

    async def llm(payload, *_args, **_kwargs):
        calls.append(payload)
        return {"candidates": [enriched]}

    async def checkpoint(*_args):
        pass

    monkeypatch.setattr(service, "llm", llm)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(service, "invoke_openclaw_tool", AsyncMock(return_value={
        "ok": True, "toolName": "web_search", "output": {"results": []},
    }))
    audit = {"errors": [], "candidate_rejections": []}
    result = await service.recover_direct_import_candidate(
        [raw],
        source_url="https://linkedin.com/jobs/view/123",
        direct_page={
            "requested_url": "https://linkedin.com/jobs/view/123",
            "final_url": "https://linkedin.com/jobs/view/123",
            "http_status": 200,
            "content": "AI Engineer at Example PI. Apply.",
        },
        search_profile=None,
        config=service.SearchConfig(),
        audit=audit,
        run_id="run1",
    )
    assert result == [service.Candidate.model_validate(enriched)]
    assert calls[0]["mode"] == "url_import_enrichment"
    assert calls[0]["original_candidate"] == raw
    assert calls[0]["web_search_results"]["ok"] is True
    assert audit["candidate_rejections"][0]["phase"] == "url_import_identity"


@pytest.mark.asyncio
async def test_direct_import_falls_back_to_provider_native_search(monkeypatch):
    raw = {
        "firm_name": "Example PI",
        "canonical_domain": None,
        "source_url": "https://linkedin.com/jobs/view/123",
        "employer_evidence_url": None,
        "title": "AI Engineer",
        "contact_urls": [],
    }
    enriched = {
        "firm_name": "Example PI",
        "canonical_domain": "example.com",
        "source_url": "https://linkedin.com/jobs/view/123",
        "employer_evidence_url": "https://example.com/about",
        "title": "AI Engineer",
        "contact_urls": [],
    }
    calls = []

    async def llm(payload, *_args, **kwargs):
        calls.append((payload, kwargs))
        return {"candidates": [enriched]}

    async def checkpoint(*_args):
        pass

    monkeypatch.setattr(service, "llm", llm)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(
        service,
        "invoke_openclaw_tool",
        AsyncMock(side_effect=RuntimeError("web_search is disabled or no provider is available")),
    )
    audit = {"errors": [], "candidate_rejections": []}
    result = await service.recover_direct_import_candidate(
        [raw],
        source_url="https://linkedin.com/jobs/view/123",
        direct_page={
            "requested_url": "https://linkedin.com/jobs/view/123",
            "final_url": "https://linkedin.com/jobs/view/123",
            "http_status": 200,
            "content": "AI Engineer at Example PI. Apply.",
        },
        search_profile=None,
        config=service.SearchConfig(),
        audit=audit,
        run_id="run1",
    )
    assert result == [service.Candidate.model_validate(enriched)]
    payload, kwargs = calls[0]
    assert payload["research_transport"] == "provider_native_agent_search"
    assert payload["web_search_results"] is None
    assert kwargs["allow_tools"] is True
    assert audit["url_import_search"][0]["fallback"] == "provider_native_agent_search"


@pytest.mark.asyncio
async def test_direct_import_researches_official_identity_after_empty_extraction(monkeypatch):
    enriched = {
        "firm_name": "Example PI",
        "canonical_domain": "example.com",
        "source_url": "https://linkedin.com/jobs/view/123",
        "employer_evidence_url": "https://example.com/about",
        "title": "AI Engineer",
        "contact_urls": [],
    }
    calls = []

    async def llm(payload, *_args, **_kwargs):
        calls.append(payload)
        if payload["mode"] == "url_import_identity":
            return {"identities": [{
                "firm_name": "Example PI", "title": "AI Engineer",
                "source_url": "https://linkedin.com/jobs/view/123",
            }]}
        return {"candidates": [enriched]}

    async def checkpoint(*_args):
        pass

    monkeypatch.setattr(service, "llm", llm)
    monkeypatch.setattr(service, "checkpoint", checkpoint)
    monkeypatch.setattr(service, "invoke_openclaw_tool", AsyncMock(return_value={
        "ok": True, "toolName": "web_search", "output": {"results": []},
    }))
    audit = {"errors": [], "candidate_rejections": []}
    result = await service.recover_direct_import_candidate(
        [],
        source_url="https://linkedin.com/jobs/view/123",
        direct_page={
            "requested_url": "https://linkedin.com/jobs/view/123",
            "final_url": "https://linkedin.com/jobs/view/123",
            "http_status": 200,
            "content": "AI Engineer at Example PI. Apply.",
        },
        search_profile=None,
        config=service.SearchConfig(),
        audit=audit,
        run_id="run1",
    )
    assert result == [service.Candidate.model_validate(enriched)]
    assert calls[0]["mode"] == "url_import_identity"
    assert calls[1]["original_candidate"] is None
    assert "official employer identity" in calls[1]["validation_error"]


def test_shared_recruiting_source_uses_exact_host_boundaries():
    assert service.shared_recruiting_source("https://co.linkedin.com/jobs/view/123")
    assert service.shared_recruiting_source("https://jobs.example.myworkdayjobs.com/job/123")
    assert not service.shared_recruiting_source("https://linkedin.com.example.org/jobs/123")
    assert not service.shared_recruiting_source("https://employer.example/jobs/123")


def test_official_page_transport_fallback_is_same_origin_wordpress_api():
    assert service.official_page_transport_fallbacks("https://www.example.com/about-us/") == [
        "https://www.example.com/wp-json/wp/v2/pages?slug=about-us&_fields=link%2Ctitle%2Ccontent"
    ]
    assert service.official_page_transport_fallbacks("http://www.example.com/about-us/") == []


def test_json_page_extraction_decodes_unicode_for_exact_evidence():
    raw = json.dumps({
        "content": {"rendered": "Skydropx es una plataforma de gesti\u00f3n log\u00edstica"}
    }, ensure_ascii=True)
    extracted = extract_page(raw)
    assert "Skydropx es una plataforma de gestión logística" in extracted
    assert "\\u00f3" not in extracted


@pytest.mark.asyncio
async def test_direct_import_recovers_blocked_official_page_with_verified_transport(monkeypatch):
    prospect = service.Candidate(
        firm_name="Example PI",
        canonical_domain="example.com",
        source_url="https://linkedin.com/jobs/view/123",
        employer_evidence_url="https://example.com/about-us/",
        title="AI Engineer",
    )
    fetched = []

    async def fetch(url):
        fetched.append(url)
        if url == "https://example.com/about-us/":
            raise RuntimeError("unverified HTTP 403")
        return {
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "content": "Example PI official company page",
        }

    monkeypatch.setattr(service, "fetch_page", fetch)
    audit = {}
    recovered, page = await service.fetch_direct_import_employer_page(prospect, {}, audit)
    assert str(recovered.employer_evidence_url).startswith(
        "https://example.com/wp-json/wp/v2/pages?slug=about-us"
    )
    assert page["http_status"] == 200
    assert fetched == [
        "https://example.com/about-us/",
        "https://example.com/wp-json/wp/v2/pages?slug=about-us&_fields=link%2Ctitle%2Ccontent",
    ]
    assert audit["official_evidence_fetch_fallbacks"][0]["transport"] == "wordpress_rest_api"


def install_verifier_run(monkeypatch, responses, *, count=1):
    from pydantic import HttpUrl
    items, decisions, fetched = [], [], {}
    for index in range(count):
        url = f"https://example.com/jobs/{index + 1}"
        prospect = candidate().model_copy(update={"source_url": HttpUrl(url)})
        raw = decision().model_dump(mode="json")
        raw["candidate_id"] = str(index)
        for field in ("role_evidence", "status_evidence"):
            raw[field]["source_url"] = url
        decisions.append(raw)
        items.append({"candidate": prospect})
        fetched[url] = {"requested_url": url, "final_url": url, "http_status": 200, "content": pages()[1]["content"]}
    fetched["https://example.com/about"] = {"requested_url": "https://example.com/about", "final_url": "https://example.com/about",
                                          "http_status": 200, "content": pages()[0]["content"]}
    calls, stored, checkpoints, fetches = [], [], [], []

    async def tracked(_limit): return items
    async def fetch(url):
        fetches.append(url)
        return fetched[url]
    async def save(run_id, audit, *args): checkpoints.append(deepcopy(audit))
    async def gateway(**kwargs):
        calls.append(deepcopy(kwargs))
        answer = responses[len(calls) - 1](decisions) if callable(responses[len(calls) - 1]) else responses[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(parsed=deepcopy(answer), usage={})
    async def ingest(prospect, posting):
        stored.append(posting)
        return {"firm_id": "existing-firm", "job_id": posting["id"], "added": 1}
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return SimpleNamespace(config={"source_urls": ["https://example.com/about"]})
    monkeypatch.setattr(service, "tracked_candidates", tracked)
    monkeypatch.setattr(service, "fetch_page", fetch)
    monkeypatch.setattr(service, "checkpoint", save)
    monkeypatch.setattr(service, "call_skill_json", gateway)
    monkeypatch.setattr(service, "ingest", ingest)
    monkeypatch.setattr(service, "AsyncSessionLocal", Session)
    monkeypatch.setattr(service, "SEEDS", SimpleNamespace(read_text=lambda: '{"candidates": []}'))
    audit = {"new_jobs": 0, "verified": 0, "closed": 0, "rejected": 0, "candidates": 0,
             "llm_calls": 0, "errors": [], "attempt_errors": [], "stored": [{"job_id": "previous-success"}], "decisions": [], "usage": []}
    return audit, calls, stored, checkpoints, fetches


def paraphrased(decisions):
    rows = deepcopy(decisions)
    rows[0]["employer_evidence"]["text"] = "The firm handles personal injury cases."
    return {"decisions": rows}


@pytest.mark.asyncio
async def test_bad_quote_is_audited_then_repaired_and_ingested(monkeypatch):
    audit, calls, stored, checkpoints, fetches = install_verifier_run(
        monkeypatch, [paraphrased, lambda rows: {"decisions": [rows[0]]}], count=2)
    await service.execute("test", service.SearchConfig(), seed_only=True, audit=audit)
    assert len(calls) == audit["llm_calls"] == 2
    assert audit["repair_calls"] == 1
    assert len(stored) == audit["new_jobs"] == 2
    assert audit["errors"] == []
    assert audit["stored"][0]["job_id"] == "previous-success"
    rejected = audit["verification_rejections"][0]
    assert rejected["original_decision"]["employer_evidence"] == {
        "source_url": "https://example.com/about", "text": "The firm handles personal injury cases."}
    assert "employer_evidence excerpt not found" in rejected["validation_error"]
    assert len(rejected["pages"][0]["sha256"]) == 64
    repair = calls[1]["payload"]
    assert repair["mode"] == "verification_repair"
    assert len(repair["candidates"]) == 1
    assert repair["candidates"][0]["candidate_id"] == "0"
    assert repair["candidates"][0]["pages"] == calls[0]["payload"]["candidates"][0]["pages"]
    assert len(fetches) == 3  # Two jobs plus one shared employer page; no repair fetch.
    assert any(snapshot.get("repair_calls") == 1 and snapshot["verified"] == 1 for snapshot in checkpoints)
    assert all(call["schema_repair_retries"] == 0 for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_response", [paraphrased, TimeoutError("repair timeout")])
async def test_failed_repair_never_ingests_bad_row_and_keeps_valid_ids(monkeypatch, repair_response):
    audit, calls, stored, _, _ = install_verifier_run(monkeypatch, [paraphrased, repair_response], count=2)
    await service.execute("test", service.SearchConfig(max_attempts=3), seed_only=True, audit=audit)
    assert len(calls) == 2  # Repair transport failure is not retried.
    assert len(stored) == audit["new_jobs"] == 1
    assert audit["stored"][0]["job_id"] == "previous-success"
    assert audit["errors"][0]["status"] == "unverified"
    assert audit["errors"][0]["source_url"] == "https://example.com/jobs/1"
    assert len(audit["verification_rejections"]) >= 2


@pytest.mark.asyncio
async def test_valid_batch_has_no_repair_or_extra_llm_call(monkeypatch):
    audit, calls, stored, _, _ = install_verifier_run(monkeypatch, [lambda rows: {"decisions": rows}], count=2)
    await service.execute("test", service.SearchConfig(), seed_only=True, audit=audit)
    assert len(calls) == audit["llm_calls"] == 1
    assert len(stored) == 2
    assert not audit.get("repair_calls") and not audit.get("verification_rejections")


@pytest.mark.asyncio
@pytest.mark.parametrize("initial", [
    {"decisions": "malformed array"},
    service.LLMGatewayResponseError("invalid JSON", raw_response='{"decisions": broken', parsed_response={}),
    lambda rows: {"decisions": [{**rows[0], "remote_scope": "invented_scope"}]},
])
async def test_schema_failure_gets_one_audited_repair(monkeypatch, initial):
    audit, calls, stored, _, _ = install_verifier_run(monkeypatch, [initial, lambda rows: {"decisions": rows}])
    await service.execute("test", service.SearchConfig(), seed_only=True, audit=audit)
    assert len(calls) == 2 and len(stored) == 1
    assert audit["errors"] == []
    assert audit["verification_rejections"][0]["original_decision"]
    assert calls[1]["payload"]["candidates"][0]["validation_error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,parsed,error", [
    ('{"jobs": []}', {"jobs": []}, "gateway JSON missing required fields decisions"),
    ('{"decisions": broken', {}, "gateway returned invalid JSON"),
])
async def test_real_gateway_wrapper_uses_observed_shape_failure_for_one_repair(monkeypatch, raw, parsed, error):
    from app.services.llm_gateway import LLMGatewayError
    audit, _, stored, checkpoints, _ = install_verifier_run(monkeypatch, [])
    calls = []

    async def gateway(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            await kwargs["attempt_observer"]({
                "phase": "failed", "attempt": 1, "model": "openclaw/main", "http_status": 200,
                "raw_response": raw, "parsed_response": parsed, "error": error, "will_retry": False,
                "usage": {"prompt_tokens": 100},
            })
            raise LLMGatewayError(f"gateway call failed after 1 attempts: {error}")
        return SimpleNamespace(parsed={"decisions": [decision().model_dump(mode="json")]}, usage={})

    monkeypatch.setattr(service, "call_skill_json", gateway)
    await service.execute("test", service.SearchConfig(max_attempts=3), seed_only=True, audit=audit)
    assert [call["payload"]["mode"] for call in calls] == ["verification", "verification_repair"]
    assert len(stored) == 1 and audit["llm_calls"] == 2 and audit["repair_calls"] == 1
    assert audit["errors"] == [] and audit["attempt_errors"] == []
    failure = audit["gateway_failures"][0]
    assert failure["raw_response"] == raw and failure["parsed_response"] == parsed
    assert failure["error"] == error and failure["usage"] == {"prompt_tokens": 100}
    assert audit["usage"][0] == {"prompt_tokens": 100}
    repair = calls[1]["payload"]["candidates"][0]
    assert repair["original_decision"]["invalid_response"] == raw
    assert repair["original_decision"]["parsed_response"] == parsed
    assert error in repair["validation_error"]
    assert any(snapshot.get("gateway_failures") and snapshot["llm_calls"] == 1 for snapshot in checkpoints)


@pytest.mark.asyncio
async def test_observed_transport_failure_still_retries_verification_not_repair(monkeypatch):
    from app.services.llm_gateway import LLMGatewayError
    audit, _, stored, _, _ = install_verifier_run(monkeypatch, [])
    calls, delays = [], []

    async def gateway(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            await kwargs["attempt_observer"]({"phase": "failed", "http_status": 502,
                "raw_response": "Bad Gateway", "error": "HTTP 502", "will_retry": False})
            raise LLMGatewayError("gateway call failed after 1 attempts: HTTP 502")
        return SimpleNamespace(parsed={"decisions": [decision().model_dump(mode="json")]}, usage={})
    async def sleep(delay): delays.append(delay)

    monkeypatch.setattr(service, "call_skill_json", gateway)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    await service.execute("test", service.SearchConfig(), seed_only=True, audit=audit)
    assert [call["payload"]["mode"] for call in calls] == ["verification", "verification"]
    assert len(delays) == 1 and len(stored) == 1
    assert not audit.get("repair_calls") and len(audit["attempt_errors"]) == 1
    assert audit["gateway_failures"][0]["usage"] is None


@pytest.mark.asyncio
async def test_cross_page_quote_is_not_accepted_until_llm_corrects_citation(monkeypatch):
    quote = "Specializing in all types of accident claims"
    def wrong_page(rows):
        result = deepcopy(rows)
        result[0]["employer_evidence"] = {"source_url": "https://example.com/about", "text": quote}
        return {"decisions": result}
    def repair(rows):
        result = wrong_page(rows)
        result["decisions"][0]["employer_evidence"]["source_url"] = "https://example.com/jobs/1"
        return result
    audit, calls, stored, snapshots, _ = install_verifier_run(monkeypatch, [wrong_page, repair])
    original_fetch = service.fetch_page
    async def fetch(url):
        page = await original_fetch(url)
        if "/jobs/" in url:
            page = {**page, "content": page["content"] + " " + quote}
        return page
    monkeypatch.setattr(service, "fetch_page", fetch)
    await service.execute("test", service.SearchConfig(), seed_only=True, audit=audit)
    assert len(calls) == 2 and len(stored) == 1 and not audit["errors"]
    rejection = audit["verification_rejections"][0]
    assert rejection["original_decision"]["employer_evidence"]["source_url"] == "https://example.com/about"
    assert rejection["evidence_source_matches"]["employer_evidence"] == ["https://example.com/jobs/1"]
    assert calls[1]["payload"]["candidates"][0]["evidence_source_matches"] == rejection["evidence_source_matches"]
    assert any(s.get("verification_rejections") and not s["verified"] for s in snapshots)


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_valid", [True, False])
async def test_candidate_domain_mismatch_retains_raw_and_gets_one_strict_repair(monkeypatch, repair_valid):
    raw = candidate().model_dump(mode="json")
    raw["employer_evidence_url"] = "https://wrong.example/about"
    original = deepcopy(raw)
    calls, snapshots = [], []
    async def fetch(url):
        return {"requested_url": url, "final_url": url, "http_status": 200, "content": "Example PI personal injury firm"}
    async def save(_id, audit): snapshots.append(deepcopy(audit))
    async def llm(payload, *args):
        calls.append(payload)
        fixed = {**raw, "candidate_id": "0", "employer_evidence_url": "https://example.com/"} if repair_valid else {**raw, "candidate_id": "0"}
        return {"candidates": [fixed]}
    monkeypatch.setattr(service, "fetch_page", fetch)
    monkeypatch.setattr(service, "checkpoint", save)
    monkeypatch.setattr(service, "llm", llm)
    audit = {"errors": []}
    recovered = await service.recover_candidates([raw, candidate().model_dump(mode="json")], service.SearchConfig(), audit, "retry")
    assert len(calls) == audit["candidate_repair_calls"] == 1
    assert len(calls[0]["candidates"]) == 1  # Valid candidates do not enter repair.
    assert audit["candidate_rejections"][0]["original_candidate"] == original == raw
    assert len(recovered) == (2 if repair_valid else 1)
    assert bool(audit["errors"]) is not repair_valid
    assert snapshots[0]["candidate_rejections"][0]["original_candidate"] == original
    assert audit["candidate_repair_responses"]


@pytest.mark.asyncio
async def test_valid_candidates_do_not_fetch_or_call_repair(monkeypatch):
    async def unexpected(*args, **kwargs): pytest.fail("no repair needed")
    async def save(*args): pass
    monkeypatch.setattr(service, "fetch_page", unexpected)
    monkeypatch.setattr(service, "llm", unexpected)
    monkeypatch.setattr(service, "checkpoint", save)
    assert await service.recover_candidates([candidate().model_dump(mode="json")], service.SearchConfig(), {}, "run") == [candidate()]


def test_retry_inputs_only_failed_sources_and_keeps_original_history():
    raw = candidate().model_dump(mode="json")
    prior = {"errors": [{"source_url": raw["source_url"], "error": "quote absent"},
                         {"phase": "candidate_validation", "error": "legacy mismatch"}],
             "verification_rejections": [{"candidate": raw}, {"candidate": raw},
                                        {"candidate": {**raw, "source_url": "https://example.com/success"}}],
             "stored": [{"job_id": "successful-existing"}]}
    before = deepcopy(prior)
    retry = service.retry_inputs(prior)
    assert retry["candidates"] == [raw]
    assert retry["career_sources"] == [raw["employer_evidence_url"]]
    assert len(retry["legacy_errors"]) == 1
    assert prior == before


def test_cli_targeted_retry_routes_file_and_rejects_due(monkeypatch, tmp_path):
    calls = []
    async def run(**kwargs):
        calls.append(kwargs)
        return {"status": "completed", "result": {"new_jobs": 0}}
    monkeypatch.setattr(service, "run", run)
    path = tmp_path / "candidates.json"
    path.write_text('{"candidates": []}')
    runner = CliRunner()
    result = runner.invoke(cli.app, ["pif", "career-search-run", "--retry-run", "prior", "--candidates-file", str(path)])
    assert result.exit_code == 0, result.output
    assert calls == [{"due_only": False, "seed_only": False, "retry_run": "prior", "retry_candidates": []}]
    assert runner.invoke(cli.app, ["pif", "career-search-run", "--retry-run", "prior", "--due"]).exit_code != 0
    assert runner.invoke(cli.app, ["pif", "career-search-run", "--candidates-file", str(path)]).exit_code != 0
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_targeted_retry_excludes_unrelated_rechecks_and_discovery(monkeypatch):
    audit, calls, stored, _, _ = install_verifier_run(monkeypatch, [lambda rows: {"decisions": rows}])
    raw = candidate().model_dump(mode="json")
    tracked_calls = []
    async def tracked(limit, source_urls=None):
        tracked_calls.append((limit, source_urls))
        return []
    monkeypatch.setattr(service, "tracked_candidates", tracked)
    prior = {"errors": [{"phase": "candidate_validation", "error": "missing original"}]}
    await service.execute("retry", service.SearchConfig(), seed_only=False, audit=audit,
                          retry_result=prior, retry_candidates=[raw])
    assert tracked_calls == [(10, [raw["source_url"]])]
    assert [c["payload"]["mode"] for c in calls] == ["verification"]
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_status_recovery_success_does_not_complete_normal_daily_slot(monkeypatch):
    now = datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
    row = SimpleNamespace(id="retry", scheduled_day="2026-09-12", status="completed",
                          started_at=now, completed_at=now, result={"retry_of": "old"})
    async def config(): return service.SearchConfig(enabled=True)
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def scalars(self, *args): return SimpleNamespace(all=lambda: [row])
        async def scalar(self, *args): return None  # Saved-search migration not installed.
    monkeypatch.setattr(service, "configuration", config)
    monkeypatch.setattr(service, "AsyncSessionLocal", Session)
    monkeypatch.setattr(service, "now_utc", lambda: now)
    result = await service.status()
    assert result["next_due_at"] == "2026-09-12T13:00:00+00:00"


@pytest.mark.parametrize("host", ["jobs.jobvite.com", "firm.greenhouse.io", "ats.rippling.com", "linkedin.com"])
def test_shared_ats_domain_is_never_canonical_employer(host):
    with pytest.raises(ValueError, match="shared recruiting platform"):
        service.Candidate(**{**candidate().model_dump(mode="json"), "canonical_domain": host,
                             "employer_evidence_url": f"https://{host}/firm/job/1"})


@pytest.mark.asyncio
async def test_candidate_repair_cannot_promote_jobvite_to_canonical_employer(monkeypatch):
    source = "https://jobs.jobvite.com/jacobyandmeyerscareers/job/ovuGzfwY"
    raw = {"firm_name": "Jacoby & Meyers", "canonical_domain": "jacobyandmeyers.com",
           "employer_evidence_url": source, "source_url": source, "title": "Salesforce Developer"}
    async def fetch(url):
        return {"requested_url": url, "final_url": url, "http_status": 200, "content": "Personal injury firm"}
    async def save(*args): pass
    async def llm(*args): return {"candidates": [{**raw, "candidate_id": "0", "canonical_domain": "jobs.jobvite.com"}]}
    monkeypatch.setattr(service, "fetch_page", fetch)
    monkeypatch.setattr(service, "checkpoint", save)
    monkeypatch.setattr(service, "llm", llm)
    audit = {"errors": []}
    assert await service.recover_candidates([raw], service.SearchConfig(), audit, "retry") == []
    assert "shared recruiting platform" in audit["errors"][0]["error"]
