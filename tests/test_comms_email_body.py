from types import SimpleNamespace

import pytest

from app.api import comms


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)

    def all(self):
        return self._rows


class _Session:
    def __init__(self, results):
        self._results = iter(results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement):
        return _Result(next(self._results))


@pytest.mark.asyncio
async def test_email_item_recovers_full_body_from_product_trace(monkeypatch):
    sent_at = comms.datetime.now(comms.timezone.utc)
    row = SimpleNamespace(
        id="email-1",
        sent_at=sent_at,
        pif_id=None,
        call_id=None,
        recipient_name="Kenechi Agu",
        recipient_email="kagu@example.com",
        subject="Subject",
        body_excerpt="x" * 500,
        status="delivered",
        message_type="dynamic_lead_email",
        message_id="provider-message-1",
    )
    full_body = "x" * 500 + "\n\nComplete CTA and signature"
    trace = SimpleNamespace(
        output_json={"message_id": "provider-message-1"},
        input_json={"body": full_body},
        context_json={"firm_name": "KRA Legal, PC"},
    )
    monkeypatch.setattr(
        comms,
        "AsyncSessionLocal",
        lambda: _Session([[row], [trace]]),
    )

    items = await comms._emails_to_items(
        pif_id=None,
        since=None,
        until=None,
        limit=100,
    )

    assert items[0].body_excerpt == full_body
    assert items[0].firm_name == "KRA Legal, PC"
