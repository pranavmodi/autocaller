"""Opt-out-aware review monitoring with a durable, at-most-once send outbox."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, or_, select, text, update

from app.db import AsyncSessionLocal, async_engine
from app.db.models import (
    EmailLogRow, FirmContactRow, FirmReviewRow, InboundEmailRow,
    LeadGenObservationRow, PifFirmRow, ReviewAlertDeliveryRow,
    ReviewAlertItemRow, ReviewAlertReplyRow, ReviewAlertSubscriptionRow,
    SystemSettingsRow,
)
from app.services.contact_selection import classify_email_quality, classify_persona, has_usable_email

logger = logging.getLogger(__name__)
KEY = "review_alerts"
LOCK = 920260921
DEFAULTS = {"enabled": False, "auto_send": False, "daily_limit": 25,
            "postal_address": "", "sender": "",
            "auto_schedule": False, "auto_schedule_time": "09:15",
            "auto_schedule_limit": 20}
NEGATIVE = {"do_not_contact", "bounce", "not_interested", "unsubscribe", "declined", "negative_reply"}


def now():
    return datetime.now(timezone.utc)


def outgoing_suppression(email, pif_id=None):
    """Final common-transport guard, including sends outside this workflow."""
    from app.services.comms_log import _engine
    with _engine().connect() as connection:
        return bool(connection.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM review_alert_subscriptions "
            "WHERE status = 'unsubscribed' AND (recipient_email = :email OR pif_id = :pif_id))"
        ), {"email": email.strip().lower(), "pif_id": pif_id}))


def domain(value):
    value = str(value or "").strip()
    return (urlsplit(value if "://" in value else "https://" + value).hostname or "").lower().removeprefix("www.")


def recent_date(value, today):
    # Collection time is never a substitute for publication time.
    try:
        posted = date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return False
    return today - timedelta(days=13) <= posted <= today


def platform_url(value, platform):
    try:
        parsed = urlsplit(str(value or ""))
        host = (parsed.hostname or "").lower()
        allowed = (host == "google.com" or host.endswith(".google.com") or host == "maps.app.goo.gl") if platform == "google" else (host == "yelp.com" or host.endswith(".yelp.com"))
        return parsed.scheme == "https" and not parsed.username and allowed
    except ValueError:
        return False


def eligible_reviews(payload, today):
    result = {}
    for source in (payload or {}).get("sources", []):
        platform = str(source.get("source") or "").lower()
        if platform not in {"google", "google_maps", "yelp"}:
            continue
        platform = "google" if platform.startswith("google") else "yelp"
        listing = source.get("listing_url")
        if not platform_url(listing, platform):
            continue
        for review in source.get("reviews", []):
            review_text = review.get("text")
            if not recent_date(review.get("review_date"), today) or not isinstance(review_text, str) or not review_text.strip():
                continue
            url = review.get("review_url") or listing
            if not platform_url(url, platform):
                continue
            name = str(review.get("reviewer_name") or "").strip().casefold()
            query = parse_qs(urlsplit(url).query)
            native_id = next((query[k][0] for k in ("reviewid", "review_id", "hrid") if query.get(k)), None)
            # Do not use content hashes: edits must not become another alert.
            if not native_id and not name:
                continue
            identity = native_id or f"{name}|{review['review_date']}"
            key = hashlib.sha256(f"{platform}|{domain(listing)}|{identity}".encode()).hexdigest()
            result[key] = {"key": key, "source": platform, "review_date": review["review_date"],
                           "rating": review.get("rating"), "url": url,
                           "text": review_text, "reviewer_name": review.get("reviewer_name")}
    return sorted(result.values(), key=lambda r: (r["review_date"], r["key"]))


def potential_leader(contact, firm_domain):
    email = str(contact.email or "").strip().lower()
    if not has_usable_email(email) or email.rsplit("@", 1)[-1] != firm_domain:
        return None
    if not contact.full_name or "@" in contact.full_name or classify_email_quality(email, contact.full_name) != "direct_named_email":
        return None
    # Reuse the established contact policy; do not equate the broad coo_ops
    # persona (which includes administrators) with an actual COO.
    title = contact.research_title or contact.title or ""
    role, _ = classify_persona(title, contact.source)
    if role not in {"founder_owner", "managing_partner", "coo"} and getattr(contact, "persona", None) not in {"founder_owner", "managing_partner", "coo_ops"}:
        return None
    return title


def leader_candidate(contact, firm_domain, decisions):
    title = potential_leader(contact, firm_domain)
    decision = decisions.get(title, {})
    if decision.get("confidence", 0) < 90:
        return None
    role = decision.get("role")
    rank = {"founder_owner": 0, "managing_partner": 1, "coo": 2}.get(role)
    if rank is None or not decision.get("evidence") or decision["evidence"] not in title:
        return None
    return (rank, contact.email.strip().lower(), contact.id)


async def classify_leader_titles():
    from collections import Counter
    from app.services.llm_gateway import call_skill_json, prompt_cache_metrics
    config = await settings()
    decisions = dict(config.get("title_decisions") or {})
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(FirmContactRow, PifFirmRow.canonical_website).join(
            PifFirmRow, PifFirmRow.id == FirmContactRow.pif_id).where(
            PifFirmRow.entity_type == "pi_law_firm", PifFirmRow.canonical_website.is_not(None),
            FirmContactRow.email.is_not(None),
            or_(FirmContactRow.title.is_not(None), FirmContactRow.research_title.is_not(None)),
        ))).all()
    counts = Counter(title for c, website in rows if (title := potential_leader(c, domain(website))) and title not in decisions)
    titles = [t for t, _ in counts.most_common(50)]
    if not titles:
        return 0
    result = await call_skill_json(skill_path="app/skills/review-alert-leader-titles/SKILL.md",
        payload={"titles": [{"id": str(i), "title": title} for i, title in enumerate(titles)]},
        required_fields=["decisions"], model="openclaw/main", timeout_s=180,
        max_tokens=6500, retries=1, prompt_cache_key="possibleos:review-alert-leader-titles:v1",
        lane=os.getenv("OPENCLAW_RPC_BATCH_LANE", "possibleos-batch"), allow_tools=False)
    raw = result.parsed["decisions"]
    if not isinstance(raw, list):
        raise ValueError("Leader title classifier returned invalid decisions")
    by_id = {}
    for item in raw:
        if not isinstance(item, dict) or str(item.get("id")) in by_id:
            raise ValueError("Duplicate or invalid leader classification")
        by_id[str(item.get("id"))] = item
    for i, title in enumerate(titles):
        item = by_id.get(str(i))
        if not item or item.get("role") not in {"founder_owner", "managing_partner", "coo", "other", "unknown"}:
            raise ValueError("Missing or invalid leader role")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 100:
            raise ValueError("Invalid leader confidence")
        evidence = item.get("evidence")
        if item["role"] in {"founder_owner", "managing_partner", "coo"} and (not isinstance(evidence, str) or not evidence or evidence not in title):
            raise ValueError("Leader evidence is not an exact substring of the stored title")
        decisions[title] = {**item, "model": result.model, "classified_at": now().isoformat()}
    await configure({"title_decisions": decisions, "last_title_classification": {
        "count": len(titles), "remaining": len(counts) - len(titles),
        "usage": getattr(result, "usage", None), "raw_response": result.raw_response,
        "prompt_cache_metrics": prompt_cache_metrics(getattr(result, "usage", None)),
        "finished_at": now().isoformat(),
    }})
    return len(counts) - len(titles)


async def settings():
    async with AsyncSessionLocal() as session:
        data = await session.scalar(select(SystemSettingsRow.agent_config).where(SystemSettingsRow.id == 1))
    return {**DEFAULTS, **((data or {}).get(KEY) or {})}


async def configure(changes):
    async with AsyncSessionLocal() as session:
        row = await session.get(SystemSettingsRow, 1, with_for_update=True)
        config = dict(row.agent_config or {})
        config[KEY] = {**DEFAULTS, **config.get(KEY, {}), **changes}
        row.agent_config = config
        await session.commit()
    return config[KEY]


def readiness(config):
    from app.services.email_notification_service import _choose_email_transport, _resolve_sender_address
    from app.services.inbound_email import inbound_email_config
    reasons = []
    if not config.get("postal_address", "").strip():
        reasons.append("Business postal address is required")
    inbox = inbound_email_config()
    if not inbox.configured:
        reasons.append("Reply mailbox is not configured")
    try:
        sender = _resolve_sender_address(config.get("sender") or inbox.user)
        actual_sender = os.getenv("ZOHO_MAIL_FROM_ADDRESS", "").strip() or sender
        if parseaddr(actual_sender)[1].lower() != inbox.user.lower():
            reasons.append("Sender must be the monitored reply mailbox")
        if _choose_email_transport() != "zoho_api":
            reasons.append("Zoho API transport is required; automatic transport fallback is disabled")
    except RuntimeError as exc:
        reasons.append(str(exc))
    return reasons


async def suppression(session, pif_id, email):
    observation = await session.scalar(select(LeadGenObservationRow.id).outerjoin(
        FirmContactRow, FirmContactRow.id == LeadGenObservationRow.contact_id
    ).where(LeadGenObservationRow.classified_outcome.in_(NEGATIVE), or_(
        LeadGenObservationRow.pif_id == pif_id,
        func.lower(FirmContactRow.email) == email,
        func.lower(LeadGenObservationRow.raw_event_json["from_email"].astext) == email,
        func.lower(LeadGenObservationRow.raw_event_json["recipient_email"].astext) == email,
    )).limit(1))
    if observation:
        return "Existing negative reply, opt-out, or bounce"
    bounced = await session.scalar(select(EmailLogRow.id).where(
        func.lower(EmailLogRow.recipient_email) == email,
        EmailLogRow.status.in_(["bounced", "complained", "suppressed"])).limit(1))
    return "Bounced or complained address" if bounced else None


async def enroll(*, dry_run=True):
    decisions = (await settings()).get("title_decisions") or {}
    selected, skipped = [], 0
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK + 1})
        firms = (await session.scalars(select(PifFirmRow).where(PifFirmRow.entity_type == "pi_law_firm"))).all()
        contacts = (await session.scalars(select(FirmContactRow).where(
            FirmContactRow.pif_id.in_([f.id for f in firms]), FirmContactRow.email.is_not(None),
            or_(FirmContactRow.title.is_not(None), FirmContactRow.research_title.is_not(None)),
        ))).all()
        by_firm = {}
        for contact in contacts:
            by_firm.setdefault(contact.pif_id, []).append(contact)
        existing = (await session.scalars(select(ReviewAlertSubscriptionRow))).all()
        ids = {s.pif_id for s in existing}
        domains = {s.domain for s in existing}
        emails = {s.recipient_email for s in existing}
        for firm in sorted(firms, key=lambda f: (-(f.icp_score or 0), f.id)):
            host = domain(firm.canonical_website)
            if not host or firm.id in ids or host in domains or (firm.source_json or {}).get("merged_into"):
                skipped += 1
                continue
            potential = [c for c in by_firm.get(firm.id, []) if potential_leader(c, host)]
            # Do not enroll a lower-ranked person before a possible founder is classified.
            if any(potential_leader(c, host) not in decisions for c in potential):
                skipped += 1
                continue
            candidates = [(leader_candidate(c, host, decisions), c) for c in potential]
            candidates = sorted((x for x in candidates if x[0]), key=lambda x: x[0])
            if not candidates:
                skipped += 1
                continue
            # Never move to another leader to evade a suppression.
            rank, contact = candidates[0]
            email = rank[1]
            if email in emails or await suppression(session, firm.id, email):
                skipped += 1
                continue
            item = dict(pif_id=firm.id, domain=host, firm_name=firm.firm_name,
                        contact_id=contact.id, recipient_email=email, recipient_name=contact.full_name,
                        title=contact.research_title or contact.title or "", status="active")
            selected.append(item)
            domains.add(host)
            emails.add(email)
            if not dry_run:
                session.add(ReviewAlertSubscriptionRow(**item))
        if not dry_run:
            await session.commit()
    return {"dry_run": dry_run, "selected": len(selected), "skipped": skipped, "firms": selected}


def compose(subscription, reviews, config, *, standard_lead_gen=False):
    first_name = subscription.recipient_name.split()[0]
    subject = f"New public review{'s' if len(reviews) != 1 else ''} for {subscription.firm_name}"
    lines = [f"Hi {first_name},", "", f"I found {len(reviews)} recent public review{'s' if len(reviews) != 1 else ''} for {subscription.firm_name}:", ""]
    for review in reviews:
        review_text = review.get("text")
        if not isinstance(review_text, str) or not review_text.strip():
            raise ValueError("Review text is missing; refresh the review evidence before composing")
        rating = f"{review['rating']:g}/5" if isinstance(review.get("rating"), (int, float)) else "Rating unavailable"
        lines.append(f"{review['source'].title()} | {rating} | Posted {review['review_date']}")
        if review.get("reviewer_name"):
            lines.append(f"Reviewer: {review['reviewer_name']}")
        lines.extend(["", f'"{review_text}"', "", f"Source: {review['url']}", ""])
    lines += ["Your response matters too: prospective clients read how a firm replies, not just the review. "
              "If you haven't replied yet, thank the reviewer personally. For critical feedback, acknowledge the concern "
              "professionally and invite a private conversation rather than arguing publicly. Keep client and case "
              "details out of public replies.", "",
              "Would a heads-up like this be useful? I'd appreciate your feedback.", "",
              "To stop these emails, just reply to this email asking me to stop. No form or login needed.", "",
              "Regards,", "Pranav", "Founder, Possible Minds", "https://getpossibleminds.com", "",
              "Business outreach from Possible Minds."]
    if config.get("postal_address"):
        lines.append(config["postal_address"])
    elif not standard_lead_gen:
        lines.append("[Business postal address required before sending]")
    return subject, "\n".join(lines)


async def set_subscription(pif_id, status):
    if status not in {"active", "paused", "unsubscribed"}:
        raise ValueError("Invalid subscription status")
    async with AsyncSessionLocal() as session:
        sub = await session.get(ReviewAlertSubscriptionRow, pif_id, with_for_update=True)
        if not sub:
            raise ValueError("Subscription not found")
        if sub.status == "unsubscribed" and status == "active":
            raise ValueError("Unsubscribed firms require fresh documented consent; automatic re-enrollment is blocked")
        if status == "active" and await suppression(session, pif_id, sub.recipient_email):
            raise ValueError("Recipient is suppressed")
        sub.status, sub.reason, sub.updated_at = status, "Operator update", now()
        if status != "active":
            await session.execute(update(ReviewAlertDeliveryRow).where(
                ReviewAlertDeliveryRow.pif_id == pif_id, ReviewAlertDeliveryRow.status == "queued"
            ).values(status="cancelled", error=f"Subscription {status}"))
        await session.commit()


async def pause_replies():
    """Pause all matching senders before running any potentially slow classifier."""
    pending = []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(InboundEmailRow, ReviewAlertSubscriptionRow).join(
            ReviewAlertSubscriptionRow, func.lower(InboundEmailRow.from_email) == ReviewAlertSubscriptionRow.recipient_email
        ).outerjoin(ReviewAlertReplyRow, ReviewAlertReplyRow.inbound_id == InboundEmailRow.id).where(
            ReviewAlertReplyRow.inbound_id.is_(None),
            InboundEmailRow.received_at >= ReviewAlertSubscriptionRow.created_at,
        ))).all()
        for reply, sub in rows:
            sub.status = "paused" if sub.status != "unsubscribed" else sub.status
            sub.reason = "Incoming email received; waiting for review"
            sub.updated_at = now()
            session.add(ReviewAlertReplyRow(inbound_id=reply.id, pif_id=sub.pif_id, outcome="needs_human_review"))
            await session.execute(update(ReviewAlertDeliveryRow).where(
                ReviewAlertDeliveryRow.pif_id == sub.pif_id, ReviewAlertDeliveryRow.status == "queued"
            ).values(status="cancelled", error="Incoming reply"))
            pending.append((reply, sub))
        await session.commit()
    from app.services.lead_feedback_classifier import classify_feedback_event
    from app.services.lead_gen_cybernetic import record_observation
    for reply, sub in pending[:20]:
        try:
            decision = await asyncio.wait_for(classify_feedback_event(
                event_type="email_reply", raw_event={"subject": reply.subject, "body_text": reply.body_text, "from_email": reply.from_email},
                contact={"id": sub.contact_id, "name": sub.recipient_name, "email": sub.recipient_email},
                firm={"pif_id": sub.pif_id, "firm_name": sub.firm_name}, model="openclaw/main",
            ), timeout=45)
            async with AsyncSessionLocal() as session:
                row = await session.get(ReviewAlertReplyRow, reply.id)
                row.outcome, row.decision = decision.outcome, asdict(decision)
                if decision.outcome in NEGATIVE or decision.next_action in {"mark_do_not_contact", "suppress_email"}:
                    current = await session.get(ReviewAlertSubscriptionRow, sub.pif_id)
                    current.status, current.reason = "unsubscribed", decision.reasoning
                await session.commit()
            await record_observation(event_type="email_reply", raw_event={"from_email": reply.from_email,
                                     "subject": reply.subject, "pif_id": sub.pif_id, "inbound_email_id": reply.id},
                                     contact_id=sub.contact_id, classification=decision, infer_batch_from_contact=False)
        except Exception as exc:
            async with AsyncSessionLocal() as session:
                row = await session.get(ReviewAlertReplyRow, reply.id)
                row.decision = {"error": str(exc)[:500], "held": True}
                await session.commit()
    return len(pending)


async def prepare(config):
    created = 0
    today = now().date()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(ReviewAlertSubscriptionRow, FirmReviewRow).join(
            FirmReviewRow, FirmReviewRow.pif_id == ReviewAlertSubscriptionRow.pif_id
        ).where(ReviewAlertSubscriptionRow.status == "active"))).all()
        for sub, corpus in rows:
            if await suppression(session, sub.pif_id, sub.recipient_email):
                sub.status, sub.reason = "paused", "Existing suppression"
                continue
            exists = await session.scalar(select(ReviewAlertDeliveryRow.id).where(
                ReviewAlertDeliveryRow.pif_id == sub.pif_id, ReviewAlertDeliveryRow.day == today.isoformat()))
            if exists:
                continue
            seen = set((await session.scalars(select(ReviewAlertItemRow.review_key).where(ReviewAlertItemRow.pif_id == sub.pif_id))).all())
            reviews = [r for r in eligible_reviews(corpus.reviews_json, today) if r["key"] not in seen][:10]
            if not reviews:
                continue
            subject, body = compose(sub, reviews, config, standard_lead_gen=config.get("delivery_mode") == "lead_gen")
            delivery = ReviewAlertDeliveryRow(id=uuid.uuid4().hex, pif_id=sub.pif_id, day=today.isoformat(),
                recipient_email=sub.recipient_email, recipient_name=sub.recipient_name, subject=subject, body=body, reviews=reviews)
            session.add(delivery)
            await session.flush()
            for review in reviews:
                session.add(ReviewAlertItemRow(pif_id=sub.pif_id, review_key=review["key"], delivery_id=delivery.id))
            created += 1
        await session.commit()
    return created


async def send_one(delivery_id):
    from app.services.email_notification_service import _send_email
    from app.services.inbound_email import inbound_email_config
    async with AsyncSessionLocal() as session:
        delivery = await session.get(ReviewAlertDeliveryRow, delivery_id, with_for_update=True)
        if not delivery or delivery.status != "queued":
            return "skipped"
        config = await settings()
        sub = await session.get(ReviewAlertSubscriptionRow, delivery.pif_id, with_for_update=True)
        firm = await session.get(PifFirmRow, delivery.pif_id)
        contact = await session.get(FirmContactRow, sub.contact_id) if sub else None
        reason = None
        if not config["enabled"] or not config["auto_send"] or readiness(config):
            return "held"
        if not sub or sub.status != "active" or sub.recipient_email != delivery.recipient_email:
            reason = "Subscription is no longer active"
        elif not firm or (firm.source_json or {}).get("merged_into") or domain(firm.canonical_website) != sub.domain:
            reason = "Canonical firm identity changed"
        elif not contact or not leader_candidate(contact, sub.domain, config.get("title_decisions") or {}) or contact.email.lower() != delivery.recipient_email:
            reason = "Leader contact needs revalidation"
        elif await suppression(session, sub.pif_id, sub.recipient_email):
            reason = "Recipient suppressed"
        elif await session.scalar(select(InboundEmailRow.id).where(
            func.lower(InboundEmailRow.from_email) == sub.recipient_email,
            InboundEmailRow.received_at >= sub.created_at).limit(1)):
            reason = "Reply received; operator review required"
        if reason:
            delivery.status, delivery.error = "cancelled", reason
            await session.commit()
            return "cancelled"
        cutoff = datetime.combine(now().date(), datetime.min.time(), tzinfo=timezone.utc)
        used = await session.scalar(select(func.count()).select_from(ReviewAlertDeliveryRow).where(
            ReviewAlertDeliveryRow.started_at >= cutoff,
            ReviewAlertDeliveryRow.status.in_(["sending", "sent", "uncertain"])))
        if used >= config["daily_limit"]:
            return "held"
        if await session.scalar(select(ReviewAlertDeliveryRow.id).where(
            ReviewAlertDeliveryRow.pif_id == delivery.pif_id,
            ReviewAlertDeliveryRow.started_at > now() - timedelta(hours=24),
            ReviewAlertDeliveryRow.status.in_(["sending", "sent", "uncertain"])).limit(1)):
            return "held"
        fresh = [r for r in delivery.reviews if recent_date(r["review_date"], now().date())]
        if not fresh:
            delivery.status, delivery.error = "cancelled", "Reviews aged out of the 14-day window"
            await session.commit()
            return "cancelled"
        delivery.subject, delivery.body = compose(sub, fresh, config)
        delivery.status, delivery.started_at = "sending", now()
        # Comms is created transactionally BEFORE calling the provider.
        log_id = hashlib.sha256(f"review_alert:{delivery.id}".encode()).hexdigest()
        session.add(EmailLogRow(id=log_id, pif_id=sub.pif_id, firm_name=sub.firm_name,
            recipient_email=delivery.recipient_email, recipient_name=delivery.recipient_name,
            subject=delivery.subject, body_excerpt=delivery.body, message_type="review_alert", transport="zoho_api",
            source_type="review_alert", source_id=delivery.id, status="sending"))
        await session.commit()
    try:
        message_id = await asyncio.to_thread(_send_email, delivery.subject, delivery.body,
            to=delivery.recipient_email, recipient_name=delivery.recipient_name, pif_id=delivery.pif_id,
            message_type="review_alert", transport="zoho_api", from_addr=config.get("sender") or inbound_email_config().user,
            source_type="review_alert", source_id=delivery.id, firm_name=sub.firm_name)
        if not message_id or message_id.startswith("zoho-api:"):
            raise RuntimeError("Provider returned no durable message ID; Sent verification required")
        status, error = "sent", None
    except Exception as exc:
        # A timeout may occur AFTER provider acceptance. Never automatically retry.
        message_id, status, error = None, "uncertain", str(exc)[:1000]
    async with AsyncSessionLocal() as session:
        current = await session.get(ReviewAlertDeliveryRow, delivery.id)
        current.status, current.error, current.message_id = status, error, message_id
        current.sent_at = now() if status == "sent" else None
        log = await session.get(EmailLogRow, log_id)
        log.status, log.error, log.message_id = status, error, message_id
        await session.commit()
    return status


async def run_once():
    async with async_engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK})
        await connection.commit()
        if not acquired:
            return {"status": "already_running"}
        result = {"status": "running", "started_at": now().isoformat(), "prepared": 0, "sent": 0}
        try:
            await configure({"last_run": result, "run_requested": False})
            config = await settings()
            if config.get("enrollment_requested"):
                try:
                    remaining = await classify_leader_titles()
                    enrollment = await enroll(dry_run=False)
                    await configure({"enrollment_requested": remaining > 0, "last_enrollment": {
                        "enrolled": enrollment["selected"], "titles_remaining": remaining, "finished_at": now().isoformat()}})
                    result["enrolled"] = enrollment["selected"]
                except Exception as exc:
                    result["enrollment_error"] = str(exc)[:1000]
                config = await settings()
            # A previous process died after claiming a send. Surface uncertainty,
            # never requeue it or imply that a recipient received the message.
            async with AsyncSessionLocal() as session:
                stale = (await session.scalars(select(ReviewAlertDeliveryRow).where(
                    ReviewAlertDeliveryRow.status == "sending",
                    ReviewAlertDeliveryRow.lead_gen_action_id.is_(None),
                ))).all()
                for row in stale:
                    row.status, row.error = "uncertain", "Interrupted during provider send; inspect Sent before taking any action"
                    await session.execute(update(EmailLogRow).where(EmailLogRow.source_type == "review_alert", EmailLogRow.source_id == row.id).values(status="uncertain", error=row.error))
                await session.commit()
            result["prepared"] = await prepare(config)
            await pause_replies()
            result["blockers"] = [] if config.get("delivery_mode") == "lead_gen" else readiness(config)
            async with AsyncSessionLocal() as session:
                previously_attempted = bool(await session.scalar(select(ReviewAlertDeliveryRow.id).where(
                    ReviewAlertDeliveryRow.started_at.is_not(None)).limit(1)))
            from app.services.review_alert_lead_gen import sync_linked_actions, mailbox_check, run_automatic_schedule
            if config.get("auto_schedule") and config.get("delivery_mode") == "lead_gen":
                try:
                    automatic = await run_automatic_schedule(config)
                    if automatic is not None:
                        result["auto_schedule"] = automatic
                except Exception as exc:
                    result["auto_schedule_error"] = str(exc)[:1000]
                config = await settings()
            linked_pending = await sync_linked_actions()
            can_send = config["enabled"] and config["auto_send"] and config.get("delivery_mode") != "lead_gen" and not result["blockers"]
            # Disabling new alerts must not disable handling opt-outs to old ones.
            if can_send or previously_attempted or linked_pending:
                result["replies"] = await mailbox_check()
            if can_send:
                async with AsyncSessionLocal() as session:
                    ids = (await session.scalars(select(ReviewAlertDeliveryRow.id).where(ReviewAlertDeliveryRow.status == "queued").order_by(ReviewAlertDeliveryRow.created_at).limit(100))).all()
                attempts = 0
                for delivery_id in ids:
                    outcome = await send_one(delivery_id)
                    result[outcome] = result.get(outcome, 0) + 1
                    attempts += int(outcome in {"sent", "uncertain"})
                    if attempts >= 5:
                        break
            result["status"] = "partial" if any(result.get(key) for key in (
                "enrollment_error", "auto_schedule_error")) else "completed"
        except Exception as exc:
            logger.exception("Review alert cycle failed; sends held")
            result.update(status="failed", error=str(exc)[:1000])
        finally:
            result["finished_at"] = now().isoformat()
            try:
                await configure({"last_run": result})
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK})
                await connection.commit()
        return result


def row_dict(row):
    return {column.name: (value.isoformat() if isinstance(value := getattr(row, column.name), datetime) else value)
            for column in row.__table__.columns}


async def status():
    config = await settings()
    async with AsyncSessionLocal() as session:
        subscriptions = (await session.scalars(select(ReviewAlertSubscriptionRow).order_by(ReviewAlertSubscriptionRow.firm_name))).all()
        review_checks = {
            row.pif_id: row.last_review_researched_at
            for row in (await session.execute(select(
                FirmReviewRow.pif_id,
                FirmReviewRow.last_review_researched_at,
            ))).all()
        }
        deliveries = (await session.scalars(select(ReviewAlertDeliveryRow).order_by(ReviewAlertDeliveryRow.created_at.desc()).limit(200))).all()
        counts = dict((await session.execute(select(ReviewAlertDeliveryRow.status, func.count()).group_by(ReviewAlertDeliveryRow.status))).all())
    blockers = readiness(config)
    if config.get("delivery_mode") == "lead_gen":
        blockers = []
    subscription_rows = []
    for subscription in subscriptions:
        item = row_dict(subscription)
        checked_at = review_checks.get(subscription.pif_id)
        item["last_review_researched_at"] = checked_at.isoformat() if checked_at else None
        subscription_rows.append(item)
    return {"config": config, "blockers": blockers, "counts": counts,
            "review_collection": {"mode": "nightly_profile_maintenance", "window_days": 14},
            "subscriptions": subscription_rows, "deliveries": [row_dict(d) for d in deliveries]}


async def review_alert_loop():
    await asyncio.sleep(30)
    while True:
        try:
            config = await settings()
            async with AsyncSessionLocal() as session:
                previously_attempted = bool(await session.scalar(select(ReviewAlertDeliveryRow.id).where(
                    ReviewAlertDeliveryRow.started_at.is_not(None)).limit(1)))
            if config["enabled"] or config.get("run_requested") or config.get("enrollment_requested") or previously_attempted:
                await run_once()
        except Exception:
            logger.exception("Review alerts loop error")
        await asyncio.sleep(300)
