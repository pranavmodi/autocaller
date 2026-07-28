"""Add manually-added origin flag to PIF firms

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-07-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "z7a8b9c0d1e2"
down_revision = "y6z7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pif_directory_firms",
        sa.Column("manually_added", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE pif_directory_firms
        SET manually_added = true
        WHERE profile_source = 'manual'
           OR COALESCE(source_json ->> 'operator_managed', 'false') = 'true'
        """
    )
    op.create_index(
        "ix_pif_directory_firms_manually_added",
        "pif_directory_firms",
        ["manually_added"],
    )


def downgrade() -> None:
    op.drop_index("ix_pif_directory_firms_manually_added", table_name="pif_directory_firms")
    op.drop_column("pif_directory_firms", "manually_added")
