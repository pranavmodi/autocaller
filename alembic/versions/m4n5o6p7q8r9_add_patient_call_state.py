"""Add patient_call_state table for local tracking in live mode

Tracks per-patient call outcomes, attempt counts, and cooldowns
when using the live RadFlow patient provider (which is read-only).
Merged with API data on each fetch to enforce retry controls.

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-03-23 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP

revision = "m4n5o6p7q8r9"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "patient_call_state",
        sa.Column("patient_id", sa.String(64), primary_key=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_attempt_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_outcome", sa.String(32), nullable=True),
        sa.Column("ai_called_before", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("invalid_number", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_patient_call_state_updated", "patient_call_state", ["updated_at"])


def downgrade():
    op.drop_index("ix_patient_call_state_updated")
    op.drop_table("patient_call_state")
