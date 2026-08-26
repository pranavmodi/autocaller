"""Cross-channel campaigns and first-party Possible Minds tracking links."""
from __future__ import annotations

import os
import re
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import desc, func, or_, select

from app.db import AsyncSessionLocal
from app.db.models import (
    EngagementCampaignClickRow,
    EngagementCampaignLinkRow,
    EngagementCampaignRow,
    FirmContactRow,
    LeadGenObservationRow,
    PifFirmRow,
)
from app.services.workshop_tracking_analytics import (
    _dedupe_page_events,
    _is_reveal_event,
    _is_scanner_ua,
    _session_quality,
)


CHANNELS = {"email", "linkedin", "public"}
STATUSES = {"draft", "active", "completed", "archived"}
MEANINGFUL_EVENTS = {"click", "scroll_25", "scroll_50", "scroll_75", "scroll_90"}
TRACKING_LINK_RE = re.compile(
    r"https://(?:www\.)?getpossibleminds\.com/t/([A-Za-z0-9_-]{1,32})"
)


class EngagementCampaignError(ValueError):
    pass


def _clean(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _observed_time_on_page_ms(rows: list[LeadGenObservationRow]) -> int:
    values = []
    for row in rows:
        try:
            values.append(max(0, int((row.raw_event_json or {}).get("time_on_page_ms") or 0)))
        except (TypeError, ValueError):
            continue
    return max(values, default=0)


def _tracking_codes_from_text(value: Any) -> list[str]:
    return list(dict.fromkeys(TRACKING_LINK_RE.findall(str(value or ""))))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def _new_code() -> str:
    return secrets.token_urlsafe(7).rstrip("=")


def validate_destination_url(value: str) -> str:
    raw = _clean(value, 2048)
    if not raw:
        raise EngagementCampaignError("destination_url_required")
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise EngagementCampaignError("destination_must_be_https")
    if host != "getpossibleminds.com" and not host.endswith(".getpossibleminds.com"):
        raise EngagementCampaignError("destination_must_be_possible_minds")
    if not parsed.path:
        parsed = parsed._replace(path="/")
    return urlunsplit(parsed)


def tracking_url(code: str) -> str:
    base = (
        os.getenv("CAMPAIGN_TRACKING_BASE_URL", "").strip().rstrip("/")
        or "https://getpossibleminds.com"
    )
    return f"{base}/t/{code}"


def tracked_destination(
    link: EngagementCampaignLinkRow,
    campaign: EngagementCampaignRow,
    click_id: str,
) -> str:
    parsed = urlsplit(link.destination_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["lc"] = link.code
    params["c"] = click_id
    params.setdefault("utm_source", "possibleos")
    params.setdefault(
        "utm_medium",
        {"email": "email", "linkedin": "linkedin_dm", "public": "referral"}[link.channel],
    )
    params.setdefault("utm_campaign", campaign.id)
    return urlunsplit(parsed._replace(query=urlencode(params)))


def _campaign_dict(row: EngagementCampaignRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "campaign_date": row.campaign_date.isoformat(),
        "timezone": row.timezone,
        "workflow": row.workflow,
        "destination_url": row.destination_url,
        "status": row.status,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def create_campaign(
    *,
    name: str,
    campaign_date: date,
    timezone_name: str = "UTC",
    workflow: str = "content",
    destination_url: str = "",
    notes: str = "",
    created_by: str = "operator",
) -> dict[str, Any]:
    clean_name = _clean(name, 255)
    if not clean_name:
        raise EngagementCampaignError("name_required")
    clean_destination = validate_destination_url(destination_url) if destination_url else None
    row = EngagementCampaignRow(
        id=_new_id("cmp"),
        name=clean_name,
        campaign_date=campaign_date,
        timezone=_clean(timezone_name, 64) or "UTC",
        workflow=_clean(workflow, 64) or "content",
        destination_url=clean_destination,
        notes=_clean(notes, 4000) or None,
        created_by=_clean(created_by, 128) or "operator",
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return _campaign_dict(row)


async def list_campaigns(*, search: str = "", limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(EngagementCampaignRow).order_by(
        desc(EngagementCampaignRow.campaign_date),
        desc(EngagementCampaignRow.created_at),
    ).limit(limit)
    clean_search = _clean(search, 255)
    if clean_search:
        stmt = stmt.where(or_(
            EngagementCampaignRow.name.ilike(f"%{clean_search}%"),
            EngagementCampaignRow.workflow.ilike(f"%{clean_search}%"),
        ))
    async with AsyncSessionLocal() as session:
        campaigns = list((await session.execute(stmt)).scalars().all())
        if not campaigns:
            return []
        ids = [row.id for row in campaigns]
        link_counts = dict((await session.execute(
            select(EngagementCampaignLinkRow.campaign_id, func.count())
            .where(EngagementCampaignLinkRow.campaign_id.in_(ids))
            .group_by(EngagementCampaignLinkRow.campaign_id)
        )).all())
        click_counts = dict((await session.execute(
            select(EngagementCampaignClickRow.campaign_id, func.count())
            .where(EngagementCampaignClickRow.campaign_id.in_(ids))
            .group_by(EngagementCampaignClickRow.campaign_id)
        )).all())
    return [
        {
            **_campaign_dict(row),
            "tracked_links": int(link_counts.get(row.id, 0)),
            "raw_clicks": int(click_counts.get(row.id, 0)),
        }
        for row in campaigns
    ]


async def get_campaign(campaign_id: str) -> EngagementCampaignRow:
    async with AsyncSessionLocal() as session:
        row = await session.get(EngagementCampaignRow, campaign_id)
    if row is None:
        raise EngagementCampaignError("campaign_not_found")
    return row


async def create_tracking_link(
    *,
    campaign_id: str,
    channel: str,
    destination_url: str = "",
    contact_id: str = "",
    label: str = "",
    advisor_briefing: str = "",
    mark_sent: bool = False,
) -> dict[str, Any]:
    clean_channel = _clean(channel, 16).lower()
    if clean_channel not in CHANNELS:
        raise EngagementCampaignError("unsupported_channel")
    clean_contact_id = _clean(contact_id, 64) or None
    async with AsyncSessionLocal() as session:
        campaign = await session.get(EngagementCampaignRow, campaign_id)
        if campaign is None:
            raise EngagementCampaignError("campaign_not_found")
        clean_destination = validate_destination_url(destination_url or campaign.destination_url or "")
        contact = await session.get(FirmContactRow, clean_contact_id) if clean_contact_id else None
        if clean_contact_id and contact is None:
            raise EngagementCampaignError("contact_not_found")
        for _ in range(8):
            code = _new_code()
            if await session.get(EngagementCampaignLinkRow, code) is None:
                break
        else:
            raise RuntimeError("campaign_link_code_collision")
        row = EngagementCampaignLinkRow(
            code=code,
            campaign_id=campaign.id,
            contact_id=clean_contact_id,
            pif_id=contact.pif_id if contact else None,
            channel=clean_channel,
            label=_clean(label, 255) or None,
            destination_url=clean_destination,
            advisor_briefing=_clean(advisor_briefing, 4000) or None,
            sent_at=datetime.now(timezone.utc) if mark_sent else None,
        )
        session.add(row)
        if campaign.status == "draft":
            campaign.status = "active"
        await session.commit()
        await session.refresh(row)
    return {
        "code": row.code,
        "campaign_id": row.campaign_id,
        "contact_id": row.contact_id,
        "pif_id": row.pif_id,
        "channel": row.channel,
        "label": row.label,
        "destination_url": row.destination_url,
        "advisor_briefing": row.advisor_briefing,
        "tracking_url": tracking_url(row.code),
        "sent_at": _iso(row.sent_at),
        "created_at": _iso(row.created_at),
    }


async def mark_tracking_link_sent(code: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        row = await session.get(EngagementCampaignLinkRow, code)
        if row is None:
            raise EngagementCampaignError("tracking_link_not_found")
        if row.sent_at is None:
            row.sent_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
    return {"code": row.code, "sent_at": _iso(row.sent_at)}


async def mark_tracking_links_sent_from_text(
    value: Any,
    *,
    sent_at: datetime | None = None,
) -> list[str]:
    codes = _tracking_codes_from_text(value)
    if not codes:
        return []
    marked_at = sent_at or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(EngagementCampaignLinkRow).where(
                EngagementCampaignLinkRow.code.in_(codes),
                EngagementCampaignLinkRow.channel == "email",
            )
        )).scalars().all())
        for row in rows:
            if row.sent_at is None:
                row.sent_at = marked_at
        await session.commit()
    found = {row.code for row in rows}
    return [code for code in codes if code in found]


async def resolve_campaign_tracking_code(code: str) -> dict[str, Any] | None:
    clean_code = _clean(code, 32)
    if not clean_code:
        return None
    async with AsyncSessionLocal() as session:
        link = await session.get(EngagementCampaignLinkRow, clean_code)
        campaign = await session.get(EngagementCampaignRow, link.campaign_id) if link else None
    if link is None or campaign is None:
        return None
    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "workflow": campaign.workflow,
        "contact_id": link.contact_id,
        "pif_id": link.pif_id,
        "source": f"campaign_{link.channel}",
        "channel": link.channel,
        "link_code": link.code,
        "destination_url": link.destination_url,
    }


def _approved_vendor_stack(value: Any) -> dict[str, Any]:
    """Return only evidence-bearing technographic observations."""
    if not isinstance(value, dict):
        return {}
    approved: dict[str, Any] = {}
    for key, detail in value.items():
        if isinstance(detail, dict):
            evidence = detail.get("evidence") or detail.get("source") or detail.get("sources")
            status = str(detail.get("status") or detail.get("confidence") or "").lower()
            if evidence or status in {"confirmed", "verified", "high"}:
                approved[_clean(key, 128)] = detail
        elif isinstance(detail, str) and detail.lower() in {"confirmed", "verified"}:
            approved[_clean(key, 128)] = detail
    return approved


async def advisor_context(code: str) -> dict[str, Any] | None:
    clean_code = _clean(code, 32)
    if not clean_code:
        return None
    async with AsyncSessionLocal() as session:
        link = await session.get(EngagementCampaignLinkRow, clean_code)
        if link is None or not link.contact_id:
            return None
        campaign = await session.get(EngagementCampaignRow, link.campaign_id)
        contact = await session.get(FirmContactRow, link.contact_id)
        firm = await session.get(PifFirmRow, link.pif_id) if link.pif_id else None
    if campaign is None or contact is None:
        return None
    return {
        "first_name": _clean(contact.first_name, 128),
        "full_name": _clean(contact.full_name, 255),
        "role": _clean(contact.title or contact.research_title, 255),
        "firm_name": _clean(firm.firm_name, 512) if firm else "",
        "location": _clean(firm.metro, 255) if firm else "",
        "vendor_stack": _approved_vendor_stack(firm.vendor_stack) if firm else {},
        "briefing": _clean(link.advisor_briefing, 4000),
        "contact_id": contact.id,
        "pif_id": link.pif_id,
        "campaign_id": campaign.id,
    }


async def record_campaign_click(
    code: str,
    *,
    ip: str = "",
    user_agent: str = "",
    referer: str = "",
) -> tuple[EngagementCampaignLinkRow, EngagementCampaignRow, EngagementCampaignClickRow] | None:
    async with AsyncSessionLocal() as session:
        link = await session.get(EngagementCampaignLinkRow, _clean(code, 32))
        if link is None:
            return None
        campaign = await session.get(EngagementCampaignRow, link.campaign_id)
        if campaign is None:
            return None
        click = EngagementCampaignClickRow(
            id=_new_id("cmpclick"),
            link_code=link.code,
            campaign_id=campaign.id,
            contact_id=link.contact_id,
            pif_id=link.pif_id,
            channel=link.channel,
            ip=_clean(ip, 64) or None,
            user_agent=_clean(user_agent, 512) or None,
            referer=_clean(referer, 1024) or None,
        )
        session.add(click)
        await session.commit()
        await session.refresh(click)
    return link, campaign, click


async def search_contacts(*, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    stmt = (
        select(FirmContactRow, PifFirmRow)
        .outerjoin(PifFirmRow, PifFirmRow.id == FirmContactRow.pif_id)
        .order_by(FirmContactRow.full_name.asc().nulls_last(), FirmContactRow.email.asc())
        .limit(limit)
    )
    clean_query = _clean(query, 255)
    if clean_query:
        pattern = f"%{clean_query}%"
        stmt = stmt.where(or_(
            FirmContactRow.full_name.ilike(pattern),
            FirmContactRow.email.ilike(pattern),
            FirmContactRow.title.ilike(pattern),
            PifFirmRow.firm_name.ilike(pattern),
        ))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).all()
    return [
        {
            "id": contact.id,
            "name": _clean(contact.full_name) or _clean(contact.email) or "Unknown contact",
            "email": _clean(contact.email),
            "title": _clean(contact.title),
            "firm_name": _clean(firm.firm_name if firm else None),
            "pif_id": contact.pif_id,
        }
        for contact, firm in rows
    ]


def _latest_activity_rows(
    *,
    campaigns: list[EngagementCampaignRow],
    links: list[EngagementCampaignLinkRow],
    clicks: list[EngagementCampaignClickRow],
    observations: list[LeadGenObservationRow],
    contacts: list[FirmContactRow],
    firms: list[PifFirmRow],
) -> list[dict[str, Any]]:
    """Build the cross-campaign stream with the same human/scanner rules as campaign detail."""
    campaign_map = {row.id: row for row in campaigns}
    link_map = {row.code: row for row in links}
    contact_map = {row.id: row for row in contacts}
    firm_map = {row.id: row for row in firms}
    activities: list[dict[str, Any]] = []

    def identity(link: EngagementCampaignLinkRow) -> tuple[str, str, str]:
        contact = contact_map.get(link.contact_id or "")
        firm = firm_map.get(link.pif_id or "")
        name = (
            _clean(contact.full_name if contact else None)
            or _clean(contact.email if contact else None)
            or _clean(link.label)
            or "Anonymous visitor"
        )
        return name, _clean(contact.email if contact else None), _clean(firm.firm_name if firm else None)

    def base(link: EngagementCampaignLinkRow) -> dict[str, Any]:
        campaign = campaign_map[link.campaign_id]
        name, email, firm_name = identity(link)
        return {
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "campaign_date": campaign.campaign_date.isoformat(),
            "workflow": campaign.workflow,
            "destination_url": link.destination_url,
            "contact_id": link.contact_id,
            "contact_name": name,
            "contact_email": email,
            "firm_name": firm_name,
            "channel": link.channel,
            "link_code": link.code,
        }

    for click in clicks:
        link = link_map.get(click.link_code)
        if link is None or link.campaign_id not in campaign_map:
            continue
        quality = "scanner" if _is_scanner_ua(click.user_agent) else "suspect"
        activities.append({
            **base(link),
            "id": click.id,
            "occurred_at": _iso(click.clicked_at),
            "event": "redirect_click",
            "label": "Tracked link opened",
            "detail": "Redirect fetched; human interest is not confirmed",
            "quality": quality,
            "page": "tracked redirect",
        })

    sessions: dict[tuple[str, str], list[LeadGenObservationRow]] = defaultdict(list)
    for observation in _dedupe_page_events(observations):
        raw = observation.raw_event_json or {}
        code = _clean(raw.get("link_code"), 32)
        if code not in link_map:
            continue
        session_id = _clean(raw.get("session_id"), 64) or observation.id
        sessions[(code, session_id)].append(observation)

    for (code, session_id), rows in sessions.items():
        link = link_map[code]
        if link.campaign_id not in campaign_map:
            continue
        quality = _session_quality(rows)
        newest = max(rows, key=lambda row: row.created_at)
        raw_newest = newest.raw_event_json or {}
        max_time = _observed_time_on_page_ms(rows)
        page = _clean(raw_newest.get("page"), 160).strip("/") or "landing page"
        activities.append({
            **base(link),
            "id": f"session:{code}:{session_id}",
            "occurred_at": _iso(newest.created_at),
            "event": "page_visit",
            "label": "Confirmed page visit" if quality == "human" else "Unconfirmed page visit",
            "detail": f"{round(max_time / 1000, 1)} seconds maximum observed time",
            "quality": quality,
            "page": page,
        })
        for observation in rows:
            raw = observation.raw_event_json or {}
            event = _clean(raw.get("event"), 64) or "session_ready"
            if event not in MEANINGFUL_EVENTS and not _is_reveal_event(event):
                continue
            if _is_reveal_event(event):
                label = "Content revealed"
                detail = "Visitor revealed interactive content"
            elif event.startswith("scroll_"):
                percent = event.split("_", 1)[1]
                label = f"Scrolled {percent}%"
                detail = f"Visitor reached at least {percent}% of the page"
            else:
                label = "Page click"
                text = _clean(raw.get("click_text"), 180) or "Button or link"
                href = _clean(raw.get("click_href"), 512)
                detail = f"{text}{f' -> {href}' if href else ''}"
            activities.append({
                **base(link),
                "id": observation.id,
                "occurred_at": _iso(observation.created_at),
                "event": event,
                "label": label,
                "detail": detail,
                "quality": quality,
                "page": _clean(raw.get("page"), 160).strip("/") or "landing page",
            })

    activities.sort(key=lambda row: row["occurred_at"] or "", reverse=True)
    return activities


async def latest_campaign_activity(
    *,
    since_days: int = 1,
    limit: int = 100,
    human_only: bool = True,
) -> dict[str, Any]:
    """Return newest-first engagement events across every campaign."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days > 0 else None
    sample_limit = min(max(limit * 25, 1000), 7500)
    observation_stmt = (
        select(LeadGenObservationRow)
        .where(
            LeadGenObservationRow.event_type == "page_session",
            LeadGenObservationRow.raw_event_json["campaign_id"].astext.isnot(None),
            LeadGenObservationRow.raw_event_json["campaign_id"].astext != "",
        )
        .order_by(desc(LeadGenObservationRow.created_at))
        .limit(sample_limit)
    )
    click_stmt = select(EngagementCampaignClickRow).order_by(
        desc(EngagementCampaignClickRow.clicked_at)
    ).limit(sample_limit)
    if cutoff is not None:
        observation_stmt = observation_stmt.where(LeadGenObservationRow.created_at >= cutoff)
        click_stmt = click_stmt.where(EngagementCampaignClickRow.clicked_at >= cutoff)

    async with AsyncSessionLocal() as session:
        observations = list((await session.execute(observation_stmt)).scalars().all())
        clicks = list((await session.execute(click_stmt)).scalars().all())
        codes = {
            _clean((row.raw_event_json or {}).get("link_code"), 32)
            for row in observations
        } | {row.link_code for row in clicks}
        codes.discard("")
        links = list((await session.execute(
            select(EngagementCampaignLinkRow).where(EngagementCampaignLinkRow.code.in_(codes))
        )).scalars().all()) if codes else []
        campaign_ids = {row.campaign_id for row in links}
        campaigns = list((await session.execute(
            select(EngagementCampaignRow).where(EngagementCampaignRow.id.in_(campaign_ids))
        )).scalars().all()) if campaign_ids else []
        contact_ids = {row.contact_id for row in links if row.contact_id}
        contacts = list((await session.execute(
            select(FirmContactRow).where(FirmContactRow.id.in_(contact_ids))
        )).scalars().all()) if contact_ids else []
        pif_ids = {row.pif_id for row in links if row.pif_id}
        firms = list((await session.execute(
            select(PifFirmRow).where(PifFirmRow.id.in_(pif_ids))
        )).scalars().all()) if pif_ids else []

    activities = _latest_activity_rows(
        campaigns=campaigns,
        links=links,
        clicks=clicks,
        observations=observations,
        contacts=contacts,
        firms=firms,
    )
    if human_only:
        activities = [row for row in activities if row["quality"] == "human"]
    return {
        "activities": activities[:limit],
        "count": min(len(activities), limit),
        "has_more": len(activities) > limit,
        "since_days": since_days,
        "quality": "human" if human_only else "all",
    }


async def campaign_analytics(campaign_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        campaign = await session.get(EngagementCampaignRow, campaign_id)
        if campaign is None:
            raise EngagementCampaignError("campaign_not_found")
        links = list((await session.execute(
            select(EngagementCampaignLinkRow)
            .where(EngagementCampaignLinkRow.campaign_id == campaign_id)
            .order_by(desc(EngagementCampaignLinkRow.created_at))
        )).scalars().all())
        clicks = list((await session.execute(
            select(EngagementCampaignClickRow)
            .where(EngagementCampaignClickRow.campaign_id == campaign_id)
            .order_by(desc(EngagementCampaignClickRow.clicked_at))
        )).scalars().all())
        codes = [link.code for link in links]
        observations = list((await session.execute(
            select(LeadGenObservationRow).where(
                LeadGenObservationRow.event_type == "page_session",
                LeadGenObservationRow.raw_event_json["link_code"].astext.in_(codes),
            )
        )).scalars().all()) if codes else []
        contact_ids = {link.contact_id for link in links if link.contact_id}
        contacts = list((await session.execute(
            select(FirmContactRow).where(FirmContactRow.id.in_(contact_ids))
        )).scalars().all()) if contact_ids else []
        pif_ids = {link.pif_id for link in links if link.pif_id}
        firms = list((await session.execute(
            select(PifFirmRow).where(PifFirmRow.id.in_(pif_ids))
        )).scalars().all()) if pif_ids else []

    link_map = {link.code: link for link in links}
    contact_map = {contact.id: contact for contact in contacts}
    firm_map = {firm.id: firm for firm in firms}
    clicks_by_code: dict[str, list[EngagementCampaignClickRow]] = defaultdict(list)
    for click in clicks:
        clicks_by_code[click.link_code].append(click)

    deduped = _dedupe_page_events(observations)
    sessions: dict[tuple[str, str], list[LeadGenObservationRow]] = defaultdict(list)
    for observation in deduped:
        raw = observation.raw_event_json or {}
        code = _clean(raw.get("link_code"), 32)
        if code not in link_map:
            continue
        session_id = _clean(raw.get("session_id"), 64) or observation.id
        sessions[(code, session_id)].append(observation)

    channel_stats = {
        channel: {
            "channel": channel,
            "tracked_links": 0,
            "tracked_people": 0,
            "sent": 0,
            "raw_clicks": 0,
            "scanner_or_suspect_clicks": 0,
            "confirmed_visits": 0,
            "meaningful_actions": 0,
            "engaged_people": 0,
        }
        for channel in ("email", "linkedin", "public")
    }
    channel_contacts: dict[str, set[str]] = defaultdict(set)
    channel_engaged_contacts: dict[str, set[str]] = defaultdict(set)
    link_metrics = {
        link.code: {
            "raw_clicks": 0,
            "confirmed_visits": 0,
            "meaningful_actions": 0,
            "deepest_scroll": 0,
            "max_time_on_page_seconds": 0.0,
        }
        for link in links
    }
    activities: list[dict[str, Any]] = []

    def identity(link: EngagementCampaignLinkRow) -> tuple[str, str, str]:
        contact = contact_map.get(link.contact_id or "")
        firm = firm_map.get(link.pif_id or "")
        name = _clean(contact.full_name if contact else None) or _clean(contact.email if contact else None) or "Anonymous visitor"
        email = _clean(contact.email if contact else None)
        firm_name = _clean(firm.firm_name if firm else None)
        return name, email, firm_name

    for link in links:
        channel_stats[link.channel]["tracked_links"] += 1
        if link.contact_id:
            channel_contacts[link.channel].add(link.contact_id)
        if link.sent_at:
            channel_stats[link.channel]["sent"] += 1

    for click in clicks:
        link = link_map.get(click.link_code)
        if link is None:
            continue
        quality = "scanner" if _is_scanner_ua(click.user_agent) else "suspect"
        channel_stats[link.channel]["raw_clicks"] += 1
        channel_stats[link.channel]["scanner_or_suspect_clicks"] += 1
        link_metrics[link.code]["raw_clicks"] += 1
        name, email, firm_name = identity(link)
        activities.append({
            "id": click.id,
            "occurred_at": _iso(click.clicked_at),
            "contact_id": link.contact_id,
            "contact_name": name,
            "contact_email": email,
            "firm_name": firm_name,
            "channel": link.channel,
            "event": "redirect_click",
            "label": "Tracked link opened",
            "detail": "Redirect fetched; human interest is not confirmed",
            "quality": quality,
            "page": "tracked redirect",
            "link_code": link.code,
        })

    engaged_contacts: set[str] = set()
    anonymous_human_sessions = 0
    for (code, session_id), rows in sessions.items():
        link = link_map[code]
        quality = _session_quality(rows)
        raw_last = rows[-1].raw_event_json or {}
        page = _clean(raw_last.get("page"), 160).strip("/") or "landing page"
        max_time = _observed_time_on_page_ms(rows)
        if quality == "human":
            channel_stats[link.channel]["confirmed_visits"] += 1
            link_metrics[code]["confirmed_visits"] += 1
            link_metrics[code]["max_time_on_page_seconds"] = max(
                link_metrics[code]["max_time_on_page_seconds"],
                round(max_time / 1000, 1),
            )
            if link.contact_id:
                engaged_contacts.add(link.contact_id)
                channel_engaged_contacts[link.channel].add(link.contact_id)
            else:
                anonymous_human_sessions += 1
        name, email, firm_name = identity(link)
        activities.append({
            "id": f"session:{code}:{session_id}",
            "occurred_at": _iso(max(row.created_at for row in rows)),
            "contact_id": link.contact_id,
            "contact_name": name,
            "contact_email": email,
            "firm_name": firm_name,
            "channel": link.channel,
            "event": "page_visit",
            "label": "Confirmed page visit" if quality == "human" else "Unconfirmed page visit",
            "detail": f"{round(max_time / 1000, 1)} seconds maximum observed time",
            "quality": quality,
            "page": page,
            "link_code": code,
        })

        for observation in rows:
            raw = observation.raw_event_json or {}
            event = _clean(raw.get("event"), 64) or "session_ready"
            if event not in MEANINGFUL_EVENTS and not _is_reveal_event(event):
                continue
            if quality == "human":
                channel_stats[link.channel]["meaningful_actions"] += 1
                link_metrics[code]["meaningful_actions"] += 1
            if _is_reveal_event(event):
                label = "Content revealed"
                detail = "Visitor revealed interactive content"
            elif event.startswith("scroll_"):
                percent = event.split("_", 1)[1]
                if quality == "human":
                    try:
                        link_metrics[code]["deepest_scroll"] = max(
                            link_metrics[code]["deepest_scroll"], int(percent),
                        )
                    except ValueError:
                        pass
                label = f"Scrolled {percent}%"
                detail = f"Visitor reached at least {percent}% of the page"
            else:
                label = "Page click"
                text = _clean(raw.get("click_text"), 180) or "Button or link"
                href = _clean(raw.get("click_href"), 512)
                detail = f"{text}{f' -> {href}' if href else ''}"
            activities.append({
                "id": observation.id,
                "occurred_at": _iso(observation.created_at),
                "contact_id": link.contact_id,
                "contact_name": name,
                "contact_email": email,
                "firm_name": firm_name,
                "channel": link.channel,
                "event": event,
                "label": label,
                "detail": detail,
                "quality": quality,
                "page": _clean(raw.get("page"), 160).strip("/") or "landing page",
                "link_code": code,
            })

    for channel, stats in channel_stats.items():
        stats["tracked_people"] = len(channel_contacts[channel])
        stats["engaged_people"] = len(channel_engaged_contacts[channel])

    link_rows = []
    for link in links:
        name, email, firm_name = identity(link)
        link_rows.append({
            "code": link.code,
            "tracking_url": tracking_url(link.code),
            "destination_url": link.destination_url,
            "channel": link.channel,
            "label": link.label,
            "contact_id": link.contact_id,
            "contact_name": name,
            "contact_email": email,
            "firm_name": firm_name,
            "sent_at": _iso(link.sent_at),
            "created_at": _iso(link.created_at),
            **link_metrics[link.code],
        })

    activities.sort(key=lambda row: row["occurred_at"] or "", reverse=True)
    return {
        "campaign": _campaign_dict(campaign),
        "summary": {
            "tracked_links": len(links),
            "tracked_people": len({link.contact_id for link in links if link.contact_id}),
            "sent": sum(1 for link in links if link.sent_at),
            "raw_clicks": len(clicks),
            "scanner_or_suspect_clicks": len(clicks),
            "confirmed_visits": sum(stats["confirmed_visits"] for stats in channel_stats.values()),
            "meaningful_actions": sum(stats["meaningful_actions"] for stats in channel_stats.values()),
            "engaged_people": len(engaged_contacts),
            "anonymous_human_sessions": anonymous_human_sessions,
        },
        "channels": [channel_stats[channel] for channel in ("email", "linkedin", "public")],
        "links": link_rows,
        "activities": activities[:500],
    }
