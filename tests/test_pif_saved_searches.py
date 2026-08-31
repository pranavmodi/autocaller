from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import pif as pif_api
from app.services.pif_saved_searches import (
    normalize_contact_search_criteria,
    normalize_firm_trigger_search_criteria,
)
from app.services.firm_intel_sync import _has_contact_email


def test_normalize_contact_search_criteria_for_filevine_decision_makers():
    criteria = normalize_contact_search_criteria({
        "vendor": " Filevine ",
        "leader": "leader",
        "email_presence": "has",
        "source": "all",
    })

    assert criteria == {
        "vendor": "filevine",
        "leader": "leader",
        "email_presence": "has",
        "source": "all",
    }


def test_normalize_contact_search_criteria_deduplicates_multi_value_filters():
    criteria = normalize_contact_search_criteria({
        "titles": ["Partner", "Partner", "CEO"],
        "role_categories": ["owner", "owner"],
    })

    assert criteria["titles"] == ["Partner", "CEO"]
    assert criteria["role_categories"] == ["owner"]
    assert criteria["email_presence"] == "any"


def test_normalize_contact_search_criteria_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unsupported_search_criteria"):
        normalize_contact_search_criteria({"vendor": "filevine", "limit": 20})


def test_normalize_firm_trigger_search_criteria_keeps_trigger_filters():
    normalized = normalize_firm_trigger_search_criteria({
        "entity_type": "pi_law_firm",
        "staff_count_range": "11-25",
        "vendor": "Filevine",
        "job_postings_presence": "has",
        "job_posting_role": "intake",
        "job_posting_query": "lead conversion CRM",
        "job_posted_within_days": "30",
        "active_only": True,
    })

    assert normalized["entity_type"] == "pi_law_firm"
    assert normalized["vendor"] == "filevine"
    assert normalized["job_posting_role"] == "intake"
    assert normalized["job_posting_query"] == "lead conversion CRM"
    assert normalized["job_posted_within_days"] == "30"
    assert normalized["active_only"] is True


def test_normalize_firm_trigger_search_criteria_rejects_unknown_role():
    with pytest.raises(ValueError, match="unsupported_job_posting_role"):
        normalize_firm_trigger_search_criteria({"job_posting_role": "rainmaker"})


@pytest.mark.parametrize("value", [None, "", "null", "None", "unknown", "not-an-email"])
def test_has_contact_email_rejects_placeholders(value):
    assert not _has_contact_email(value)


def test_has_contact_email_accepts_address():
    assert _has_contact_email("leader@example.com")


def test_people_endpoint_passes_email_presence(monkeypatch):
    captured = {}

    async def fake_list_people(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "page": 1, "page_size": 25, "total_pages": 0}

    monkeypatch.setattr(pif_api, "list_mirrored_pif_people", fake_list_people)
    app = FastAPI()
    app.include_router(pif_api.router)
    client = TestClient(app)

    response = client.get(
        "/api/pif/people?vendor=filevine&leader=leader&email_presence=has"
    )

    assert response.status_code == 200
    assert captured["vendor"] == "filevine"
    assert captured["leader"] == "leader"
    assert captured["email_presence"] == "has"
