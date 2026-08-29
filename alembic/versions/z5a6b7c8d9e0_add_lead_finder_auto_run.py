"""Add durable bounded auto-run state to Lead Finder runs.

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-08-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "z5a6b7c8d9e0"
down_revision = "y4z5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_finder_runs",
        sa.Column("auto_run_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "lead_finder_runs",
        sa.Column("auto_run_max_steps", sa.Integer(), nullable=False, server_default="25"),
    )
    op.add_column(
        "lead_finder_runs",
        sa.Column("auto_run_started_step", sa.Integer(), nullable=True),
    )
    op.add_column(
        "lead_finder_runs",
        sa.Column("auto_run_stop_reason", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_lead_finder_runs_auto_max_steps",
        "lead_finder_runs",
        "auto_run_max_steps BETWEEN 1 AND 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_lead_finder_runs_auto_max_steps",
        "lead_finder_runs",
        type_="check",
    )
    op.drop_column("lead_finder_runs", "auto_run_stop_reason")
    op.drop_column("lead_finder_runs", "auto_run_started_step")
    op.drop_column("lead_finder_runs", "auto_run_max_steps")
    op.drop_column("lead_finder_runs", "auto_run_enabled")
