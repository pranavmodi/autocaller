"""Add learning loop tables

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-05-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "improvement_findings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("finding_key", sa.String(length=160), nullable=False),
        sa.Column("workflow", sa.String(length=64), nullable=False),
        sa.Column("finding_type", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_trace_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("suggested_change_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="proposed"),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'implemented')",
            name="ck_improvement_findings_status",
        ),
        sa.UniqueConstraint("finding_key", name="uq_improvement_findings_finding_key"),
    )
    op.create_index("ix_improvement_findings_workflow", "improvement_findings", ["workflow"])
    op.create_index("ix_improvement_findings_type", "improvement_findings", ["finding_type"])
    op.create_index("ix_improvement_findings_status", "improvement_findings", ["status"])
    op.create_index("ix_improvement_findings_created_at", "improvement_findings", ["created_at"])

    op.create_table(
        "eval_cases",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(length=64),
            sa.ForeignKey("improvement_findings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workflow", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("input_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expected_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_eval_cases_status"),
    )
    op.create_index("ix_eval_cases_finding_id", "eval_cases", ["finding_id"])
    op.create_index("ix_eval_cases_workflow", "eval_cases", ["workflow"])
    op.create_index("ix_eval_cases_created_at", "eval_cases", ["created_at"])

    op.create_table(
        "codex_task_packets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(length=64),
            sa.ForeignKey("improvement_findings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "eval_case_id",
            sa.String(length=64),
            sa.ForeignKey("eval_cases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("packet_path", sa.Text(), nullable=True),
        sa.Column("task_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("traces_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("eval_cases_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("relevant_files_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("validation_commands_json", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("exported_at", TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'exported')",
            name="ck_codex_task_packets_status",
        ),
    )
    op.create_index("ix_codex_task_packets_finding_id", "codex_task_packets", ["finding_id"])
    op.create_index("ix_codex_task_packets_status", "codex_task_packets", ["status"])
    op.create_index("ix_codex_task_packets_created_at", "codex_task_packets", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_codex_task_packets_created_at", table_name="codex_task_packets")
    op.drop_index("ix_codex_task_packets_status", table_name="codex_task_packets")
    op.drop_index("ix_codex_task_packets_finding_id", table_name="codex_task_packets")
    op.drop_table("codex_task_packets")
    op.drop_index("ix_eval_cases_created_at", table_name="eval_cases")
    op.drop_index("ix_eval_cases_workflow", table_name="eval_cases")
    op.drop_index("ix_eval_cases_finding_id", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_index("ix_improvement_findings_created_at", table_name="improvement_findings")
    op.drop_index("ix_improvement_findings_status", table_name="improvement_findings")
    op.drop_index("ix_improvement_findings_type", table_name="improvement_findings")
    op.drop_index("ix_improvement_findings_workflow", table_name="improvement_findings")
    op.drop_table("improvement_findings")
