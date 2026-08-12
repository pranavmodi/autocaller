"""Add operator-approved Mira briefing to campaign links.

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
Create Date: 2026-08-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "u0v1w2x3y4z5"
down_revision = "t9u0v1w2x3y4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "engagement_campaign_links",
        sa.Column("advisor_briefing", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("engagement_campaign_links", "advisor_briefing")
