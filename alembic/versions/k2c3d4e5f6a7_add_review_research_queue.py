"""add source-backed firm review research

Revision ID: k2c3d4e5f6a7
Revises: j1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "k2c3d4e5f6a7"
down_revision = "j1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("firm_reviews", sa.Column("reviews_json", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("firm_reviews", sa.Column("review_research_status", sa.String(length=32), nullable=True))
    op.add_column("firm_reviews", sa.Column("review_research_provider", sa.String(length=64), nullable=True))
    op.add_column("firm_reviews", sa.Column("last_review_researched_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("firm_reviews", sa.Column("review_research_error", sa.Text(), nullable=True))
    op.create_table(
        "firm_review_research_tasks",
        sa.Column("task_id", sa.String(length=128), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result_summary", JSONB(), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'in_progress', 'completed', 'failed')", name="ck_firm_review_research_tasks_status"),
    )
    op.create_index("ix_firm_review_research_tasks_pif_status", "firm_review_research_tasks", ["pif_id", "status"])
    op.create_index("ix_firm_review_research_tasks_status_requested", "firm_review_research_tasks", ["status", "requested_at"])


def downgrade() -> None:
    op.drop_index("ix_firm_review_research_tasks_status_requested", table_name="firm_review_research_tasks")
    op.drop_index("ix_firm_review_research_tasks_pif_status", table_name="firm_review_research_tasks")
    op.drop_table("firm_review_research_tasks")
    op.drop_column("firm_reviews", "review_research_error")
    op.drop_column("firm_reviews", "last_review_researched_at")
    op.drop_column("firm_reviews", "review_research_provider")
    op.drop_column("firm_reviews", "review_research_status")
    op.drop_column("firm_reviews", "reviews_json")
