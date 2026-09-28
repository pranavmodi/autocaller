import httpx
import pytest

from app.services import job_browser_jev as jev


class Client:
    response = {}
    request = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        type(self).request = (url, kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json=type(self).response)


def choice(selected, options, confidence=0.96):
    remaining = (1 - confidence) / max(1, len(options) - 1)
    return {
        "type": "choice",
        "choice": selected,
        "confidence": confidence,
        "probabilities": {option: confidence if option == selected else remaining for option in options},
    }


@pytest.fixture(autouse=True)
def typesafe(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-key")
    monkeypatch.setattr(jev.httpx, "AsyncClient", Client)


@pytest.mark.asyncio
async def test_action_audit_uses_jev_for_supported_common_path():
    Client.response = {
        "model": "jev-fixture",
        "answers": {
            "action_support": choice("supported", set(jev.ACTION_SUPPORT_OPTIONS)),
            "action_effect": choice("input", set(jev.ACTION_EFFECT_OPTIONS)),
        },
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    audit, metadata = await jev.audit_action({
        "posting": {"firm_name": "Fixture", "title": "AI Engineer"},
        "resume": {"text": "Applicant has AI engineering experience."},
        "snapshot": {"frames": [{"text": "Application", "controls": [{"id": "e1"}]}]},
        "authorized_at": "2026-09-28T00:00:00Z",
    }, {"kind": "fill", "element": "e1", "value": "Applicant", "summary": "Fill name"})

    assert audit == {
        "allowed": True, "effect": "input",
        "reason": "Jev found the proposed action supported by the saved application facts.",
        "recovery": "none", "repair_hint": "",
    }
    assert metadata["provider"] == "typesafe" and metadata["model"] == "jev-fixture"
    assert Client.request[1]["headers"]["Authorization"] == "Bearer fixture-key"
    assert set(Client.request[1]["json"]["questions"]) == {"action_support", "action_effect"}


@pytest.mark.asyncio
async def test_action_audit_defers_unsupported_proposal_to_richer_auditor():
    Client.response = {
        "model": "jev-fixture",
        "answers": {
            "action_support": choice("unsupported", set(jev.ACTION_SUPPORT_OPTIONS)),
            "action_effect": choice("input", set(jev.ACTION_EFFECT_OPTIONS)),
        },
    }
    audit, metadata = await jev.audit_action({}, {
        "kind": "fill", "element": "e1", "value": "Invented credential", "summary": "Fill credential",
    })
    assert audit is None
    assert metadata["support"]["choice"] == "unsupported"


@pytest.mark.asyncio
async def test_profile_resolution_copies_selected_answer_verbatim():
    item = {
        "id": "saved1", "question": "Current address", "answer": "Bengaluru, India",
        "scope": "global", "scope_value": "", "context": {}, "revision": 2,
    }
    options = {"answer_0", jev.NONE_PROFILE}
    Client.response = {
        "model": "jev-fixture",
        "answers": {"saved_answer": choice("answer_0", options)},
    }
    result, metadata = await jev.resolve_profile_question({
        "posting": {"firm_name": "Fixture", "title": "Engineer"},
        "saved_profile": [item],
    }, "What is your current address?")
    assert result["answer"] == item["answer"]
    assert result["citations"] == [{"id": "saved1", "quote": "Bengaluru, India"}]
    assert metadata["selection"]["choice"] == "answer_0"


@pytest.mark.asyncio
async def test_profile_resolution_defers_when_no_saved_answer_applies():
    item = {
        "id": "saved1", "question": "India work authorization", "answer": "Yes",
        "scope": "country", "scope_value": "India", "context": {}, "revision": 1,
    }
    options = {"answer_0", jev.NONE_PROFILE}
    Client.response = {
        "model": "jev-fixture",
        "answers": {"saved_answer": choice(jev.NONE_PROFILE, options)},
    }
    result, _metadata = await jev.resolve_profile_question({
        "posting": {"location": "United States"}, "saved_profile": [item],
    }, "Are you authorized to work in the United States?")
    assert result is None


@pytest.mark.asyncio
async def test_confirmation_uses_jev_for_exact_visible_receipt():
    Client.response = {
        "model": "jev-fixture",
        "answers": {
            "submission_confirmation": choice("confirmed", set(jev.CONFIRMATION_OPTIONS)),
        },
    }
    result, metadata = await jev.verify_confirmation({
        "posting": {"firm_name": "Fixture", "title": "Engineer"},
        "snapshot": {"frames": [{"text": "Thank you. Your application was submitted."}]},
        "submit_started_at": "2026-09-28T00:00:00Z",
    }, "Your application was submitted.")
    assert result["confirmed"] is True
    assert metadata["confirmation"]["choice"] == "confirmed"


def test_choice_rejects_incomplete_probability_map():
    with pytest.raises(ValueError, match="invalid options"):
        jev._choice({
            "answers": {"q": {"type": "choice", "choice": "yes", "confidence": 0.9,
                               "probabilities": {"yes": 1.0}}},
        }, "q", {"yes", "no"})
