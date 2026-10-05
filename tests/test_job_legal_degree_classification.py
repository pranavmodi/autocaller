"""TypeSafe Jev legal-degree classification and persistence metadata."""
import httpx
import pytest

from app.services import job_legal_degree_classification as legal_degree


@pytest.mark.asyncio
async def test_legal_degree_jobs_share_one_jev_choice_request(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured["request"] = kwargs["json"]
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "model": "jev-legal-test",
                "answers": {
                    "job_0": {
                        "type": "choice", "choice": "required", "confidence": 0.97,
                        "probabilities": {"required": 0.96, "not_required": 0.01, "unclear": 0.03},
                    },
                    "job_1": {
                        "type": "choice", "choice": "unclear", "confidence": 0.82,
                        "probabilities": {"required": 0.05, "not_required": 0.12, "unclear": 0.83},
                    },
                },
            })

    monkeypatch.setattr(legal_degree.httpx, "AsyncClient", Client)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    decisions = await legal_degree.classify_postings([
        {"candidate_id": "a", "title": "Compliance Director", "qualifications": ["JD required"]},
        {"candidate_id": "b", "title": "Legal Editor", "qualifications": ["Law degree preferred"]},
    ])

    assert [decision.status for decision in decisions] == ["required", "unclear"]
    assert set(captured["request"]["questions"]) == {"job_0", "job_1"}
    assert "preferred" in " ".join(captured["request"]["questions"]["job_0"]["instructions"]["rules"]).lower()


@pytest.mark.asyncio
async def test_unrelated_roles_remain_visible_without_a_model_call(monkeypatch):
    class Client:
        def __init__(self, **_kwargs):
            raise AssertionError("TypeSafe should not be called without a legal-credential candidate")

    monkeypatch.setattr(legal_degree.httpx, "AsyncClient", Client)
    decisions = await legal_degree.classify_postings([
        {"candidate_id": "a", "title": "Receptionist", "qualifications": ["Fluent Spanish"]},
        {"candidate_id": "b", "title": "Occupational Therapist", "qualifications": ["Occupational therapy license"]},
    ])

    assert [decision.status for decision in decisions] == ["unclear", "unclear"]
    assert all(decision.provider == "mechanical_prefilter" for decision in decisions)


def test_legal_degree_decision_persists_model_probabilities_and_input_hash():
    posting = {"title": "Operations Director", "qualifications": ["Juris Doctor is mandatory"]}
    decision = legal_degree.LegalDegreeDecision(
        candidate_id="a", status="required", confidence=0.95,
        probabilities={"required": 0.95, "not_required": 0.01, "unclear": 0.04},
        model="jev-legal-test",
    )

    result = legal_degree.apply_decision(posting, decision)

    assert result["legal_degree_requirement"] == "required"
    assert result["legal_degree_classification"]["model"] == "jev-legal-test"
    assert result["legal_degree_classification"]["probabilities"]["required"] == 0.95
    assert legal_degree.current_classification(result)


@pytest.mark.asyncio
async def test_missing_typesafe_key_keeps_job_visible_as_unclear(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    postings, error = await legal_degree.classify_extracted_postings([
        {"title": "Legal Operations Manager", "qualifications": ["JD required"]},
    ])

    assert error == "TYPESAFE_API_KEY is not configured."
    assert postings[0]["legal_degree_requirement"] == "unclear"
    assert postings[0]["legal_degree_classification"]["state"] == "error"
