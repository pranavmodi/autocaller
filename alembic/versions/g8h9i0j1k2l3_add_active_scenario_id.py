"""Add active_scenario_id column to system_settings

Revision ID: g8h9i0j1k2l3
Revises: f6a7b8c9d0e1
Create Date: 2026-02-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g8h9i0j1k2l3'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'system_settings',
        sa.Column(
            'active_scenario_id',
            sa.String(64),
            sa.ForeignKey('simulation_scenarios.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('system_settings', 'active_scenario_id')
