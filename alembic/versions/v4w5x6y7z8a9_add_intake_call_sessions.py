"""Add inbound PI intake call sessions

Revision ID: v4w5x6y7z8a9
Revises: u3v4w5x6y7z8
Create Date: 2026-06-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "v4w5x6y7z8a9"
down_revision = "u3v4w5x6y7z8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intake_call_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("stream_id", sa.String(length=128), nullable=False),
        sa.Column("carrier", sa.String(length=16), nullable=False, server_default="telnyx"),
        sa.Column("carrier_call_control_id", sa.String(length=128), nullable=True),
        sa.Column("caller_number", sa.String(length=64), nullable=True),
        sa.Column("dialed_number", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
        sa.Column("consent_recording", sa.Boolean(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("intake_packet", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("urgency_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("notification_recipient", sa.String(length=255), nullable=True),
        sa.Column("notification_sent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notification_error", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ended_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stream_id"),
    )
    op.create_index("ix_intake_call_sessions_started_at", "intake_call_sessions", ["started_at"])
    op.create_index("ix_intake_call_sessions_status", "intake_call_sessions", ["status"])
    op.create_index("ix_intake_call_sessions_caller_number", "intake_call_sessions", ["caller_number"])
    op.create_index("ix_intake_call_sessions_stream_id", "intake_call_sessions", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_intake_call_sessions_stream_id", table_name="intake_call_sessions")
    op.drop_index("ix_intake_call_sessions_caller_number", table_name="intake_call_sessions")
    op.drop_index("ix_intake_call_sessions_status", table_name="intake_call_sessions")
    op.drop_index("ix_intake_call_sessions_started_at", table_name="intake_call_sessions")
    op.drop_table("intake_call_sessions")
