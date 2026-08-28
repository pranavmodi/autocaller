"""Add durable Lead Finder tool calls.

Revision ID: y4z5a6b7c8d9
Revises: x3y4z5a6b7c8
Create Date: 2026-08-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "y4z5a6b7c8d9"
down_revision = "x3y4z5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_finder_tool_calls",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("arguments_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'interrupted')",
            name="ck_lead_finder_tool_calls_status",
        ),
        sa.ForeignKeyConstraint(["step_id"], ["lead_finder_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_finder_tool_calls_step_id", "lead_finder_tool_calls", ["step_id"])
    op.create_index("ix_lead_finder_tool_calls_status", "lead_finder_tool_calls", ["status"])


def downgrade() -> None:
    op.drop_index("ix_lead_finder_tool_calls_status", table_name="lead_finder_tool_calls")
    op.drop_index("ix_lead_finder_tool_calls_step_id", table_name="lead_finder_tool_calls")
    op.drop_table("lead_finder_tool_calls")
