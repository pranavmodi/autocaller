"""allow sitemap maintenance tasks

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
"""
from alembic import op


revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_pif_job_research_tasks_kind",
        "pif_job_research_tasks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pif_job_research_tasks_kind",
        "pif_job_research_tasks",
        "kind IN ('research', 'classify', 'sitemap')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_pif_job_research_tasks_kind",
        "pif_job_research_tasks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pif_job_research_tasks_kind",
        "pif_job_research_tasks",
        "kind IN ('research', 'classify')",
    )
