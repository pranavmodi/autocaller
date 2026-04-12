"""Add attorney autocaller columns (leads, call outcomes, sales context)

Adapts the original medical-patient schema for cold-calling PI attorneys.
Adds attorney-facing columns to the existing `patients` table (treated as
leads), post-call capture fields to `call_logs`, and Cal.com + sales-rep
context to `system_settings`. Medical-specific columns are kept nullable
so rollback/back-compat with the feature branch still works.

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-04-12 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "r9s0t1u2v3w4"
down_revision = "q8r9s0t1u2v3"
branch_labels = None
depends_on = None


def upgrade():
    # ---- patients (leads) ------------------------------------------------
    op.add_column("patients", sa.Column("firm_name", sa.String(255), nullable=True))
    op.add_column("patients", sa.Column("state", sa.String(2), nullable=True))
    op.add_column("patients", sa.Column("practice_area", sa.String(128), nullable=True))
    op.add_column("patients", sa.Column("website", sa.String(512), nullable=True))
    op.add_column("patients", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("patients", sa.Column("title", sa.String(128), nullable=True))
    op.add_column("patients", sa.Column("source", sa.String(64), nullable=True))
    op.add_column(
        "patients",
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("patients", sa.Column("notes", sa.Text, nullable=True))
    op.create_index("ix_patients_state", "patients", ["state"])

    # ---- call_logs (post-call structured capture) ------------------------
    op.add_column("call_logs", sa.Column("pain_point_summary", sa.Text, nullable=True))
    op.add_column("call_logs", sa.Column("interest_level", sa.Integer, nullable=True))
    op.add_column("call_logs", sa.Column("is_decision_maker", sa.Boolean, nullable=True))
    op.add_column("call_logs", sa.Column("was_gatekeeper", sa.Boolean, nullable=False,
                                          server_default=sa.text("false")))
    op.add_column("call_logs", sa.Column("gatekeeper_contact", JSONB, nullable=True))
    op.add_column("call_logs", sa.Column("demo_booking_id", sa.String(128), nullable=True))
    op.add_column("call_logs", sa.Column("demo_scheduled_at",
                                          sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("call_logs", sa.Column("demo_meeting_url", sa.String(512), nullable=True))
    op.add_column("call_logs", sa.Column("followup_email_sent", sa.Boolean, nullable=False,
                                          server_default=sa.text("false")))
    op.add_column("call_logs", sa.Column("firm_name", sa.String(255), nullable=True))
    op.add_column("call_logs", sa.Column("lead_state", sa.String(2), nullable=True))

    # ---- system_settings (Cal.com + sales rep context) ------------------
    op.add_column(
        "system_settings",
        sa.Column(
            "calcom_config",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "'{\"event_type_id\": null, \"default_timezone\": \"America/New_York\"}'::jsonb"
            ),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "sales_context",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "'{\"rep_name\": \"\", \"rep_company\": \"\", "
                "\"rep_email\": \"\", \"product_context\": \"\"}'::jsonb"
            ),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "per_state_hours",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "'{\"start\": \"09:00\", \"end\": \"17:00\", "
                "\"days\": [0, 1, 2, 3, 4]}'::jsonb"
            ),
        ),
    )


def downgrade():
    op.drop_column("system_settings", "per_state_hours")
    op.drop_column("system_settings", "sales_context")
    op.drop_column("system_settings", "calcom_config")

    op.drop_column("call_logs", "lead_state")
    op.drop_column("call_logs", "firm_name")
    op.drop_column("call_logs", "followup_email_sent")
    op.drop_column("call_logs", "demo_meeting_url")
    op.drop_column("call_logs", "demo_scheduled_at")
    op.drop_column("call_logs", "demo_booking_id")
    op.drop_column("call_logs", "gatekeeper_contact")
    op.drop_column("call_logs", "was_gatekeeper")
    op.drop_column("call_logs", "is_decision_maker")
    op.drop_column("call_logs", "interest_level")
    op.drop_column("call_logs", "pain_point_summary")

    op.drop_index("ix_patients_state", table_name="patients")
    op.drop_column("patients", "notes")
    op.drop_column("patients", "tags")
    op.drop_column("patients", "source")
    op.drop_column("patients", "title")
    op.drop_column("patients", "email")
    op.drop_column("patients", "website")
    op.drop_column("patients", "practice_area")
    op.drop_column("patients", "state")
    op.drop_column("patients", "firm_name")
