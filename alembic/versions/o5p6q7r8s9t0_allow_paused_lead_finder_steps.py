"""Allow transiently paused Lead Finder steps.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
"""
from alembic import op


revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_lead_finder_steps_status", "lead_finder_steps", type_="check")
    op.create_check_constraint(
        "ck_lead_finder_steps_status",
        "lead_finder_steps",
        "status IN ('queued', 'running', 'retrying', 'completed', 'paused', 'failed', 'interrupted')",
    )


def downgrade() -> None:
    op.execute("UPDATE lead_finder_steps SET status = 'failed' WHERE status = 'paused'")
    op.drop_constraint("ck_lead_finder_steps_status", "lead_finder_steps", type_="check")
    op.create_check_constraint(
        "ck_lead_finder_steps_status",
        "lead_finder_steps",
        "status IN ('queued', 'running', 'retrying', 'completed', 'failed', 'interrupted')",
    )
