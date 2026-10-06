"""Add the quick company job-link inbox."""
from alembic import op
import sqlalchemy as sa


revision = "h2061006a001"
down_revision = "g2060926a001"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "quick_job_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("job_url", sa.String(length=2048), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_url"),
    )
    op.create_index("ix_quick_job_links_created_at", "quick_job_links", ["created_at"])
    op.create_index("ix_quick_job_links_company_name", "quick_job_links", ["company_name"])


def downgrade():
    op.drop_index("ix_quick_job_links_company_name", table_name="quick_job_links")
    op.drop_index("ix_quick_job_links_created_at", table_name="quick_job_links")
    op.drop_table("quick_job_links")
