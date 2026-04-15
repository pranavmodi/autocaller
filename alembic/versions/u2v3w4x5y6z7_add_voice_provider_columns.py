"""Add voice_provider + voice_model columns for per-call backend attribution.

Per-call record of which realtime voice backend handled the call, so we can
A/B OpenAI Realtime vs Gemini Live on cost + quality + success rate. The
default setting lives on `system_settings` and is overridden per call via
CLI / API / frontend toggle.

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-04-15 00:35:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("voice_provider", sa.String(32), nullable=True))
    op.add_column("call_logs", sa.Column("voice_model", sa.String(64), nullable=True))
    op.create_index(
        "ix_call_logs_voice_provider", "call_logs", ["voice_provider"]
    )

    op.add_column(
        "system_settings",
        sa.Column("voice_provider", sa.String(32), nullable=False, server_default="openai"),
    )
    op.add_column(
        "system_settings",
        sa.Column("voice_model", sa.String(64), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("system_settings", "voice_model")
    op.drop_column("system_settings", "voice_provider")
    op.drop_index("ix_call_logs_voice_provider", table_name="call_logs")
    op.drop_column("call_logs", "voice_model")
    op.drop_column("call_logs", "voice_provider")
