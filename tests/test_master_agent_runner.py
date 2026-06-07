import pytest

from app.services.master_agent_runner import run_master_agent_tool_loop


@pytest.mark.asyncio
async def test_runner_executes_bounded_filesystem_call_and_compacts_summary(monkeypatch):
    async def noop_trace(**kwargs):
        return None

    monkeypatch.setattr("app.services.master_agent_runner.safe_record_product_trace", noop_trace)
    decisions = iter([
        {
            "decision": "tool_call",
            "tool": "filesystem_read",
            "operation": "search_text",
            "path": "app/services",
            "query": "run_master_heartbeat",
            "reason": "Find heartbeat implementation.",
        },
        {
            "decision": "finish",
            "summary": "Found heartbeat implementation.",
            "facts_learned": ["Heartbeat is implemented in master_agent.py."],
            "next_actions": ["Read app/api/agents.py."],
        },
    ])

    async def provider(payload):
        assert payload["limits"]["allowed_tools"] == ["filesystem_read", "action_read", "sandbox_write"]
        return next(decisions)

    async def executor(payload):
        assert payload["operation"] == "search_text"
        return {
            "allowed": True,
            "result": {
                "operation": "search_text",
                "summary": "1 match",
                "files_touched": ["app/services/master_agent.py"],
                "truncated": False,
            },
        }

    result = await run_master_agent_tool_loop(
        wake_context={"kind": "master_agent_wake_context_v2"},
        active_goal={"id": "goal_1", "goal": "Understand the codebase."},
        decision_provider=provider,
        tool_executor=executor,
        persist_continuation=False,
    )

    assert result["status"] == "completed"
    assert result["tool_calls_used"] == 1
    assert result["steps"][0]["operation"] == "search_text"
    assert result["previous_heartbeat_summary"]["files_inspected"] == ["app/services/master_agent.py"]
    assert result["previous_heartbeat_summary"]["learned"] == ["Heartbeat is implemented in master_agent.py."]


@pytest.mark.asyncio
async def test_runner_blocks_when_no_decision_provider(monkeypatch):
    async def noop_trace(**kwargs):
        return None

    monkeypatch.setattr("app.services.master_agent_runner.safe_record_product_trace", noop_trace)

    result = await run_master_agent_tool_loop(
        wake_context={"kind": "master_agent_wake_context_v2"},
        active_goal={"id": "goal_1", "goal": "Understand the codebase."},
        persist_continuation=False,
    )

    assert result["status"] == "blocked"
    assert result["tool_calls_used"] == 0
    assert "No runner decision provider" in result["final_answer"]["summary"]


@pytest.mark.asyncio
async def test_runner_continuation_merges_prior_files(monkeypatch):
    async def noop_trace(**kwargs):
        return None

    async def fake_report(**kwargs):
        return {
            "continuation_state": {
                "files_read": kwargs["files_read"],
                "facts_learned": kwargs["facts_learned"],
                "remaining_questions": kwargs["remaining_questions"],
            },
            "report": {"id": "report_1"},
        }

    monkeypatch.setattr("app.services.master_agent_runner.safe_record_product_trace", noop_trace)
    monkeypatch.setattr("app.services.master_agent_runner.create_goal_continuation_report", fake_report)

    decisions = iter([
        {
            "decision": "tool_call",
            "tool": "filesystem_read",
            "operation": "read_file",
            "path": "app/services/master_agent.py",
        },
    ])

    async def provider(payload):
        return next(decisions)

    async def executor(payload):
        return {
            "allowed": True,
            "result": {
                "operation": "read_file",
                "summary": "read app/services/master_agent.py:1-20",
                "files_touched": ["app/services/master_agent.py"],
                "truncated": False,
                "content": "1|code",
            },
        }

    result = await run_master_agent_tool_loop(
        wake_context={
            "volatile_wake_state": {
                "goal_continuation_state": {
                    "files_read": ["1518", "app/api/agents.py"],
                    "facts_learned": ["API exposes heartbeat."],
                    "remaining_questions": ["Inspect CLI."],
                },
            },
        },
        active_goal={"id": "goal_1", "goal": "Understand the codebase."},
        decision_provider=provider,
        tool_executor=executor,
        max_iterations=1,
    )

    continuation = result["goal_continuation_state"]
    assert continuation["files_read"] == ["app/api/agents.py", "app/services/master_agent.py"]
    assert continuation["facts_learned"] == ["API exposes heartbeat."]
    assert continuation["remaining_questions"] == [
        "Continue from the compact step summaries.",
        "Inspect CLI.",
    ]


@pytest.mark.asyncio
async def test_runner_executes_action_read_tool_call(monkeypatch):
    async def noop_trace(**kwargs):
        return None

    monkeypatch.setattr("app.services.master_agent_runner.safe_record_product_trace", noop_trace)
    decisions = iter([
        {
            "decision": "tool_call",
            "tool": "action_read",
            "operation": "get_action",
            "action_id": "action_blocked",
            "reason": "Inspect blocked action feedback.",
        },
        {
            "decision": "finish",
            "summary": "Action was stale duplicate work.",
            "facts_learned": ["Policy blocks duplicate sends and exposes the prior successful action."],
            "next_actions": [],
        },
    ])

    async def provider(payload):
        if payload["steps"]:
            assert payload["observations"][0]["interpretation"]["feedback_type"] == "action_not_executable"
        return next(decisions)

    async def fake_action_read(payload, *, actor="master-agent"):
        assert actor == "master-agent"
        assert payload["operation"] == "get_action"
        assert payload["action_id"] == "action_blocked"
        return {
            "allowed": True,
            "result": {
                "operation": "get_action",
                "action_id": "action_blocked",
                "summary": "blocked send_email action_blocked",
                "files_touched": [],
                "truncated": False,
                "interpretation": {
                    "feedback_type": "action_not_executable",
                    "reason": "no_prior_successful_lead_gen_action_for_recipient",
                    "related_action_ids": ["action_prior_success"],
                },
            },
        }

    monkeypatch.setattr("app.services.master_agent_runner.run_action_read", fake_action_read)

    result = await run_master_agent_tool_loop(
        wake_context={"kind": "master_agent_wake_context_v2"},
        active_goal={"id": "goal_1", "goal": "Understand why action_blocked did not send."},
        decision_provider=provider,
        persist_continuation=False,
    )

    assert result["status"] == "completed"
    assert result["tool_calls_used"] == 1
    assert result["steps"][0]["tool"] == "action_read"
    assert result["steps"][0]["operation"] == "get_action"
    assert result["previous_heartbeat_summary"]["files_inspected"] == []
    assert result["previous_heartbeat_summary"]["learned"] == [
        "Policy blocks duplicate sends and exposes the prior successful action.",
    ]


@pytest.mark.asyncio
async def test_runner_executes_sandbox_write_tool_call(monkeypatch):
    async def noop_trace(**kwargs):
        return None

    monkeypatch.setattr("app.services.master_agent_runner.safe_record_product_trace", noop_trace)
    decisions = iter([
        {
            "decision": "tool_call",
            "tool": "sandbox_write",
            "operation": "write",
            "path": "master-agent-understanding.md",
            "content": "# Master Agent Understanding\n\nFirst durable note.",
            "reason": "Persist a working understanding note.",
        },
        {
            "decision": "finish",
            "summary": "Wrote the sandbox understanding note.",
            "facts_learned": ["Sandbox writes can persist working notes."],
            "next_actions": [],
        },
    ])

    async def provider(payload):
        if payload["steps"]:
            assert payload["observations"][0]["path"] == "master-agent-understanding.md"
            assert payload["observations"][0]["bytes_written"] > 0
        return next(decisions)

    async def fake_sandbox_write(payload, *, actor="master-agent"):
        assert actor == "master-agent"
        assert payload["operation"] == "write"
        assert payload["path"] == "master-agent-understanding.md"
        return {
            "allowed": True,
            "result": {
                "operation": "write",
                "path": "master-agent-understanding.md",
                "summary": "write sandbox file master-agent-understanding.md",
                "files_touched": ["master-agent-understanding.md"],
                "bytes_written": len(payload["content"]),
                "before_bytes": 0,
                "after_bytes": len(payload["content"]),
                "truncated": False,
            },
        }

    monkeypatch.setattr("app.services.master_agent_runner.run_sandbox_write", fake_sandbox_write)

    result = await run_master_agent_tool_loop(
        wake_context={"kind": "master_agent_wake_context_v2"},
        active_goal={"id": "goal_1", "goal": "Write a sandbox understanding note."},
        decision_provider=provider,
        persist_continuation=False,
    )

    assert result["status"] == "completed"
    assert result["tool_calls_used"] == 1
    assert result["steps"][0]["tool"] == "sandbox_write"
    assert result["steps"][0]["operation"] == "write"
    assert result["previous_heartbeat_summary"]["files_inspected"] == [
        "master-agent-understanding.md",
    ]
