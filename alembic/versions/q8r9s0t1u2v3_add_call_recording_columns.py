"""Add recording columns to call_logs

Stores metadata for Twilio recordings downloaded to the local filesystem.
The actual MP3 files live under app/audio/recordings/YYYY/MM/{call_id}.mp3.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-04-09 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "q8r9s0t1u2v3"
down_revision = "p7q8r9s0t1u2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("call_logs", sa.Column("recording_sid", sa.String(64), nullable=True))
    op.add_column("call_logs", sa.Column("recording_path", sa.String(512), nullable=True))
    op.add_column("call_logs", sa.Column("recording_size_bytes", sa.Integer(), nullable=True))
    op.add_column("call_logs", sa.Column("recording_duration_seconds", sa.Integer(), nullable=True))
    op.add_column("call_logs", sa.Column("recording_format", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("call_logs", "recording_format")
    op.drop_column("call_logs", "recording_duration_seconds")
    op.drop_column("call_logs", "recording_size_bytes")
    op.drop_column("call_logs", "recording_path")
    op.drop_column("call_logs", "recording_sid")
