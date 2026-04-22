"""Add acknowledged_at to consult_bookings

Drives the one-shot operator popup: any booking with
acknowledged_at IS NULL surfaces as a modal on the dashboard. Once
the operator clicks Acknowledge, acknowledged_at is set and that
booking never pops again.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-22 20:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "consult_bookings",
        sa.Column("acknowledged_at", TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_consult_bookings_ack_pending",
        "consult_bookings",
        ["created_at"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_consult_bookings_ack_pending", table_name="consult_bookings")
    op.drop_column("consult_bookings", "acknowledged_at")
