"""Saved targeted job searches; runs retain snapshots in career_search_runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = 'g2060926a001'
down_revision = 'f2060920a001'
branch_labels = None
depends_on = None

def upgrade():
    # Startup may already have installed the additive table.
    table = sa.Table('job_agent_saved_searches', sa.MetaData(),
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('config', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    table.create(op.get_bind(), checkfirst=True)

def downgrade():
    op.drop_table('job_agent_saved_searches')
