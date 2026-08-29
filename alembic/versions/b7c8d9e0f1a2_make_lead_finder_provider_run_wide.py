"""Make the Lead Finder provider run-wide.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-08-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_lead_finder_runs_web_research_provider",
        "lead_finder_runs",
        type_="check",
    )
    op.alter_column(
        "lead_finder_runs",
        "web_research_provider",
        new_column_name="llm_provider",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_lead_finder_runs_llm_provider",
        "lead_finder_runs",
        "llm_provider IN ('openai', 'openclaw')",
    )
    op.add_column(
        "lead_finder_runs",
        sa.Column("openai_previous_response_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "lead_finder_runs",
        sa.Column(
            "openclaw_session_started",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(sa.text("""
        UPDATE lead_finder_runs AS run
        SET openclaw_session_started = EXISTS (
            SELECT 1
            FROM lead_finder_steps AS step
            JOIN lead_finder_attempts AS attempt ON attempt.step_id = step.id
            WHERE step.run_id = run.id
              AND attempt.model LIKE 'openclaw/%'
              AND attempt.status = 'completed'
        )
    """))


def downgrade() -> None:
    op.drop_column("lead_finder_runs", "openclaw_session_started")
    op.drop_column("lead_finder_runs", "openai_previous_response_id")
    op.drop_constraint(
        "ck_lead_finder_runs_llm_provider",
        "lead_finder_runs",
        type_="check",
    )
    op.alter_column(
        "lead_finder_runs",
        "llm_provider",
        new_column_name="web_research_provider",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_lead_finder_runs_web_research_provider",
        "lead_finder_runs",
        "web_research_provider IN ('openai', 'openclaw')",
    )
