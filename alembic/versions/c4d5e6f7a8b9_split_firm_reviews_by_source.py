"""Split firm_reviews content into google / yelp columns

Operator wants separate paste areas per source. Adds google_content
and yelp_content TEXT columns; leaves the legacy `content` column in
place (unused by the API) so any hand-pasted data from the previous
single-blob iteration isn't destroyed.

Revision ID: c4d5e6f7a8b9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-24 01:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "firm_reviews",
        sa.Column(
            "google_content", sa.Text(), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "firm_reviews",
        sa.Column(
            "yelp_content", sa.Text(), nullable=False, server_default=""
        ),
    )


def downgrade() -> None:
    op.drop_column("firm_reviews", "yelp_content")
    op.drop_column("firm_reviews", "google_content")
