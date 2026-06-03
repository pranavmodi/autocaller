"""Add master agent task coordination tables

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-06-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "j5k6l7m8n9o0"
down_revision = "i4j5k6l7m8n9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("parent_task_id", sa.String(length=64), nullable=True),
        sa.Column("assigned_agent", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("context_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("allowed_tools_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("forbidden_actions_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expected_output_schema_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("acceptance_criteria_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("verification_commands_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifacts_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("heartbeat_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("last_heartbeat_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("claimed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deadline_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('queued', 'accepted', 'running', 'waiting_on_tool', "
            "'waiting_on_user', 'blocked', 'completed', 'failed', 'cancelled', 'stale')",
            name="ck_agent_tasks_status",
        ),
    )
    op.create_index("ix_agent_tasks_status", "agent_tasks", ["status"])
    op.create_index("ix_agent_tasks_agent_status", "agent_tasks", ["assigned_agent", "status"])
    op.create_index("ix_agent_tasks_updated_at", "agent_tasks", ["updated_at"])
    op.create_index("ix_agent_tasks_last_heartbeat", "agent_tasks", ["last_heartbeat_at"])

    op.create_table(
        "agent_task_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("input_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_task_events_task_id", "agent_task_events", ["task_id"])
    op.create_index("ix_agent_task_events_agent_type", "agent_task_events", ["agent_id", "event_type"])
    op.create_index("ix_agent_task_events_created_at", "agent_task_events", ["created_at"])

    op.create_table(
        "agent_reports",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="reported"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_findings_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("actions_taken_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("artifacts_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("verification_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("risks_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("open_questions_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recommended_next_actions_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_reports_task_id", "agent_reports", ["task_id"])
    op.create_index("ix_agent_reports_agent_status", "agent_reports", ["agent_id", "status"])
    op.create_index("ix_agent_reports_created_at", "agent_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_reports_created_at", table_name="agent_reports")
    op.drop_index("ix_agent_reports_agent_status", table_name="agent_reports")
    op.drop_index("ix_agent_reports_task_id", table_name="agent_reports")
    op.drop_table("agent_reports")
    op.drop_index("ix_agent_task_events_created_at", table_name="agent_task_events")
    op.drop_index("ix_agent_task_events_agent_type", table_name="agent_task_events")
    op.drop_index("ix_agent_task_events_task_id", table_name="agent_task_events")
    op.drop_table("agent_task_events")
    op.drop_index("ix_agent_tasks_last_heartbeat", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_updated_at", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_agent_status", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_status", table_name="agent_tasks")
    op.drop_table("agent_tasks")
