"""Add generic source identity and firm labels to outbound email logs."""
from alembic import op
import sqlalchemy as sa


revision = "d9e0f1g2h3i4"
down_revision = "c9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_logs", sa.Column("firm_name", sa.String(length=255), nullable=True))
    op.add_column("email_logs", sa.Column("source_type", sa.String(length=64), nullable=True))
    op.add_column("email_logs", sa.Column("source_id", sa.String(length=64), nullable=True))
    op.create_index(
        "ux_email_logs_source",
        "email_logs",
        ["source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_type IS NOT NULL AND source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_email_logs_source", table_name="email_logs")
    op.drop_column("email_logs", "source_id")
    op.drop_column("email_logs", "source_type")
    op.drop_column("email_logs", "firm_name")
