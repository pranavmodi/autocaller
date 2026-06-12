from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.front import router as front_router
from app.db.models import FirmContactRow, FrontFirmActivityRow, PatientRow
from app.services import front_sync


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, _stmt):
        return _Result(self.results.pop(0))

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None

    async def commit(self):
        return None


def test_status_day_delta_math():
    assert front_sync._day_delta(10, 4, 2) == {
        "total": 10,
        "last_24h": 4,
        "previous_24h": 2,
        "delta": 2,
    }
    assert front_sync._day_delta(10, 1, 3)["delta"] == -2


@pytest.mark.asyncio
async def test_front_warm_batch_creation_shapes_items(monkeypatch):
    now = datetime.now(timezone.utc)
    activity = FrontFirmActivityRow(
        domain="examplelaw.com",
        pif_id="pif-1",
        contact_count=3,
        last_seen_at=now - timedelta(hours=3),
        last_referral_at=now - timedelta(days=1),
        inbox_breakdown={"inb_qfq9": {"name": "Scheduling", "conversation_count": 2}},
        tech_signals={"case_mgmt": "filevine"},
        warm_score=245,
    )
    contact = FirmContactRow(
        id="fc_1",
        pif_id="pif-1",
        full_name="Jane Owner",
        first_name="Jane",
        email="jane@examplelaw.com",
        title="Managing Partner",
        source="front",
        front_contact_id="crd_1",
        front_last_seen=now - timedelta(hours=4),
    )
    patient = PatientRow(
        patient_id="pif-pif-1",
        name="Jane Owner",
        phone="+15555550100",
        firm_name="Example Law",
    )
    session = _FakeSession([
        [activity],
        [(patient.patient_id, patient.firm_name, patient.name)],
        [contact],
        [],
    ])

    monkeypatch.setattr(front_sync, "AsyncSessionLocal", lambda: session)
    async def fake_policy():
        return SimpleNamespace(version="lead-gen-v1")

    monkeypatch.setattr(front_sync, "ensure_default_policy", fake_policy)

    captured = {}

    async def fake_get_batch(batch_id):
        captured["batch_id"] = batch_id
        return {"batch": {"id": batch_id}, "items": [], "observations": []}

    monkeypatch.setattr(front_sync, "get_batch", fake_get_batch)

    result = await front_sync.create_front_warm_batch(
        domains=["examplelaw.com"],
        name="TEST-packet14",
        created_by="test",
    )

    batch = next(row for row in session.added if row.__class__.__name__ == "LeadGenBatchRow")
    item = next(row for row in session.added if row.__class__.__name__ == "LeadGenBatchItemRow")
    assert batch.name == "TEST-packet14"
    assert batch.counts_json["basis"] == "front-warm"
    assert item.firm_name == "Example Law"
    assert item.contact_email == "jane@examplelaw.com"
    assert item.reason_json["basis"] == "front-warm"
    assert item.reason_json["selection_features"]["domain"] == "examplelaw.com"
    assert result["link"] == f"/lead-gen?batch={captured['batch_id']}"


def test_front_api_smoke(monkeypatch):
    app = FastAPI()
    app.include_router(front_router)

    async def fake_status():
        return {"counts": {}, "funnel": [], "states": [], "sync_health": {}, "timing_feed": []}

    async def fake_warm(limit):
        return [{"domain": "examplelaw.com", "warm_score": 100}]

    async def fake_contacts(domain="", q="", limit=50):
        return [{"front_id": "crd_1", "domain": domain or "examplelaw.com"}]

    async def fake_signals():
        return {"tech_stack_counts": [], "inbox_activity_mix": [], "suppress_flagged_firms": []}

    async def fake_batch(**_kwargs):
        return {"batch": {"id": "batch-1"}, "items": [], "observations": [], "link": "/lead-gen?batch=batch-1"}

    monkeypatch.setattr("app.api.front.front_status", fake_status)
    monkeypatch.setattr("app.api.front.front_warm_firms", fake_warm)
    monkeypatch.setattr("app.api.front.list_front_contacts", fake_contacts)
    monkeypatch.setattr("app.api.front.front_signals", fake_signals)
    monkeypatch.setattr("app.api.front.create_front_warm_batch", fake_batch)

    client = TestClient(app)
    assert client.get("/api/front/status").status_code == 200
    assert client.get("/api/front/warm-list?limit=1").json()["warm_list"][0]["domain"] == "examplelaw.com"
    assert client.get("/api/front/contacts?domain=examplelaw.com").json()["contacts"][0]["domain"] == "examplelaw.com"
    assert client.get("/api/front/signals").json()["tech_stack_counts"] == []
    assert client.post("/api/front/warm-batch", json={"domains": ["examplelaw.com"]}).json()["batch"]["id"] == "batch-1"
