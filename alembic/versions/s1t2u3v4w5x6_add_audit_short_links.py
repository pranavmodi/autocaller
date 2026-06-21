"""Add short AI Audit links

Revision ID: s1t2u3v4w5x6
Revises: r0s1t2u3v4w5
Create Date: 2026-06-19 14:55:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "s1t2u3v4w5x6"
down_revision = "r0s1t2u3v4w5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_links",
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
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_links_contact_id", "audit_links", ["contact_id"])
    op.create_index("ix_audit_links_created_at", "audit_links", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_links_created_at", table_name="audit_links")
    op.drop_index("ix_audit_links_contact_id", table_name="audit_links")
    op.drop_table("audit_links")
