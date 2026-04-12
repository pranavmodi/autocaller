"""Add preferred_callback_time to call_logs

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-02-22 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "call_logs",
        sa.Column("preferred_callback_time", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_logs", "preferred_callback_time")
