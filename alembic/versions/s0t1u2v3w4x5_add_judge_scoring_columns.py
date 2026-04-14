"""Add judge scoring + prompt_version columns to call_logs

Phase A of the self-improvement loop: every completed call is scored by a
background LLM judge against a quality rubric. Stored on the call_logs row.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-04-14 22:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("judge_score", sa.Integer, nullable=True))
    op.add_column("call_logs", sa.Column("judge_scores", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("judge_notes", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("judged_at",
                                         sa.TIMESTAMP(timezone=True),
                                         nullable=True))
    op.add_column("call_logs", sa.Column("prompt_version",
                                         sa.String(64),
                                         nullable=True))
    op.create_index(
        "ix_call_logs_judge_pending",
        "call_logs",
        ["ended_at"],
        unique=False,
        postgresql_where=sa.text("judged_at IS NULL AND ended_at IS NOT NULL"),
    )
    op.create_index("ix_call_logs_prompt_version", "call_logs", ["prompt_version"])


def downgrade():
    op.drop_index("ix_call_logs_prompt_version", table_name="call_logs")
    op.drop_index("ix_call_logs_judge_pending", table_name="call_logs")
    op.drop_column("call_logs", "prompt_version")
    op.drop_column("call_logs", "judged_at")
    op.drop_column("call_logs", "judge_notes")
    op.drop_column("call_logs", "judge_scores")
    op.drop_column("call_logs", "judge_score")
