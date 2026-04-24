"""Add carrier reconciliation columns to call_logs

Enforces the invariant "ended_at IS NOT NULL ⟺ carrier acknowledged terminal":

  carrier_call_sid          — the carrier's call handle (Twilio call SID,
                              Telnyx call_control_id). Required for
                              reconciliation + manual force-hangup.
  termination_state         — FSM for carrier teardown. Values:
                              'live', 'hangup_requested', 'hangup_acked',
                              'carrier_confirmed_ended', 'hangup_failed'.
  termination_last_error    — last error from a failed hangup attempt.
  termination_last_checked_at — last time the reconciler polled the
                                carrier for this row.

Existing rows: we pre-mark every already-ended call
'carrier_confirmed_ended' (we don't know, but they're old enough that
the carrier has certainly cleaned them up) and every NULL-ended row
'hangup_failed' so the reconciler picks them up on the next tick.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-24 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_logs",
        sa.Column("carrier_call_sid", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "call_logs",
        sa.Column(
            "termination_state", sa.String(length=32),
            nullable=False, server_default=sa.text("'live'"),
        ),
    )
    op.add_column(
        "call_logs",
        sa.Column("termination_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "call_logs",
        sa.Column(
            "termination_last_checked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # Backfill termination_state for pre-existing rows.
    # Rule: ended_at IS NOT NULL → carrier is definitely gone by now (old
    # enough). ended_at IS NULL → orphan that needs reconciliation.
    op.execute("""
        UPDATE call_logs
        SET termination_state = 'carrier_confirmed_ended'
        WHERE ended_at IS NOT NULL
    """)
    op.execute("""
        UPDATE call_logs
        SET termination_state = 'hangup_failed',
            termination_last_error = 'Pre-existing orphan; never received terminal carrier state'
        WHERE ended_at IS NULL
    """)

    # Partial index — reconciler only cares about non-terminal rows.
    op.create_index(
        "ix_call_logs_termination_state_nonterm",
        "call_logs",
        ["termination_state"],
        postgresql_where=sa.text("termination_state <> 'carrier_confirmed_ended'"),
    )


def downgrade() -> None:
    op.drop_index("ix_call_logs_termination_state_nonterm", table_name="call_logs")
    op.drop_column("call_logs", "termination_last_checked_at")
    op.drop_column("call_logs", "termination_last_error")
    op.drop_column("call_logs", "termination_state")
    op.drop_column("call_logs", "carrier_call_sid")
