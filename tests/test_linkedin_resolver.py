import asyncio
from types import SimpleNamespace

import pytest

from app.db.models import FirmContactRow, LeadGenBatchRow, PifFirmRow
from app.services import linkedin_resolver


class _FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.outputs.pop(0))


class _FakeClient:
    def __init__(self, *outputs):
        self.responses = _FakeResponses(outputs)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        return self


class _Session:
    def __init__(self, *, contacts=None, pifs=None, batches=None, execute_rows=None):
        self.contacts = contacts or {}
        self.pifs = pifs or {}
        self.batches = batches or {}
        self.execute_rows = execute_rows or []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, model, row_id):
        if model is FirmContactRow:
            return self.contacts.get(row_id)
        if model is PifFirmRow:
            return self.pifs.get(row_id)
        if model is LeadGenBatchRow:
            return self.batches.get(row_id)
        return None

    async def execute(self, _stmt):
        return _Result(self.execute_rows)

    async def commit(self):
        self.commits += 1


def _contact(
    contact_id="contact_1",
    *,
    linkedin_url=None,
    title="Managing Partner",
    persona="founder_owner",
):
    return FirmContactRow(
        id=contact_id,
        pif_id="pif_1",
        full_name=f"Contact {contact_id}",
        first_name="Contact",
        email=f"{contact_id}@example.com",
        title=title,
        linkedin_url=linkedin_url,
        persona=persona,
    )


def _pif():
    return PifFirmRow(
        id="pif_1",
        firm_name="Example Law",
        addresses=[{"city": "Los Angeles", "state": "CA"}],
        research_data={},
    )


def test_valid_personal_linkedin_url_is_written(monkeypatch):
    contact = _contact()
    session = _Session(contacts={contact.id: contact}, pifs={"pif_1": _pif()})
    monkeypatch.setattr(linkedin_resolver, "AsyncSessionLocal", lambda: session)
    monkeypatch.setenv("LINKEDIN_RESOLVER_MODEL", "test-model")
    client = _FakeClient('{"linkedin_url": "https://www.linkedin.com/in/contact-example"}')

    result = asyncio.run(
        linkedin_resolver.resolve_linkedin_for_contact(contact.id, client=client)
    )

    assert result == {
        "status": "resolved",
        "linkedin_url": "https://www.linkedin.com/in/contact-example",
        "model": "test-model",
    }
    assert contact.linkedin_url == "https://www.linkedin.com/in/contact-example"
    assert session.commits == 1
    assert client.responses.calls[0]["tools"] == [{"type": "web_search"}]


@pytest.mark.parametrize(
    "output",
    [
        '{"linkedin_url": "https://www.linkedin.com/company/example-law"}',
        '{"linkedin_url": "https://example.com/contact"}',
        'Here is the URL: {"linkedin_url": "https://www.linkedin.com/in/contact-example"}',
    ],
)
def test_invalid_or_explanatory_responses_are_not_found(monkeypatch, output):
    contact = _contact()
    session = _Session(contacts={contact.id: contact}, pifs={"pif_1": _pif()})
    monkeypatch.setattr(linkedin_resolver, "AsyncSessionLocal", lambda: session)
    client = _FakeClient(output)

    result = asyncio.run(
        linkedin_resolver.resolve_linkedin_for_contact(contact.id, client=client)
    )

    assert result["status"] == "not_found"
    assert contact.linkedin_url is None
    assert session.commits == 0


def test_existing_linkedin_url_skips_without_api_call(monkeypatch):
    contact = _contact(linkedin_url="https://www.linkedin.com/in/already-known")
    session = _Session(contacts={contact.id: contact}, pifs={"pif_1": _pif()})
    monkeypatch.setattr(linkedin_resolver, "AsyncSessionLocal", lambda: session)
    client = _FakeClient('{"linkedin_url": "https://www.linkedin.com/in/new"}')

    result = asyncio.run(
        linkedin_resolver.resolve_linkedin_for_contact(contact.id, client=client)
    )

    assert result == {
        "status": "skipped",
        "linkedin_url": "https://www.linkedin.com/in/already-known",
    }
    assert client.responses.calls == []
    assert session.commits == 0


def test_force_re_resolves_existing_linkedin_url(monkeypatch):
    contact = _contact(linkedin_url="https://www.linkedin.com/in/old")
    session = _Session(contacts={contact.id: contact}, pifs={"pif_1": _pif()})
    monkeypatch.setattr(linkedin_resolver, "AsyncSessionLocal", lambda: session)
    client = _FakeClient('{"linkedin_url": "https://www.linkedin.com/in/new"}')

    result = asyncio.run(
        linkedin_resolver.resolve_linkedin_for_contact(contact.id, force=True, client=client)
    )

    assert result["status"] == "resolved"
    assert contact.linkedin_url == "https://www.linkedin.com/in/new"
    assert len(client.responses.calls) == 1
    assert session.commits == 1


def test_batch_contact_selection_defaults_to_missing_decision_makers(monkeypatch):
    owner = _contact("owner", linkedin_url=None, title="Owner", persona="founder_owner")
    staff = _contact("staff", linkedin_url=None, title="Paralegal", persona="staff")
    existing = _contact("existing", linkedin_url="https://www.linkedin.com/in/existing")
    session = _Session(
        batches={"batch_1": LeadGenBatchRow(id="batch_1", name="Batch", template_key="t", policy_version="p")},
        execute_rows=[owner, staff, existing],
    )
    monkeypatch.setattr(linkedin_resolver, "AsyncSessionLocal", lambda: session)

    selected = asyncio.run(
        linkedin_resolver._batch_contacts(
            "batch_1",
            only_decision_makers=True,
            force=False,
        )
    )

    assert [row["id"] for row in selected] == ["owner"]


def test_batch_respects_limit_and_returns_summary(monkeypatch):
    candidates = [
        {"id": "c1", "name": "One", "title": "Owner"},
        {"id": "c2", "name": "Two", "title": "Partner"},
        {"id": "c3", "name": "Three", "title": "Attorney"},
    ]
    resolved_ids = []

    async def fake_batch_contacts(batch_id, *, only_decision_makers, force):
        assert batch_id == "batch_1"
        assert only_decision_makers is True
        assert force is False
        return candidates

    async def fake_resolve(contact_id, *, force, client):
        resolved_ids.append(contact_id)
        return {"status": "resolved", "linkedin_url": f"https://www.linkedin.com/in/{contact_id}"}

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(linkedin_resolver, "_batch_contacts", fake_batch_contacts)
    monkeypatch.setattr(linkedin_resolver, "resolve_linkedin_for_contact", fake_resolve)
    monkeypatch.setattr(linkedin_resolver.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        linkedin_resolver.resolve_linkedin_for_batch("batch_1", limit=2, client=object())
    )

    assert resolved_ids == ["c1", "c2"]
    assert result["summary"]["eligible"] == 3
    assert result["summary"]["resolved"] == 2
    assert result["summary"]["attempted"] == 2
    assert len(result["results"]) == 2
