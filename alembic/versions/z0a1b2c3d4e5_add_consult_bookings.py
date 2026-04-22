"""Add consult_bookings table

Stores the free 30-minute AI-consult bookings made via
getpossibleminds.com/consult. Populated by the public POST endpoint
(the website form) + viewable in the autocaller admin UI.

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-04-22 00:15:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "z0a1b2c3d4e5"
down_revision = "y9z0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consult_bookings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("firm_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("slot_start", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("slot_end", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        # "booked" | "cancelled" | "completed". Created-as-booked; other
        # states are operator-driven from the admin UI.
        sa.Column("status", sa.String(length=16), nullable=False, server_default="booked"),
        # Where the booking came from — "website", "manual_admin", etc.
        sa.Column("source", sa.String(length=32), nullable=False, server_default="website"),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_consult_bookings_slot_start", "consult_bookings", ["slot_start"]
    )
    op.create_index(
        "ix_consult_bookings_created_at", "consult_bookings", ["created_at"]
    )
    op.create_index(
        "ix_consult_bookings_email", "consult_bookings", ["email"]
    )


def downgrade() -> None:
    op.drop_index("ix_consult_bookings_email", table_name="consult_bookings")
    op.drop_index("ix_consult_bookings_created_at", table_name="consult_bookings")
    op.drop_index("ix_consult_bookings_slot_start", table_name="consult_bookings")
    op.drop_table("consult_bookings")
