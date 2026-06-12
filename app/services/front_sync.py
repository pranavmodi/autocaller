"""Budgeted Front sync for lead-generation warmth signals."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal
from app.db.models import (
    EmailLogRow,
    FirmContactRow,
    FrontContactRow,
    FrontFirmActivityRow,
    FrontSyncStateRow,
    LeadGenPolicyVersionRow,
)
from app.services.contact_selection import DEFAULT_CONTACT_SELECTION_WEIGHTS, deep_merge_policy
from app.services.lead_gen_cybernetic import DEFAULT_DAILY_SEND_BUDGET, TARGET_METRIC


FRONT_ENV_PATH = Path("/root/.openclaw/workspace/secrets/front_precise.env")
MISSION_DB_PATH = Path("/root/.openclaw/workspace/mission-control/data/mission.db")
DEFAULT_INBOXES = {
    "inb_qfq9": "Scheduling & Orders",
    "inb_rcld": "Records & Images",
    "inb_37vb5": "AR Case Updates",
}
CONSUMER_DOMAINS = {
    "aol.com",
    "gmail.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "me.com",
    "msn.com",
    "outlook.com",
    "proton.me",
    "protonmail.com",
    "yahoo.com",
}
FILEVINE_RE = re.compile(r"(^|\.)filevineapp\.com$", re.I)
EMAIL_RE = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_front_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_front_datetime(int(text))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def normalize_domain(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw or raw in {"none", "null", "n/a", "na", "-"}:
        return ""
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    if "://" not in raw and "/" not in raw:
        host = raw
    else:
        host = urlparse(raw if "://" in raw else f"https://{raw}").netloc
    host = host.split("@")[-1].split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def is_consumer_domain(domain: str | None) -> bool:
    return normalize_domain(domain) in CONSUMER_DOMAINS


def is_filevine_domain(domain: str | None) -> bool:
    return bool(FILEVINE_RE.search(normalize_domain(domain)))


def is_human_named_contact(name: str | None, email: str | None) -> bool:
    clean_name = (name or "").strip()
    clean_email = (email or "").strip()
    if "@" not in clean_email:
        return False
    if not clean_name or "@" in clean_name or clean_name.lower() in {"user", "unknown"}:
        return False
    if any(marker in clean_name.lower() for marker in ("mailbox", "prelit", "pre-lit", "shared")):
        return False
    if clean_name.startswith("+"):
        return False
    if not re.search(r"[A-Za-z]{2,}", clean_name):
        return False
    local = clean_email.split("@", 1)[0]
    if any(local.lower().startswith(prefix) for prefix in ("prelit", "records", "intake", "referral", "case")):
        return False
    if local.isdigit():
        return False
    return True


def extract_emails(value: Any) -> list[str]:
    emails: list[str] = []
    if value is None:
        return emails
    if isinstance(value, str):
        emails.extend(match.group(0).lower() for match in EMAIL_RE.finditer(value))
    elif isinstance(value, dict):
        for key in ("handle", "email", "address", "value", "source", "recipient", "from", "to"):
            emails.extend(extract_emails(value.get(key)))
        for key in ("handles", "participants", "recipients", "links"):
            emails.extend(extract_emails(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            emails.extend(extract_emails(item))
    return list(dict.fromkeys(emails))


def derive_contact_fields(contact: dict[str, Any]) -> dict[str, Any]:
    emails = extract_emails(contact.get("handles") or contact)
    primary = (
        str(contact.get("email") or contact.get("primary_email") or "").strip().lower()
        if (contact.get("email") or contact.get("primary_email"))
        else ""
    )
    if not primary and emails:
        primary = emails[0]
    updated = parse_front_datetime(
        contact.get("updated_at")
        or contact.get("front_updated_at")
        or contact.get("last_message_at")
        or contact.get("created_at")
    )
    return {
        "front_id": str(contact.get("id") or contact.get("front_id") or "").strip(),
        "name": str(contact.get("name") or contact.get("display_name") or "").strip() or None,
        "handles": contact.get("handles") if isinstance(contact.get("handles"), list) else emails,
        "primary_email": primary or None,
        "domain": normalize_domain(primary) if primary else None,
        "front_updated_at": updated,
        "raw_json": contact,
    }


@dataclass
class FrontRateBudget:
    max_calls: int = 300
    min_interval_seconds: float = 1.5
    calls_made: int = 0
    _last_call_monotonic: float = 0.0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls_made)

    def exhausted(self) -> bool:
        return self.remaining <= 0

    async def before_call(self) -> bool:
        if self.exhausted():
            return False
        now = time.monotonic()
        delay = self.min_interval_seconds - (now - self._last_call_monotonic)
        if self._last_call_monotonic and delay > 0:
            await asyncio.sleep(delay)
        self.calls_made += 1
        self._last_call_monotonic = time.monotonic()
        return True


class FrontClient:
    def __init__(self, *, budget: FrontRateBudget):
        load_dotenv(FRONT_ENV_PATH)
        token = os.getenv("FRONT_AUTH_TOKEN", "").strip()
        base = os.getenv("FRONT_API_BASE_URL", "").strip().rstrip("/")
        if not token or not base:
            raise RuntimeError(f"Front credentials missing from {FRONT_ENV_PATH}")
        self.base = base
        self.budget = budget
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    async def __aenter__(self) -> "FrontClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    async def get(self, path_or_url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not await self.budget.before_call():
            return None
        url = path_or_url if path_or_url.startswith("http") else f"{self.base}{path_or_url}"
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def _get_state(session, key: str) -> FrontSyncStateRow:
    row = await session.get(FrontSyncStateRow, key)
    if row is None:
        row = FrontSyncStateRow(key=key, cursor=None, watermark=None, updated_at=_utcnow())
        session.add(row)
        await session.flush()
    return row


async def _upsert_front_contacts(session, contacts: list[dict[str, Any]]) -> int:
    rows = [derive_contact_fields(contact) for contact in contacts]
    rows = [row for row in rows if row.get("front_id")]
    if not rows:
        return 0
    stmt = insert(FrontContactRow).values(rows)
    update_cols = {
        "name": stmt.excluded.name,
        "handles": stmt.excluded.handles,
        "primary_email": stmt.excluded.primary_email,
        "domain": stmt.excluded.domain,
        "front_updated_at": stmt.excluded.front_updated_at,
        "raw_json": stmt.excluded.raw_json,
    }
    await session.execute(stmt.on_conflict_do_update(index_elements=["front_id"], set_=update_cols))
    return len(rows)


async def sync_contacts(*, max_calls: int = 300, full: bool = False, budget: FrontRateBudget | None = None) -> dict[str, Any]:
    budget = budget or FrontRateBudget(max_calls=max_calls)
    fetched = upserted = pages = 0
    async with AsyncSessionLocal() as session:
        state = await _get_state(session, "contacts")
        cursor = None if full else state.cursor
        watermark = None if full else state.watermark
        await session.commit()

    async with FrontClient(budget=budget) as client:
        while not budget.exhausted():
            params: dict[str, Any] | None = {"limit": 100}
            path = "/contacts"
            if cursor:
                path = cursor
                params = None
            elif watermark:
                params["updated_after"] = watermark.isoformat()
            data = await client.get(path, params=params)
            if data is None:
                break
            contacts = data.get("_results") or data.get("results") or data.get("contacts") or []
            next_cursor = (data.get("_pagination") or {}).get("next") or data.get("next")
            max_seen = watermark
            async with AsyncSessionLocal() as session:
                upserted += await _upsert_front_contacts(session, list(contacts))
                for contact in contacts:
                    updated = derive_contact_fields(contact).get("front_updated_at")
                    if updated and (max_seen is None or updated > max_seen):
                        max_seen = updated
                state = await _get_state(session, "contacts")
                state.cursor = next_cursor
                state.watermark = max_seen
                state.updated_at = _utcnow()
                await session.commit()
            fetched += len(contacts)
            pages += 1
            cursor = next_cursor
            watermark = max_seen
            if not contacts or not cursor:
                break
    return {
        "stage": "contacts",
        "pages": pages,
        "fetched": fetched,
        "upserted": upserted,
        "calls_made": budget.calls_made,
        "remaining_calls": budget.remaining,
        "budget_exhausted": budget.exhausted(),
    }


def _conversation_timestamp(convo: dict[str, Any]) -> datetime | None:
    return parse_front_datetime(
        convo.get("last_message_at")
        or convo.get("updated_at")
        or convo.get("created_at")
    )


async def _merge_activity(session, *, domain: str, inbox_id: str, inbox_name: str, ts: datetime | None) -> None:
    if not domain or is_consumer_domain(domain):
        return
    now = _utcnow()
    row = await session.get(FrontFirmActivityRow, domain)
    if row is None:
        row = FrontFirmActivityRow(
            domain=domain,
            contact_count=0,
            inbox_breakdown={},
            tech_signals={},
            synced_at=now,
        )
        session.add(row)
    breakdown = dict(row.inbox_breakdown or {})
    inbox_stats = dict(breakdown.get(inbox_id) or {})
    inbox_stats["name"] = inbox_name
    inbox_stats["conversation_count"] = int(inbox_stats.get("conversation_count") or 0) + 1
    if ts:
        last = parse_front_datetime(inbox_stats.get("last_seen_at"))
        if last is None or ts > last:
            inbox_stats["last_seen_at"] = ts.isoformat()
    breakdown[inbox_id] = inbox_stats
    row.inbox_breakdown = breakdown
    if ts and (row.last_seen_at is None or ts > row.last_seen_at):
        row.last_seen_at = ts
    if inbox_id == "inb_qfq9" and ts and (row.last_referral_at is None or ts > row.last_referral_at):
        row.last_referral_at = ts
    if inbox_id == "inb_rcld" and ts and (row.last_records_at is None or ts > row.last_records_at):
        row.last_records_at = ts
    row.synced_at = now


async def sync_inbox_activity(*, max_calls: int = 300, full: bool = False, budget: FrontRateBudget | None = None) -> dict[str, Any]:
    budget = budget or FrontRateBudget(max_calls=max_calls)
    fetched = pages = domains_seen = 0
    inboxes = dict(DEFAULT_INBOXES)
    configured = os.getenv("FRONT_ACTIVITY_INBOXES", "").strip()
    if configured:
        inboxes = {}
        for item in configured.split(","):
            inbox_id, _, label = item.strip().partition(":")
            if inbox_id:
                inboxes[inbox_id] = label or inbox_id

    async with FrontClient(budget=budget) as client:
        for inbox_id, inbox_name in inboxes.items():
            if budget.exhausted():
                break
            state_key = f"inbox:{inbox_id}"
            async with AsyncSessionLocal() as session:
                state = await _get_state(session, state_key)
                cursor = None if full else state.cursor
                watermark = None if full else state.watermark
                await session.commit()
            while not budget.exhausted():
                params: dict[str, Any] | None = {"limit": 100}
                path = f"/inboxes/{inbox_id}/conversations"
                if cursor:
                    path = cursor
                    params = None
                elif watermark:
                    params["since"] = watermark.isoformat()
                data = await client.get(path, params=params)
                if data is None:
                    break
                conversations = data.get("_results") or data.get("results") or data.get("conversations") or []
                next_cursor = (data.get("_pagination") or {}).get("next") or data.get("next")
                max_seen = watermark
                async with AsyncSessionLocal() as session:
                    page_domains: set[str] = set()
                    for convo in conversations:
                        ts = _conversation_timestamp(convo)
                        if ts and (max_seen is None or ts > max_seen):
                            max_seen = ts
                        for email in extract_emails(convo):
                            domain = normalize_domain(email)
                            if not domain:
                                continue
                            page_domains.add(domain)
                            await _merge_activity(
                                session,
                                domain=domain,
                                inbox_id=inbox_id,
                                inbox_name=inbox_name,
                                ts=ts,
                            )
                    state = await _get_state(session, state_key)
                    state.cursor = next_cursor
                    state.watermark = max_seen
                    state.updated_at = _utcnow()
                    await session.commit()
                fetched += len(conversations)
                domains_seen += len(page_domains)
                pages += 1
                cursor = next_cursor
                watermark = max_seen
                if not conversations or not cursor:
                    break
    return {
        "stage": "activity",
        "pages": pages,
        "fetched": fetched,
        "domains_seen": domains_seen,
        "calls_made": budget.calls_made,
        "remaining_calls": budget.remaining,
        "budget_exhausted": budget.exhausted(),
    }


def _load_pif_domain_map(db_path: Path = MISSION_DB_PATH) -> dict[str, str]:
    domains: dict[str, str] = {}
    uri = f"file:{db_path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        for pif_id, website, emails in conn.execute("SELECT id, website, emails FROM pif_firms"):
            for candidate in [website, *extract_emails(emails), *(json.loads(emails) if str(emails or "").strip().startswith("[") else [])]:
                domain = normalize_domain(str(candidate))
                if domain and not is_consumer_domain(domain):
                    domains.setdefault(domain, str(pif_id))
    finally:
        conn.close()
    return domains


async def _refresh_contact_counts(session) -> None:
    rows = (await session.execute(
        select(
            FrontContactRow.domain,
            func.count(FrontContactRow.front_id),
            func.max(FrontContactRow.front_updated_at),
        )
        .where(FrontContactRow.domain.isnot(None))
        .group_by(FrontContactRow.domain)
    )).all()
    for domain, count, latest_contact_at in rows:
        if not domain or is_consumer_domain(domain):
            continue
        activity = await session.get(FrontFirmActivityRow, domain)
        if activity is None:
            activity = FrontFirmActivityRow(
                domain=domain,
                contact_count=int(count or 0),
                inbox_breakdown={},
                tech_signals={},
                synced_at=_utcnow(),
            )
            session.add(activity)
        else:
            activity.contact_count = int(count or 0)
            activity.synced_at = _utcnow()
        if latest_contact_at and (activity.last_seen_at is None or latest_contact_at > activity.last_seen_at):
            activity.last_seen_at = latest_contact_at


def _new_contact_id() -> str:
    return f"fc_{uuid.uuid4().hex[:24]}"


async def resolve_firms(*, mission_db_path: Path = MISSION_DB_PATH) -> dict[str, Any]:
    domain_map = _load_pif_domain_map(mission_db_path)
    matched = upserted_contacts = skipped_consumer = skipped_filevine = tech_signal_domains = 0
    async with AsyncSessionLocal() as session:
        await _refresh_contact_counts(session)
        contacts = (await session.execute(
            select(FrontContactRow).where(FrontContactRow.domain.isnot(None))
        )).scalars().all()
        for contact in contacts:
            domain = normalize_domain(contact.domain)
            if not domain:
                continue
            activity = await session.get(FrontFirmActivityRow, domain)
            if activity is None:
                activity = FrontFirmActivityRow(
                    domain=domain,
                    contact_count=1,
                    inbox_breakdown={},
                    tech_signals={},
                    synced_at=_utcnow(),
                )
                session.add(activity)
            if is_consumer_domain(domain):
                skipped_consumer += 1
                continue
            if is_filevine_domain(domain):
                skipped_filevine += 1
                signals = dict(activity.tech_signals or {})
                signals["case_mgmt"] = "filevine"
                activity.tech_signals = signals
                activity.synced_at = _utcnow()
                tech_signal_domains += 1
                continue
            pif_id = domain_map.get(domain)
            if pif_id:
                activity.pif_id = pif_id
                matched += 1
            else:
                continue
            email = (contact.primary_email or "").strip().lower()
            if not email:
                continue
            existing = (await session.execute(
                select(FirmContactRow)
                .where(FirmContactRow.pif_id == pif_id)
                .where(FirmContactRow.email == email)
                .limit(1)
            )).scalar_one_or_none()
            if existing is None:
                existing = FirmContactRow(
                    id=_new_contact_id(),
                    pif_id=pif_id,
                    full_name=contact.name or "",
                    first_name=(contact.name or "").strip().split(" ", 1)[0],
                    email=email,
                    title=None,
                    source="front",
                )
                session.add(existing)
            existing.front_contact_id = contact.front_id
            existing.front_last_seen = activity.last_seen_at or contact.front_updated_at
            existing.tech_signals = activity.tech_signals or {}
            if contact.name and not existing.full_name:
                existing.full_name = contact.name
                existing.first_name = contact.name.split(" ", 1)[0]
            existing.updated_at = _utcnow()
            upserted_contacts += 1
        await session.commit()
    return {
        "matched_domains": matched,
        "upserted_contacts": upserted_contacts,
        "skipped_consumer_contacts": skipped_consumer,
        "skipped_filevine_contacts": skipped_filevine,
        "tech_signal_domains": tech_signal_domains,
    }


def recency_decay_score(*dates: datetime | None, now: datetime | None = None) -> float:
    latest = max((d for d in dates if d is not None), default=None)
    if latest is None:
        return 0.0
    now = now or _utcnow()
    days = max(0.0, (now - latest).total_seconds() / 86400.0)
    return math.exp(-days / 45.0)


def seniority_multiplier(title: str | None) -> float:
    t = (title or "").lower()
    if any(x in t for x in ("owner", "founder", "ceo", "president", "managing partner")):
        return 1.35
    if any(x in t for x in ("coo", "operations", "office manager", "partner", "principal")):
        return 1.2
    if any(x in t for x in ("manager", "director", "supervisor")):
        return 1.08
    return 1.0


def compute_warm_score(
    *,
    contact_count: int,
    last_referral_at: datetime | None,
    last_seen_at: datetime | None,
    max_seniority: float = 1.0,
    tech_signals: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    recency = recency_decay_score(last_referral_at, last_seen_at, now=now)
    if recency <= 0:
        return 0
    contact_component = math.log1p(max(0, contact_count))
    tech_bonus = 1.08 if (tech_signals or {}).get("case_mgmt") in {"filevine", "litify", "smartadvocate"} else 1.0
    return int(round(100 * recency * contact_component * max_seniority * tech_bonus))


async def refresh_warm_scores() -> dict[str, Any]:
    updated = 0
    async with AsyncSessionLocal() as session:
        activities = (await session.execute(select(FrontFirmActivityRow))).scalars().all()
        for activity in activities:
            seniority = 1.0
            if activity.pif_id:
                contacts = (await session.execute(
                    select(FirmContactRow).where(FirmContactRow.pif_id == activity.pif_id)
                )).scalars().all()
                seniority = max([seniority_multiplier(c.title) for c in contacts] or [1.0])
            activity.warm_score = compute_warm_score(
                contact_count=activity.contact_count,
                last_referral_at=activity.last_referral_at,
                last_seen_at=activity.last_seen_at,
                max_seniority=seniority,
                tech_signals=activity.tech_signals or {},
            )
            activity.synced_at = _utcnow()
            updated += 1
        await ensure_lead_gen_v2_policy(session)
        await session.commit()
    return {"updated": updated}


async def ensure_lead_gen_v2_policy(session) -> LeadGenPolicyVersionRow:
    existing = await session.get(LeadGenPolicyVersionRow, "lead-gen-v2")
    if existing:
        if existing.active:
            existing.active = False
        return existing
    weights = deep_merge_policy(
        DEFAULT_CONTACT_SELECTION_WEIGHTS,
        {
            "selection_policy": {
                "name": "contact-selection-v2",
                "objective": TARGET_METRIC,
            },
            "front_warmth": {
                "weight": 1,
                "max_bonus": 75,
            },
            "target_metric": TARGET_METRIC,
            "daily_send_budget": DEFAULT_DAILY_SEND_BUDGET,
        },
    )
    row = LeadGenPolicyVersionRow(
        version="lead-gen-v2",
        label="Lead generation v2 (Front warmth, inactive)",
        target_metric=TARGET_METRIC,
        weights_json=weights,
        suppressions_json={
            "exclude_comms_history": True,
            "exclude_existing_sequences": True,
            "exclude_unusable_email": True,
            "dedupe_by_email": True,
            "human_approval_required": True,
        },
        notes="Copy of v1-style contact policy with Front warmth feature. Left inactive for orchestrator review.",
        active=False,
        created_by="front_sync",
    )
    session.add(row)
    return row


async def front_status() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        states = (await session.execute(select(FrontSyncStateRow).order_by(FrontSyncStateRow.key.asc()))).scalars().all()
        contact_count = (await session.execute(select(func.count(FrontContactRow.front_id)))).scalar_one()
        activity_count = (await session.execute(select(func.count(FrontFirmActivityRow.domain)))).scalar_one()
        matched_count = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain)).where(FrontFirmActivityRow.pif_id.isnot(None))
        )).scalar_one()
        warm_count = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain)).where(FrontFirmActivityRow.warm_score > 0)
        )).scalar_one()
        latest_contact = (await session.execute(
            select(FrontContactRow).order_by(desc(FrontContactRow.first_synced_at)).limit(1)
        )).scalar_one_or_none()
    return {
        "counts": {
            "front_contacts": int(contact_count or 0),
            "front_firm_activity": int(activity_count or 0),
            "matched_domains": int(matched_count or 0),
            "warm_domains": int(warm_count or 0),
        },
        "states": [
            {
                "key": row.key,
                "cursor": row.cursor,
                "watermark": row.watermark.isoformat() if row.watermark else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in states
        ],
        "latest_contact_synced_at": latest_contact.first_synced_at.isoformat() if latest_contact else None,
    }


async def list_front_contacts(*, firm: str = "", domain: str = "", limit: int = 50) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        stmt = select(FrontContactRow, FrontFirmActivityRow).join(
            FrontFirmActivityRow,
            FrontFirmActivityRow.domain == FrontContactRow.domain,
            isouter=True,
        )
        if domain:
            stmt = stmt.where(FrontContactRow.domain == normalize_domain(domain))
        if firm:
            stmt = stmt.where(FrontFirmActivityRow.pif_id == firm)
        stmt = stmt.order_by(desc(FrontContactRow.front_updated_at)).limit(max(1, min(limit, 500)))
        rows = (await session.execute(stmt)).all()
    return [
        {
            "front_id": contact.front_id,
            "name": contact.name,
            "primary_email": contact.primary_email,
            "domain": contact.domain,
            "front_updated_at": contact.front_updated_at.isoformat() if contact.front_updated_at else None,
            "pif_id": activity.pif_id if activity else None,
            "warm_score": activity.warm_score if activity else 0,
            "tech_signals": activity.tech_signals if activity else {},
        }
        for contact, activity in rows
    ]


async def warm_list(*, limit: int = 20) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(FrontFirmActivityRow, FirmContactRow)
            .join(FirmContactRow, FirmContactRow.pif_id == FrontFirmActivityRow.pif_id)
            .where(FrontFirmActivityRow.pif_id.isnot(None))
            .where(FirmContactRow.email.isnot(None))
            .where(FirmContactRow.email != "")
            .where(~FirmContactRow.email.in_(select(EmailLogRow.recipient_email)))
            .where(~FirmContactRow.email.ilike("%filevineapp.com%"))
            .where(~FirmContactRow.email.ilike("%casepeer.com%"))
            .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
            .limit(max(10, min(limit * 5, 500)))
        )
        rows = (await session.execute(stmt)).all()
    out = [
        {
            "domain": activity.domain,
            "pif_id": activity.pif_id,
            "warm_score": activity.warm_score,
            "last_seen_at": activity.last_seen_at.isoformat() if activity.last_seen_at else None,
            "last_referral_at": activity.last_referral_at.isoformat() if activity.last_referral_at else None,
            "contact_id": contact.id,
            "contact_name": contact.full_name,
            "contact_email": contact.email,
            "contact_title": contact.title,
            "tech_signals": activity.tech_signals or {},
        }
        for activity, contact in rows
        if is_human_named_contact(contact.full_name, contact.email)
    ]
    return out[: max(1, min(limit, 100))]


async def run_front_sync(*, max_calls: int = 300, full: bool = False) -> dict[str, Any]:
    budget = FrontRateBudget(max_calls=max(1, max_calls))
    contacts = await sync_contacts(max_calls=max_calls, full=full, budget=budget)
    activity = await sync_inbox_activity(max_calls=max_calls, full=full, budget=budget) if not budget.exhausted() else {
        "stage": "activity",
        "skipped": "api_budget_exhausted",
        "calls_made": budget.calls_made,
        "remaining_calls": budget.remaining,
        "budget_exhausted": True,
    }
    resolve = await resolve_firms()
    scores = await refresh_warm_scores()
    return {
        "contacts": contacts,
        "activity": activity,
        "resolve": resolve,
        "scores": scores,
        "status": await front_status(),
    }


async def front_sync_loop(*, interval_seconds: int = 86400, max_calls: int = 300) -> None:
    while True:
        try:
            await run_front_sync(max_calls=max_calls, full=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)
