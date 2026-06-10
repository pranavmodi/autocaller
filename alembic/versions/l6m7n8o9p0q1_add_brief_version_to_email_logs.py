"""Add brief_version to email_logs

Revision ID: l6m7n8o9p0q1
Revises: k6l7m8n9o0p1
Create Date: 2026-06-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "l6m7n8o9p0q1"
down_revision = "k6l7m8n9o0p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_logs",
        sa.Column("brief_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_logs", "brief_version")
