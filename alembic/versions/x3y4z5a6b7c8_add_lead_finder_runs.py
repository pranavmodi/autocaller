"""Add durable Lead Finder runs, steps, and gateway attempts.

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-08-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_finder_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("debug_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("user_direction", sa.Text(), nullable=False, server_default=""),
        sa.Column("job_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("baseline_context_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("baseline_context_hash", sa.String(length=64), nullable=False),
        sa.Column("current_context_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("restarted_from_run_id", sa.String(length=64), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ready', 'queued', 'running', 'paused', 'completed', 'failed')", name="ck_lead_finder_runs_status"),
        sa.ForeignKeyConstraint(["restarted_from_run_id"], ["lead_finder_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_finder_runs_status", "lead_finder_runs", ["status"])
    op.create_index("ix_lead_finder_runs_created_at", "lead_finder_runs", ["created_at"])
    op.create_index("ix_lead_finder_runs_restarted_from", "lead_finder_runs", ["restarted_from_run_id"])

    op.create_table(
        "lead_finder_steps",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("user_direction", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_before_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("request_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_parsed_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_after_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_diff_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("skill_path", sa.String(length=512), nullable=True),
        sa.Column("usage_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('queued', 'running', 'retrying', 'completed', 'failed', 'interrupted')", name="ck_lead_finder_steps_status"),
        sa.ForeignKeyConstraint(["run_id"], ["lead_finder_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_lead_finder_steps_request_id"),
        sa.UniqueConstraint("run_id", "step_number", name="uq_lead_finder_steps_run_number"),
    )
    op.create_index("ix_lead_finder_steps_run_id", "lead_finder_steps", ["run_id"])
    op.create_index("ix_lead_finder_steps_status", "lead_finder_steps", ["status"])
    op.create_index("ix_lead_finder_steps_created_at", "lead_finder_steps", ["created_at"])

    op.create_table(
        "lead_finder_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("request_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("response_parsed_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("usage_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'timed_out', 'interrupted')", name="ck_lead_finder_attempts_status"),
        sa.ForeignKeyConstraint(["step_id"], ["lead_finder_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id", "attempt_number", name="uq_lead_finder_attempts_step_number"),
    )
    op.create_index("ix_lead_finder_attempts_step_id", "lead_finder_attempts", ["step_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_finder_attempts_step_id", table_name="lead_finder_attempts")
    op.drop_table("lead_finder_attempts")
    op.drop_index("ix_lead_finder_steps_created_at", table_name="lead_finder_steps")
    op.drop_index("ix_lead_finder_steps_status", table_name="lead_finder_steps")
    op.drop_index("ix_lead_finder_steps_run_id", table_name="lead_finder_steps")
    op.drop_table("lead_finder_steps")
    op.drop_index("ix_lead_finder_runs_restarted_from", table_name="lead_finder_runs")
    op.drop_index("ix_lead_finder_runs_created_at", table_name="lead_finder_runs")
    op.drop_index("ix_lead_finder_runs_status", table_name="lead_finder_runs")
    op.drop_table("lead_finder_runs")
