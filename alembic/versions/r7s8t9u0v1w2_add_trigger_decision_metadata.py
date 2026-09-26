"""Add structured LLM decision metadata to firm trigger events.

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-09-09 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "r7s8t9u0v1w2"
down_revision = "q6r7s8t9u0v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "firm_trigger_events",
        sa.Column(
            "decision_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("firm_trigger_events", "decision_metadata")
