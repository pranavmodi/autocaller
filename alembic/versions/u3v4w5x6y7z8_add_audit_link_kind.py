"""Add kind column to audit_links (audit vs consult destination)

Revision ID: u3v4w5x6y7z8
Revises: t2u3v4w5x6y7
Create Date: 2026-06-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "u3v4w5x6y7z8"
down_revision = "t2u3v4w5x6y7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Short links are reused for two destinations now: the AI Audit page
    # (kind="audit", the historical default) and the consult page
    # (kind="consult"). Existing rows are all audit links.
    op.add_column(
        "audit_links",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="audit",
        ),
    )


def downgrade() -> None:
    op.drop_column("audit_links", "kind")
