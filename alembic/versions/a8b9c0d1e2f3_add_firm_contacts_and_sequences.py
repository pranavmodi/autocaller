"""Add firm_contacts + email_sequences for the 4-step email sequence dashboard

`firm_contacts`     — one row per known person at a firm. Backfilled
                      from PIF Stats `leadership[]` and the `patients` DM.
                      Identity for everything sequence-related.
`email_sequences`   — one row per (contact, template) pair. Holds which
                      step is next, when it's due, current status, and
                      the personalization frozen at start time so a
                      mid-sequence Yelp re-extraction can't re-rewrite
                      messages already sent.

Strict invariant enforced by the unique constraint:
  (contact_id, template_key) → at most one sequence per template per
  contact, ever. Restarts not supported in v1.

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-30 19:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firm_contacts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("first_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("linkedin_url", sa.String(length=512), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_firm_contacts_pif_id", "firm_contacts", ["pif_id"])
    op.create_index("ix_firm_contacts_email", "firm_contacts", ["email"])
    # Treat (pif_id, lower(email)) as the natural key when email is present;
    # rely on the backfill to dedupe rather than a partial index here, to keep
    # the migration portable.
    op.create_unique_constraint(
        "uq_firm_contacts_pif_email",
        "firm_contacts",
        ["pif_id", "email"],
    )

    op.create_table(
        "email_sequences",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "contact_id", sa.String(length=64),
            sa.ForeignKey("firm_contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("current_step", sa.Integer, nullable=False, server_default="0"),
        sa.Column("steps_total", sa.Integer, nullable=False, server_default="4"),
        sa.Column("variant", sa.String(length=32), nullable=False, server_default="with_quote"),
        sa.Column("last_sent_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_step_due_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("paused_reason", sa.Text, nullable=True),
        sa.Column("pain_point_key", sa.String(length=64), nullable=True),
        sa.Column("frozen_pain_quote", sa.Text, nullable=True),
        sa.Column("frozen_reviewer_name", sa.String(length=255), nullable=True),
        sa.Column("frozen_review_date", sa.String(length=32), nullable=True),
        sa.Column("started_by", sa.String(length=255), nullable=False, server_default="operator"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_email_sequences_contact_template",
        "email_sequences",
        ["contact_id", "template_key"],
    )
    op.create_index(
        "ix_email_sequences_due",
        "email_sequences",
        ["status", "next_step_due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_sequences_due", table_name="email_sequences")
    op.drop_constraint(
        "uq_email_sequences_contact_template", "email_sequences", type_="unique",
    )
    op.drop_table("email_sequences")
    op.drop_constraint("uq_firm_contacts_pif_email", "firm_contacts", type_="unique")
    op.drop_index("ix_firm_contacts_email", table_name="firm_contacts")
    op.drop_index("ix_firm_contacts_pif_id", table_name="firm_contacts")
    op.drop_table("firm_contacts")
