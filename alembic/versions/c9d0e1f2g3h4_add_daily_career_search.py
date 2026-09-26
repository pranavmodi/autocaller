"""Durable daily PI technology career-search state and audit runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

revision = "c9d0e1f2g3h4"
down_revision = "r7s8t9u0v1w2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("career_search_state",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False))
    op.create_table("career_search_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("scheduled_day", sa.String(10), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", TIMESTAMP(timezone=True)),
        sa.Column("result", JSONB, nullable=False))
    op.create_index("ix_career_search_runs_scheduled_day", "career_search_runs", ["scheduled_day"])


def downgrade():
    op.drop_table("career_search_runs")
    op.drop_table("career_search_state")
