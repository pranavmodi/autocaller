"""add firm sitemap snapshots

Revision ID: m3n4o5p6q7r8
Revises: k2c3d4e5f6a7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "m3n4o5p6q7r8"
down_revision = "k2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firm_sitemap_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("website", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sitemap_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=True),
        sa.Column("added_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("removed_urls", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'missing', 'failed')",
            name="ck_firm_sitemap_snapshots_status",
        ),
    )
    op.create_index(
        "ix_firm_sitemap_snapshots_pif_fetched",
        "firm_sitemap_snapshots",
        ["pif_id", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_firm_sitemap_snapshots_pif_fetched", table_name="firm_sitemap_snapshots")
    op.drop_table("firm_sitemap_snapshots")
