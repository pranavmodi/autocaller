"""Add short AI Visibility report links

Revision ID: t2u3v4w5x6y7
Revises: s1t2u3v4w5x6
Create Date: 2026-06-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "t2u3v4w5x6y7"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visibility_links",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column(
            "contact_id",
            sa.String(length=64),
            sa.ForeignKey("firm_contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_item_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("scan_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_visibility_links_contact_id", "visibility_links", ["contact_id"])
    op.create_index("ix_visibility_links_created_at", "visibility_links", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_visibility_links_created_at", table_name="visibility_links")
    op.drop_index("ix_visibility_links_contact_id", table_name="visibility_links")
    op.drop_table("visibility_links")
