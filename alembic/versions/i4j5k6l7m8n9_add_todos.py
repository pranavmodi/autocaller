"""Add editable todos

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-05-31 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


revision = "i4j5k6l7m8n9"
down_revision = "h3i4j5k6l7m8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "todos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("area", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("section", sa.String(length=64), nullable=False, server_default="Not Started"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="not_started"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("area", "title", name="uq_todos_area_title"),
    )
    op.create_index("ix_todos_area_status", "todos", ["area", "status"])
    op.create_index("ix_todos_updated_at", "todos", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_todos_updated_at", table_name="todos")
    op.drop_index("ix_todos_area_status", table_name="todos")
    op.drop_table("todos")
