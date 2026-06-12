"""Add lead-gen daily run checkpoints

Revision ID: q9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-06-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "q9r0s1t2u3v4"
down_revision = "p8q9r0s1t2u3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_gen_daily_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(length=64), nullable=False, server_default="pending"),
        sa.Column("stages_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'partial', 'completed', 'failed', 'skipped')",
            name="ck_lead_gen_daily_runs_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["lead_gen_batches.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("run_date", name="uq_lead_gen_daily_runs_run_date"),
    )
    op.create_index("ix_lead_gen_daily_runs_run_date", "lead_gen_daily_runs", ["run_date"])
    op.create_index("ix_lead_gen_daily_runs_status", "lead_gen_daily_runs", ["status"])
    op.create_index("ix_lead_gen_daily_runs_created_at", "lead_gen_daily_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_lead_gen_daily_runs_created_at", table_name="lead_gen_daily_runs")
    op.drop_index("ix_lead_gen_daily_runs_status", table_name="lead_gen_daily_runs")
    op.drop_index("ix_lead_gen_daily_runs_run_date", table_name="lead_gen_daily_runs")
    op.drop_table("lead_gen_daily_runs")
