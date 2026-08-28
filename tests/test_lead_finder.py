from __future__ import annotations

import asyncio

from app.services import lead_finder
from app.services import lead_finder_tools
from app.services.lead_finder_web_research import normalize_person_research
from app.db.models import (
    LeadFinderAttemptRow,
    LeadFinderRunRow,
    LeadFinderStepRow,
    LeadFinderToolCallRow,
)
from app.services.llm_gateway import GatewayJSONResult, prompt_cache_metrics
from app.services.mission_control_search import (
    MissionControlToolError,
    validate_lead_finder_tool_call,
)


def test_load_lead_finder_context_includes_job_and_four_baseline_files():
    context = lead_finder.load_lead_finder_context()

    assert context["kind"] == "lead_finder_context_v1"
    assert context["job"]["name"] == "Lead Finder Agent"
    assert set(context["baseline_context"]["files"]) == {
        "company.md",
        "customer.md",
        "offer.md",
        "voice.md",
    }
    assert all(
        item["content"].strip()
        for item in context["baseline_context"]["files"].values()
    )


def test_step_uses_main_gateway_and_adds_direction_to_context(monkeypatch):
    captured = {}

    async def fake_call_skill_json(**kwargs):
        captured.update(kwargs)
        return GatewayJSONResult(
            parsed={
                "step_name": "Clarify target",
                "summary": "Converted the direction into targeting criteria.",
                "reasoning": "The user specified geography and intake pain.",
                "state_updates": {
                    "targeting_criteria": {"state": "California", "pain": "after-hours intake"},
                },
                "action": {"type": "reason", "tool": None, "arguments": {}},
                "next_step": "Plan source queries.",
                "is_complete": False,
            },
            raw_response="{}",
            model="openclaw/main",
            usage={"input_tokens": 100},
        )

    monkeypatch.setattr(lead_finder, "call_skill_json", fake_call_skill_json)
    initial = lead_finder.load_lead_finder_context()
    result = asyncio.run(
        lead_finder.run_lead_finder_step(
            context=initial,
            user_direction="California firms with after-hours intake pain",
            run_id="lfr_test_run",
        )
    )

    assert captured["model"] == "openclaw/main"
    assert captured["gateway_user"] == lead_finder._cache_session_user("lfr_test_run")
    assert "attempt_observer" in captured
    assert result["gateway"]["used_llm"] is True
    assert result["gateway"]["raw_response"] == "{}"
    assert result["context"]["user_direction"].startswith("California")
    assert result["context"]["agent_state"]["completed_steps"] == 1
    assert result["context"]["agent_state"]["status"] == "paused"
    assert result["context"]["agent_state"]["working_state"]["targeting_criteria"]["state"] == "California"


def test_lead_finder_cache_session_is_stable_per_run_and_scoped_between_runs():
    first = lead_finder._cache_session_user("lfr_one")
    assert first == lead_finder._cache_session_user("lfr_one")
    assert first != lead_finder._cache_session_user("lfr_two")
    assert len(first or "") <= 64


def test_prompt_cache_metrics_normalizes_openclaw_chat_usage():
    metrics = prompt_cache_metrics({
        "prompt_tokens": 5000,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 4096},
    })

    assert metrics == {
        "status": "hit",
        "cached_tokens": 4096,
        "cache_write_tokens": None,
        "input_tokens": 5000,
        "hit_rate_percent": 81.9,
    }


def test_persistence_models_cover_runs_steps_and_every_gateway_attempt():
    assert LeadFinderRunRow.__tablename__ == "lead_finder_runs"
    assert LeadFinderStepRow.__tablename__ == "lead_finder_steps"
    assert LeadFinderAttemptRow.__tablename__ == "lead_finder_attempts"
    assert LeadFinderToolCallRow.__tablename__ == "lead_finder_tool_calls"
    assert {"request_json", "response_raw", "response_parsed_json"}.issubset(
        LeadFinderAttemptRow.__table__.columns.keys()
    )
    assert {"context_before_json", "context_after_json", "context_diff_json"}.issubset(
        LeadFinderStepRow.__table__.columns.keys()
    )
    step_run_fk = next(iter(LeadFinderStepRow.__table__.c.run_id.foreign_keys))
    attempt_step_fk = next(iter(LeadFinderAttemptRow.__table__.c.step_id.foreign_keys))
    tool_step_fk = next(iter(LeadFinderToolCallRow.__table__.c.step_id.foreign_keys))
    assert step_run_fk.ondelete == "CASCADE"
    assert attempt_step_fk.ondelete == "CASCADE"
    assert tool_step_fk.ondelete == "CASCADE"


def test_changed_paths_identifies_nested_context_evolution():
    assert lead_finder._changed_paths(
        {"agent_state": {"next_step": "one", "completed_steps": 0}},
        {"agent_state": {"next_step": "two", "completed_steps": 1}},
    ) == ["agent_state.completed_steps", "agent_state.next_step"]


def test_fresh_run_row_starts_before_step_one_with_requested_direction():
    row = lead_finder._build_lead_finder_run_row(
        user_direction="  California intake teams  ",
    )

    assert row.id.startswith("lfr_")
    assert row.status == "ready"
    assert row.current_step == 0
    assert row.user_direction == "California intake teams"
    assert row.current_context_json["user_direction"] == "California intake teams"
    assert row.next_step == "Assess the baseline context and the user's lead direction."


def test_mission_control_search_tool_validation_is_bounded():
    assert validate_lead_finder_tool_call(
        "mission_control.search",
        {"query": "after hours intake", "mode": "hybrid", "limit": 4},
    )["limit"] == 4
    try:
        validate_lead_finder_tool_call(
            "mission_control.search",
            {"query": "after hours intake", "limit": 11},
        )
    except MissionControlToolError as exc:
        assert str(exc) == "limit_must_be_between_1_and_10"
    else:
        raise AssertionError("expected bounded tool validation to reject limit=11")


def test_step_executes_one_requested_tool_and_adds_result_to_context(monkeypatch):
    async def fake_call_skill_json(**kwargs):
        return GatewayJSONResult(
            parsed={
                "step_name": "Search intake evidence",
                "summary": "Requested one transcript search.",
                "reasoning": "Podcast evidence is the next missing input.",
                "state_updates": {"search_plan": ["Search intake response discussions"]},
                "action": {
                    "type": "tool_call",
                    "tool": "mission_control.search",
                    "arguments": {"query": "after hours intake", "mode": "hybrid", "limit": 3},
                },
                "next_step": "Inspect the persisted search results.",
                "is_complete": False,
            },
            raw_response="{}",
            model="openclaw/main",
            usage={},
        )

    calls = []

    async def fake_tool_executor(tool_name, arguments):
        calls.append((tool_name, arguments))
        return {
            "id": "lft_test",
            "tool_name": tool_name,
            "status": "completed",
            "arguments": arguments,
            "result": {"results": [{"chunk_id": 42, "excerpt": "Calls after hours"}]},
            "error": None,
            "started_at": "2026-08-27T00:00:00+00:00",
            "completed_at": "2026-08-27T00:00:01+00:00",
        }

    monkeypatch.setattr(lead_finder, "call_skill_json", fake_call_skill_json)
    result = asyncio.run(
        lead_finder.run_lead_finder_step(
            context=lead_finder.load_lead_finder_context(),
            user_direction="Find intake leaders",
            tool_executor=fake_tool_executor,
        )
    )

    assert calls == [("mission_control.search", {
        "query": "after hours intake", "mode": "hybrid", "limit": 3,
    })]
    assert result["transition"]["tool_execution"]["id"] == "lft_test"
    history = result["context"]["agent_state"]["working_state"]["tool_history"]
    assert history[-1]["result"]["results"][0]["chunk_id"] == 42


def test_lead_finder_catalog_has_narrow_discovery_research_and_publish_tools():
    names = [item["name"] for item in lead_finder_tools.lead_finder_tool_catalog()]

    assert names == [
        "mission_control.search",
        "mission_control.get_passages",
        "mission_control.index_status",
        "web.research_person",
        "lead_finder.add_researched_lead",
    ]


def test_web_research_requires_mission_control_evidence():
    try:
        lead_finder_tools.validate_lead_finder_tool_call(
            "web.research_person",
            {"person_name": "Jane Operator", "mission_control_evidence": []},
        )
    except lead_finder_tools.LeadFinderToolError as exc:
        assert str(exc) == "mission_control_evidence_must_contain_1_to_5_items"
    else:
        raise AssertionError("expected web research without transcript evidence to fail")


def test_web_research_normalization_keeps_only_source_backed_angles():
    request = {
        "person_name": "Jane Operator",
        "organization": "Intake Co",
        "mission_control_evidence": [{"chunk_id": 42, "episode_title": "Intake"}],
    }
    normalized = normalize_person_research(
        {
            "person": {"name": "Jane Operator", "identity_confidence": 1.4},
            "profile_summary": "Runs intake operations.",
            "recent_signals": [],
            "sources": [{
                "url": "https://example.com/jane",
                "title": "Jane Operator",
                "supports": "Current role",
            }],
            "outreach_angles": [
                {
                    "title": "Supported",
                    "why_relevant": "Directly relevant.",
                    "evidence": "Published evidence.",
                    "question": "How do you handle follow-up?",
                    "source_urls": ["https://example.com/jane"],
                },
                {
                    "title": "Unsupported",
                    "source_urls": ["https://unsupported.example/test"],
                },
            ],
        },
        request=request,
    )

    assert normalized["person"]["organization"] == "Intake Co"
    assert normalized["person"]["identity_confidence"] == 1.0
    assert [item["title"] for item in normalized["outreach_angles"]] == ["Supported"]
    assert normalized["mission_control_evidence"][0]["chunk_id"] == 42


def test_add_researched_lead_requires_completed_research_and_selects_angles():
    research = {
        "person": {
            "name": "Jane Operator",
            "current_role": "COO",
            "organization": "Intake Co",
            "official_profile_url": "https://example.com/jane",
            "identity_confidence": 0.95,
        },
        "profile_summary": "Runs intake operations.",
        "recent_signals": [],
        "outreach_angles": [
            {"title": "First", "source_urls": ["https://example.com/jane"]},
            {"title": "Second", "source_urls": ["https://example.com/news"]},
        ],
        "sources": [{"url": "https://example.com/jane", "title": "Profile"}],
        "contrary_evidence": [],
        "mission_control_evidence": [{"chunk_id": 42}],
        "researched_at": "2026-08-28T00:00:00+00:00",
    }
    history = [{
        "id": "lft_research123",
        "tool_name": "web.research_person",
        "status": "completed",
        "result": research,
    }]

    result = asyncio.run(lead_finder_tools.execute_lead_finder_tool(
        "lead_finder.add_researched_lead",
        {
            "research_tool_call_id": "lft_research123",
            "selected_angle_indexes": [1],
            "notes": "Best fit for operations angle.",
        },
        tool_history=history,
    ))

    lead = result["lead"]
    assert lead["id"].startswith("lflead_")
    assert lead["name"] == "Jane Operator"
    assert [item["title"] for item in lead["outreach_angles"]] == ["Second"]
    assert lead["research_tool_call_id"] == "lft_research123"


def test_step_appends_explicitly_added_researched_lead_to_found_leads(monkeypatch):
    async def fake_call_skill_json(**kwargs):
        return GatewayJSONResult(
            parsed={
                "step_name": "Publish researched lead",
                "summary": "Added the verified candidate.",
                "reasoning": "Research is complete and source-backed.",
                "state_updates": {},
                "action": {
                    "type": "tool_call",
                    "tool": "lead_finder.add_researched_lead",
                    "arguments": {"research_tool_call_id": "lft_research123"},
                },
                "next_step": "Find another transcript candidate.",
                "is_complete": False,
            },
            raw_response="{}",
            model="openclaw/main",
            usage={},
        )

    lead = {
        "id": "lflead_test",
        "name": "Jane Operator",
        "sources": [{"url": "https://example.com/jane"}],
        "outreach_angles": [{"title": "Intake follow-up"}],
    }

    async def fake_tool_executor(tool_name, arguments):
        return {
            "id": "lft_add123",
            "tool_name": tool_name,
            "status": "completed",
            "arguments": arguments,
            "result": {"lead": lead},
            "error": None,
            "started_at": "2026-08-28T00:00:00+00:00",
            "completed_at": "2026-08-28T00:00:01+00:00",
        }

    monkeypatch.setattr(lead_finder, "call_skill_json", fake_call_skill_json)
    result = asyncio.run(lead_finder.run_lead_finder_step(
        context=lead_finder.load_lead_finder_context(),
        user_direction="Find intake experts",
        tool_executor=fake_tool_executor,
    ))

    found = result["context"]["agent_state"]["working_state"]["found_leads"]
    assert found == [lead]
