"""Add call_status and call_disposition to call_logs

Splits the old single-field outcome into:
- call_status: high-level (called vs failed)
- call_disposition: detailed (transferred, voicemail_left, hung_up, no_answer, ...)

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-04-09 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "n5o6p7q8r9s0"
down_revision = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


# Map legacy outcome values to (call_status, call_disposition) for backfilling
# existing rows.  Mirrors derive_status_and_disposition() in app/models/call_log.py
# but expressed in SQL.
OUTCOME_BACKFILL = [
    ("transferred", "called", "transferred"),
    ("voicemail", "called", "voicemail_left"),
    ("callback_requested", "called", "callback_requested"),
    ("wrong_number", "called", "wrong_number"),
    ("no_answer", "called", "no_answer"),
    ("completed", "called", "completed"),
    # disconnected without context is ambiguous — mark as hung_up by default
    ("disconnected", "called", "hung_up"),
    # failed without context — technical error
    ("failed", "failed", "technical_error"),
    ("in_progress", "in_progress", "in_progress"),
]


def upgrade():
    op.add_column(
        "call_logs",
        sa.Column("call_status", sa.String(32), nullable=False, server_default="in_progress"),
    )
    op.add_column(
        "call_logs",
        sa.Column("call_disposition", sa.String(32), nullable=False, server_default="in_progress"),
    )
    op.create_index("ix_call_logs_call_status", "call_logs", ["call_status"])
    op.create_index("ix_call_logs_call_disposition", "call_logs", ["call_disposition"])

    # Backfill from existing outcome values
    for outcome, status, disposition in OUTCOME_BACKFILL:
        op.execute(
            sa.text(
                "UPDATE call_logs SET call_status = :status, call_disposition = :disposition "
                "WHERE outcome = :outcome"
            ).bindparams(outcome=outcome, status=status, disposition=disposition)
        )


def downgrade():
    op.drop_index("ix_call_logs_call_disposition")
    op.drop_index("ix_call_logs_call_status")
    op.drop_column("call_logs", "call_disposition")
    op.drop_column("call_logs", "call_status")
