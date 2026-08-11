"""Add saved lead searches.

Revision ID: s8t9u0v1w2x3
Revises: z7a8b9c0d1e2
Create Date: 2026-08-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "s8t9u0v1w2x3"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_lead_searches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("view", sa.String(length=32), nullable=False, server_default="contacts"),
        sa.Column("criteria_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=128), nullable=False, server_default="operator"),
        sa.Column("updated_by", sa.String(length=128), nullable=False, server_default="operator"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("view IN ('contacts')", name="ck_saved_lead_searches_view"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("view", "name", name="uq_saved_lead_searches_view_name"),
    )
    op.create_index(
        "ix_saved_lead_searches_view_updated",
        "saved_lead_searches",
        ["view", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_lead_searches_view_updated", table_name="saved_lead_searches")
    op.drop_table("saved_lead_searches")
