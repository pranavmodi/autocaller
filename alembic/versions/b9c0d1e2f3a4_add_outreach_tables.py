"""Add outreach tables for blog-post email campaigns

Three tables:
- outreach_campaigns: one row per blog-post blast (slug, intent, sender, status)
- outreach_sends:     one row per (campaign, contact). Holds the LLM-composed
                      email cached for preview/regenerate, the tracking token,
                      send status, and resend message-id. Tokens are the natural
                      key for /t/o/{token}.gif (open pixel) and /t/c/{token}
                      (click redirect).
- link_events:        append-only event log for opens/clicks. Joined to
                      outreach_sends by send_id.

The contact FK is ON DELETE SET NULL so deleting a contact preserves the
send history (audit trail matters for cold email, suppression decisions,
and ROI attribution). The denormalized recipient_email / recipient_name /
firm_name on outreach_sends are the source of truth at send time.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-24 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP


revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outreach_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Operator-visible label. Defaults to "<post_title> — <date>" at
        # create time; editable from the UI.
        sa.Column("name", sa.String(length=255), nullable=False),
        # Blog post identity. post_slug is the routing key; post_url is the
        # canonical https://getpossibleminds.com/blog/<slug> snapshot;
        # post_title is captured at create time so renaming the post on
        # the website doesn't rewrite history.
        sa.Column("post_slug", sa.String(length=255), nullable=False),
        sa.Column("post_url", sa.String(length=1024), nullable=False),
        sa.Column("post_title", sa.String(length=512), nullable=False),
        sa.Column("post_description", sa.Text(), nullable=True),
        sa.Column("post_category", sa.String(length=64), nullable=True),
        # Tags + excerpts handed to the LLM composer alongside the recipient.
        # Stored as JSONB so we can edit/regenerate without re-fetching.
        sa.Column("post_tags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("post_excerpts", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Composer hint. Maps to SKILL.md's `intent` field.
        # share | followup | reengage | warm-intro
        sa.Column("intent", sa.String(length=32), nullable=False, server_default="share"),
        # Lifecycle. draft (audience not built yet) | ready (audience built,
        # nothing sent) | sending (at least one send in flight) | paused |
        # complete (all recipients processed) | archived
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("sender_name", sa.String(length=128), nullable=False),
        sa.Column("sender_email", sa.String(length=320), nullable=False),
        sa.Column("sender_title", sa.String(length=128), nullable=True),
        # Composer model identifier — captured per-campaign so we can A/B and
        # know which model rendered which campaign. Free-form string like
        # "openclaw" or "openai-codex/gpt-5.4".
        sa.Column("composer_model", sa.String(length=64), nullable=False, server_default="openclaw"),
        # Optional operator note.
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_outreach_campaigns_status", "outreach_campaigns", ["status"])
    op.create_index("ix_outreach_campaigns_post_slug", "outreach_campaigns", ["post_slug"])
    op.create_index("ix_outreach_campaigns_created_at", "outreach_campaigns", ["created_at"])

    op.create_table(
        "outreach_sends",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer(),
            sa.ForeignKey("outreach_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Contact FK is nullable + ON DELETE SET NULL: deleting a contact
        # preserves the send row for audit, suppression, and stats.
        sa.Column(
            "contact_id",
            sa.String(length=64),
            sa.ForeignKey("firm_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Denormalized at compose time. Source of truth for what was sent —
        # changes to firm_contacts after send must not retroactively rewrite
        # who-got-what.
        sa.Column("pif_id", sa.String(length=64), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("recipient_first_name", sa.String(length=128), nullable=True),
        sa.Column("recipient_title", sa.String(length=255), nullable=True),
        sa.Column("firm_name", sa.String(length=255), nullable=True),
        # Token is the opaque identifier in /t/o/{token}.gif and /t/c/{token}.
        # Generated as secrets.token_urlsafe(18) → 24-char string. Globally
        # unique so a single token unambiguously identifies one send.
        sa.Column("token", sa.String(length=64), nullable=False),
        # Composed email cache. Populated by the LLM composer on first
        # compose; cleared + repopulated on regenerate. The send pipeline
        # reads from these fields, not the LLM directly — so preview and
        # send always show the same content.
        sa.Column("composed_subject", sa.String(length=512), nullable=True),
        sa.Column("composed_preheader", sa.String(length=512), nullable=True),
        sa.Column("composed_body_html", sa.Text(), nullable=True),
        sa.Column("composed_plaintext", sa.Text(), nullable=True),
        sa.Column("composed_reasoning", sa.Text(), nullable=True),
        sa.Column("composed_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("composer_model", sa.String(length=64), nullable=True),
        # Free-form operator edits to the composed output. When set, the
        # send pipeline uses these instead of the composed_* fields.
        # Lets the operator hand-tweak in the UI without losing the
        # original LLM output.
        sa.Column("edited_subject", sa.String(length=512), nullable=True),
        sa.Column("edited_body_html", sa.Text(), nullable=True),
        sa.Column("edited_plaintext", sa.Text(), nullable=True),
        sa.Column("edited_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("edited_by", sa.String(length=128), nullable=True),
        # Lifecycle.
        # pending  : in audience, not yet composed
        # composed : LLM output cached, awaiting operator review/send
        # sending  : send call in flight (transient — should rarely be seen)
        # sent     : successfully handed to Resend/SMTP
        # skipped  : operator chose to skip; skip_reason explains
        # failed   : send attempt errored; failure_reason explains
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("send_attempted_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("transport", sa.String(length=16), nullable=True),  # resend | smtp
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("campaign_id", "contact_id", name="uq_outreach_sends_campaign_contact"),
        sa.UniqueConstraint("token", name="uq_outreach_sends_token"),
    )
    op.create_index("ix_outreach_sends_campaign_id", "outreach_sends", ["campaign_id"])
    op.create_index("ix_outreach_sends_status", "outreach_sends", ["status"])
    op.create_index("ix_outreach_sends_recipient_email", "outreach_sends", ["recipient_email"])
    op.create_index("ix_outreach_sends_sent_at", "outreach_sends", ["sent_at"])

    op.create_table(
        "link_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "send_id",
            sa.Integer(),
            sa.ForeignKey("outreach_sends.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 'open' (pixel fetch) | 'click' (link redirect). Opens are noisy
        # (Apple Mail Privacy Protection pre-fetches); clicks are trustworthy.
        sa.Column("kind", sa.String(length=16), nullable=False),
        # For clicks, the destination URL the recipient was redirected to.
        # Stored even though it's also reconstructible from the send, in
        # case we ever support multi-link emails.
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("referer", sa.String(length=1024), nullable=True),
        sa.Column(
            "ts",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("kind IN ('open', 'click')", name="ck_link_events_kind"),
    )
    op.create_index("ix_link_events_send_id", "link_events", ["send_id"])
    op.create_index("ix_link_events_kind_ts", "link_events", ["kind", "ts"])


def downgrade() -> None:
    op.drop_index("ix_link_events_kind_ts", table_name="link_events")
    op.drop_index("ix_link_events_send_id", table_name="link_events")
    op.drop_table("link_events")

    op.drop_index("ix_outreach_sends_sent_at", table_name="outreach_sends")
    op.drop_index("ix_outreach_sends_recipient_email", table_name="outreach_sends")
    op.drop_index("ix_outreach_sends_status", table_name="outreach_sends")
    op.drop_index("ix_outreach_sends_campaign_id", table_name="outreach_sends")
    op.drop_table("outreach_sends")

    op.drop_index("ix_outreach_campaigns_created_at", table_name="outreach_campaigns")
    op.drop_index("ix_outreach_campaigns_post_slug", table_name="outreach_campaigns")
    op.drop_index("ix_outreach_campaigns_status", table_name="outreach_campaigns")
    op.drop_table("outreach_campaigns")
