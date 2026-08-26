import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.models import FirmContactRow, LeadGenBatchItemRow, LeadGenBatchRow
from app.services import lead_gen_curated


class _FakeSession:
    def __init__(self):
        self.batches: dict[str, LeadGenBatchRow] = {}
        self.contacts: dict[str, FirmContactRow] = {}
        self.items: list[LeadGenBatchItemRow] = []
        self.commits = 0
        self.flushes = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def add(self, row):
        if isinstance(row, LeadGenBatchRow):
            self.batches[row.id] = row
        elif isinstance(row, LeadGenBatchItemRow):
            self.items.append(row)
        else:
            raise AssertionError(f"unexpected row type: {type(row)}")

    async def get(self, model, row_id):
        if model is LeadGenBatchRow:
            return self.batches.get(row_id)
        if model is FirmContactRow:
            return self.contacts.get(row_id)
        return None

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


def _contact(contact_id: str, email: str, pif_id: str = "pif_1") -> FirmContactRow:
    return FirmContactRow(
        id=contact_id,
        pif_id=pif_id,
        full_name=f"Contact {contact_id}",
        email=email,
        title="Owner",
        persona="founder_owner",
    )


def test_create_curated_batch_sets_empty_counts(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(lead_gen_curated, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(lead_gen_curated, "_new_id", lambda: "batch_1")

    async def fake_policy():
        return SimpleNamespace(version="policy_v1")

    monkeypatch.setattr(lead_gen_curated, "ensure_default_policy", fake_policy)

    batch = asyncio.run(
        lead_gen_curated.create_curated_batch(
            name="TEST curated",
            created_by="tester",
        )
    )

    assert batch["id"] == "batch_1"
    assert batch["status"] == "approved"
    assert batch["policy_version"] == "policy_v1"
    assert batch["counts"] == {
        "basis": "operator-curated",
        "returned": 0,
        "requested": 0,
    }
    assert session.commits == 1


def test_add_contacts_resolves_by_id_and_email_and_is_idempotent(monkeypatch):
    session = _FakeSession()
    batch = LeadGenBatchRow(
        id="batch_1",
        name="TEST curated",
        target_metric="meetings_booked",
        template_key="possible_minds_dynamic",
        policy_version="policy_v1",
        status="approved",
        counts_json={"basis": "operator-curated", "returned": 0, "requested": 0},
        created_by="tester",
    )
    session.batches[batch.id] = batch
    contact_one = _contact("contact_1", "one@example.com", pif_id="pif_1")
    contact_two = _contact("contact_2", "two@example.com", pif_id="pif_2")
    contacts_by_ref = {
        contact_one.id: contact_one,
        contact_one.email: contact_one,
        contact_two.id: contact_two,
        contact_two.email: contact_two,
    }
    ids = iter(["item_1", "item_2"])

    async def fake_resolve(_session, ref):
        return contacts_by_ref.get(str(ref).lower()) or contacts_by_ref.get(str(ref))

    async def fake_existing(_session, batch_id):
        return {item.contact_id for item in session.items if item.batch_id == batch_id}

    async def fake_count(_session, batch_id):
        return len([item for item in session.items if item.batch_id == batch_id])

    async def fake_firm_name(_session, contact):
        return f"Firm {contact.pif_id}"

    monkeypatch.setattr(lead_gen_curated, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(lead_gen_curated, "_new_id", lambda: next(ids))
    monkeypatch.setattr(lead_gen_curated, "_resolve_contact", fake_resolve)
    monkeypatch.setattr(lead_gen_curated, "_existing_contact_ids", fake_existing)
    monkeypatch.setattr(lead_gen_curated, "_live_item_count", fake_count)
    monkeypatch.setattr(lead_gen_curated, "_firm_name_for_contact", fake_firm_name)

    result = asyncio.run(
        lead_gen_curated.add_contacts_to_batch(
            "batch_1",
            ["contact_1", "two@example.com", "contact_1", "missing@example.com"],
            actor="tester",
        )
    )

    assert result["added"] == 2
    assert result["item_ids"] == [
        {"contact_email": "one@example.com", "item_id": "item_1"},
        {"contact_email": "two@example.com", "item_id": "item_2"},
    ]
    assert [row["reason"] for row in result["skipped"]] == ["already_in_batch", "unresolved"]
    assert batch.counts_json["returned"] == 2
    assert batch.counts_json["requested"] == 2
    assert {item.contact_id for item in session.items} == {"contact_1", "contact_2"}
    assert all((item.reason_json or {}).get("source") == "operator-curated" for item in session.items)
    assert all(item.approval_status == "pending" for item in session.items)

    second = asyncio.run(
        lead_gen_curated.add_contacts_to_batch(
            "batch_1",
            ["one@example.com"],
            actor="tester",
        )
    )

    assert second["added"] == 0
    assert second["skipped"][0]["reason"] == "already_in_batch"
    assert batch.counts_json["returned"] == 2
    assert len(session.items) == 2


def test_recount_batch_repairs_empty_counts(monkeypatch):
    session = _FakeSession()
    batch = LeadGenBatchRow(
        id="batch_1",
        name="TEST curated",
        target_metric="meetings_booked",
        template_key="possible_minds_dynamic",
        policy_version="policy_v1",
        status="approved",
        counts_json={"basis": "operator-curated"},
        created_by="tester",
    )
    session.batches[batch.id] = batch
    session.items = [
        LeadGenBatchItemRow(
            id=f"item_{idx}",
            batch_id=batch.id,
            contact_id=f"contact_{idx}",
            pif_id=f"pif_{idx}",
            firm_name=f"Firm {idx}",
            contact_name=f"Contact {idx}",
            contact_email=f"{idx}@example.com",
            contact_title="Owner",
            persona="founder_owner",
            template_key=batch.template_key,
            score=0,
            reason_json={"source": "operator-curated"},
            approval_status="pending",
        )
        for idx in range(3)
    ]

    async def fake_count(_session, batch_id):
        return len([item for item in session.items if item.batch_id == batch_id])

    monkeypatch.setattr(lead_gen_curated, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(lead_gen_curated, "_live_item_count", fake_count)

    result = asyncio.run(lead_gen_curated.recount_batch("batch_1"))

    assert result["returned"] == 3
    assert result["requested"] == 3
    assert batch.counts_json == {
        "basis": "operator-curated",
        "returned": 3,
        "requested": 3,
    }
    assert session.commits == 1


def test_schedule_manual_email_creates_policy_checked_scheduled_action(monkeypatch):
    session = _FakeSession()
    contact = _contact("contact_1", "owner@example.com")
    session.contacts[contact.id] = contact
    scheduled_for = datetime(2030, 6, 11, 16, 30, tzinfo=timezone.utc)
    captured: dict[str, object] = {}

    async def fake_firm_name(_session, _contact):
        return "Example Injury Law"

    async def fake_create_batch(**kwargs):
        captured["batch"] = kwargs
        return {"id": "batch_manual"}

    async def fake_add_contacts(batch_id, contact_refs, actor):
        captured["added"] = (batch_id, contact_refs, actor)
        return {"item_ids": [{"item_id": "item_manual", "contact_email": contact.email}]}

    async def fake_create_action(**kwargs):
        captured["action"] = kwargs
        return {"id": "action_manual", "status": "approved"}

    async def fake_policy(action_id, actor):
        captured["policy"] = (action_id, actor)
        return {"allowed": True, "reason": "allowed"}

    monkeypatch.setattr(lead_gen_curated, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(lead_gen_curated, "_firm_name_for_contact", fake_firm_name)
    monkeypatch.setattr(lead_gen_curated, "create_curated_batch", fake_create_batch)
    monkeypatch.setattr(lead_gen_curated, "add_contacts_to_batch", fake_add_contacts)
    monkeypatch.setattr(lead_gen_curated, "create_send_email_action", fake_create_action)
    monkeypatch.setattr(lead_gen_curated, "check_action_policy", fake_policy)

    result = asyncio.run(lead_gen_curated.schedule_manual_email(
        contact_id=contact.id,
        subject="A manual note",
        body="Hi there,\n\nThis was written by the operator.",
        scheduled_for=scheduled_for,
        transport="zoho_api",
        actor="tester",
    ))

    assert result["batch_id"] == "batch_manual"
    assert result["batch_item_id"] == "item_manual"
    assert result["policy"]["allowed"] is True
    assert captured["action"] == {
        "to": "owner@example.com",
        "subject": "A manual note",
        "body": "Hi there,\n\nThis was written by the operator.",
        "mode": "lead_gen",
        "requested_by": "tester",
        "approved_by": "tester",
        "contact_id": "contact_1",
        "batch_item_id": "item_manual",
        "pif_id": "pif_1",
        "firm_name": "Example Injury Law",
        "composer_variant_key": "manual",
        "lead_gen_action_type": "manual_email",
        "scheduled_for": scheduled_for,
        "transport": "zoho_api",
    }
