"""Add experiment lifecycle fields to lead-gen batches

Revision ID: w5x6y7z8a9b0
Revises: v4w5x6y7z8a9
Create Date: 2026-07-09 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "w5x6y7z8a9b0"
down_revision = "v4w5x6y7z8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_gen_batches",
        sa.Column(
            "experiment_status",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "lead_gen_batches",
        sa.Column(
            "experiment_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "lead_gen_batches",
        sa.Column("experiment_updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "lead_gen_batches",
        sa.Column("experiment_closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_lead_gen_batches_experiment_status",
        "lead_gen_batches",
        "experiment_status IN ('none', 'draft', 'ready', 'scheduled', 'measuring', 'awaiting_verdict', 'closed', 'superseded')",
    )
    op.create_index(
        "ix_lead_gen_batches_experiment_status",
        "lead_gen_batches",
        ["experiment_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_gen_batches_experiment_status", table_name="lead_gen_batches")
    op.drop_constraint(
        "ck_lead_gen_batches_experiment_status",
        "lead_gen_batches",
        type_="check",
    )
    op.drop_column("lead_gen_batches", "experiment_closed_at")
    op.drop_column("lead_gen_batches", "experiment_updated_at")
    op.drop_column("lead_gen_batches", "experiment_json")
    op.drop_column("lead_gen_batches", "experiment_status")
