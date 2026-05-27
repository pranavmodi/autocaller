"""Add bcc_email to outreach_campaigns

Per-campaign BCC address. When set on send, the recipient at
campaign.bcc_email gets a blind copy of every send in that campaign —
useful for archiving outreach to a shared inbox without adding the
address to every recipient row. Falls back to env BCC_EMAIL when unset.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-05-24 16:45:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_campaigns",
        sa.Column("bcc_email", sa.String(length=320), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outreach_campaigns", "bcc_email")
