"""Add voice_config JSONB to system_settings

Per-provider voice knobs — which named voice (alloy/Aoede/etc), affective
dialog flag (Gemini), proactive audio flag (Gemini), temperature. One
JSONB column so future providers / knobs don't need more migrations.

Schema:
  voice_config = {
    "openai":  {"voice": "alloy", "temperature": 0.8},
    "gemini":  {"voice": "Aoede", "affective_dialog": false,
                "proactive_audio": false, "temperature": 1.0}
  }

Missing keys fall back to env-var defaults at call time.

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2026-04-21 23:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "x8y9z0a1b2c3"
down_revision = "w7x8y9z0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "voice_config",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "voice_config")
