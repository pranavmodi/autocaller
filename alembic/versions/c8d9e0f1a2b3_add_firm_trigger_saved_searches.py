"""Allow saved firm trigger searches.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-08-31 00:00:00.000000
"""
from alembic import op


revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_saved_lead_searches_view", "saved_lead_searches", type_="check")
    op.create_check_constraint(
        "ck_saved_lead_searches_view",
        "saved_lead_searches",
        "view IN ('contacts', 'firms')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM saved_lead_searches WHERE view = 'firms'")
    op.drop_constraint("ck_saved_lead_searches_view", "saved_lead_searches", type_="check")
    op.create_check_constraint(
        "ck_saved_lead_searches_view",
        "saved_lead_searches",
        "view IN ('contacts')",
    )
