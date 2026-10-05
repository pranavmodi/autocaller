import httpx
import pytest

from app.services import job_work_arrangement_classification as arrangement


def test_conflict_prefilter_finds_hybrid_and_negated_remote_but_not_plain_remote():
    assert arrangement.has_conflicting_evidence({"remote_eligibility": "Hybrid; work from home Monday and Friday"})
    assert arrangement.has_conflicting_evidence({"remote_eligibility": "This is not a remote or hybrid position"})
    assert not arrangement.has_conflicting_evidence({"remote_eligibility": "Fully remote within the United States"})


@pytest.mark.asyncio
async def test_conflicting_jobs_share_one_jev_request(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured["request"] = kwargs["json"]
            return httpx.Response(200, request=httpx.Request("POST", url), json={
                "model": "jev-arrangement-test",
                "answers": {
                    "job_0": {"type": "choice", "choice": "hybrid", "confidence": 0.96, "probabilities": {"remote": 0.01, "hybrid": 0.96, "onsite": 0.01, "unclear": 0.02}},
                    "job_1": {"type": "choice", "choice": "onsite", "confidence": 0.94, "probabilities": {"remote": 0.01, "hybrid": 0.02, "onsite": 0.94, "unclear": 0.03}},
                },
            })

    monkeypatch.setattr(arrangement.httpx, "AsyncClient", Client)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    postings = [
        {"title": "Engineer", "remote_eligibility": "Hybrid; work from home Monday and Friday", "work_arrangement": "remote", "remote_scope": "unclear"},
        {"title": "Paralegal", "remote_eligibility": "NO REMOTE/HYBRID WORK", "work_arrangement": "remote", "remote_scope": "unclear"},
    ]
    classified, error = await arrangement.classify_conflicts(postings)

    assert error is None
    assert [item["work_arrangement"] for item in classified] == ["hybrid", "onsite"]
    assert all(item["remote_scope"] == "not_remote" for item in classified)
    assert len(captured["request"]["questions"]) == 2


def test_remote_option_remains_remote_after_conflict_decision():
    posting = {"work_arrangement": "remote", "remote_scope": "country_restricted", "global_remote": False}
    decision = arrangement.WorkArrangementDecision(
        candidate_id="a", status="remote", confidence=0.9,
        probabilities={"remote": 0.9, "hybrid": 0.04, "onsite": 0.01, "unclear": 0.05},
        model="jev-arrangement-test",
    )
    result = arrangement.apply_decision(posting, decision)
    assert result["work_arrangement"] == "remote"
    assert result["remote_scope"] == "country_restricted"
