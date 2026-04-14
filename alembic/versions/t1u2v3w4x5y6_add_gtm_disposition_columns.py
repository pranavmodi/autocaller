"""Add GTM disposition columns to call_logs

Complements the judge scoring columns (s0t1u2v3w4x5) — the same LLM pass
also classifies the call into a GTM-actionable disposition and captures
everything a sales specialist needs to decide on follow-up.

See docs/DISPOSITIONS.md for the 15-class taxonomy and field semantics.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-04-14 23:10:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("gtm_disposition", sa.String(64), nullable=True))
    op.add_column("call_logs", sa.Column("follow_up_action", sa.String(64), nullable=True))
    op.add_column("call_logs", sa.Column("follow_up_when", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("call_logs", sa.Column("follow_up_owner", sa.String(32), nullable=True))
    op.add_column("call_logs", sa.Column("follow_up_note", sa.Text, nullable=True))
    op.add_column("call_logs", sa.Column("call_summary", sa.Text, nullable=True))
    op.add_column("call_logs", sa.Column("signal_flags", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("pain_points_discussed", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("objections_raised", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("captured_contacts", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("dm_reachability", sa.String(32), nullable=True))
    op.add_column("call_logs", sa.Column("dnc_reason", sa.Text, nullable=True))
    # The exact system prompt rendered for this call (strings substituted,
    # tools serialized). Stored per-call so we can reason about AI behaviour
    # after the fact — what INSTRUCTIONS did the model have?
    op.add_column("call_logs", sa.Column("prompt_text", sa.Text, nullable=True))
    op.add_column("call_logs", sa.Column("tools_snapshot", JSONB, nullable=True))

    op.create_index("ix_call_logs_gtm_disposition", "call_logs", ["gtm_disposition"])
    op.create_index("ix_call_logs_follow_up_when", "call_logs", ["follow_up_when"])
    op.create_index("ix_call_logs_follow_up_action", "call_logs", ["follow_up_action"])


def downgrade():
    op.drop_index("ix_call_logs_follow_up_action", table_name="call_logs")
    op.drop_index("ix_call_logs_follow_up_when", table_name="call_logs")
    op.drop_index("ix_call_logs_gtm_disposition", table_name="call_logs")
    for col in (
        "tools_snapshot", "prompt_text", "dnc_reason", "dm_reachability",
        "captured_contacts", "objections_raised", "pain_points_discussed",
        "signal_flags", "call_summary", "follow_up_note", "follow_up_owner",
        "follow_up_when", "follow_up_action", "gtm_disposition",
    ):
        op.drop_column("call_logs", col)
