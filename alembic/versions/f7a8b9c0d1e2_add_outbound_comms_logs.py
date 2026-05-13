"""Add email_logs + sms_logs for outbound communications dashboard

Two narrow tables that capture every outbound email + SMS at send-time.
Phone calls and voicemails already live in `call_logs` (rich) — those
are NOT duplicated here; the dashboard assembler unions all three.

Send-attempt semantics: a row is written immediately after the
provider call returns (sid for Twilio, message_id for Resend / SMTP
Message-ID). `status` reflects what we knew at that moment, not the
async delivery state. Engagement (opens, clicks, replies) is out of
scope for v1.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-30 18:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("call_id", sa.String(length=64), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("message_type", sa.String(length=64), nullable=False, server_default="other"),
        sa.Column("transport", sa.String(length=16), nullable=False, server_default="resend"),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="sent"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "sent_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_email_logs_pif_id", "email_logs", ["pif_id"])
    op.create_index("ix_email_logs_call_id", "email_logs", ["call_id"])
    op.create_index("ix_email_logs_sent_at", "email_logs", ["sent_at"])

    op.create_table(
        "sms_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("call_id", sa.String(length=64), nullable=True),
        sa.Column("recipient_phone", sa.String(length=32), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("message_sid", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="sent"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "sent_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_sms_logs_pif_id", "sms_logs", ["pif_id"])
    op.create_index("ix_sms_logs_call_id", "sms_logs", ["call_id"])
    op.create_index("ix_sms_logs_sent_at", "sms_logs", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_sms_logs_sent_at", table_name="sms_logs")
    op.drop_index("ix_sms_logs_call_id", table_name="sms_logs")
    op.drop_index("ix_sms_logs_pif_id", table_name="sms_logs")
    op.drop_table("sms_logs")
    op.drop_index("ix_email_logs_sent_at", table_name="email_logs")
    op.drop_index("ix_email_logs_call_id", table_name="email_logs")
    op.drop_index("ix_email_logs_pif_id", table_name="email_logs")
    op.drop_table("email_logs")
