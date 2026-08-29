"""Add selectable web research provider to Lead Finder runs.

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-08-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_finder_runs",
        sa.Column(
            "web_research_provider",
            sa.String(length=32),
            nullable=False,
            server_default="openai",
        ),
    )
    op.create_check_constraint(
        "ck_lead_finder_runs_web_research_provider",
        "lead_finder_runs",
        "web_research_provider IN ('openai', 'openclaw')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_lead_finder_runs_web_research_provider",
        "lead_finder_runs",
        type_="check",
    )
    op.drop_column("lead_finder_runs", "web_research_provider")
