"""TypeSafe Jev contract-status extraction and persistence metadata."""
import httpx
import pytest

from app.services import job_contract_classification as contract


@pytest.mark.asyncio
async def test_contract_jobs_share_one_jev_choice_request(monkeypatch):
    captured = {}
    answers = {
        "job_0": {
            "type": "choice",
            "choice": "contract",
            "confidence": 0.96,
            "probabilities": {"contract": 0.95, "non_contract": 0.03, "unknown": 0.02},
        },
        "job_1": {
            "type": "choice",
            "choice": "unknown",
            "confidence": 0.83,
            "probabilities": {"contract": 0.08, "non_contract": 0.12, "unknown": 0.80},
        },
    }

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured["url"], captured["request"] = url, kwargs
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "model": "jev-contract-test",
                "answers": answers,
                "usage": {"input_tokens": 200, "output_tokens": 40},
            })

    monkeypatch.setattr(contract.httpx, "AsyncClient", Client)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    postings = [
        {"candidate_id": "a", "title": "AI Engineer", "employment_type": "Contract"},
        {"candidate_id": "b", "title": "AI Engineer", "description_summary": "Build agents"},
    ]

    decisions = await contract.classify_contract_postings(postings)

    assert [decision.status for decision in decisions] == ["contract", "unknown"]
    assert decisions[0].model == "jev-contract-test"
    assert set(captured["request"]["json"]["questions"]) == {"job_0", "job_1"}
    assert set(captured["request"]["json"]["questions"]["job_0"]["criteria"]) == set(contract.CONTRACT_OPTIONS)
    assert captured["request"]["headers"]["Authorization"] == "Bearer test-key"


def test_contract_decision_persists_probabilities_model_and_input_hash():
    posting = {"title": "Engineer", "employment_type": "Full-time"}
    decision = contract.ContractDecision(
        candidate_id="a",
        status="non_contract",
        confidence=0.94,
        probabilities={"contract": 0.03, "non_contract": 0.95, "unknown": 0.02},
        model="jev-contract-test",
    )

    result = contract.apply_contract_decision(posting, decision)

    assert result["contract_status"] == "non_contract"
    assert result["contract_classification"]["state"] == "completed"
    assert result["contract_classification"]["version"] == contract.CONTRACT_CLASSIFICATION_VERSION
    assert result["contract_classification"]["model"] == "jev-contract-test"
    assert result["contract_classification"]["probabilities"]["non_contract"] == 0.95
    assert len(result["contract_classification"]["input_sha256"]) == 64
    assert contract.current_contract_classification(result)


@pytest.mark.asyncio
async def test_extraction_records_retryable_unknown_when_typesafe_is_unavailable(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    postings, error = await contract.classify_extracted_postings([
        {"title": "Engineer", "description_summary": "Build software"},
    ])

    assert error == "TYPESAFE_API_KEY is not configured."
    assert postings[0]["contract_status"] == "unknown"
    assert postings[0]["contract_classification"]["state"] == "error"
    assert not contract.current_contract_classification(postings[0])


def test_choice_response_requires_all_contract_probabilities():
    response = {
        "model": "jev-contract-test",
        "answers": {
            "job_0": {
                "type": "choice",
                "choice": "contract",
                "confidence": 0.9,
                "probabilities": {"contract": 1.0},
            },
        },
    }

    with pytest.raises(ValueError, match="invalid options"):
        contract._parse_jev_decisions(response, ["a"])
