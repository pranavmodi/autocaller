"""Add returned-data events and editable script tables

Revision ID: x5y6z7a8b9c0
Revises: w5x6y7z8a9b0
Create Date: 2026-07-10 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "x5y6z7a8b9c0"
down_revision = "w5x6y7z8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The service can create these callback tables on demand when code reaches
    # a host before its migration. Keep the migration safe in that state and
    # still advance Alembic's revision normally.
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "data_returned_events" not in existing_tables:
        op.create_table(
            "data_returned_events",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("headers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
            sa.Column("source_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("content_type", sa.String(length=255), nullable=True),
            sa.Column(
                "received_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "ix_data_returned_events_received_at",
            "data_returned_events",
            ["received_at"],
        )
        op.create_index(
            "ix_data_returned_events_source_ip",
            "data_returned_events",
            ["source_ip"],
        )
    if "data_returned_script" not in existing_tables:
        op.create_table(
            "data_returned_script",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("script_text", sa.Text(), nullable=False),
            sa.Column(
                "updated_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )


def downgrade() -> None:
    op.drop_table("data_returned_script")
    op.drop_index("ix_data_returned_events_source_ip", table_name="data_returned_events")
    op.drop_index("ix_data_returned_events_received_at", table_name="data_returned_events")
    op.drop_table("data_returned_events")
