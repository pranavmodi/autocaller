"""Add inbound email ingestion table

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_emails",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="zoho_imap"),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.Column("mailbox", sa.String(length=255), nullable=False, server_default="INBOX"),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=512), nullable=True),
        sa.Column("in_reply_to", sa.String(length=512), nullable=True),
        sa.Column("references_text", sa.Text(), nullable=True),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("from_name", sa.String(length=255), nullable=True),
        sa.Column("to_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cc_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("text_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_headers_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "matched_contact_id",
            sa.String(length=64),
            sa.ForeignKey("firm_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("matched_pif_id", sa.String(length=64), nullable=True),
        sa.Column(
            "matched_batch_item_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "matched_sequence_id",
            sa.String(length=64),
            sa.ForeignKey("email_sequences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "lead_gen_observation_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_observations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("classification_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("received_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ingested_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "provider", "account_email", "mailbox", "uid",
            name="uq_inbound_emails_provider_account_mailbox_uid",
        ),
    )
    op.create_index("ix_inbound_emails_from_email", "inbound_emails", ["from_email"])
    op.create_index("ix_inbound_emails_received_at", "inbound_emails", ["received_at"])
    op.create_index("ix_inbound_emails_matched_contact", "inbound_emails", ["matched_contact_id"])
    op.create_index("ix_inbound_emails_matched_batch_item", "inbound_emails", ["matched_batch_item_id"])
    op.create_index("ix_inbound_emails_classification_status", "inbound_emails", ["classification_status"])


def downgrade() -> None:
    op.drop_index("ix_inbound_emails_classification_status", table_name="inbound_emails")
    op.drop_index("ix_inbound_emails_matched_batch_item", table_name="inbound_emails")
    op.drop_index("ix_inbound_emails_matched_contact", table_name="inbound_emails")
    op.drop_index("ix_inbound_emails_received_at", table_name="inbound_emails")
    op.drop_index("ix_inbound_emails_from_email", table_name="inbound_emails")
    op.drop_table("inbound_emails")
