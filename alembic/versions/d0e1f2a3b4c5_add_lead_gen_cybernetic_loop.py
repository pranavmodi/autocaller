"""Add cybernetic lead-generation loop tables

Revision ID: d0e1f2a3b4c5
Revises: c0d1e2f3a4b5
Create Date: 2026-05-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "d0e1f2a3b4c5"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_gen_policy_versions",
        sa.Column("version", sa.String(length=64), primary_key=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column(
            "target_metric",
            sa.String(length=64),
            nullable=False,
            server_default="booked_qualified_conversations",
        ),
        sa.Column("weights_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("suppressions_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_lead_gen_policy_versions_active", "lead_gen_policy_versions", ["active"])
    op.create_index("ix_lead_gen_policy_versions_created_at", "lead_gen_policy_versions", ["created_at"])

    op.create_table(
        "lead_gen_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "target_metric",
            sa.String(length=64),
            nullable=False,
            server_default="booked_qualified_conversations",
        ),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column(
            "policy_version",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_policy_versions.version", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="recommended"),
        sa.Column("counts_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('recommended', 'approved', 'sequencing', 'observing', 'completed', 'archived')",
            name="ck_lead_gen_batches_status",
        ),
    )
    op.create_index("ix_lead_gen_batches_status", "lead_gen_batches", ["status"])
    op.create_index("ix_lead_gen_batches_template", "lead_gen_batches", ["template_key"])
    op.create_index("ix_lead_gen_batches_created_at", "lead_gen_batches", ["created_at"])

    op.create_table(
        "lead_gen_batch_items",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            sa.String(length=64),
            sa.ForeignKey("firm_contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("firm_name", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(length=320), nullable=False),
        sa.Column("contact_title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("persona", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("approval_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column(
            "sequence_id",
            sa.String(length=64),
            sa.ForeignKey("email_sequences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("outcome_confidence", sa.Integer(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected', 'started', 'skipped')",
            name="ck_lead_gen_batch_items_approval_status",
        ),
        sa.UniqueConstraint("batch_id", "contact_id", name="uq_lead_gen_batch_items_batch_contact"),
    )
    op.create_index("ix_lead_gen_batch_items_batch_id", "lead_gen_batch_items", ["batch_id"])
    op.create_index("ix_lead_gen_batch_items_contact_id", "lead_gen_batch_items", ["contact_id"])
    op.create_index("ix_lead_gen_batch_items_pif_id", "lead_gen_batch_items", ["pif_id"])
    op.create_index("ix_lead_gen_batch_items_outcome", "lead_gen_batch_items", ["outcome"])

    op.create_table(
        "lead_gen_observations",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "batch_item_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_batch_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.String(length=64),
            sa.ForeignKey("firm_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("raw_event_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("classified_outcome", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("next_action", sa.String(length=64), nullable=True),
        sa.Column("llm_reasoning", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.String(length=128), nullable=True),
        sa.Column("llm_raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_lead_gen_observations_batch_id", "lead_gen_observations", ["batch_id"])
    op.create_index("ix_lead_gen_observations_contact_id", "lead_gen_observations", ["contact_id"])
    op.create_index("ix_lead_gen_observations_event_type", "lead_gen_observations", ["event_type"])
    op.create_index("ix_lead_gen_observations_outcome", "lead_gen_observations", ["classified_outcome"])
    op.create_index("ix_lead_gen_observations_created_at", "lead_gen_observations", ["created_at"])

    op.create_table(
        "lead_gen_policy_proposals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "source_batch_id",
            sa.String(length=64),
            sa.ForeignKey("lead_gen_batches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("proposal_type", sa.String(length=64), nullable=False),
        sa.Column("proposed_change_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("llm_model", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("applied_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'applied')",
            name="ck_lead_gen_policy_proposals_status",
        ),
    )
    op.create_index("ix_lead_gen_policy_proposals_status", "lead_gen_policy_proposals", ["status"])
    op.create_index("ix_lead_gen_policy_proposals_source_batch", "lead_gen_policy_proposals", ["source_batch_id"])
    op.create_index("ix_lead_gen_policy_proposals_created_at", "lead_gen_policy_proposals", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_gen_policy_proposals_created_at", table_name="lead_gen_policy_proposals")
    op.drop_index("ix_lead_gen_policy_proposals_source_batch", table_name="lead_gen_policy_proposals")
    op.drop_index("ix_lead_gen_policy_proposals_status", table_name="lead_gen_policy_proposals")
    op.drop_table("lead_gen_policy_proposals")

    op.drop_index("ix_lead_gen_observations_created_at", table_name="lead_gen_observations")
    op.drop_index("ix_lead_gen_observations_outcome", table_name="lead_gen_observations")
    op.drop_index("ix_lead_gen_observations_event_type", table_name="lead_gen_observations")
    op.drop_index("ix_lead_gen_observations_contact_id", table_name="lead_gen_observations")
    op.drop_index("ix_lead_gen_observations_batch_id", table_name="lead_gen_observations")
    op.drop_table("lead_gen_observations")

    op.drop_index("ix_lead_gen_batch_items_outcome", table_name="lead_gen_batch_items")
    op.drop_index("ix_lead_gen_batch_items_pif_id", table_name="lead_gen_batch_items")
    op.drop_index("ix_lead_gen_batch_items_contact_id", table_name="lead_gen_batch_items")
    op.drop_index("ix_lead_gen_batch_items_batch_id", table_name="lead_gen_batch_items")
    op.drop_table("lead_gen_batch_items")

    op.drop_index("ix_lead_gen_batches_created_at", table_name="lead_gen_batches")
    op.drop_index("ix_lead_gen_batches_template", table_name="lead_gen_batches")
    op.drop_index("ix_lead_gen_batches_status", table_name="lead_gen_batches")
    op.drop_table("lead_gen_batches")

    op.drop_index("ix_lead_gen_policy_versions_created_at", table_name="lead_gen_policy_versions")
    op.drop_index("ix_lead_gen_policy_versions_active", table_name="lead_gen_policy_versions")
    op.drop_table("lead_gen_policy_versions")
