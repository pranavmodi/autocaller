"""Add firm research orchestrator tables

Revision ID: p8q9r0s1t2u3
Revises: o7p8q9r0s1t2
Create Date: 2026-06-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "p8q9r0s1t2u3"
down_revision = "o7p8q9r0s1t2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_tasks",
        sa.Column("task_id", sa.String(length=128), primary_key=True),
        sa.Column("pif_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("requested_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("result_summary", JSONB(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('research', 'research_staff', 'analyze_behavior')",
            name="ck_research_tasks_kind",
        ),
    )
    op.create_index("ix_research_tasks_pif_id", "research_tasks", ["pif_id"])
    op.create_index("ix_research_tasks_status", "research_tasks", ["status"])
    op.create_index("ix_research_tasks_kind_status", "research_tasks", ["kind", "status"])

    op.add_column("firm_contacts", sa.Column("persona", sa.String(length=32), nullable=True))
    op.add_column("firm_contacts", sa.Column("persona_source", sa.String(length=32), nullable=True))
    op.add_column("firm_contacts", sa.Column("persona_confidence", sa.Float(), nullable=True))
    op.add_column("firm_contacts", sa.Column("research_title", sa.String(length=255), nullable=True))
    op.add_column("front_firm_activity", sa.Column("behavioral_json", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("front_firm_activity", "behavioral_json")
    op.drop_column("firm_contacts", "research_title")
    op.drop_column("firm_contacts", "persona_confidence")
    op.drop_column("firm_contacts", "persona_source")
    op.drop_column("firm_contacts", "persona")
    op.drop_index("ix_research_tasks_kind_status", table_name="research_tasks")
    op.drop_index("ix_research_tasks_status", table_name="research_tasks")
    op.drop_index("ix_research_tasks_pif_id", table_name="research_tasks")
    op.drop_table("research_tasks")
