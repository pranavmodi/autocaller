"""Blog-post outreach campaign orchestrator.

Owns the lifecycle: create campaign → build audience → compose per-recipient
→ preview → send (manual or batch) → track opens/clicks → report.

Wraps the LLM-composed body in brand HTML chrome, substitutes the
tracking placeholder for the real tracked URL, appends signature and
1x1 open pixel, then sends via Resend (HTML email). Falls back to SMTP
only if Resend is misconfigured.

For tracking endpoints to actually reach the daemon from email clients,
the operator must expose the daemon publicly and set OUTREACH_PUBLIC_BASE_URL
to that hostname (e.g. https://autocaller.getpossibleminds.com). The
service does not validate reachability — that's a deploy-time concern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select, update, func, and_, case
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal
from app.db.models import (
    OutreachCampaignRow,
    OutreachSendRow,
    LinkEventRow,
    FirmContactRow,
    PatientRow,
)
from app.services import blog_post_service
from app.services.comms_log import log_email
from app.services.outreach_composer import (
    compose,
    ComposerInput,
    ComposedEmail,
    substitute_tracked_url,
    TRACKED_URL_PLACEHOLDER,
)
from app.services.product_learning import link_event_trace_kwargs
from app.services.product_traces import safe_record_product_trace
from app.services.lead_gen_cybernetic import record_observation


logger = logging.getLogger(__name__)


# A pragmatic email check — exactly one @, no whitespace, dot in the
# domain. firm_contacts.email is a free-text column that has historically
# been used as a notes field ("not publicly listed; ...", "[email protected]
# and [email protected]", "x@... (press release 2024) and y@...
# (directory)"). Any of those would otherwise sail past `if not email`
# and end up as recipient_email in a real send.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def _is_valid_email(s: str) -> bool:
    return bool(_EMAIL_RE.match(s))


# --- Config ----------------------------------------------------------------

PUBLIC_BASE_URL = os.getenv("OUTREACH_PUBLIC_BASE_URL", "").rstrip("/")
WEBSITE_URL = os.getenv("WEBSITE_URL", "https://getpossibleminds.com").rstrip("/")
CONSULT_URL = os.getenv("CONSULT_URL", f"{WEBSITE_URL}/consult")

DEFAULT_SENDER_NAME = os.getenv("OUTREACH_SENDER_NAME", "Pranav Modi")
DEFAULT_SENDER_EMAIL = os.getenv("OUTREACH_SENDER_EMAIL", "").strip()
DEFAULT_SENDER_TITLE = os.getenv("OUTREACH_SENDER_TITLE", "Founder, Possible Minds")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _public_base_url() -> str:
    if not PUBLIC_BASE_URL:
        raise RuntimeError(
            "OUTREACH_PUBLIC_BASE_URL is not set. Set it to the hostname "
            "the autocaller daemon is reachable at from email clients "
            "(e.g. https://autocaller.getpossibleminds.com) so /t/o/ and "
            "/t/c/ tracking links work."
        )
    return PUBLIC_BASE_URL


def _token() -> str:
    """24-char URL-safe token; unique constraint on outreach_sends.token
    enforces collision detection (chance of collision at this length is
    cryptographically negligible)."""
    return secrets.token_urlsafe(18)


def tracked_click_url(token: str) -> str:
    return f"{_public_base_url()}/t/c/{token}"


def tracked_open_url(token: str) -> str:
    return f"{_public_base_url()}/t/o/{token}.gif"


# --- Campaign lifecycle ----------------------------------------------------

@dataclass
class CampaignSummary:
    id: int
    name: str
    post_slug: str
    post_title: str
    status: str
    intent: str
    sender_name: str
    sender_email: str
    bcc_email: str | None
    created_at: datetime


async def create_campaign(
    *,
    post_slug: str,
    sender_email: str | None = None,
    sender_name: str | None = None,
    sender_title: str | None = None,
    bcc_email: str | None = None,
    intent: str = "share",
    name: str | None = None,
    notes: str | None = None,
    created_by: str | None = None,
    with_excerpts: bool = True,
    composer_model: str = "openclaw",
) -> CampaignSummary:
    """Create a campaign for a blog post. Fetches post metadata (and
    excerpts) at creation time so the body LLM-composer sees the same
    snapshot every recipient gets."""
    sender_email = (sender_email or DEFAULT_SENDER_EMAIL).strip()
    if not sender_email:
        raise ValueError(
            "sender_email required (or set OUTREACH_SENDER_EMAIL env)"
        )
    sender_name = (sender_name or DEFAULT_SENDER_NAME).strip()
    sender_title = (sender_title or DEFAULT_SENDER_TITLE).strip() or None
    bcc_email = (bcc_email or "").strip() or None

    post = await blog_post_service.fetch_post(post_slug, with_excerpts=with_excerpts)
    campaign_name = name or f"{post.title} — {_utcnow().strftime('%Y-%m-%d')}"

    async with AsyncSessionLocal() as session:
        row = OutreachCampaignRow(
            name=campaign_name[:255],
            post_slug=post.slug,
            post_url=post.url,
            post_title=post.title[:512],
            post_description=post.description,
            post_category=post.category or None,
            post_tags=post.tags,
            post_excerpts=post.excerpts,
            intent=intent,
            status="draft",
            sender_name=sender_name,
            sender_email=sender_email,
            sender_title=sender_title,
            bcc_email=bcc_email,
            composer_model=composer_model,
            notes=notes,
            created_by=created_by,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _campaign_summary(row)


def _campaign_summary(row: OutreachCampaignRow) -> CampaignSummary:
    return CampaignSummary(
        id=row.id,
        name=row.name,
        post_slug=row.post_slug,
        post_title=row.post_title,
        status=row.status,
        intent=row.intent,
        sender_name=row.sender_name,
        sender_email=row.sender_email,
        bcc_email=row.bcc_email,
        created_at=row.created_at,
    )


async def list_campaigns(*, status: str | None = None, limit: int = 50) -> list[CampaignSummary]:
    async with AsyncSessionLocal() as session:
        stmt = select(OutreachCampaignRow).order_by(OutreachCampaignRow.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(OutreachCampaignRow.status == status)
        rows = (await session.execute(stmt)).scalars().all()
        return [_campaign_summary(r) for r in rows]


async def get_campaign(campaign_id: int) -> OutreachCampaignRow:
    async with AsyncSessionLocal() as session:
        row = await session.get(OutreachCampaignRow, campaign_id)
        if not row:
            raise LookupError(f"campaign {campaign_id} not found")
        return row


async def update_campaign_bcc(campaign_id: int, bcc_email: str | None) -> OutreachCampaignRow:
    """Update the BCC address on a campaign. Pass empty/None to clear it."""
    cleaned: str | None = (bcc_email or "").strip() or None
    if cleaned is not None and not _is_valid_email(cleaned):
        raise ValueError(f"invalid bcc email: {cleaned!r}")
    async with AsyncSessionLocal() as session:
        row = await session.get(OutreachCampaignRow, campaign_id)
        if not row:
            raise LookupError(f"campaign {campaign_id} not found")
        row.bcc_email = cleaned
        row.updated_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        return row


# --- Audience build --------------------------------------------------------

@dataclass
class AudienceResult:
    added: int
    skipped_no_email: int
    skipped_duplicate: int
    skipped_recent_outreach: int


async def add_contacts_to_campaign(
    *,
    campaign_id: int,
    contact_ids: list[str],
    exclude_recent_days: int = 14,
) -> AudienceResult:
    """Insert outreach_sends rows in pending status for the given contacts.

    Skips:
      - contacts with no email on file
      - duplicates (already in this campaign)
      - contacts whose recipient_email got any outreach send in the
        last `exclude_recent_days` days (across all campaigns)
    """
    result = AudienceResult(0, 0, 0, 0)
    if not contact_ids:
        return result

    cutoff = _utcnow() - timedelta(days=exclude_recent_days) if exclude_recent_days > 0 else None

    async with AsyncSessionLocal() as session:
        contacts = (await session.execute(
            select(FirmContactRow).where(FirmContactRow.id.in_(contact_ids))
        )).scalars().all()

        # Pre-fetch existing sends for this campaign (for dup check) and
        # recent sends across all campaigns (for stale-contact check).
        existing_contact_ids = set((await session.execute(
            select(OutreachSendRow.contact_id)
            .where(OutreachSendRow.campaign_id == campaign_id)
        )).scalars().all())

        recent_emails: set[str] = set()
        if cutoff is not None:
            recent_emails = set(e.lower() for e in (await session.execute(
                select(OutreachSendRow.recipient_email)
                .where(
                    OutreachSendRow.sent_at.isnot(None),
                    OutreachSendRow.sent_at >= cutoff,
                )
            )).scalars().all() if e)

        # Track emails added in THIS batch so two firm_contacts rows that
        # happen to share an email don't both get inserted.
        added_emails_this_batch: set[str] = set()

        for c in contacts:
            email = (c.email or "").strip()
            if not email or not _is_valid_email(email):
                result.skipped_no_email += 1
                continue
            if c.id in existing_contact_ids:
                result.skipped_duplicate += 1
                continue
            email_l = email.lower()
            if email_l in added_emails_this_batch:
                result.skipped_duplicate += 1
                continue
            if email_l in recent_emails:
                result.skipped_recent_outreach += 1
                continue

            # Pull firm denorm from patients table by pif_id (autocaller's
            # firm-level metadata lives there). Fall back to pif_id as the
            # firm name if no patient row exists.
            patient_row = (await session.execute(
                select(PatientRow.firm_name)
                .where(PatientRow.patient_id == c.pif_id)
                .limit(1)
            )).scalar_one_or_none()
            firm_name = patient_row or c.pif_id

            send = OutreachSendRow(
                campaign_id=campaign_id,
                contact_id=c.id,
                pif_id=c.pif_id,
                recipient_email=email,
                recipient_name=c.full_name or None,
                recipient_first_name=c.first_name or None,
                recipient_title=c.title or None,
                firm_name=firm_name,
                token=_token(),
                status="pending",
            )
            session.add(send)
            try:
                await session.flush()
                existing_contact_ids.add(c.id)
                added_emails_this_batch.add(email_l)
                result.added += 1
            except IntegrityError:
                await session.rollback()
                result.skipped_duplicate += 1

        # Move campaign out of draft now that it has an audience.
        if result.added > 0:
            await session.execute(
                update(OutreachCampaignRow)
                .where(
                    OutreachCampaignRow.id == campaign_id,
                    OutreachCampaignRow.status == "draft",
                )
                .values(status="ready", updated_at=_utcnow())
            )
        await session.commit()
    return result


async def resolve_contacts_by_pif_ids(pif_ids: list[str]) -> list[str]:
    """Return all firm_contacts.id for the given firm ids that have an
    email. Used by the CLI when the operator builds an audience from a
    firm list."""
    if not pif_ids:
        return []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FirmContactRow.id)
            .where(
                FirmContactRow.pif_id.in_(pif_ids),
                FirmContactRow.email.isnot(None),
                func.length(FirmContactRow.email) > 0,
            )
        )).scalars().all()
        return list(rows)


# --- Compose ---------------------------------------------------------------

async def compose_for_send(
    send_id: int, *, regenerate: bool = False, model: str | None = None,
) -> OutreachSendRow:
    """Call the LLM composer for one send. Caches the output on the row
    so preview + send always see the same content. Pass regenerate=True
    to force a re-render."""
    async with AsyncSessionLocal() as session:
        send = await session.get(OutreachSendRow, send_id)
        if not send:
            raise LookupError(f"send {send_id} not found")
        if send.status == "sent":
            raise RuntimeError(f"send {send_id} already sent; cannot recompose")
        if send.status not in ("pending", "composed", "failed") and not regenerate:
            raise RuntimeError(f"send {send_id} in unexpected state {send.status!r}")
        if send.composed_subject and not regenerate:
            return send  # cached
        campaign = await session.get(OutreachCampaignRow, send.campaign_id)
        if not campaign:
            raise LookupError(f"campaign {send.campaign_id} not found")

    payload = _build_composer_payload(campaign, send)
    composed = await compose(payload, model=model or campaign.composer_model)

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(OutreachSendRow)
            .where(OutreachSendRow.id == send_id)
            .values(
                composed_subject=composed.subject[:512],
                composed_preheader=composed.preheader[:512],
                composed_body_html=composed.body_html,
                composed_plaintext=composed.plaintext,
                composed_reasoning=composed.reasoning,
                composed_at=_utcnow(),
                composer_model=composed.model,
                status="composed",
                failure_reason=None,
            )
        )
        await session.commit()
        return await session.get(OutreachSendRow, send_id)


def _build_composer_payload(
    campaign: OutreachCampaignRow, send: OutreachSendRow,
) -> ComposerInput:
    return ComposerInput(
        post={
            "title": campaign.post_title,
            "slug": campaign.post_slug,
            "description": campaign.post_description or "",
            "category": campaign.post_category or "",
            "tags": campaign.post_tags or [],
            "read_time": "",
            "excerpts": campaign.post_excerpts or [],
        },
        recipient={
            "first_name": send.recipient_first_name or "",
            "full_name": send.recipient_name or "",
            "title": send.recipient_title or "",
            "email": send.recipient_email,
        },
        firm={
            "name": send.firm_name or "",
            "pif_id": send.pif_id or "",
        },
        sender={
            "first_name": (campaign.sender_name or "").split()[0] or "",
            "full_name": campaign.sender_name,
            "title": campaign.sender_title or DEFAULT_SENDER_TITLE,
            "website": WEBSITE_URL.replace("https://", "").replace("http://", ""),
            "consult_link": CONSULT_URL.replace("https://", "").replace("http://", ""),
        },
        tracked_post_url=tracked_click_url(send.token),
        intent=campaign.intent,
    )


# --- Send ------------------------------------------------------------------

@dataclass
class SendResult:
    send_id: int
    message_id: str
    transport: str


@dataclass
class RenderedSend:
    """What actually goes on the wire for one send — operator-previewable."""
    subject: str
    full_html: str
    full_plaintext: str
    from_header: str
    to: str
    tracked_click_url: str
    open_pixel_url: str


async def render_send(send_id: int) -> RenderedSend:
    """Return the exact subject / wrapped HTML / plaintext that send_now
    would post to Resend, without sending. Used by preview (CLI + UI)."""
    async with AsyncSessionLocal() as session:
        send = await session.get(OutreachSendRow, send_id)
        if not send:
            raise LookupError(f"send {send_id} not found")
        if not send.composed_subject:
            raise RuntimeError(
                f"send {send_id} has no composed email — call compose_for_send first"
            )
        campaign = await session.get(OutreachCampaignRow, send.campaign_id)

    subject = (send.edited_subject or send.composed_subject or "").strip()
    raw_html = send.edited_body_html or send.composed_body_html or ""
    raw_plain = send.edited_plaintext or send.composed_plaintext or ""

    click_url = tracked_click_url(send.token)
    pixel_url = tracked_open_url(send.token)
    body_html = substitute_tracked_url(raw_html, click_url)
    plaintext = substitute_tracked_url(raw_plain, click_url)

    full_html = _wrap_html(
        inner_html=body_html,
        preheader=send.composed_preheader or "",
        sender_name=campaign.sender_name,
        sender_title=campaign.sender_title or DEFAULT_SENDER_TITLE,
        website_url=WEBSITE_URL,
        consult_url=CONSULT_URL,
        open_pixel_url=pixel_url,
    )
    full_plain = _append_plaintext_signature(
        plaintext, campaign.sender_name, campaign.sender_title or DEFAULT_SENDER_TITLE,
        WEBSITE_URL, CONSULT_URL,
    )
    from_header = (
        f"{campaign.sender_name} <{campaign.sender_email}>"
        if campaign.sender_name else campaign.sender_email
    )
    return RenderedSend(
        subject=subject,
        full_html=full_html,
        full_plaintext=full_plain,
        from_header=from_header,
        to=send.recipient_email,
        tracked_click_url=click_url,
        open_pixel_url=pixel_url,
    )


async def send_now(send_id: int) -> SendResult:
    """Send one composed email. Substitutes tracked URLs, wraps in brand
    HTML chrome, appends tracking pixel + signature, posts via Resend."""
    async with AsyncSessionLocal() as session:
        send = await session.get(OutreachSendRow, send_id)
        if not send:
            raise LookupError(f"send {send_id} not found")
        if send.status == "sent":
            raise RuntimeError(f"send {send_id} already sent at {send.sent_at}")
        if send.status == "skipped":
            raise RuntimeError(f"send {send_id} is skipped")
        if not send.composed_subject:
            raise RuntimeError(
                f"send {send_id} has no composed email — call compose_for_send first"
            )
        campaign = await session.get(OutreachCampaignRow, send.campaign_id)

    rendered = await render_send(send_id)

    # Stamp send_attempted_at before the network call so a crash mid-send
    # doesn't lose the attempt record.
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(OutreachSendRow)
            .where(OutreachSendRow.id == send_id)
            .values(send_attempted_at=_utcnow(), status="sending", failure_reason=None)
        )
        await session.commit()

    try:
        msg_id, transport = await _send_email(
            from_name=campaign.sender_name,
            from_email=campaign.sender_email,
            to=send.recipient_email,
            subject=rendered.subject,
            html=rendered.full_html,
            text=rendered.full_plaintext,
            bcc_override=campaign.bcc_email,
        )
    except Exception as e:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(OutreachSendRow)
                .where(OutreachSendRow.id == send_id)
                .values(
                    status="failed",
                    failure_reason=f"{type(e).__name__}: {str(e)[:500]}",
                )
            )
            await session.commit()
        # Mirror failure into the /comms log so operators can see it.
        await asyncio.to_thread(
            log_email,
            recipient_email=send.recipient_email,
            subject=rendered.subject,
            body=rendered.full_plaintext,
            message_type="outreach",
            transport="resend",
            status="failed",
            error=f"{type(e).__name__}: {str(e)[:300]}",
            pif_id=send.pif_id,
            recipient_name=send.recipient_name,
        )
        raise

    # Mirror success into the /comms log.
    await asyncio.to_thread(
        log_email,
        recipient_email=send.recipient_email,
        subject=rendered.subject,
        body=rendered.full_plaintext,
        message_type="outreach",
        transport=transport,
        message_id=msg_id,
        status="sent",
        pif_id=send.pif_id,
        recipient_name=send.recipient_name,
    )

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(OutreachSendRow)
            .where(OutreachSendRow.id == send_id)
            .values(
                status="sent",
                sent_at=_utcnow(),
                message_id=msg_id[:255] if msg_id else None,
                transport=transport,
            )
        )
        # Flip campaign status to sending on first send.
        await session.execute(
            update(OutreachCampaignRow)
            .where(
                OutreachCampaignRow.id == send.campaign_id,
                OutreachCampaignRow.status.in_(("ready", "draft")),
            )
            .values(status="sending", updated_at=_utcnow())
        )
        await session.commit()

    return SendResult(send_id=send_id, message_id=msg_id, transport=transport)


async def skip(send_id: int, *, reason: str) -> None:
    async with AsyncSessionLocal() as session:
        send = await session.get(OutreachSendRow, send_id)
        if not send:
            raise LookupError(f"send {send_id} not found")
        if send.status == "sent":
            raise RuntimeError("cannot skip an already-sent send")
        await session.execute(
            update(OutreachSendRow)
            .where(OutreachSendRow.id == send_id)
            .values(status="skipped", skip_reason=reason[:2000])
        )
        await session.commit()


# --- Email transport (HTML-capable) ---------------------------------------

async def _send_email(
    *, from_name: str, from_email: str, to: str, subject: str, html: str, text: str,
    bcc_override: str | None = None,
) -> tuple[str, str]:
    """Send HTML+text email. Returns (message_id, transport).

    Prefers Resend (HTTPS API, no SMTP needed). The existing
    email_notification_service handles operator alerts (text-only);
    this one is HTML-capable for outreach."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "RESEND_API_KEY not set — outreach sends require HTML-capable transport. "
            "Add the key to .env or extend with an SMTP HTML sender."
        )

    fallback_from = os.getenv("RESEND_FALLBACK_FROM", "").strip()
    reply_to = os.getenv("REPLY_TO_EMAIL", "").strip()
    # Per-campaign BCC overrides the global env default. None falls through to env.
    bcc = (bcc_override or "").strip() or os.getenv("BCC_EMAIL", "").strip()

    from_header = f'{from_name} <{from_email}>' if from_name else from_email

    async def _post(this_from: str) -> httpx.Response:
        payload: dict = {
            "from": this_from,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        if reply_to:
            payload["reply_to"] = reply_to
        if bcc and bcc.lower() != to.lower():
            payload["bcc"] = [bcc]
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )

    resp = await _post(from_header)
    if resp.status_code == 403 and fallback_from:
        logger.warning(
            "resend 403 from=%s — retrying with RESEND_FALLBACK_FROM=%s",
            from_header, fallback_from,
        )
        resp = await _post(fallback_from)
    if resp.status_code >= 300:
        raise RuntimeError(f"resend HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json() if resp.content else {}
    return str(data.get("id", "")), "resend"


# --- HTML chrome -----------------------------------------------------------

def _wrap_html(
    *,
    inner_html: str,
    preheader: str,
    sender_name: str,
    sender_title: str,
    website_url: str,
    consult_url: str,
    open_pixel_url: str,
) -> str:
    """Wrap the LLM's inner body in brand chrome: 600px dark table,
    hidden preheader, signature block, 1x1 tracking pixel."""
    preheader_safe = (preheader or "").replace("<", "").replace(">", "")[:200]
    website_label = website_url.replace("https://", "").replace("http://", "")
    consult_label = consult_url.replace("https://", "").replace("http://", "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title></title>
</head>
<body style="margin:0;padding:0;background:#04150d;color:#e8efe9;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
             -webkit-font-smoothing:antialiased;">
<div style="display:none;font-size:1px;color:#04150d;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
  {preheader_safe}
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#04150d;">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
           style="max-width:600px;width:100%;background:#04150d;">
      <tr><td style="padding:0 8px;">
        {inner_html}
        <hr style="margin:32px 0 20px;border:none;border-top:1px solid #1d3a26;">
        <p style="margin:0 0 6px;font-size:14px;line-height:1.5;color:#cfe9d8;">
          &mdash; {sender_name}
        </p>
        <p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#a8c7b3;">
          {sender_title}
        </p>
        <p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#a8c7b3;">
          <a href="{website_url}" style="color:#00ff41;text-decoration:none;">{website_label}</a>
        </p>
        <p style="margin:0 0 6px;font-size:13px;line-height:1.5;color:#a8c7b3;">
          Free 30-min consult: <a href="{consult_url}" style="color:#00ff41;text-decoration:none;">{consult_label}</a>
        </p>
        <img src="{open_pixel_url}" width="1" height="1" alt="" border="0"
             style="display:block;border:0;width:1px;height:1px;line-height:1px;">
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def _append_plaintext_signature(
    plain: str, sender_name: str, sender_title: str,
    website_url: str, consult_url: str,
) -> str:
    website_label = website_url.replace("https://", "").replace("http://", "")
    consult_label = consult_url.replace("https://", "").replace("http://", "")
    sig = (
        f"\n\n— {sender_name}\n"
        f"{sender_title}\n"
        f"{website_label}\n"
        f"Free 30-min consult: {consult_label}\n"
    )
    return plain.rstrip() + sig


# --- Tracking --------------------------------------------------------------

# 43-byte transparent 1x1 GIF, served by the open-pixel endpoint.
TRANSPARENT_GIF_BYTES = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


async def record_open(
    token: str, *, ip: str | None = None, user_agent: str | None = None,
) -> None:
    """Log an open event for a token. Idempotent at the row level (each
    pixel fetch is its own event)."""
    trace_kwargs = None
    async with AsyncSessionLocal() as session:
        send = (await session.execute(
            select(OutreachSendRow).where(OutreachSendRow.token == token)
        )).scalar_one_or_none()
        if send is None:
            return  # unknown token — silently drop (don't 404 the pixel)
        campaign = await session.get(OutreachCampaignRow, send.campaign_id)
        event = LinkEventRow(
            send_id=send.id,
            kind="open",
            ip=(ip or "")[:64] or None,
            user_agent=(user_agent or "")[:512] or None,
        )
        session.add(event)
        await session.flush()
        trace_kwargs = link_event_trace_kwargs(event, send=send, campaign=campaign)
        await session.commit()
    if trace_kwargs:
        await safe_record_product_trace(**trace_kwargs)


async def record_click(
    token: str, *, ip: str | None = None, user_agent: str | None = None,
    referer: str | None = None,
) -> str | None:
    """Log a click event and return the destination URL the recipient
    should be redirected to (the canonical blog post URL). Returns
    None if the token is unknown."""
    trace_kwargs = None
    async with AsyncSessionLocal() as session:
        send = (await session.execute(
            select(OutreachSendRow).where(OutreachSendRow.token == token)
        )).scalar_one_or_none()
        if send is None:
            return None
        campaign = await session.get(OutreachCampaignRow, send.campaign_id)
        if not campaign:
            return None
        dest = campaign.post_url
        event = LinkEventRow(
            send_id=send.id,
            kind="click",
            url=dest[:2048],
            ip=(ip or "")[:64] or None,
            user_agent=(user_agent or "")[:512] or None,
            referer=(referer or "")[:1024] or None,
        )
        session.add(event)
        await session.flush()
        trace_kwargs = link_event_trace_kwargs(event, send=send, campaign=campaign)
        await session.commit()
    if trace_kwargs:
        await safe_record_product_trace(**trace_kwargs)
    await record_observation(
        "link_clicked",
        {
            "dedupe_key": f"link_event:{event.id}",
            "link_event_id": event.id,
            "send_id": send.id,
            "campaign_id": send.campaign_id,
            "token": token,
            "url": dest,
            "recipient_email": send.recipient_email,
            "recipient_name": send.recipient_name,
            "firm_name": send.firm_name,
            "pif_id": send.pif_id,
            "clicked_at": event.ts.isoformat() if event.ts else None,
            "ip": event.ip,
            "user_agent": event.user_agent,
            "referer": event.referer,
        },
        contact_id=send.contact_id,
    )
    return dest


# --- Queries (for CLI + UI) ------------------------------------------------

@dataclass
class CampaignStats:
    campaign_id: int
    total: int
    pending: int
    composed: int
    sent: int
    skipped: int
    failed: int
    opens: int
    unique_opens: int
    clicks: int
    unique_clicks: int


async def campaign_stats(campaign_id: int) -> CampaignStats:
    async with AsyncSessionLocal() as session:
        send_counts = dict((await session.execute(
            select(OutreachSendRow.status, func.count())
            .where(OutreachSendRow.campaign_id == campaign_id)
            .group_by(OutreachSendRow.status)
        )).all())

        # Open / click counts via join.
        opens_total = (await session.execute(
            select(func.count()).select_from(LinkEventRow)
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .where(
                OutreachSendRow.campaign_id == campaign_id,
                LinkEventRow.kind == "open",
            )
        )).scalar_one() or 0
        opens_unique = (await session.execute(
            select(func.count(func.distinct(LinkEventRow.send_id)))
            .select_from(LinkEventRow)
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .where(
                OutreachSendRow.campaign_id == campaign_id,
                LinkEventRow.kind == "open",
            )
        )).scalar_one() or 0
        clicks_total = (await session.execute(
            select(func.count()).select_from(LinkEventRow)
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .where(
                OutreachSendRow.campaign_id == campaign_id,
                LinkEventRow.kind == "click",
            )
        )).scalar_one() or 0
        clicks_unique = (await session.execute(
            select(func.count(func.distinct(LinkEventRow.send_id)))
            .select_from(LinkEventRow)
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .where(
                OutreachSendRow.campaign_id == campaign_id,
                LinkEventRow.kind == "click",
            )
        )).scalar_one() or 0

        total = sum(send_counts.values())
        return CampaignStats(
            campaign_id=campaign_id,
            total=total,
            pending=send_counts.get("pending", 0),
            composed=send_counts.get("composed", 0),
            sent=send_counts.get("sent", 0),
            skipped=send_counts.get("skipped", 0),
            failed=send_counts.get("failed", 0),
            opens=opens_total,
            unique_opens=opens_unique,
            clicks=clicks_total,
            unique_clicks=clicks_unique,
        )


async def get_next_for_review(campaign_id: int) -> OutreachSendRow | None:
    """Used by the step-through UI: returns the next send the operator
    should look at (composed-but-not-sent first, then pending, then None)."""
    async with AsyncSessionLocal() as session:
        # Prefer composed rows (ready to review/send).
        stmt = (
            select(OutreachSendRow)
            .where(
                OutreachSendRow.campaign_id == campaign_id,
                OutreachSendRow.status.in_(("composed", "pending")),
            )
            .order_by(
                # Composed first, then pending. status sorts alphabetically:
                # 'composed' < 'pending' — perfect.
                OutreachSendRow.status.asc(),
                OutreachSendRow.id.asc(),
            )
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def get_send(send_id: int) -> OutreachSendRow:
    async with AsyncSessionLocal() as session:
        row = await session.get(OutreachSendRow, send_id)
        if not row:
            raise LookupError(f"send {send_id} not found")
        return row


async def list_sends(
    campaign_id: int, *, status: str | None = None, limit: int = 200,
) -> list[OutreachSendRow]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(OutreachSendRow)
            .where(OutreachSendRow.campaign_id == campaign_id)
            .order_by(OutreachSendRow.id.asc())
            .limit(limit)
        )
        if status:
            stmt = stmt.where(OutreachSendRow.status == status)
        return list((await session.execute(stmt)).scalars().all())


@dataclass
class SendEngagement:
    """Per-send open + click counts and most-recent-event timestamp."""
    opens: int
    clicks: int
    last_event_at: datetime | None


async def engagement_by_send(campaign_id: int) -> dict[int, SendEngagement]:
    """Single grouped query: returns {send_id: SendEngagement} for every
    send in the campaign that has at least one event. Sends with no events
    are absent from the dict — callers should treat missing as zeroes."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(
                LinkEventRow.send_id,
                func.sum(case((LinkEventRow.kind == "open", 1), else_=0)).label("opens"),
                func.sum(case((LinkEventRow.kind == "click", 1), else_=0)).label("clicks"),
                func.max(LinkEventRow.ts).label("last_ts"),
            )
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .where(OutreachSendRow.campaign_id == campaign_id)
            .group_by(LinkEventRow.send_id)
        )
        rows = (await session.execute(stmt)).all()
        return {
            r.send_id: SendEngagement(
                opens=int(r.opens or 0),
                clicks=int(r.clicks or 0),
                last_event_at=r.last_ts,
            )
            for r in rows
        }


@dataclass
class LinkEventDetail:
    """One row from link_events, joined with the send's recipient_email
    for display. Append-only, so safe to page by id desc."""
    id: int
    send_id: int
    recipient_email: str
    kind: str
    url: str | None
    ip: str | None
    user_agent: str | None
    ts: datetime


async def list_events(
    campaign_id: int, *, limit: int = 200, kind: str | None = None,
) -> list[LinkEventDetail]:
    """Newest-first event timeline for one campaign. kind filter accepts
    'open' or 'click'."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(LinkEventRow, OutreachSendRow.recipient_email)
            .join(OutreachSendRow, LinkEventRow.send_id == OutreachSendRow.id)
            .where(OutreachSendRow.campaign_id == campaign_id)
            .order_by(LinkEventRow.ts.desc())
            .limit(limit)
        )
        if kind in ("open", "click"):
            stmt = stmt.where(LinkEventRow.kind == kind)
        rows = (await session.execute(stmt)).all()
        return [
            LinkEventDetail(
                id=ev.id,
                send_id=ev.send_id,
                recipient_email=email,
                kind=ev.kind,
                url=ev.url,
                ip=ev.ip,
                user_agent=ev.user_agent,
                ts=ev.ts,
            )
            for ev, email in rows
        ]


async def apply_edits(
    send_id: int, *,
    edited_subject: str | None = None,
    edited_body_html: str | None = None,
    edited_plaintext: str | None = None,
    edited_by: str | None = None,
) -> OutreachSendRow:
    """Operator-applied hand edits. None = no change to that field;
    empty string = clear the override (fall back to composed_*)."""
    async with AsyncSessionLocal() as session:
        send = await session.get(OutreachSendRow, send_id)
        if not send:
            raise LookupError(f"send {send_id} not found")
        if send.status == "sent":
            raise RuntimeError("cannot edit an already-sent send")
        vals: dict = {"edited_at": _utcnow(), "edited_by": edited_by or send.edited_by}
        if edited_subject is not None:
            vals["edited_subject"] = edited_subject[:512] if edited_subject else None
        if edited_body_html is not None:
            vals["edited_body_html"] = edited_body_html or None
        if edited_plaintext is not None:
            vals["edited_plaintext"] = edited_plaintext or None
        # Sanity: edited bodies must still contain the placeholder so
        # tracking works after substitution.
        for fld in ("edited_body_html", "edited_plaintext"):
            v = vals.get(fld)
            if v and TRACKED_URL_PLACEHOLDER not in v:
                raise ValueError(
                    f"{fld} must contain the literal {TRACKED_URL_PLACEHOLDER} "
                    "placeholder so the send pipeline can substitute the tracked URL"
                )
        await session.execute(
            update(OutreachSendRow).where(OutreachSendRow.id == send_id).values(**vals)
        )
        await session.commit()
        return await session.get(OutreachSendRow, send_id)


async def mark_campaign_complete_if_drained(campaign_id: int) -> None:
    """Set campaign.status='complete' when no pending/composed/sending rows remain."""
    async with AsyncSessionLocal() as session:
        n = (await session.execute(
            select(func.count()).select_from(OutreachSendRow).where(
                OutreachSendRow.campaign_id == campaign_id,
                OutreachSendRow.status.in_(("pending", "composed", "sending")),
            )
        )).scalar_one()
        if n == 0:
            await session.execute(
                update(OutreachCampaignRow)
                .where(
                    OutreachCampaignRow.id == campaign_id,
                    OutreachCampaignRow.status != "complete",
                )
                .values(status="complete", updated_at=_utcnow())
            )
            await session.commit()
