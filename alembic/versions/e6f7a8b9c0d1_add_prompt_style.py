"""Add prompt_style to system_settings

Persisted source-of-truth for the active voice-AI prompt style
("current" | "minimal"). Replaces the env-var-only PROMPT_STYLE so
operators can flip styles from CLI or UI without restarting the
daemon. The env var, if set, still wins on first boot until DB is
reconciled — see app/prompts/active.py for resolution order.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-29 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "prompt_style",
            sa.String(length=32),
            nullable=False,
            server_default="current",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "prompt_style")
