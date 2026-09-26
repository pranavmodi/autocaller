"""Add durable firm snapshots, evidence, vendor state, and trigger events.

Revision ID: q6r7s8t9u0v1
Revises: p6q7r8s9t0u1
Create Date: 2026-09-09 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "q6r7s8t9u0v1"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firm_research_states",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("last_attempt_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_success_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_due_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pif_id", "module", name="uq_firm_research_states_pif_module"),
    )
    op.create_index("ix_firm_research_states_module_due", "firm_research_states", ["module", "next_due_at"])
    op.create_index("ix_firm_research_states_pif_id", "firm_research_states", ["pif_id"])

    op.create_table(
        "firm_research_snapshots",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("captured_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_firm_research_snapshots_pif_module_time",
        "firm_research_snapshots",
        ["pif_id", "module", "captured_at"],
    )

    op.create_table(
        "firm_vendor_relationships",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("vendor", sa.String(length=128), nullable=False),
        sa.Column("product", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("first_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("removed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("absent_scans", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'suspected_removed', 'removed')",
            name="ck_firm_vendor_relationships_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pif_id", "vendor", "product",
            name="uq_firm_vendor_relationships_pif_vendor_product",
        ),
    )
    op.create_index(
        "ix_firm_vendor_relationships_vendor_status",
        "firm_vendor_relationships",
        ["vendor", "status"],
    )
    op.create_index("ix_firm_vendor_relationships_pif_id", "firm_vendor_relationships", ["pif_id"])

    op.create_table(
        "firm_trigger_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("old_value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("new_value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("detected_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_firm_trigger_events_dedupe_key"),
    )
    op.create_index("ix_firm_trigger_events_pif_detected", "firm_trigger_events", ["pif_id", "detected_at"])
    op.create_index("ix_firm_trigger_events_active_detected", "firm_trigger_events", ["active", "detected_at"])
    op.create_index("ix_firm_trigger_events_category_type", "firm_trigger_events", ["category", "event_type"])
    op.create_index("ix_firm_trigger_events_score", "firm_trigger_events", ["score"])

    op.create_table(
        "firm_evidence",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("claim_type", sa.String(length=64), nullable=False),
        sa.Column("claim_key", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("source_published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("first_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pif_id", "claim_type", "claim_key", "content_hash",
            name="uq_firm_evidence_claim_content",
        ),
    )
    op.create_index("ix_firm_evidence_pif_claim", "firm_evidence", ["pif_id", "claim_type"])
    op.create_index("ix_firm_evidence_event_id", "firm_evidence", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_firm_evidence_event_id", table_name="firm_evidence")
    op.drop_index("ix_firm_evidence_pif_claim", table_name="firm_evidence")
    op.drop_table("firm_evidence")
    op.drop_index("ix_firm_trigger_events_score", table_name="firm_trigger_events")
    op.drop_index("ix_firm_trigger_events_category_type", table_name="firm_trigger_events")
    op.drop_index("ix_firm_trigger_events_active_detected", table_name="firm_trigger_events")
    op.drop_index("ix_firm_trigger_events_pif_detected", table_name="firm_trigger_events")
    op.drop_table("firm_trigger_events")
    op.drop_index("ix_firm_vendor_relationships_pif_id", table_name="firm_vendor_relationships")
    op.drop_index("ix_firm_vendor_relationships_vendor_status", table_name="firm_vendor_relationships")
    op.drop_table("firm_vendor_relationships")
    op.drop_index("ix_firm_research_snapshots_pif_module_time", table_name="firm_research_snapshots")
    op.drop_table("firm_research_snapshots")
    op.drop_index("ix_firm_research_states_pif_id", table_name="firm_research_states")
    op.drop_index("ix_firm_research_states_module_due", table_name="firm_research_states")
    op.drop_table("firm_research_states")
