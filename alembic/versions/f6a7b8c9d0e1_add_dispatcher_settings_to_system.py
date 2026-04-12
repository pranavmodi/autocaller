"""Add dispatcher_settings column to system_settings

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'system_settings',
        sa.Column(
            'dispatcher_settings',
            JSONB,
            nullable=False,
            server_default='{"poll_interval": 10, "dispatch_timeout": 30, "max_attempts": 3, "min_hours_between": 6}',
        ),
    )


def downgrade() -> None:
    op.drop_column('system_settings', 'dispatcher_settings')
