from datetime import datetime, timezone

from app.db.models import AgentReportRow, AgentTaskEventRow, AgentTaskRow
from app.services.master_agent import event_to_dict, report_to_dict, task_to_dict


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
