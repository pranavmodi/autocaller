"""Drop foreign key from call_logs.patient_id to patients

Call logs are historical records that must persist across patient
table resets (scenario switches, server restarts).  The FK forced
all patient-reset paths to DELETE FROM call_logs first.

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-03-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'l3m4n5o6p7q8'
down_revision: Union[str, None] = 'k2l3m4n5o6p7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('call_logs_patient_id_fkey', 'call_logs', type_='foreignkey')


def downgrade() -> None:
    op.create_foreign_key(
        'call_logs_patient_id_fkey',
        'call_logs', 'patients',
        ['patient_id'], ['patient_id'],
    )
