"""Add employer ATS registry and durable per-source search coverage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "j2061008a001"
down_revision = "i2061006a002"
branch_labels = None
depends_on = None


def upgrade():
    boards = sa.Table(
        "job_search_employer_boards", sa.MetaData(),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("board_key", sa.String(255), nullable=False),
        sa.Column("board_url", sa.String(2000), nullable=False),
        sa.Column("employer_name", sa.String(512), nullable=False),
        sa.Column("employer_domain", sa.String(255), nullable=False),
        sa.Column("employer_url", sa.String(2000), nullable=False),
        sa.Column("firm_id", sa.String(64), nullable=True),
        sa.Column("discovered_from", sa.String(2000), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cursor", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "board_key", name="uq_job_search_board_provider_key"),
    )
    boards.create(op.get_bind(), checkfirst=True)
    op.create_index("ix_job_search_employer_boards_active", "job_search_employer_boards", ["active"], if_not_exists=True)
    op.create_index("ix_job_search_employer_boards_firm", "job_search_employer_boards", ["firm_id"], if_not_exists=True)

    runs = sa.Table(
        "job_search_source_runs", sa.MetaData(),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("source_key", sa.String(320), nullable=False),
        sa.Column("source_name", sa.String(512), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("adapter_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("pages_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("listings_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_emitted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor_before", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cursor_after", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "source_key", name="uq_job_search_source_run_key"),
    )
    runs.create(op.get_bind(), checkfirst=True)
    op.create_index("ix_job_search_source_runs_run_id", "job_search_source_runs", ["run_id"], if_not_exists=True)
    op.create_index("ix_job_search_source_runs_status", "job_search_source_runs", ["status"], if_not_exists=True)


def downgrade():
    op.drop_table("job_search_source_runs")
    op.drop_table("job_search_employer_boards")
