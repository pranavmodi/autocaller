"""Add lead-gen observation dedupe key

Revision ID: m6n7o8p9q0r1
Revises: l6m7n8o9p0q1
Create Date: 2026-06-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "m6n7o8p9q0r1"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_gen_observations",
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_lead_gen_observations_dedupe_key",
        "lead_gen_observations",
        ["dedupe_key"],
    )
    op.create_unique_constraint(
        "uq_lead_gen_observations_event_dedupe",
        "lead_gen_observations",
        ["event_type", "dedupe_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_lead_gen_observations_event_dedupe",
        "lead_gen_observations",
        type_="unique",
    )
    op.drop_index("ix_lead_gen_observations_dedupe_key", table_name="lead_gen_observations")
    op.drop_column("lead_gen_observations", "dedupe_key")
