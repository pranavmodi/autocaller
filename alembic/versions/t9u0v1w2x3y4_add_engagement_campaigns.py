"""Add cross-channel engagement campaigns and tracking links.

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
Create Date: 2026-08-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "t9u0v1w2x3y4"
down_revision = "s8t9u0v1w2x3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engagement_campaigns",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("campaign_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("workflow", sa.String(length=64), nullable=False, server_default="content"),
        sa.Column("destination_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False, server_default="operator"),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'archived')",
            name="ck_engagement_campaigns_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_engagement_campaigns_date", "engagement_campaigns", ["campaign_date"])
    op.create_index("ix_engagement_campaigns_status", "engagement_campaigns", ["status"])
    op.create_index("ix_engagement_campaigns_created_at", "engagement_campaigns", ["created_at"])

    op.create_table(
        "engagement_campaign_links",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("contact_id", sa.String(length=64), nullable=True),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("destination_url", sa.String(length=2048), nullable=False),
        sa.Column("sent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "channel IN ('email', 'linkedin', 'public')",
            name="ck_engagement_campaign_links_channel",
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["engagement_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["firm_contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_index("ix_engagement_campaign_links_campaign", "engagement_campaign_links", ["campaign_id"])
    op.create_index("ix_engagement_campaign_links_contact", "engagement_campaign_links", ["contact_id"])
    op.create_index("ix_engagement_campaign_links_created_at", "engagement_campaign_links", ["created_at"])

    op.create_table(
        "engagement_campaign_clicks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("link_code", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("contact_id", sa.String(length=64), nullable=True),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("referer", sa.String(length=1024), nullable=True),
        sa.Column("clicked_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["campaign_id"], ["engagement_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["firm_contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["link_code"], ["engagement_campaign_links.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_engagement_campaign_clicks_campaign", "engagement_campaign_clicks", ["campaign_id"])
    op.create_index("ix_engagement_campaign_clicks_link", "engagement_campaign_clicks", ["link_code"])
    op.create_index("ix_engagement_campaign_clicks_contact", "engagement_campaign_clicks", ["contact_id"])
    op.create_index("ix_engagement_campaign_clicks_clicked_at", "engagement_campaign_clicks", ["clicked_at"])


def downgrade() -> None:
    op.drop_index("ix_engagement_campaign_clicks_clicked_at", table_name="engagement_campaign_clicks")
    op.drop_index("ix_engagement_campaign_clicks_contact", table_name="engagement_campaign_clicks")
    op.drop_index("ix_engagement_campaign_clicks_link", table_name="engagement_campaign_clicks")
    op.drop_index("ix_engagement_campaign_clicks_campaign", table_name="engagement_campaign_clicks")
    op.drop_table("engagement_campaign_clicks")
    op.drop_index("ix_engagement_campaign_links_created_at", table_name="engagement_campaign_links")
    op.drop_index("ix_engagement_campaign_links_contact", table_name="engagement_campaign_links")
    op.drop_index("ix_engagement_campaign_links_campaign", table_name="engagement_campaign_links")
    op.drop_table("engagement_campaign_links")
    op.drop_index("ix_engagement_campaigns_created_at", table_name="engagement_campaigns")
    op.drop_index("ix_engagement_campaigns_status", table_name="engagement_campaigns")
    op.drop_index("ix_engagement_campaigns_date", table_name="engagement_campaigns")
    op.drop_table("engagement_campaigns")
