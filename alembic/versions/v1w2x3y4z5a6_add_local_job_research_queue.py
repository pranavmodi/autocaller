"""Add local OpenClaw job-opening research queue.

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "v1w2x3y4z5a6"
down_revision = "u0v1w2x3y4z5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pif_job_research_tasks",
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column(
            "requested_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'in_progress', 'completed', 'failed')",
            name="ck_pif_job_research_tasks_status",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_pif_job_research_tasks_pif_id",
        "pif_job_research_tasks",
        ["pif_id"],
    )
    op.create_index(
        "ix_pif_job_research_tasks_status_requested",
        "pif_job_research_tasks",
        ["status", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pif_job_research_tasks_status_requested",
        table_name="pif_job_research_tasks",
    )
    op.drop_index("ix_pif_job_research_tasks_pif_id", table_name="pif_job_research_tasks")
    op.drop_table("pif_job_research_tasks")
