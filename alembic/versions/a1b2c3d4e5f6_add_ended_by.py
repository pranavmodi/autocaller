"""Add ended_by column to call_logs

Records who ended the call (ai_tool, vm_detect, ivr_navigator,
silence_watchdog, stream_closed, error, manual). Null on legacy rows.

Revision ID: a1b2c3d4e5f6
Revises: z0a1b2c3d4e5
Create Date: 2026-04-22 15:40:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_logs",
        sa.Column("ended_by", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_logs", "ended_by")
