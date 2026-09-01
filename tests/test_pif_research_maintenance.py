import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import pif_research_maintenance as service


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _firm(research_data=None):
    return SimpleNamespace(research_data=research_data or {})


def test_job_maintenance_is_due_when_missing_or_thirty_days_old():
    assert service._job_due(
        _firm(), now=NOW, refresh_days=30, retry_days=3
    ) == (True, None)

    checked_at = NOW - timedelta(days=30)
    due, due_at = service._job_due(
        _firm({
            "job_postings_research_status": "completed",
            "last_job_postings_researched_at": checked_at.isoformat(),
        }),
        now=NOW,
        refresh_days=30,
        retry_days=3,
    )
    assert due is True
    assert due_at == NOW


def test_failed_sitemap_retries_after_three_days():
    checked_at = NOW - timedelta(days=2)
    due, due_at = service._sitemap_due(
        _firm({
            "sitemap_monitor": {
                "status": "failed",
                "checked_at": checked_at.isoformat(),
            }
        }),
        now=NOW,
        refresh_days=30,
        retry_days=3,
    )
    assert due is False
    assert due_at == checked_at + timedelta(days=3)


def test_queue_due_maintenance_queues_sitemaps_before_jobs(monkeypatch):
    events = []

    async def fake_candidates(*, now):
        return {
            "job_ids": ["job-1", "job-2"],
            "sitemap_ids": ["site-1", "site-2"],
            "today_job_tasks": 0,
            "today_sitemap_tasks": 0,
            "refresh_days": 30,
            "retry_days": 3,
        }

    async def fake_sitemap(firm_id):
        events.append(("sitemap", firm_id))
        return {"status": "queued"}

    async def fake_job(firm_id):
        events.append(("research", firm_id))
        return {"status": "queued"}

    monkeypatch.setattr(service, "_maintenance_candidates", fake_candidates)
    monkeypatch.setattr(service, "start_sitemap_research", fake_sitemap)
    monkeypatch.setattr(service, "start_job_posting_research", fake_job)

    result = asyncio.run(service.queue_due_firm_maintenance(limit=1, now=NOW))

    assert events == [("sitemap", "site-1"), ("research", "job-1")]
    assert result["queued_sitemaps"] == 1
    assert result["queued_job_postings"] == 1


def test_queue_due_maintenance_only_tops_up_daily_cohort(monkeypatch):
    events = []

    async def fake_candidates(*, now):
        return {
            "job_ids": ["job-1", "job-2"],
            "sitemap_ids": ["site-1", "site-2"],
            "today_job_tasks": 2,
            "today_sitemap_tasks": 1,
            "refresh_days": 30,
            "retry_days": 3,
        }

    async def fake_sitemap(firm_id):
        events.append(("sitemap", firm_id))
        return {"status": "queued"}

    async def fake_job(firm_id):
        events.append(("research", firm_id))
        return {"status": "queued"}

    monkeypatch.setattr(service, "_maintenance_candidates", fake_candidates)
    monkeypatch.setattr(service, "start_sitemap_research", fake_sitemap)
    monkeypatch.setattr(service, "start_job_posting_research", fake_job)

    result = asyncio.run(service.queue_due_firm_maintenance(limit=2, now=NOW))

    assert events == [("sitemap", "site-1")]
    assert result["already_queued_job_postings_today"] == 2
    assert result["already_queued_sitemaps_today"] == 1
