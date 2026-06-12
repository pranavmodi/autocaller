"""Add competitor graph tables

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-06-12 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "o7p8q9r0s1t2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "firm_competitive_features",
        sa.Column("pif_id", sa.String(length=64), primary_key=True),
        sa.Column("firm_name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("metro", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=True),
        sa.Column("case_mix", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("value_tier", sa.String(length=16), nullable=True),
        sa.Column("volume_proxy", sa.Integer(), nullable=True),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("computed_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_firm_competitive_features_domain", "firm_competitive_features", ["domain"])
    op.create_index("ix_firm_competitive_features_metro", "firm_competitive_features", ["metro"])
    op.create_index("ix_firm_competitive_features_value_tier", "firm_competitive_features", ["value_tier"])

    op.create_table(
        "competitor_edges",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("firm_a_pif_id", sa.String(length=64), nullable=False),
        sa.Column("firm_b_pif_id", sa.String(length=64), nullable=False),
        sa.Column("metro", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("components", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("computed_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("firm_a_pif_id", "firm_b_pif_id", name="uq_competitor_edges_pair"),
    )
    op.create_index("ix_competitor_edges_firm_a", "competitor_edges", ["firm_a_pif_id"])
    op.create_index("ix_competitor_edges_firm_b", "competitor_edges", ["firm_b_pif_id"])
    op.create_index("ix_competitor_edges_metro", "competitor_edges", ["metro"])
    op.create_index("ix_competitor_edges_score", "competitor_edges", ["score"])


def downgrade() -> None:
    op.drop_index("ix_competitor_edges_score", table_name="competitor_edges")
    op.drop_index("ix_competitor_edges_metro", table_name="competitor_edges")
    op.drop_index("ix_competitor_edges_firm_b", table_name="competitor_edges")
    op.drop_index("ix_competitor_edges_firm_a", table_name="competitor_edges")
    op.drop_table("competitor_edges")
    op.drop_index("ix_firm_competitive_features_value_tier", table_name="firm_competitive_features")
    op.drop_index("ix_firm_competitive_features_metro", table_name="firm_competitive_features")
    op.drop_index("ix_firm_competitive_features_domain", table_name="firm_competitive_features")
    op.drop_table("firm_competitive_features")
