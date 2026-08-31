"""add job task kind

Revision ID: j1b2c3d4e5f6
Revises: c8d9e0f1a2b3
"""
from alembic import op
import sqlalchemy as sa


revision = "j1b2c3d4e5f6"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pif_job_research_tasks",
        sa.Column("kind", sa.String(length=32), server_default="research", nullable=False),
    )
    op.create_check_constraint(
        "ck_pif_job_research_tasks_kind",
        "pif_job_research_tasks",
        "kind IN ('research', 'classify')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pif_job_research_tasks_kind", "pif_job_research_tasks", type_="check")
    op.drop_column("pif_job_research_tasks", "kind")
