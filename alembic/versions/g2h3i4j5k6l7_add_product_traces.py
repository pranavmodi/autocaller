"""Add product traces

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-05-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "g2h3i4j5k6l7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_traces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("surface", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(length=128), nullable=True),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("parent_trace_id", sa.String(length=64), nullable=True),
        sa.Column("input_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("diff_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_product_traces_trace_id", "product_traces", ["trace_id"])
    op.create_index("ix_product_traces_session_id", "product_traces", ["session_id"])
    op.create_index("ix_product_traces_request_id", "product_traces", ["request_id"])
    op.create_index("ix_product_traces_event_type", "product_traces", ["event_type"])
    op.create_index("ix_product_traces_surface", "product_traces", ["surface"])
    op.create_index("ix_product_traces_entity", "product_traces", ["entity_type", "entity_id"])
    op.create_index("ix_product_traces_created_at", "product_traces", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_product_traces_created_at", table_name="product_traces")
    op.drop_index("ix_product_traces_entity", table_name="product_traces")
    op.drop_index("ix_product_traces_surface", table_name="product_traces")
    op.drop_index("ix_product_traces_event_type", table_name="product_traces")
    op.drop_index("ix_product_traces_request_id", table_name="product_traces")
    op.drop_index("ix_product_traces_session_id", table_name="product_traces")
    op.drop_index("ix_product_traces_trace_id", table_name="product_traces")
    op.drop_table("product_traces")
