"""Add queue_source column to system_settings

Revision ID: d4e5f6a7b8c9
Revises: b1f3a7c9d2e4
Create Date: 2026-02-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b1f3a7c9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'system_settings',
        sa.Column('queue_source', sa.String(20), nullable=False, server_default='simulation'),
    )


def downgrade() -> None:
    op.drop_column('system_settings', 'queue_source')
