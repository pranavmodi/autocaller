"""Add AI Audit link click tracking

Revision ID: r0s1t2u3v4w5
Revises: q9r0s1t2u3v4
Create Date: 2026-06-19 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "r0s1t2u3v4w5"
down_revision = "q9r0s1t2u3v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_link_clicks",
        sa.Column("id", sa.String(length=64), primary_key=True),
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
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("referer", sa.String(length=1024), nullable=True),
        sa.Column(
            "clicked_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_link_clicks_contact_id", "audit_link_clicks", ["contact_id"])
    op.create_index("ix_audit_link_clicks_clicked_at", "audit_link_clicks", ["clicked_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_link_clicks_clicked_at", table_name="audit_link_clicks")
    op.drop_index("ix_audit_link_clicks_contact_id", table_name="audit_link_clicks")
    op.drop_table("audit_link_clicks")
