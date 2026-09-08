"""Add the dedicated Codex app-server Lead Finder provider.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-09-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "p6q7r8s9t0u1"
down_revision = "o5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_lead_finder_runs_llm_provider", "lead_finder_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_lead_finder_runs_llm_provider",
        "lead_finder_runs",
        "llm_provider IN ('openai', 'openclaw', 'codex')",
    )
    op.add_column(
        "lead_finder_runs",
        sa.Column("codex_thread_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE lead_finder_runs SET llm_provider = 'openai' "
        "WHERE llm_provider = 'codex'"
    ))
    op.drop_column("lead_finder_runs", "codex_thread_id")
    op.drop_constraint(
        "ck_lead_finder_runs_llm_provider", "lead_finder_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_lead_finder_runs_llm_provider",
        "lead_finder_runs",
        "llm_provider IN ('openai', 'openclaw')",
    )
