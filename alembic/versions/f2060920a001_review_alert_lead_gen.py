"""Link review alerts to the standard lead-gen draft and action queue."""
from alembic import op
import sqlalchemy as sa

revision = "f2060920a001"
down_revision = "e2060920a001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("review_alert_deliveries", sa.Column("lead_gen_action_id", sa.String(64), nullable=True))
    op.add_column("review_alert_deliveries", sa.Column("lead_gen_item_id", sa.String(64), nullable=True))
    op.add_column("review_alert_deliveries", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_review_alert_lead_gen_action", "review_alert_deliveries", ["lead_gen_action_id"])


def downgrade():
    op.drop_constraint("uq_review_alert_lead_gen_action", "review_alert_deliveries", type_="unique")
    for name in ("scheduled_for", "lead_gen_item_id", "lead_gen_action_id"):
        op.drop_column("review_alert_deliveries", name)
