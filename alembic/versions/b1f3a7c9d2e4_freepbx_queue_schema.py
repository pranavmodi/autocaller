"""Align queue_state_snapshots with real FreePBX format

- Rename global_oldest_wait_seconds → global_max_holdtime
- Drop global_agents_logged_in (not in FreePBX response)

Revision ID: b1f3a7c9d2e4
Revises: acf4fe2063fa
Create Date: 2026-02-02 09:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1f3a7c9d2e4'
down_revision: Union[str, None] = 'c7d960b54d3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'queue_state_snapshots',
        'global_oldest_wait_seconds',
        new_column_name='global_max_holdtime',
    )
    op.drop_column('queue_state_snapshots', 'global_agents_logged_in')


def downgrade() -> None:
    op.add_column(
        'queue_state_snapshots',
        sa.Column('global_agents_logged_in', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column(
        'queue_state_snapshots',
        'global_max_holdtime',
        new_column_name='global_oldest_wait_seconds',
    )
