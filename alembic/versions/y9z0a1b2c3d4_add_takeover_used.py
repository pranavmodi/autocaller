"""Add takeover_used flag to call_logs

True if the operator pressed "Take over" at any point during the call.
Used by the post-call pipeline to auto-trigger segment-level Whisper
transcription (since during takeover the operator's side isn't fed to
the live voice backend, so the live transcript is incomplete).

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-04-21 23:45:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "y9z0a1b2c3d4"
down_revision = "x8y9z0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_logs",
        sa.Column(
            "takeover_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("call_logs", "takeover_used")
