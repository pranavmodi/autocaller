from datetime import datetime, timezone

from app.db.models import AgentReportRow, AgentTaskEventRow, AgentTaskRow
from app.services.master_agent import (
    _build_wake_context,
    _normalize_agent_config,
    _objective_status_context,
    continuation_state_from_report,
    event_summary_to_dict,
    event_to_dict,
    report_to_dict,
    task_to_dict,
)


def test_agent_task_to_dict_exposes_delegation_packet_fields():
    row = AgentTaskRow(
        id="task_1",
        assigned_agent="ResearchScoutAgent",
        title="Scan official agent articles",
        objective="Find useful self-improvement ideas.",
        context_json={"source_scope": ["openai", "anthropic"]},
        allowed_tools_json=["web_search"],
        forbidden_actions_json=["edit soul.md"],
        expected_output_schema_json={"summary": "string"},
        acceptance_criteria_json=["official sources only"],
        verification_commands_json=[],
        artifacts_json=[],
        risk_level="low",
        requires_human_approval=False,
        status="queued",
        priority=80,
        heartbeat_interval_seconds=300,
        created_by="operator",
        created_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    assert task_to_dict(row) == {
        "id": "task_1",
        "parent_task_id": None,
        "assigned_agent": "ResearchScoutAgent",
        "title": "Scan official agent articles",
        "objective": "Find useful self-improvement ideas.",
        "context": {"source_scope": ["openai", "anthropic"]},
        "allowed_tools": ["web_search"],
        "forbidden_actions": ["edit soul.md"],
        "expected_output_schema": {"summary": "string"},
        "acceptance_criteria": ["official sources only"],
        "verification_commands": [],
        "artifacts": [],
        "risk_level": "low",
        "requires_human_approval": False,
        "status": "queued",
        "priority": 80,
        "heartbeat_interval_seconds": 300,
        "last_heartbeat_at": None,
        "claimed_at": None,
        "deadline_at": None,
        "completed_at": None,
        "created_by": "operator",
        "created_at": "2026-06-03T00:00:00+00:00",
        "updated_at": "2026-06-03T00:00:00+00:00",
    }


def test_event_and_report_dicts_expose_report_back_fields():
    event = AgentTaskEventRow(
        id=4,
        task_id="task_1",
        agent_id="ResearchScoutAgent",
        event_type="heartbeat",
        message="still reading",
        input_json={},
        output_json={"status": "running"},
        metadata_json={"source": "unit-test"},
        created_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    report = AgentReportRow(
        id="report_1",
        task_id="task_1",
        agent_id="ResearchScoutAgent",
        status="reported",
        summary="Found one useful idea.",
        key_findings_json=["Use evals before changing skills."],
        actions_taken_json=[],
        artifacts_json=[],
        evidence_json=[],
        verification_json=[],
        risks_json=[],
        open_questions_json=[],
        recommended_next_actions_json=["Create eval case."],
        created_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    assert event_to_dict(event)["event_type"] == "heartbeat"
    assert event_to_dict(event)["output"] == {"status": "running"}
    assert report_to_dict(report)["summary"] == "Found one useful idea."
    assert report_to_dict(report)["recommended_next_actions"] == ["Create eval case."]


def test_continuation_state_from_report_extracts_goal_handoff():
    state = {
        "kind": "goal_continuation_state",
        "goal_id": "goal_1",
        "files_read": ["app/services/master_agent.py"],
    }
    report = {
        "id": "report_1",
        "evidence": [{"kind": "other"}, state],
    }

    assert continuation_state_from_report(report) == state


def test_agent_config_normalizes_tool_runner_settings():
    config = _normalize_agent_config({
        "tool_runner_enabled": True,
        "tool_runner_max_iterations": 50,
        "tool_runner_max_runtime_seconds": 999,
        "tool_runner_persist_continuation": False,
    })

    assert config["tool_runner_enabled"] is True
    assert config["tool_runner_max_iterations"] == 5
    assert config["tool_runner_max_runtime_seconds"] == 180
    assert config["tool_runner_persist_continuation"] is False


def test_event_summary_dict_omits_heavy_payloads():
    event = AgentTaskEventRow(
        id=5,
        task_id=None,
        agent_id="master-agent",
        event_type="master_heartbeat_completed",
        message="heartbeat completed",
        input_json={"large": "x" * 1000},
        output_json={
            "active_task_count": 0,
            "queued_task_count": 0,
            "blocked_task_count": 0,
            "human_status": {"state": "The system is idle but ready."},
        },
        metadata_json={"source": "unit-test"},
        created_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    summary = event_summary_to_dict(event)

    assert summary["summary"] == "The system is idle but ready."
    assert summary["has_payload"] is True
    assert summary["payload_size_bytes"] > 1000
    assert "input" not in summary
    assert "output" not in summary
    assert "metadata" not in summary


def test_wake_context_v2_does_not_duplicate_legacy_top_level_fields():
    continuation_state = {
        "kind": "goal_continuation_state",
        "goal_id": "goal_1",
        "tool_loop": {
            "previous_heartbeat_summary": {
                "status": "completed",
                "files_inspected": ["app/services/master_agent.py"],
            },
        },
    }
    context = _build_wake_context(
        started_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
        actor="operator",
        agent_config={
            "heartbeat_enabled": False,
            "heartbeat_interval_seconds": 600,
            "tool_runner_enabled": True,
            "tool_runner_max_iterations": 3,
            "tool_runner_max_runtime_seconds": 90,
            "tool_runner_persist_continuation": True,
        },
        active_tasks=[],
        recent_reports=[],
        recent_events=[],
        heartbeat_history={},
        queue_analysis={"stale_queue_items": [], "blocked_capabilities": []},
        capabilities=[],
        active_goal={"goal": "Test goal", "next_actions": ["Do the next thing"]},
        recent_actions=[],
        goal_continuation_state=continuation_state,
    )

    assert context["kind"] == "master_agent_wake_context_v2"
    assert "cached_static_context" in context
    assert "volatile_wake_state" in context
    assert "active_goal" in context["volatile_wake_state"]
    assert "recent_actions" in context["volatile_wake_state"]
    assert context["volatile_wake_state"]["tool_runner"]["enabled"] is True
    assert context["volatile_wake_state"]["tool_runner"]["allowed_tools"] == [
        "filesystem_read",
        "action_read",
        "sandbox_write",
    ]
    assert context["volatile_wake_state"]["tool_runner"]["sandbox_root"] == "data/agent-sandbox"
    assert context["volatile_wake_state"]["goal_continuation_state"] == continuation_state
    assert context["volatile_wake_state"]["previous_heartbeat_summary"]["files_inspected"] == [
        "app/services/master_agent.py",
    ]

    for legacy_key in (
        "mission",
        "woke_at",
        "actor",
        "prime_directives",
        "soul_compact",
        "active_goal",
        "goal_stack",
        "objective_status",
        "current_state",
        "configuration",
        "capabilities_today",
        "current_tasks",
        "recent_actions",
        "goal_evidence",
        "recent_evidence",
        "queue_analysis",
        "recent_reports",
        "recent_events",
        "recent_heartbeat_summary",
        "constraints",
        "next_recommended_slice",
        "soul",
    ):
        assert legacy_key not in context


def test_objective_status_detects_satisfied_test_email_goal():
    active_goal = {
        "id": "goal_1",
        "goal": "Test the durable action execution path by sending a test email to pranav.modi@gmail.com.",
        "success_metric": "A test email is sent to pranav.modi@gmail.com.",
        "next_actions": ["Send the test email."],
        "source": {"manual": True},
    }
    recent_actions = [{
        "id": "action_1",
        "action_type": "send_email",
        "status": "succeeded",
        "input_summary": {"test_email": True},
        "result_summary": {
            "sent_to": "pranav.modi@gmail.com",
            "sent_message_id": "msg_123",
            "sent_at": "2026-06-05T12:00:00+00:00",
        },
    }]

    status = _objective_status_context(active_goal, recent_actions, [], [])

    assert status["status"] == "satisfied"
    assert status["remaining_work"] == []
    assert status["evidence"][0]["action_id"] == "action_1"


def test_objective_status_detects_failed_relevant_action_as_blocked():
    active_goal = {
        "id": "goal_2",
        "goal": "Send approved lead-gen emails through the durable action path.",
        "success_metric": "Approved lead-gen email sends succeed.",
        "next_actions": ["Inspect failed sends."],
    }
    recent_actions = [{
        "id": "action_2",
        "action_type": "send_email",
        "entity_type": "lead_gen_email",
        "status": "failed",
        "input_summary": {"subject": "the Precise autoresponders"},
        "result_summary": {},
        "error": "Zoho API rejected the request.",
    }]

    status = _objective_status_context(active_goal, recent_actions, [], [])

    assert status["status"] == "blocked"
    assert status["evidence"][0]["type"] == "failed_relevant_action"
    assert status["evidence"][0]["action_id"] == "action_2"


def test_objective_status_detects_stale_task():
    active_goal = {
        "id": "goal_3",
        "goal": "Run the read-only SystemsHealthAgent observation slice.",
        "next_actions": ["Resolve the stale task."],
    }
    active_tasks = [{
        "id": "task_1",
        "assigned_agent": "SystemsHealthAgent",
        "title": "Read-only health observation",
        "status": "stale",
    }]

    status = _objective_status_context(active_goal, [], active_tasks, [])

    assert status["status"] == "stale"
    assert status["evidence"][0]["type"] == "task_stale"
    assert status["next_best_action"] == "Resolve stale queued or running work before expanding autonomy."


def test_objective_status_waits_only_on_explicit_user_waiting_task():
    active_goal = {
        "id": "goal_4",
        "goal": "Resolve a task that requires user input.",
        "next_actions": ["Answer the blocking question."],
    }
    active_tasks = [{
        "id": "task_2",
        "assigned_agent": "ResearchScoutAgent",
        "title": "Needs user clarification",
        "status": "waiting_on_user",
    }]
    recent_reports = [{
        "id": "report_2",
        "open_questions": ["Non-blocking report question."],
    }]

    status = _objective_status_context(active_goal, [], active_tasks, recent_reports)

    assert status["status"] == "waiting_on_user"
    assert status["evidence"][0]["type"] == "task_waiting_on_user"


def test_objective_status_report_questions_do_not_block_without_waiting_task():
    active_goal = {
        "id": "goal_5",
        "goal": "Convert latest agent reports into reviewable improvement findings.",
        "next_actions": ["Review the latest report evidence."],
    }
    recent_reports = [{
        "id": "report_3",
        "open_questions": ["Could create a finding, but not blocking."],
    }]

    status = _objective_status_context(active_goal, [], [], recent_reports)

    assert status["status"] == "in_progress"


def test_objective_status_missing_goal():
    status = _objective_status_context(None, [], [], [])

    assert status["status"] == "missing_goal"
    assert status["active_goal_id"] is None
