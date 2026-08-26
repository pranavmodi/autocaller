"""Add local post-extraction PIF enrichment queue.

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-08-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "w2x3y4z5a6b7"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pif_enrichment_tasks",
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("requested_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'in_progress', 'completed', 'failed')",
            name="ck_pif_enrichment_tasks_status",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_pif_enrichment_tasks_pif_id", "pif_enrichment_tasks", ["pif_id"])
    op.create_index(
        "ix_pif_enrichment_tasks_status_requested",
        "pif_enrichment_tasks",
        ["status", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pif_enrichment_tasks_status_requested", table_name="pif_enrichment_tasks")
    op.drop_index("ix_pif_enrichment_tasks_pif_id", table_name="pif_enrichment_tasks")
    op.drop_table("pif_enrichment_tasks")
