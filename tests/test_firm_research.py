from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.research import router as research_router
from app.db.models import FirmContactRow, FrontFirmActivityRow, ResearchTaskRow
from app.services import firm_research
from app.services.firm_research import PifStatsBudget


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        if isinstance(self.rows, list):
            return self.rows[0] if self.rows else None
        return self.rows


class _Session:
    def __init__(self, result_queue, added):
        self.result_queue = result_queue
        self.added = added

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _stmt):
        if not self.result_queue:
            return _Result([])
        return _Result(self.result_queue.pop(0))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        return None


class _SessionFactory:
    def __init__(self, results):
        self.results = list(results)
        self.added = []

    def __call__(self):
        return _Session(self.results, self.added)


class _FakeClient:
    def __init__(self, budget=None):
        self.budget = budget or PifStatsBudget(max_task_posts=30, post_min_interval_seconds=0, get_min_interval_seconds=0)
        self.posted = []

    async def post_task(self, pif_id, kind):
        if not await self.budget.before_post():
            return None
        self.posted.append((pif_id, kind))
        return {
            "pif_id": pif_id,
            "firm_name": "Example Law",
            "task_id": f"task-{len(self.posted)}",
            "status": "queued",
            "message": "queued",
        }

    async def get_status(self, task_id):
        return {"task_id": task_id, "pif_id": "pif-1", "firm_name": "Example Law", "status": "completed", "message": "done"}

    async def get_firm(self, pif_id):
        return {
            "id": pif_id,
            "firm_name": "Example Law",
            "research_status": "completed",
            "staff_research_status": "completed",
            "leadership": [
                {
                    "name": "Jane Owner",
                    "title": "Founder",
                    "email": "jane@examplelaw.com",
                    "phone": "(555) 555-0100",
                    "linkedin": "https://linkedin.com/in/jane",
                }
            ],
            "staff": [
                {
                    "name": "Ira Intake",
                    "title": "Intake Manager",
                    "email": "ira@examplelaw.com",
                }
            ],
            "behavioral_data": {
                "after_hours_ratio": 0.714,
                "primary_pain_point": "lien_negotiation",
            },
        }


@pytest.mark.asyncio
async def test_queue_firm_research_stops_at_post_budget(monkeypatch):
    factory = _SessionFactory([[], [], []])
    client = _FakeClient(PifStatsBudget(max_task_posts=2, post_min_interval_seconds=0, get_min_interval_seconds=0))
    monkeypatch.setattr(firm_research, "AsyncSessionLocal", factory)

    result = await firm_research.queue_firm_research(
        "pif-1",
        kinds=["research", "staff", "behavior"],
        client=client,
    )

    assert [row["kind"] for row in result["queued"]] == ["research", "research_staff"]
    assert result["skipped"][-1]["reason"] == "post_budget_exhausted"
    assert result["budget"]["remaining_task_posts"] == 0
    assert len([row for row in factory.added if isinstance(row, ResearchTaskRow)]) == 2


@pytest.mark.asyncio
async def test_poll_research_tasks_upserts_contacts_and_behavior(monkeypatch):
    task = ResearchTaskRow(
        task_id="task-1",
        pif_id="pif-1",
        kind="research",
        status="queued",
        requested_at=datetime.now(timezone.utc),
    )
    activity = FrontFirmActivityRow(domain="examplelaw.com", pif_id="pif-1")
    factory = _SessionFactory([
        [task],
        [],
        [],
        [activity],
    ])
    monkeypatch.setattr(firm_research, "AsyncSessionLocal", factory)

    async def fake_map():
        return {"scanned": 2, "updated": 2, "skipped": 0}

    monkeypatch.setattr(firm_research, "map_personas", fake_map)

    result = await firm_research.poll_research_tasks(client=_FakeClient(), task_ids=["task-1"])

    assert result["completed"] == 1
    assert task.status == "completed"
    assert task.completed_at is not None
    assert task.result_summary["leadership_count"] == 1
    assert task.result_summary["staff_count"] == 1
    assert activity.behavioral_json["primary_pain_point"] == "lien_negotiation"
    contacts = [row for row in factory.added if isinstance(row, FirmContactRow)]
    assert [c.research_title for c in contacts] == ["Founder", "Intake Manager"]


@pytest.mark.asyncio
async def test_orchestrate_warm_research_stops_when_budget_exhausted(monkeypatch):
    activity = FrontFirmActivityRow(domain="examplelaw.com", pif_id="pif-1", warm_score=100)
    factory = _SessionFactory([
        [activity],
        [],
        [],
    ])
    client = _FakeClient(PifStatsBudget(max_task_posts=0, post_min_interval_seconds=0, get_min_interval_seconds=0))
    monkeypatch.setattr(firm_research, "AsyncSessionLocal", factory)

    result = await firm_research.orchestrate_warm_research(
        top_n=1,
        kinds=["research"],
        timeout_seconds=1,
        client=client,
    )

    assert result["queued_task_ids"] == []
    assert result["budget"]["remaining_task_posts"] == 0


def test_research_api_smoke(monkeypatch):
    app = FastAPI()
    app.include_router(research_router)

    async def fake_status():
        return {"coverage": {"matched_firms": 1, "researched_firms": 0}, "open_tasks": [], "task_counts": {}}

    async def fake_warm(**_kwargs):
        return {"queued_task_ids": ["task-1"], "poll": {"completed": 0}}

    monkeypatch.setattr("app.api.research.research_coverage", fake_status)
    monkeypatch.setattr("app.api.research.orchestrate_warm_research", fake_warm)

    client = TestClient(app)
    assert client.get("/api/research/status").json()["coverage"]["matched_firms"] == 1
    assert client.post("/api/research/warm", json={"top_n": 1, "kinds": ["research"], "timeout_seconds": 1}).json()["queued_task_ids"] == ["task-1"]
