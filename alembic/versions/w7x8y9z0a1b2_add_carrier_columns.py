"""Add carrier column to call_logs + default_carrier to system_settings

Second telephony carrier (Telnyx) running alongside Twilio. `carrier` on
`call_logs` records which carrier placed each call; `default_carrier` on
`system_settings` is the default selected when no per-call override is
provided. Per-call override comes from CLI `--carrier=` or API body.

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-04-16 17:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "w7x8y9z0a1b2"
down_revision = "v6w7x8y9z0a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("carrier", sa.String(16), nullable=True))
    op.create_index("ix_call_logs_carrier", "call_logs", ["carrier"])

    op.add_column(
        "system_settings",
        sa.Column("default_carrier", sa.String(16), nullable=False, server_default="twilio"),
    )


def downgrade():
    op.drop_column("system_settings", "default_carrier")
    op.drop_index("ix_call_logs_carrier", table_name="call_logs")
    op.drop_column("call_logs", "carrier")
