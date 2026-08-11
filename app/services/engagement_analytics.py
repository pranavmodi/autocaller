"""Unified recipient engagement analytics across tracked outreach workflows."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import (
    AuditLinkClickRow,
    AuditLinkRow,
    FirmContactRow,
    LeadGenBatchItemRow,
    LeadGenObservationRow,
    PifFirmRow,
)
from app.services.workshop_tracking_analytics import (
    _dedupe_page_events,
    _is_reveal_event,
    _is_scanner_ua,
    _session_quality,
)


SOURCE_META = {
    "ai_audit_email": ("ai_audit", "AI Audit", "email", "Email"),
    "ai_audit_signature": ("ai_audit", "AI Audit", "email", "Email"),
    "consult_email": ("consult", "Consult", "email", "Email"),
    "consult_signature": ("consult", "Consult", "email", "Email"),
    "solution_email": ("solution", "Solution", "email", "Email"),
    "solution_signature": ("solution", "Solution", "email", "Email"),
    "solution_email_automation": (
        "email_automation",
        "Email Automation",
        "email",
        "Email",
    ),
    "solution_client_communication": (
        "client_communication",
        "Client Communication",
        "email",
        "Email",
    ),
    "intake_demo_email": ("intake_demo", "Intake Demo", "email", "Email"),
    "intake_demo_signature": ("intake_demo", "Intake Demo", "email", "Email"),
    "workshop_email": ("workshops", "Workshops", "email", "Email"),
    "workshop_signature": ("workshops", "Workshops", "email", "Email"),
    "workshop_linkedin": ("workshops", "Workshops", "linkedin", "LinkedIn"),
}

EMAIL_EVENT_TYPES = {
    "email_sent",
    "email_delivered",
    "email_delivery_delayed",
    "email_bounce",
    "email_failed",
    "email_suppressed",
    "email_complaint",
    "email_open",
    "email_click",
    "email_reply",
}
FAILURE_EVENT_TYPES = {
    "email_delivery_delayed",
    "email_bounce",
    "email_failed",
    "email_suppressed",
    "email_complaint",
}
MEANINGFUL_PAGE_EVENTS = {"click", "scroll_25", "scroll_50", "scroll_75", "scroll_90"}


def _clean(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _meta(source: str) -> dict[str, str]:
    workflow, workflow_label, channel, channel_label = SOURCE_META[source]
    return {
        "source": source,
        "workflow": workflow,
        "workflow_label": workflow_label,
        "channel": channel,
        "channel_label": channel_label,
    }


def _selected_sources(workflow: str, channel: str) -> set[str]:
    return {
        source
        for source, values in SOURCE_META.items()
        if (workflow == "all" or values[0] == workflow)
        and (channel == "all" or values[2] == channel)
    }


def _review_subject_firm(item: LeadGenBatchItemRow | None) -> str:
    if item is None:
        return ""
    reason = item.reason_json if isinstance(item.reason_json, dict) else {}
    draft = reason.get("agent_draft") if isinstance(reason.get("agent_draft"), dict) else {}
    subject = _clean(draft.get("subject"), 512)
    marker = " submitted a Yelp review about "
    if marker in subject:
        return _clean(subject.split(marker, 1)[1], 255)
    marker = " submitted a Google review about "
    if marker in subject:
        return _clean(subject.split(marker, 1)[1], 255)
    return ""


def _recipient_status(row: dict[str, Any]) -> str:
    if row["replies"]:
        return "Replied"
    if row["meaningful_actions"]:
        return "Engaged"
    if row["confirmed_visits"]:
        return "Visited"
    if row["raw_clicks"]:
        return "Unconfirmed click"
    if row["delivered"]:
        return "Delivered"
    if row["sent"]:
        return "Sent"
    return "Tracked"


def _event_copy(event_type: str) -> tuple[str, str, str]:
    labels = {
        "email_sent": ("Email sent", "The provider accepted the send request", "system"),
        "email_delivered": ("Email delivered", "The recipient server accepted the email", "system"),
        "email_delivery_delayed": ("Delivery delayed", "The provider reported a delivery delay", "system"),
        "email_bounce": ("Email bounced", "The recipient server rejected the email", "system"),
        "email_failed": ("Email failed", "The provider could not deliver the email", "system"),
        "email_suppressed": ("Email suppressed", "The provider suppressed delivery", "system"),
        "email_complaint": ("Spam complaint", "The recipient reported the email", "system"),
        "email_open": ("Email opened", "The provider loaded the tracking pixel", "suspect"),
        "email_click": ("Provider click", "The provider recorded a link click", "suspect"),
        "email_reply": ("Reply received", "The recipient replied to the outreach", "human"),
    }
    return labels.get(event_type, (event_type.replace("_", " ").title(), "", "system"))


def _page_key(raw: dict[str, Any]) -> str:
    return _clean(raw.get("page"), 160).strip("/") or "landing page"


async def engagement_analytics(
    *,
    since_days: int = 30,
    workflow: str = "all",
    channel: str = "all",
    limit: int = 250,
) -> dict[str, Any]:
    if workflow != "all" and workflow not in {values[0] for values in SOURCE_META.values()}:
        raise ValueError(f"unsupported_workflow:{workflow}")
    if channel not in {"all", "email", "linkedin"}:
        raise ValueError(f"unsupported_channel:{channel}")

    sources = _selected_sources(workflow, channel)
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days > 0 else None

    link_stmt = select(AuditLinkRow).where(AuditLinkRow.source.in_(sources))
    click_stmt = select(AuditLinkClickRow).where(AuditLinkClickRow.source.in_(sources))
    observation_stmt = select(LeadGenObservationRow).where(
        LeadGenObservationRow.event_type.in_(EMAIL_EVENT_TYPES | {"page_session"})
    )
    if cutoff:
        click_stmt = click_stmt.where(AuditLinkClickRow.clicked_at >= cutoff)
        observation_stmt = observation_stmt.where(LeadGenObservationRow.created_at >= cutoff)

    async with AsyncSessionLocal() as session:
        links = list((await session.execute(link_stmt)).scalars().all())
        clicks = list((await session.execute(click_stmt)).scalars().all())
        observations = list((await session.execute(observation_stmt)).scalars().all())

        contact_ids = {link.contact_id for link in links}
        item_ids = {link.batch_item_id for link in links if link.batch_item_id}
        contacts = list((await session.execute(
            select(FirmContactRow).where(FirmContactRow.id.in_(contact_ids))
        )).scalars().all()) if contact_ids else []
        items = list((await session.execute(
            select(LeadGenBatchItemRow).where(LeadGenBatchItemRow.id.in_(item_ids))
        )).scalars().all()) if item_ids else []
        pif_ids = {
            value
            for value in [
                *(link.pif_id for link in links),
                *(contact.pif_id for contact in contacts),
                *(item.pif_id for item in items),
            ]
            if value
        }
        firms = list((await session.execute(
            select(PifFirmRow).where(PifFirmRow.id.in_(pif_ids))
        )).scalars().all()) if pif_ids else []

    contact_map = {row.id: row for row in contacts}
    item_map = {row.id: row for row in items}
    firm_map = {row.id: row for row in firms}
    link_by_code = {row.code: row for row in links}
    links_by_item: dict[str, list[AuditLinkRow]] = defaultdict(list)
    links_by_contact: dict[str, list[AuditLinkRow]] = defaultdict(list)
    for link in sorted(links, key=lambda row: row.created_at, reverse=True):
        if link.batch_item_id:
            links_by_item[link.batch_item_id].append(link)
        links_by_contact[link.contact_id].append(link)

    recipients: dict[str, dict[str, Any]] = {}

    def ensure_recipient(link: AuditLinkRow) -> dict[str, Any]:
        contact = contact_map.get(link.contact_id)
        item = item_map.get(link.batch_item_id or "")
        pif_id = link.pif_id or (item.pif_id if item else None) or (contact.pif_id if contact else None)
        firm = firm_map.get(pif_id or "")
        firm_name = (
            _review_subject_firm(item)
            or _clean(item.firm_name if item else None)
            or _clean(firm.firm_name if firm else None)
            or "Unknown firm"
        )
        row = recipients.setdefault(link.contact_id, {
            "contact_id": link.contact_id,
            "contact_name": _clean(contact.full_name if contact else None) or _clean(item.contact_name if item else None) or "Unknown contact",
            "contact_email": _clean(contact.email if contact else None) or _clean(item.contact_email if item else None),
            "title": _clean(contact.title if contact else None) or _clean(item.contact_title if item else None),
            "firm_name": firm_name,
            "pif_id": pif_id,
            "workflows": set(),
            "workflow_labels": set(),
            "channels": set(),
            "channel_labels": set(),
            "tracked_links": 0,
            "sent": 0,
            "delivered": 0,
            "delivery_failures": 0,
            "email_opens": 0,
            "raw_clicks": 0,
            "scanner_or_suspect_clicks": 0,
            "confirmed_visits": 0,
            "meaningful_actions": 0,
            "replies": 0,
            "last_activity_at": None,
            "in_window": False,
        })
        meta = _meta(link.source)
        row["workflows"].add(meta["workflow"])
        row["workflow_labels"].add(meta["workflow_label"])
        row["channels"].add(meta["channel"])
        row["channel_labels"].add(meta["channel_label"])
        return row

    for link in links:
        row = ensure_recipient(link)
        row["tracked_links"] += 1
        if cutoff is None or link.created_at >= cutoff:
            row["in_window"] = True

    activities: list[dict[str, Any]] = []

    def add_activity(
        *,
        activity_id: str,
        link: AuditLinkRow,
        occurred_at: datetime,
        event: str,
        label: str,
        detail: str,
        quality: str,
        page: str = "",
    ) -> None:
        row = ensure_recipient(link)
        row["in_window"] = True
        occurred_iso = _iso(occurred_at)
        if not row["last_activity_at"] or (occurred_iso and occurred_iso > row["last_activity_at"]):
            row["last_activity_at"] = occurred_iso
        activities.append({
            "id": activity_id,
            "contact_id": row["contact_id"],
            "contact_name": row["contact_name"],
            "contact_email": row["contact_email"],
            "firm_name": row["firm_name"],
            "occurred_at": occurred_iso,
            "event": event,
            "label": label,
            "detail": detail,
            "quality": quality,
            "page": page,
            **_meta(link.source),
        })

    for click in clicks:
        candidates = links_by_item.get(click.batch_item_id or "") or links_by_contact.get(click.contact_id, [])
        link = next((candidate for candidate in candidates if candidate.source == click.source), None)
        if link is None:
            continue
        row = ensure_recipient(link)
        quality = "scanner" if _is_scanner_ua(click.user_agent) else "suspect"
        row["raw_clicks"] += 1
        if quality != "human":
            row["scanner_or_suspect_clicks"] += 1
        add_activity(
            activity_id=click.id,
            link=link,
            occurred_at=click.clicked_at,
            event="redirect_click",
            label="Tracked link opened",
            detail="The redirect was fetched; human intent is not confirmed",
            quality=quality,
            page="tracked redirect",
        )

    def link_for_observation(observation: LeadGenObservationRow) -> AuditLinkRow | None:
        raw = observation.raw_event_json or {}
        code = _clean(raw.get("link_code"), 32)
        if code and code in link_by_code:
            return link_by_code[code]
        if observation.event_type == "page_session":
            return None
        candidates = links_by_item.get(observation.batch_item_id or "", [])
        for candidate in candidates:
            if candidate.source in sources and _meta(candidate.source)["channel"] == "email":
                return candidate
        return None

    email_observations: list[tuple[LeadGenObservationRow, AuditLinkRow]] = []
    page_observations: list[tuple[LeadGenObservationRow, AuditLinkRow]] = []
    for observation in observations:
        link = link_for_observation(observation)
        if link is None or link.source not in sources:
            continue
        if observation.event_type == "page_session":
            page_observations.append((observation, link))
        else:
            email_observations.append((observation, link))

    for observation, link in email_observations:
        row = ensure_recipient(link)
        event_type = observation.event_type
        if event_type == "email_sent":
            row["sent"] += 1
        elif event_type == "email_delivered":
            row["delivered"] += 1
        elif event_type in FAILURE_EVENT_TYPES:
            row["delivery_failures"] += 1
        elif event_type == "email_open":
            row["email_opens"] += 1
        elif event_type == "email_reply":
            row["replies"] += 1
        label, detail, quality = _event_copy(event_type)
        add_activity(
            activity_id=observation.id,
            link=link,
            occurred_at=observation.created_at,
            event=event_type,
            label=label,
            detail=detail,
            quality=quality,
            page="email",
        )

    deduped_page_rows = _dedupe_page_events([row for row, _link in page_observations])
    page_link_by_id = {row.id: link for row, link in page_observations}
    sessions: dict[tuple[str, str], list[LeadGenObservationRow]] = defaultdict(list)
    for observation in deduped_page_rows:
        raw = observation.raw_event_json or {}
        session_id = _clean(raw.get("session_id"), 64) or observation.id
        link = page_link_by_id[observation.id]
        sessions[(link.code, session_id)].append(observation)

    session_quality: dict[tuple[str, str], str] = {
        key: _session_quality(rows)
        for key, rows in sessions.items()
    }
    for (code, session_id), rows in sessions.items():
        link = link_by_code[code]
        quality = session_quality[(code, session_id)]
        recipient = ensure_recipient(link)
        if quality == "human":
            recipient["confirmed_visits"] += 1
        max_time = max((int((row.raw_event_json or {}).get("time_on_page_ms") or 0) for row in rows), default=0)
        page = _page_key(rows[-1].raw_event_json or {})
        add_activity(
            activity_id=f"session:{code}:{session_id}",
            link=link,
            occurred_at=max(row.created_at for row in rows),
            event="page_visit",
            label="Confirmed page visit" if quality == "human" else "Unconfirmed page visit",
            detail=f"{round(max_time / 1000, 1)} seconds maximum observed time",
            quality=quality,
            page=page,
        )

    for observation in deduped_page_rows:
        raw = observation.raw_event_json or {}
        event = _clean(raw.get("event"), 64) or "session_ready"
        if event not in MEANINGFUL_PAGE_EVENTS and not _is_reveal_event(event):
            continue
        link = page_link_by_id[observation.id]
        session_id = _clean(raw.get("session_id"), 64) or observation.id
        quality = session_quality.get((link.code, session_id), "suspect")
        row = ensure_recipient(link)
        if quality == "human":
            row["meaningful_actions"] += 1
        if _is_reveal_event(event):
            label = "Content revealed"
            detail = "The recipient revealed gated workshop content"
        elif event.startswith("scroll_"):
            percent = event.split("_", 1)[1]
            label = f"Scrolled {percent}%"
            detail = f"The recipient reached at least {percent}% of the page"
        else:
            label = "Page action"
            text = _clean(raw.get("click_text"), 180) or "Button or link"
            detail = text
        add_activity(
            activity_id=observation.id,
            link=link,
            occurred_at=observation.created_at,
            event=event,
            label=label,
            detail=detail,
            quality=quality,
            page=_page_key(raw),
        )

    recipient_rows = []
    for row in recipients.values():
        if not row.pop("in_window"):
            continue
        row["workflows"] = sorted(row["workflows"])
        row["workflow_labels"] = sorted(row["workflow_labels"])
        row["channels"] = sorted(row["channels"])
        row["channel_labels"] = sorted(row["channel_labels"])
        row["status"] = _recipient_status(row)
        recipient_rows.append(row)
    recipient_rows.sort(key=lambda row: row["last_activity_at"] or "", reverse=True)
    activities.sort(key=lambda row: row["occurred_at"] or "", reverse=True)

    workflow_options = sorted(
        (
            {"key": key, "label": label}
            for key, label in {
                values[0]: values[1]
                for values in SOURCE_META.values()
            }.items()
        ),
        key=lambda row: row["label"],
    )
    return {
        "since_days": since_days,
        "workflow": workflow,
        "channel": channel,
        "filters": {
            "workflows": [{"key": "all", "label": "All workflows"}, *workflow_options],
            "channels": [
                {"key": "all", "label": "All channels"},
                {"key": "email", "label": "Email"},
                {"key": "linkedin", "label": "LinkedIn"},
            ],
        },
        "summary": {
            "tracked_recipients": len(recipient_rows),
            "sent": sum(row["sent"] for row in recipient_rows),
            "delivered": sum(row["delivered"] for row in recipient_rows),
            "delivery_failures": sum(row["delivery_failures"] for row in recipient_rows),
            "raw_clicks": sum(row["raw_clicks"] for row in recipient_rows),
            "scanner_or_suspect_clicks": sum(row["scanner_or_suspect_clicks"] for row in recipient_rows),
            "confirmed_visits": sum(row["confirmed_visits"] for row in recipient_rows),
            "meaningful_actions": sum(row["meaningful_actions"] for row in recipient_rows),
            "replies": sum(row["replies"] for row in recipient_rows),
        },
        "recipients": recipient_rows[:limit],
        "activities": activities[:limit],
    }
