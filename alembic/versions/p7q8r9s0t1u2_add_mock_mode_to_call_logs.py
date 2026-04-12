"""Add mock_mode flag to call_logs

Records whether each call was placed in mock mode (redirected to a test
phone number) vs. to the real patient's number.  Used in the Call History
UI to visually distinguish test calls from production calls.

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-04-09 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "p7q8r9s0t1u2"
down_revision = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "call_logs",
        sa.Column("mock_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_column("call_logs", "mock_mode")
