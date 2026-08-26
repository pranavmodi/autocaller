import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api import call_lab as call_lab_api
from app.services.call_lab import (
    _contacts_for_firm,
    _firm_key,
    _firm_size,
    _matches,
    _person_like_name,
    _valid_us_phone,
)
from app.services.voice.factory import get_voice_backend


def test_callable_contacts_are_normalized_deduplicated_and_prioritized():
    row = SimpleNamespace(
        id="firm-1",
        firm_name="Example Law",
        canonical_website="https://example.com",
        website=None,
        leadership=[{
            "name": "Jamie Rivera",
            "title": "Managing Partner",
            "phone": "(415) 555-1212",
            "email": "jamie@example.com",
        }],
        staff=[],
        contacts=[{
            "name": "Jamie Rivera",
            "title": "Managing Partner",
            "phone": "+1 415 555 1212",
        }, {
            "name": "No Phone",
            "title": "Attorney",
        }],
    )

    contacts = _contacts_for_firm(row)

    assert len(contacts) == 1
    assert contacts[0]["phone"] == "+14155551212"
    assert contacts[0]["is_decision_maker"] is True
    assert contacts[0]["source"] == "leadership"


def test_contact_search_requires_every_query_token():
    contact = {
        "name": "Jamie Rivera",
        "firm_name": "Example Law",
        "title": "Managing Partner",
        "phone": "+14155551212",
        "email": "jamie@example.com",
        "role_category": "owner",
    }

    assert _matches(contact, "jamie example") is True
    assert _matches(contact, "managing owner") is True
    assert _matches(contact, "jamie missing") is False


def test_call_list_size_uses_researched_range_or_people_roster():
    ranged = SimpleNamespace(
        research_data={"firm_size": "11-50 employees"},
        leadership=[], staff=[], contacts=[],
    )
    roster = SimpleNamespace(
        research_data={"firm_size": "6 attorneys"},
        leadership=[{"name": f"Leader {i}"} for i in range(16)],
        staff=[], contacts=[],
    )

    assert _firm_size(ranged) == (30, "11-50 employees", "researched firm size")
    assert _firm_size(roster)[0] == 16


def test_call_targets_require_named_people_and_valid_us_numbers():
    assert _person_like_name("Jamie Rivera") is True
    assert _person_like_name("jaklin") is False
    assert _person_like_name("person@example.com") is False
    assert _valid_us_phone("(415) 555-1212") == "+14155551212"
    assert _valid_us_phone("213-370-2483 ext 2229") == "+12133702483"
    assert _valid_us_phone("21337024832229") is None


def test_firm_key_prefers_canonical_website():
    assert _firm_key({"website": "https://www.example.com/about", "firm_name": "Example"}) == "web:example.com"


def test_operator_backend_has_no_external_voice_dependency():
    async def run():
        backend = get_voice_backend("operator", audio_format="g711_ulaw")

        assert await backend.connect("call-1", "Jamie") is True
        assert backend.is_connected is True
        await backend.send_audio(b"audio")
        await backend.start_conversation()
        await backend.disconnect()
        assert backend.is_connected is False

    asyncio.run(run())


def test_start_call_lab_call_uses_operator_mode(monkeypatch):
    contact = {
        "id": "contact-1",
        "pif_id": "firm-1",
        "name": "Jamie Rivera",
        "phone": "+14155551212",
    }
    call = MagicMock()
    call.to_dict.return_value = {"call_id": "call-1"}
    orchestrator = MagicMock()
    orchestrator.start_call = AsyncMock(return_value=call)

    monkeypatch.setattr(call_lab_api, "get_call_lab_contact", AsyncMock(return_value=contact))
    monkeypatch.setattr(call_lab_api, "upsert_call_lab_patient", AsyncMock(return_value="calllab-firm-1-phone"))
    monkeypatch.setattr(call_lab_api, "get_orchestrator", lambda: orchestrator)

    result = asyncio.run(call_lab_api.start_call_lab_call(
        call_lab_api.StartCallLabCallRequest(pif_id="firm-1", contact_id="contact-1")
    ))

    assert result["call"]["call_id"] == "call-1"
    orchestrator.start_call.assert_awaited_once_with(
        "calllab-firm-1-phone",
        call_mode="twilio",
        operator_mode=True,
    )
