"""Add daily_report column to system_settings

Stores the daily Slack report config (enabled, webhook URL, hour, timezone)
as a JSONB blob on the singleton settings row.

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-04-09 13:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "o6p7q8r9s0t1"
down_revision = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "system_settings",
        sa.Column(
            "daily_report",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "'{\"enabled\": false, \"webhook_url\": \"\", \"hour\": 7, "
                "\"timezone\": \"America/Los_Angeles\"}'::jsonb"
            ),
        ),
    )


def downgrade():
    op.drop_column("system_settings", "daily_report")
