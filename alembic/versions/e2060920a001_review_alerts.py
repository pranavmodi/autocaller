"""Durable review subscriptions, outbox, deduplication and replies."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e2060920a001"
down_revision = "d9e0f1g2h3i4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("review_alert_subscriptions",
        sa.Column("pif_id", sa.String(64), primary_key=True),
        sa.Column("domain", sa.String(512), nullable=False, unique=True),
        sa.Column("firm_name", sa.String(512), nullable=False),
        sa.Column("contact_id", sa.String(64), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False, unique=True),
        sa.Column("recipient_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("last_queued_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("review_alert_deliveries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("pif_id", sa.String(64), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("recipient_name", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("reviews", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("message_id", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("pif_id", "day", name="uq_review_alert_firm_day"))
    op.create_index("ix_review_alert_deliveries_pif_id", "review_alert_deliveries", ["pif_id"])
    op.create_index("ix_review_alert_deliveries_status", "review_alert_deliveries", ["status"])
    op.create_table("review_alert_items",
        sa.Column("pif_id", sa.String(64), primary_key=True),
        sa.Column("review_key", sa.String(64), primary_key=True),
        sa.Column("delivery_id", sa.String(64), sa.ForeignKey("review_alert_deliveries.id"), nullable=False))
    op.create_table("review_alert_replies",
        sa.Column("inbound_id", sa.String(64), primary_key=True),
        sa.Column("pif_id", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("decision", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_review_alert_replies_pif_id", "review_alert_replies", ["pif_id"])


def downgrade():
    for table in ("review_alert_replies", "review_alert_items", "review_alert_deliveries", "review_alert_subscriptions"):
        op.drop_table(table)
