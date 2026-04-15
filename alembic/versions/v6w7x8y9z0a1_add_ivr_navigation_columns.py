"""Add IVR navigation columns to call_logs + system_settings

When the AI hits a phone tree, the navigator records every hop (menu
it heard, option chosen, rationale, result) so we can review what worked
and what didn't. The feature is opt-in via system_settings.ivr_navigate_enabled.

Revision ID: v6w7x8y9z0a1
Revises: u2v3w4x5y6z7
Create Date: 2026-04-15 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "v6w7x8y9z0a1"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("ivr_detected", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("call_logs", sa.Column("ivr_outcome", sa.String(32), nullable=True))
    op.add_column("call_logs", sa.Column("ivr_menu_log", JSONB, nullable=True))
    op.create_index("ix_call_logs_ivr_outcome", "call_logs", ["ivr_outcome"])

    op.add_column(
        "system_settings",
        sa.Column("ivr_navigate_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("system_settings", "ivr_navigate_enabled")
    op.drop_index("ix_call_logs_ivr_outcome", table_name="call_logs")
    op.drop_column("call_logs", "ivr_menu_log")
    op.drop_column("call_logs", "ivr_outcome")
    op.drop_column("call_logs", "ivr_detected")
