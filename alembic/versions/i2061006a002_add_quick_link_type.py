"""Distinguish individual jobs from reusable job portals."""
from alembic import op
import sqlalchemy as sa


revision = "i2061006a002"
down_revision = "h2061006a001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "quick_job_links",
        sa.Column("link_type", sa.String(length=16), server_default="job", nullable=False),
    )
    op.create_index("ix_quick_job_links_link_type", "quick_job_links", ["link_type"])


def downgrade():
    op.drop_index("ix_quick_job_links_link_type", table_name="quick_job_links")
    op.drop_column("quick_job_links", "link_type")
