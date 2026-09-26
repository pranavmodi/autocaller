"""Schedule review notifications through the existing lead-gen draft/action system."""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text

from app.db import AsyncSessionLocal, async_engine
from app.db.models import AgentActionRow, EmailLogRow, FirmContactRow, InboundEmailRow, LeadGenBatchRow, PifFirmRow, ReviewAlertDeliveryRow, ReviewAlertSubscriptionRow
from app.services import review_alerts as alerts

PT = ZoneInfo("America/Los_Angeles")
PENDING = {"proposed", "waiting_for_approval", "approved", "queued", "running"}


def oldest_review(delivery):
    return min((r["review_date"] for r in delivery.reviews), default="9999-12-31")


def automatic_start(config, current=None):
    """Return today's next safe automatic slot, or None when not due."""
    current = current or alerts.now()
    local = current.astimezone(PT)
    if not config.get("enabled") or not config.get("auto_schedule") or config.get("delivery_mode") != "lead_gen":
        return None
    today = local.date().isoformat()
    if config.get("last_auto_schedule_day") == today:
        return None
    retry_at = config.get("auto_schedule_retry_at")
    if retry_at:
        try:
            if datetime.fromisoformat(retry_at) > current:
                return None
        except ValueError:
            pass
    try:
        configured = time.fromisoformat(str(config.get("auto_schedule_time") or "09:15"))
    except ValueError as exc:
        raise ValueError("Automatic review schedule time must be HH:MM") from exc
    due = datetime.combine(local.date(), configured, tzinfo=PT)
    if local < due:
        return None
    candidate = max(due, local + timedelta(minutes=15))
    minute = ((candidate.minute + 4) // 5) * 5
    if minute == 60:
        candidate = candidate.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        candidate = candidate.replace(minute=minute, second=0, microsecond=0)
    if candidate.date() != local.date():
        raise ValueError("No safe review-alert send slot remains today")
    return candidate.astimezone(timezone.utc)


async def run_automatic_schedule(config):
    start_at = automatic_start(config)
    if start_at is None:
        return None
    today = start_at.astimezone(PT).date().isoformat()
    try:
        result = await schedule(limit=int(config.get("auto_schedule_limit") or 20), start_at=start_at,
                                actor="review-alerts-auto", automatic=True)
    except Exception as exc:
        await alerts.configure({
            "last_auto_schedule_error": str(exc)[:1000],
            "last_auto_schedule_attempt_at": alerts.now().isoformat(),
            "auto_schedule_retry_at": (alerts.now() + timedelta(minutes=30)).isoformat(),
        })
        raise
    await alerts.configure({
        "last_auto_schedule_day": today,
        "last_auto_schedule_at": alerts.now().isoformat(),
        "last_auto_schedule_error": None,
        "auto_schedule_retry_at": None,
        "last_auto_schedule": result,
    })
    return result


async def mailbox_check():
    from app.services.inbound_email import ingest_zoho_inbox
    result = await asyncio.wait_for(ingest_zoho_inbox(limit=2000, unseen_only=False, since_days=14, mark_seen=False), timeout=120)
    if result["fetched"] >= 2000:
        raise ValueError("Inbox scan saturated; scheduling and sending held")
    count = await alerts.pause_replies()
    await alerts.configure({"mailbox_checked_at": alerts.now().isoformat()})
    return count


def reply_readiness(transport):
    import os
    from email.utils import parseaddr
    from app.services.inbound_email import inbound_email_config
    from app.services.email_notification_service import _resolve_sender_address
    inbox = inbound_email_config()
    if not inbox.configured:
        return "Reply mailbox not configured"
    if transport == "resend":
        reply_to = os.getenv("REPLY_TO_EMAIL", "") or _resolve_sender_address()
    elif transport == "zoho_api":
        reply_to = os.getenv("ZOHO_MAIL_FROM_ADDRESS", "") or _resolve_sender_address()
    else:
        return "Review alerts require Resend or Zoho API"
    if parseaddr(reply_to)[1].lower() != inbox.user.lower():
        return "The lead-gen reply-to address must match the monitored mailbox"
    return None


async def conflict(session, delivery, sub, start, end, exclude_action=None):
    recipient = delivery.recipient_email
    matching = or_(AgentActionRow.input_json["pif_id"].astext == sub.pif_id,
                   AgentActionRow.input_json["to"].astext == recipient,
                   AgentActionRow.input_json["to"].astext.ilike(f"%@{sub.domain}"))
    existing = await session.scalar(select(AgentActionRow.id).where(
        AgentActionRow.action_type.in_(["send_email", "send_approved_lead_gen_draft"]),
        matching, AgentActionRow.status.in_(PENDING),
        AgentActionRow.id != (exclude_action or ""),
    ).limit(1))
    if existing:
        return f"Another pending email for this firm: {existing}"
    sent = await session.scalar(select(EmailLogRow.id).where(
        or_(EmailLogRow.pif_id == sub.pif_id, EmailLogRow.recipient_email.ilike(f"%@{sub.domain}")),
        EmailLogRow.sent_at >= start, EmailLogRow.sent_at < end,
        EmailLogRow.status.in_(["sent", "delivered", "sending", "uncertain"]),
    ).limit(1))
    return "Firm already contacted today" if sent else None


async def action_guard(session, action):
    payload = action.input_json or {}
    delivery = await session.get(ReviewAlertDeliveryRow, payload.get("review_alert_delivery_id"))
    if not delivery or delivery.lead_gen_action_id != action.id or delivery.status != "scheduled":
        return "Review alert is not scheduled for this action"
    if delivery.lead_gen_item_id != payload.get("batch_item_id") or delivery.recipient_email != payload.get("to"):
        return "Review alert recipient or batch linkage changed"
    sub = await session.get(ReviewAlertSubscriptionRow, delivery.pif_id)
    if not sub or sub.status != "active" or sub.recipient_email != delivery.recipient_email:
        return "Subscription paused, unsubscribed, or changed"
    firm = await session.get(PifFirmRow, sub.pif_id)
    contact = await session.get(FirmContactRow, sub.contact_id)
    config = await alerts.settings()
    if not firm or (firm.source_json or {}).get("merged_into") or alerts.domain(firm.canonical_website) != sub.domain:
        return "Firm identity changed"
    if not contact or not alerts.leader_candidate(contact, sub.domain, config.get("title_decisions") or {}):
        return "Leader no longer verified"
    if contact.email.strip().lower() != delivery.recipient_email:
        return "Leader email changed"
    when = max(action.scheduled_for or alerts.now(), alerts.now())
    if not delivery.reviews or not all(alerts.recent_date(r["review_date"], when.date()) for r in delivery.reviews):
        return "Review has left the 14-day window"
    if not all(r["url"] in (payload.get("body") or "") for r in delivery.reviews):
        return "Draft no longer contains its review source links"
    if await alerts.suppression(session, sub.pif_id, sub.recipient_email):
        return "Existing opt-out, negative reply, or bounce"
    if await session.scalar(select(InboundEmailRow.id).where(
        InboundEmailRow.from_email == sub.recipient_email, InboundEmailRow.received_at >= sub.created_at).limit(1)):
        return "Reply received; operator review required"
    try:
        checked = datetime.fromisoformat(config.get("mailbox_checked_at") or "")
        if checked < alerts.now() - timedelta(minutes=10):
            return "Reply mailbox check is stale"
    except ValueError:
        return "Reply mailbox has not been checked"
    transport = payload.get("transport")
    if reason := reply_readiness(transport):
        return reason
    local = when.astimezone(PT)
    start = datetime.combine(local.date(), datetime.min.time(), tzinfo=PT).astimezone(timezone.utc)
    return await conflict(session, delivery, sub, start, start + timedelta(days=1), exclude_action=action.id)


async def claim(action_id, delivery_id):
    async with AsyncSessionLocal() as session:
        delivery = await session.get(ReviewAlertDeliveryRow, delivery_id, with_for_update=True)
        action = await session.get(AgentActionRow, action_id or (delivery.lead_gen_action_id if delivery else None))
        if not action or (reason := await action_guard(session, action)):
            raise ValueError(reason if action else "Action missing")
        delivery.subject = action.input_json["subject"]
        delivery.body = action.input_json["body"]
        delivery.status, delivery.started_at = "sending", alerts.now()
        await session.commit()


async def finish(delivery_id, *, message_id=None, error=None):
    async with AsyncSessionLocal() as session:
        delivery = await session.get(ReviewAlertDeliveryRow, delivery_id)
        delivery.status = "uncertain" if error else "sent"
        delivery.error, delivery.message_id = error, message_id
        delivery.sent_at = alerts.now() if not error else None
        if error:
            from sqlalchemy import update
            await session.execute(update(EmailLogRow).where(EmailLogRow.source_type == "review_alert", EmailLogRow.source_id == delivery_id).values(status="uncertain", error=error))
        await session.commit()


async def sync_linked_actions():
    pending = False
    cancel = []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(ReviewAlertDeliveryRow, AgentActionRow, ReviewAlertSubscriptionRow)
            .join(AgentActionRow, AgentActionRow.id == ReviewAlertDeliveryRow.lead_gen_action_id)
            .join(ReviewAlertSubscriptionRow, ReviewAlertSubscriptionRow.pif_id == ReviewAlertDeliveryRow.pif_id)
            .where(ReviewAlertDeliveryRow.status.in_(["scheduled", "sending"])))).all()
        for delivery, action, sub in rows:
            if sub.status != "active" and action.status in PENDING - {"running"}:
                cancel.append(action.id)
            if action.status in {"cancelled", "blocked", "expired", "failed"}:
                delivery.status = "uncertain" if delivery.started_at else "cancelled"
                delivery.error = action.error or f"Lead-gen action {action.status}"
            elif action.status == "succeeded":
                delivery.status, delivery.sent_at = "sent", action.completed_at
            else:
                pending = True
        await session.commit()
    from app.services.action_execution import cancel_action
    for action_id in cancel:
        await cancel_action(action_id, actor="review-alerts", reason="Review-alert subscription paused or unsubscribed")
    return pending


async def schedule(*, limit=20, start_at, actor="operator", dry_run=False, automatic=False):
    from app.services.action_execution import create_send_email_action, check_action_policy, cancel_action
    from app.services.lead_gen_curated import create_curated_batch, add_contacts_to_batch
    from app.services.lead_gen_cybernetic import ensure_default_policy, daily_send_budget_from_policy
    from app.services.lead_gen_transport import choose_lead_gen_transport

    if not 1 <= limit <= 20:
        raise ValueError("Limit must be between 1 and 20")
    if start_at.tzinfo is None or start_at <= alerts.now():
        raise ValueError("Choose a future start time with timezone")
    send_date = start_at.astimezone(PT).date()
    if send_date != alerts.now().astimezone(PT).date():
        raise ValueError("This command schedules today's review alerts only")
    day_start = datetime.combine(send_date, datetime.min.time(), tzinfo=PT).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)
    async with async_engine.connect() as connection:
        # Automatic scheduling runs inside the monitor's primary lock. Its
        # secondary lock prevents duplicate automatic workers without deadlocking.
        lock_key = alerts.LOCK + 3 if automatic else alerts.LOCK
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})
        await connection.commit()
        if not acquired:
            raise ValueError("Review monitor is running; retry after the current cycle completes")
        try:
            if not dry_run:
                await alerts.configure({"delivery_mode": "lead_gen", "auto_send": False})
                await mailbox_check()
                await alerts.prepare(await alerts.settings())
            config = await alerts.settings()
            policy = await ensure_default_policy()
            transport = await choose_lead_gen_transport(policy.weights_json or {}, total_daily_budget=daily_send_budget_from_policy(policy))
            if reason := reply_readiness(transport):
                raise ValueError(reason)
            async with AsyncSessionLocal() as session:
                existing = (await session.scalars(select(ReviewAlertDeliveryRow).where(
                    ReviewAlertDeliveryRow.lead_gen_action_id.is_not(None),
                    ReviewAlertDeliveryRow.scheduled_for >= day_start, ReviewAlertDeliveryRow.scheduled_for < day_end,
                ))).all()
                rows = (await session.execute(select(ReviewAlertDeliveryRow, ReviewAlertSubscriptionRow).join(
                    ReviewAlertSubscriptionRow, ReviewAlertSubscriptionRow.pif_id == ReviewAlertDeliveryRow.pif_id).where(
                    ReviewAlertDeliveryRow.status == "queued", ReviewAlertDeliveryRow.lead_gen_action_id.is_(None),
                    ReviewAlertSubscriptionRow.status == "active"))).all()
                rows = sorted(rows, key=lambda pair: (oldest_review(pair[0]), pair[0].created_at))
                selected, skipped, firms = [], [], set()
                for delivery, sub in rows:
                    if len(existing) + len(selected) >= limit:
                        break
                    when = start_at + timedelta(minutes=5 * len(selected))
                    fresh = sorted((r for r in delivery.reviews if alerts.recent_date(r["review_date"], when.date())), key=lambda r: r["review_date"])
                    reason = None if fresh else "No review remains inside the 14-day window"
                    reason = reason or ("Firm already selected" if sub.domain in firms else None)
                    reason = reason or await alerts.suppression(session, sub.pif_id, sub.recipient_email)
                    reason = reason or await conflict(session, delivery, sub, day_start, day_end)
                    if when >= day_end:
                        reason = "No remaining time today"
                    if reason:
                        skipped.append({"firm": sub.firm_name, "reason": reason})
                        continue
                    selected.append((delivery, sub, when, fresh))
                    firms.add(sub.domain)
            if dry_run:
                return {"dry_run": True, "already_scheduled": len(existing), "eligible": len(selected), "skipped": skipped,
                        "candidates": [{"firm": s.firm_name, "recipient": s.recipient_email, "oldest_review": min(r["review_date"] for r in fresh), "scheduled_for": when.isoformat()} for d, s, when, fresh in selected]}
            batch_name = f"Recent review alerts - {send_date}"
            async with AsyncSessionLocal() as session:
                batch = await session.scalar(select(LeadGenBatchRow).where(LeadGenBatchRow.name == batch_name).order_by(LeadGenBatchRow.created_at).limit(1))
                batch_id = batch.id if batch else None
            if selected and not batch_id:
                batch_id = (await create_curated_batch(batch_name, template_key="possible_minds_dynamic", target_metric="review_alert_feedback", created_by=actor))["id"]
            scheduled = []
            for delivery, sub, when, fresh in selected:
                added = await add_contacts_to_batch(batch_id, [sub.contact_id], actor=actor)
                if not added["item_ids"]:
                    skipped.append({"firm": sub.firm_name, "reason": "Existing batch item requires inspection; not duplicated"})
                    continue
                item_id = added["item_ids"][0]["item_id"]
                subject, body = alerts.compose(sub, fresh, config, standard_lead_gen=True)
                # The send-time guard rejects this action until its alert link
                # is durable. Slots are kept safely in the future during setup.
                action = await create_send_email_action(to=sub.recipient_email, subject=subject, body=body,
                    mode="lead_gen", requested_by=actor, approved_by=actor, contact_id=sub.contact_id,
                    batch_item_id=item_id, pif_id=sub.pif_id, firm_name=sub.firm_name,
                    composer_variant_key="manual", lead_gen_action_type="manual_email", transport=transport,
                    review_alert_delivery_id=delivery.id, scheduled_for=when)
                async with AsyncSessionLocal() as session:
                    current = await session.get(ReviewAlertDeliveryRow, delivery.id, with_for_update=True)
                    current.lead_gen_action_id, current.lead_gen_item_id = action["id"], item_id
                    current.status, current.scheduled_for = "scheduled", when
                    current.subject, current.body, current.reviews = subject, body, fresh
                    await session.commit()
                check = await check_action_policy(action["id"], actor=actor)
                if not check["allowed"]:
                    await cancel_action(action["id"], actor=actor, reason=f"Review alert policy: {check['reason']}")
                    skipped.append({"firm": sub.firm_name, "reason": check["reason"]})
                    continue
                scheduled.append({"firm": sub.firm_name, "recipient": sub.recipient_email, "action_id": action["id"],
                    "batch_item_id": item_id, "oldest_review": min(r["review_date"] for r in fresh),
                    "scheduled_for": when.isoformat(), "policy": "allowed"})
            await sync_linked_actions()
            result = {"batch_id": batch_id, "limit": limit, "already_scheduled": len(existing), "scheduled": scheduled, "skipped": skipped, "transport": transport}
            await alerts.configure({"last_lead_gen_schedule": result})
            return result
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
            await connection.commit()
