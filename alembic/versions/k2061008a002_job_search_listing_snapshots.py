"""Persist per-run structured listings and TypeSafe relevance judgments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "k2061008a002"
down_revision = "j2061008a001"
branch_labels = None
depends_on = None


def upgrade():
    snapshots = sa.Table(
        "job_search_listing_snapshots", sa.MetaData(),
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("listing_key", sa.String(64), nullable=False),
        sa.Column("source_key", sa.String(320), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("native_id", sa.String(512), nullable=False),
        sa.Column("job_url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("employer_name", sa.String(512), nullable=False, server_default=""),
        sa.Column("location", sa.Text(), nullable=False, server_default=""),
        sa.Column("employment_type", sa.String(500), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.String(64), nullable=True),
        sa.Column("raw_fingerprint", sa.String(64), nullable=False),
        sa.Column("listing", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="collected"),
        sa.Column("choice", sa.String(32), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("judgment", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "listing_key", name="uq_job_search_snapshot_run_listing"),
    )
    snapshots.create(op.get_bind(), checkfirst=True)
    op.create_index("ix_job_search_listing_snapshots_run_id", "job_search_listing_snapshots", ["run_id"], if_not_exists=True)
    op.create_index("ix_job_search_listing_snapshots_source_key", "job_search_listing_snapshots", ["source_key"], if_not_exists=True)
    op.create_index("ix_job_search_listing_snapshots_status", "job_search_listing_snapshots", ["status"], if_not_exists=True)
    op.create_index("ix_job_search_listing_snapshots_choice", "job_search_listing_snapshots", ["choice"], if_not_exists=True)
    op.create_index("ix_job_search_listing_snapshots_selected", "job_search_listing_snapshots", ["selected"], if_not_exists=True)


def downgrade():
    op.drop_table("job_search_listing_snapshots")
