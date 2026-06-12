"""Add Front lead engine tables

Revision ID: n6o7p8q9r0s1
Revises: m6n7o8p9q0r1
Create Date: 2026-06-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "n6o7p8q9r0s1"
down_revision = "m6n7o8p9q0r1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "front_contacts",
        sa.Column("front_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("handles", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("primary_email", sa.String(length=320), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("first_synced_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("front_updated_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("raw_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_front_contacts_domain", "front_contacts", ["domain"])
    op.create_index("ix_front_contacts_primary_email", "front_contacts", ["primary_email"])
    op.create_index("ix_front_contacts_front_updated_at", "front_contacts", ["front_updated_at"])

    op.create_table(
        "front_firm_activity",
        sa.Column("domain", sa.String(length=255), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("contact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_referral_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_records_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("inbox_breakdown", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tech_signals", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warm_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("synced_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_front_firm_activity_pif_id", "front_firm_activity", ["pif_id"])
    op.create_index("ix_front_firm_activity_warm_score", "front_firm_activity", ["warm_score"])
    op.create_index("ix_front_firm_activity_last_seen", "front_firm_activity", ["last_seen_at"])

    op.create_table(
        "front_sync_state",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("watermark", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.add_column("firm_contacts", sa.Column("front_contact_id", sa.String(length=64), nullable=True))
    op.add_column("firm_contacts", sa.Column("front_last_seen", TIMESTAMP(timezone=True), nullable=True))
    op.add_column("firm_contacts", sa.Column("tech_signals", JSONB(), nullable=True))
    op.create_index("ix_firm_contacts_front_contact_id", "firm_contacts", ["front_contact_id"])


def downgrade() -> None:
    op.drop_index("ix_firm_contacts_front_contact_id", table_name="firm_contacts")
    op.drop_column("firm_contacts", "tech_signals")
    op.drop_column("firm_contacts", "front_last_seen")
    op.drop_column("firm_contacts", "front_contact_id")
    op.drop_table("front_sync_state")
    op.drop_index("ix_front_firm_activity_last_seen", table_name="front_firm_activity")
    op.drop_index("ix_front_firm_activity_warm_score", table_name="front_firm_activity")
    op.drop_index("ix_front_firm_activity_pif_id", table_name="front_firm_activity")
    op.drop_table("front_firm_activity")
    op.drop_index("ix_front_contacts_front_updated_at", table_name="front_contacts")
    op.drop_index("ix_front_contacts_primary_email", table_name="front_contacts")
    op.drop_index("ix_front_contacts_domain", table_name="front_contacts")
    op.drop_table("front_contacts")
