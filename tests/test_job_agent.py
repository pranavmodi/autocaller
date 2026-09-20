"""Contract tests and opt-in isolated PostgreSQL persistence regression."""
import os
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.job_agent import router
from app.services import job_agent as service
from app.services import daily_career_search as career_search


def test_identity_ignores_tracking_but_is_employer_scoped():
    posting = {"firm_id": "firm-a", "source_url": "https://jobs.example.com/123?source=linkedin&utm_campaign=test"}
    assert service.candidate_id(posting) == service.candidate_id({**posting, "source_url": "https://jobs.example.com/123"})
    assert service.candidate_id(posting) != service.candidate_id({**posting, "firm_id": "firm-b"})


def test_roles_on_shared_careers_page_remain_distinct():
    posting = {"firm_id": "firm-a", "source_url": "https://example.com/careers", "title": "AI Engineer"}
    assert service.candidate_id(posting) != service.candidate_id({**posting, "title": "Operations Manager"})
    assert service.candidate_id(posting) != service.candidate_id({**posting, "location": "London"})
    assert service.candidate_id({**posting, "job_id": "123"}) == service.candidate_id({**posting, "job_id": "123", "title": "Renamed role"})


def test_leads_listing_resolves_one_canonical_stored_posting():
    request = service.ListingSelection(
        firm_id="firm-a",
        source_url="https://example.com/careers?utm_source=linkedin",
        title="AI Engineer",
        location="Remote",
    )
    postings = [
        {"title": "Operations Manager", "location": "Remote", "source_url": "https://example.com/careers"},
        {"title": "AI Engineer", "location": "Remote", "source_url": "https://example.com/careers"},
    ]
    assert service.select_stored_posting(postings, request)["title"] == "AI Engineer"


def test_leads_listing_prefers_stable_job_id_and_rejects_missing_record():
    posting = {"id": "ats-123", "title": "Renamed role", "source_url": "https://example.com/jobs/123"}
    request = service.ListingSelection(
        firm_id="firm-a", job_id="ats-123", source_url="https://example.com/old",
        title="Old title", location=None,
    )
    assert service.select_stored_posting([posting], request) is posting
    with pytest.raises(KeyError):
        service.select_stored_posting([], request)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://", ""])
def test_rejects_unsafe_source_links(url):
    with pytest.raises(ValueError):
        service.candidate_id({"firm_id": "a", "source_url": url})


@pytest.mark.parametrize("changes", [{"import_limit": 501}, {"posted_within_days": 0},
                                    {"remote_scope": "us"}, {"auto_send": True},
                                    {"collection_enabled": "false"}])
def test_configuration_rejects_invalid_or_unimplemented_controls(changes):
    with pytest.raises(ValidationError):
        service.JobAgentConfig(**changes)


def _career_pages():
    return [
        {"requested_url": "https://imaging.example/about", "content": "Precise Imaging provides medical imaging services."},
        {"requested_url": "https://imaging.example/jobs/1", "content": "Build AI agents. Apply for AI Engineer."},
    ]


def _career_decision(**changes):
    values = {
        "candidate_id": "0", "status": "active", "reason": "Primary sources", "technology_role": True,
        "title": "AI Engineer", "preferred_industry_employer": True,
        "matched_preferred_industry": "medical imaging",
        "employer_evidence": {"source_url": "https://imaging.example/about", "text": "medical imaging services"},
        "role_evidence": {"source_url": "https://imaging.example/jobs/1", "text": "Build AI agents"},
        "status_evidence": {"source_url": "https://imaging.example/jobs/1", "text": "Apply for AI Engineer"},
    }
    values.update(changes)
    return career_search.Decision(**values)


def test_manual_search_verifier_uses_configured_preferred_industries():
    profile = career_search.SearchProfile(
        target_roles="AI agents", preferred_industries="Legal technology, medical imaging; medical insurance firms",
        location_preferences="Remote from Colombia",
    )
    decision = _career_decision()
    career_search.validate_decision(decision, _career_pages(), today=datetime(2026, 9, 20).date(), search_profile=profile)
    with pytest.raises(ValueError, match="saved search profile"):
        career_search.validate_decision(
            decision.model_copy(update={"matched_preferred_industry": "pharmaceuticals"}),
            _career_pages(), today=datetime(2026, 9, 20).date(), search_profile=profile,
        )
    with pytest.raises(ValueError, match="direct PI"):
        scheduled = decision.model_copy(update={
            "preferred_industry_employer": False, "matched_preferred_industry": None,
        })
        career_search.validate_decision(scheduled, _career_pages(), today=datetime(2026, 9, 20).date())

    legacy_legal = decision.model_copy(update={
        "preferred_industry_employer": False,
        "matched_preferred_industry": None,
        "legal_domain_employer": True,
        "legal_domain_kind": "legal_tech",
    })
    career_search.validate_decision(
        legacy_legal, _career_pages(), today=datetime(2026, 9, 20).date(),
        search_profile=profile.model_copy(update={"preferred_industries": "Legal technology"}),
    )
    with pytest.raises(ValueError, match="preferred-industry"):
        career_search.validate_decision(
            legacy_legal, _career_pages(), today=datetime(2026, 9, 20).date(),
            search_profile=profile.model_copy(update={"preferred_industries": "medical imaging"}),
        )


def test_manual_search_queries_cover_each_configured_industry():
    profile = career_search.SearchProfile(
        target_roles="AI agents", preferred_industries="Legal technology, medical imaging, medical insurance firms",
        location_preferences="Remote from Colombia",
    )
    queries = career_search.profile_queries(profile, 1)
    assert any('\"medical imaging\"' in query for query in queries)
    assert any('\"medical insurance firms\"' in query for query in queries)
    medical_only = career_search.profile_queries(
        profile.model_copy(update={"preferred_industries": "medical imaging"}), 1,
    )
    assert len(medical_only) == 1 and '"medical imaging"' in medical_only[0]


@pytest.mark.asyncio
async def test_review_cannot_mark_an_application_as_sent(monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(service, "review", handler)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/job-agent/jobs/example/review", json={"revision": 1, "status": "sent", "note": ""})
    assert response.status_code == 422
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_api_conflict_explains_concurrent_edit(monkeypatch):
    monkeypatch.setattr(service, "review", AsyncMock(side_effect=ValueError("Reload before saving")))
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/job-agent/jobs/example/review", json={"revision": 1, "status": "shortlisted"})
    assert response.status_code == 409
    assert "Reload" in response.json()["detail"]


@pytest.mark.asyncio
async def test_open_leads_listing_uses_job_agent_bridge(monkeypatch):
    result = {"candidate": {"id": "candidate-1"}, "categories": [], "created": True}
    handler = AsyncMock(return_value=result)
    monkeypatch.setattr(service, "open_stored_listing", handler)
    app = FastAPI()
    app.include_router(router)
    payload = {"firm_id": "firm-a", "job_id": "job-1", "source_url": "https://example.com/job-1",
               "title": "AI Engineer", "location": "Remote"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/job-agent/listings/open", json=payload)
    assert response.status_code == 200 and response.json() == result
    handler.assert_awaited_once_with(service.ListingSelection(**payload))


@pytest.mark.asyncio
async def test_search_endpoint_starts_non_sending_discovery(monkeypatch):
    result = {"status": "queued", "message": "Searching public sources"}
    handler = AsyncMock(return_value=result)
    monkeypatch.setattr(service, "request_search", handler)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/job-agent/search", json={})
    assert response.status_code == 200 and response.json() == result
    handler.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_backend_restart_closes_orphaned_manual_search(monkeypatch):
    from types import SimpleNamespace
    from app.services import daily_career_search

    completed_at = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)
    manual = SimpleNamespace(status="running", completed_at=None, result={"manual_search": True, "errors": []})
    scheduled = SimpleNamespace(status="running", completed_at=None, result={})

    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def scalar(self, *_args, **_kwargs): return True
        async def execute(self, *_args, **_kwargs): pass
        async def commit(self): pass

    class Engine:
        def connect(self): return Connection()

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def scalars(self, *_args, **_kwargs):
            return SimpleNamespace(all=lambda: [manual, scheduled])
        async def commit(self): pass

    async def ready(): pass
    monkeypatch.setattr(daily_career_search, "ensure_tables", ready)
    monkeypatch.setattr(daily_career_search, "async_engine", Engine())
    monkeypatch.setattr(daily_career_search, "AsyncSessionLocal", Session)
    monkeypatch.setattr(daily_career_search, "now_utc", lambda: completed_at)

    assert await daily_career_search.reconcile_interrupted_manual_runs() == 1
    assert manual.status == "interrupted" and manual.completed_at == completed_at
    assert manual.result["interrupted_reason"] == "backend_restart"
    assert "No automatic retry" in manual.result["errors"][-1]["error"]
    assert scheduled.status == "running" and scheduled.completed_at is None


@pytest.mark.asyncio
async def test_restart_recovery_never_touches_an_active_search(monkeypatch):
    from app.services import daily_career_search

    class Connection:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def scalar(self, *_args, **_kwargs): return False
        async def commit(self): pass

    class Engine:
        def connect(self): return Connection()

    async def ready(): pass
    monkeypatch.setattr(daily_career_search, "ensure_tables", ready)
    monkeypatch.setattr(daily_career_search, "async_engine", Engine())
    monkeypatch.setattr(daily_career_search, "AsyncSessionLocal",
                        lambda: pytest.fail("an active worker must prevent reconciliation"))
    assert await daily_career_search.reconcile_interrupted_manual_runs() == 0


@pytest.mark.parametrize("raw, expected", [("2026-09-17", "2026-09-17"), ("unknown", None), ("2026-02-30", None), ("", None), (None, None)])
def test_posting_date_normalization(raw, expected):
    assert service.normalize_posting({"posted_date": raw})["posted_date"] == expected


def test_posting_source_normalization_supports_existing_search_rows():
    assert service.normalize_posting({"discovery_provider": "possibleos_daily_career_search"})["job_source"] == "external_search"
    assert service.normalize_posting({})["job_source"] == "possibleos"


@pytest.mark.asyncio
async def test_api_defaults_to_posting_date_and_rejects_unknown_sort(monkeypatch):
    handler = AsyncMock(return_value={"items": [], "total": 0})
    monkeypatch.setattr(service, "candidates", handler)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        assert (await client.get("/api/job-agent/jobs")).status_code == 200
        handler.assert_awaited_once_with(None, "", 1, "posted_desc", "", None)
        assert (await client.get("/api/job-agent/jobs?order=random")).status_code == 422
        assert (await client.get("/api/job-agent/jobs?source=external_search")).status_code == 200
        assert handler.await_args.args[-1] == "external_search"
        assert (await client.get("/api/job-agent/jobs?source=unknown")).status_code == 422
        assert (await client.get("/api/job-agent/events?page=0")).status_code == 422


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("JOB_AGENT_DB_TESTS") != "1", reason="Requires isolated schema on local PostgreSQL")
async def test_durable_uncapped_collection_sorting_pause_retry_and_history(monkeypatch):
    import asyncio
    import json
    from sqlalchemy import text, select, func
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db import async_engine
    from app.services import daily_career_search

    schema = "job_agent_test_" + uuid4().hex
    async with async_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(async_engine.url, connect_args={"server_settings": {"search_path": schema}})
    monkeypatch.setattr(service, "async_engine", engine)
    monkeypatch.setattr(service, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(service, "_ready", False)
    monkeypatch.setattr(service, "_wakeup", asyncio.Event())
    monkeypatch.setattr(daily_career_search, "status", AsyncMock(side_effect=RuntimeError("offline")))
    postings = [{"id": str(i), "title": f"Engineer {i:04d}", "source_url": f"https://example.com/jobs/{i}",
                 "posted_date": "2026-09-15" if i % 2 else None, "work_arrangement": "remote"} for i in range(605)]
    postings[0]["posted_date"] = "2026-09-17"
    postings[1]["posted_date"] = "2026-09-16"
    postings[2]["posted_date"] = "unknown"
    postings[3]["source_url"] = "invalid"
    postings[4]["discovery_provider"] = "possibleos_daily_career_search"

    async def source_update():
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE pif_directory_firms SET research_data = CAST(:data AS jsonb)"),
                               {"data": json.dumps({"job_postings": {"postings": postings}})})

    async def drain():
        run = await service.collect()
        while run and run["status"] == "running":
            run = await service.process_batch(run["id"])
        return run

    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE pif_directory_firms (id text PRIMARY KEY, firm_name text, entity_type text, canonical_website text, website text, research_data jsonb, source_json jsonb)"))
            await conn.execute(text("INSERT INTO pif_directory_firms VALUES ('firm-a', 'Example', 'company', NULL, NULL, '{}', '{}')"))
        await source_update()
        await service.ensure_tables()
        # Existing settings and legacy URL-only identities survive the upgrade.
        legacy_posting = {**postings[0], "firm_id": "firm-a", "firm_name": "Example", "job_id": "0"}
        async with service.AsyncSessionLocal() as session:
            session.add(service.JobAgentState(id="default", config={**service.JobAgentConfig().model_dump(), "import_limit": 100}, revision=0))
            session.add(service.JobAgentCandidate(id=service.legacy_candidate_id(legacy_posting), posting=legacy_posting,
                status="shortlisted", note="Preserve my decision", revision=1))
            await session.commit()
        assert "import_limit" not in (await service.configuration())["config"]
        # Concurrent requests coalesce into a single run.
        first, second = await asyncio.gather(service.collect(), service.collect())
        assert first["id"] == second["id"]
        run = await service.process_batch(first["id"])
        assert run["total"] == 605 and run["processed"] == 100 and run["remaining"] == 505
        assert (await service.candidates())["total"] == 99
        # Research can change while the fixed snapshot is draining.
        postings.append({"id": "new", "title": "New after snapshot", "source_url": "https://example.com/new", "posted_date": "2026-09-18"})
        await source_update()
        paused = service.JobAgentConfig(collection_enabled=False)
        await service.update_config(service.ConfigUpdate(revision=0, config=paused))
        assert await service.process_batch(run["id"]) is None
        with pytest.raises(ValueError, match="paused"):
            await service.collect()
        with pytest.raises(ValueError, match="changed"):
            await service.update_config(service.ConfigUpdate(revision=0, config=paused))
        await service.update_config(service.ConfigUpdate(revision=1, config=service.JobAgentConfig()))
        # Failed chunks roll back both rows and cursor, then resume after restart.
        original = service.upsert_posting
        calls = 0
        async def fail_mid_batch(session, posting):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise RuntimeError("simulated interruption")
            return await original(session, posting)
        monkeypatch.setattr(service, "upsert_posting", fail_mid_batch)
        with pytest.raises(RuntimeError):
            await service.process_batch(run["id"])
        assert (await service.candidates())["total"] == 99
        overview = await service.overview()
        assert overview["collection"]["processed"] == 100
        assert overview["collection"]["status"] == "failed"
        assert overview["source_error"] and overview["source"] is None
        monkeypatch.setattr(service, "upsert_posting", original)
        monkeypatch.setattr(service, "_ready", False)
        result = await drain()
        assert result["total"] == 605 and result["processed"] == 605
        assert result["added"] == 603 and result["invalid"] == 1
        assert result["status"] == "completed_with_errors"
        assert (await service.candidates())["total"] == 604
        searched = await service.candidates(source="external_search")
        assert searched["total"] == 1 and searched["items"][0]["posting"]["job_source"] == "external_search"
        assert (await service.candidates(source="possibleos"))["total"] == 603
        preserved = (await service.candidates("shortlisted"))["items"][0]
        assert preserved["note"] == "Preserve my decision" and preserved["email_status"] == "not_tracked"
        with pytest.raises(ValueError, match="changed"):
            await service.review(preserved["id"], service.ReviewUpdate(revision=1, status="skipped"))
        # Next cycle catches the new source record and closures without losing reviews.
        postings[0]["status"] = "closed"
        await source_update()
        result = await drain()
        assert result["added"] == 1 and result["updated"] == 1
        assert (await service.candidates("shortlisted"))["items"][0]["posting"]["status"] == "closed"
        assert (await drain())["added"] == 0
        assert (await service.candidates())["items"][0]["posting"]["posted_date"] == "2026-09-18"
        pages = (await service.candidates())["total_pages"]
        all_rows = [row for page in range(1, pages + 1) for row in (await service.candidates(page=page))["items"]]
        assert len(all_rows) == len({r["id"] for r in all_rows}) == 605
        dates = [r["posting"].get("posted_date") for r in all_rows]
        known = [d for d in dates if d]
        assert dates == sorted(known, reverse=True) + [None] * (len(dates) - len(known))
        assert (await service.candidates(order="posted_asc"))["items"][0]["posting"]["posted_date"] == "2026-09-15"
        # All audit history remains accessible, including records beyond 100.
        async with service.AsyncSessionLocal() as session:
            for i in range(110):
                session.add(service.JobAgentEvent(kind="test", message=str(i), details={}))
            await session.commit()
        event_pages = (await service.events())["total_pages"]
        events = [e for page in range(1, event_pages + 1) for e in (await service.events(page))["items"]]
        assert len(events) > 110 and len(events) == len({e["id"] for e in events})
        assert "collection_failed" in {e["kind"] for e in events}
        async with service.AsyncSessionLocal() as session:
            assert await session.scalar(select(func.count()).select_from(service.JobAgentCollectionItem)) == 0
        # The actual background loop notices a new job without a manual collect request.
        postings.append({"id": "auto", "title": "Automatic", "source_url": "https://example.com/auto"})
        await source_update()
        monkeypatch.setattr(service, "SYNC_INTERVAL_SECONDS", 0.02)
        worker = asyncio.create_task(service.collection_loop())
        try:
            for _ in range(600):
                if (await service.candidates(search="Automatic"))["total"] == 1:
                    break
                await asyncio.sleep(0.05)
            assert (await service.candidates(search="Automatic"))["total"] == 1
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
        # Finish any snapshot interrupted by worker cancellation before new filters.
        await drain()
        # Explicit filters still work; no hidden total cap is reintroduced.
        await service.update_config(service.ConfigUpdate(revision=2, config=service.JobAgentConfig(search="Engineer", remote_scope="remote", posted_within_days=7)))
        filtered = await drain()
        assert filtered["total"] == sum(bool(p.get("posted_date") in {"2026-09-15", "2026-09-16", "2026-09-17"}) for p in postings if p["title"].startswith("Engineer"))
        await service.update_config(service.ConfigUpdate(revision=3, config=service.JobAgentConfig(remote_scope="global")))
        assert (await drain())["total"] == 0
    finally:
        await engine.dispose()
        async with async_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
