"""Add operator notifications

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-05-28 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "f1a2b3c4d5e6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("stimulus_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("suggested_action_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("acknowledged_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.UniqueConstraint(
            "notification_type", "source_type", "source_id",
            name="uq_operator_notifications_source",
        ),
    )
    op.create_index(
        "ix_operator_notifications_pending",
        "operator_notifications",
        ["status", "acknowledged_at"],
    )
    op.create_index(
        "ix_operator_notifications_created_at",
        "operator_notifications",
        ["created_at"],
    )
    op.create_index(
        "ix_operator_notifications_type",
        "operator_notifications",
        ["notification_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_operator_notifications_type", table_name="operator_notifications")
    op.drop_index("ix_operator_notifications_created_at", table_name="operator_notifications")
    op.drop_index("ix_operator_notifications_pending", table_name="operator_notifications")
    op.drop_table("operator_notifications")
