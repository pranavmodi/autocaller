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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal
from app.db.models import (
    EmailLogRow,
    FirmContactRow,
    FrontContactRow,
    FrontFirmActivityRow,
    FrontSyncStateRow,
    LeadGenBatchItemRow,
    LeadGenBatchRow,
    LeadGenPolicyVersionRow,
    PatientRow,
)
from app.services.contact_selection import DEFAULT_CONTACT_SELECTION_WEIGHTS, deep_merge_policy
from app.services.lead_gen_cybernetic import (
    DEFAULT_DAILY_SEND_BUDGET,
    TARGET_METRIC,
    ensure_default_policy,
    get_batch,
)
from app.services.sequences.registry import DEFAULT_TEMPLATE_KEY


FRONT_ENV_PATH = Path("/root/.openclaw/workspace/secrets/front_precise.env")
MISSION_DB_PATH = Path("/root/.openclaw/workspace/mission-control/data/mission.db")
DEFAULT_INBOXES = {
    "inb_qfq9": "Scheduling & Orders",
    "inb_rcld": "Records & Images",
    "inb_37vb5": "AR Case Updates",
}
FRONT_LAST_RUN_STATE_KEY = "_last_run"
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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_hours(value: datetime | None, *, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    now = now or _utcnow()
    return round(max(0.0, (now - value).total_seconds() / 3600.0), 2)


def _day_delta(total: int, last_24h: int, previous_24h: int) -> dict[str, int]:
    return {
        "total": int(total or 0),
        "last_24h": int(last_24h or 0),
        "previous_24h": int(previous_24h or 0),
        "delta": int(last_24h or 0) - int(previous_24h or 0),
    }


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _new_lead_gen_id() -> str:
    return uuid.uuid4().hex


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


async def _firm_names_for_pifs(session, pif_ids: set[str]) -> dict[str, str]:
    if not pif_ids:
        return {}
    patient_ids = [f"pif-{pif_id}" for pif_id in pif_ids] + [f"mc-{pif_id}" for pif_id in pif_ids]
    rows = (await session.execute(
        select(PatientRow.patient_id, PatientRow.firm_name, PatientRow.name)
        .where(PatientRow.patient_id.in_(patient_ids))
    )).all()
    names: dict[str, str] = {}
    for patient_id, firm_name, name in rows:
        raw = str(patient_id or "")
        pif_id = raw[4:] if raw.startswith("pif-") else raw[3:] if raw.startswith("mc-") else raw
        label = (firm_name or name or "").strip()
        if pif_id and label:
            names.setdefault(pif_id, label)
    return names


def _activity_to_signal_terms(activity: FrontFirmActivityRow) -> str:
    return json.dumps(
        {
            "domain": activity.domain,
            "inbox_breakdown": activity.inbox_breakdown or {},
            "tech_signals": activity.tech_signals or {},
        },
        sort_keys=True,
        default=str,
    ).lower()


def _suppression_reasons(activity: FrontFirmActivityRow) -> list[str]:
    terms = _activity_to_signal_terms(activity)
    reasons: list[str] = []
    if "collection" in terms or "collections" in terms:
        reasons.append("collections")
    if "non-payment" in terms or "nonpayment" in terms or "non payment" in terms:
        reasons.append("non_payment")
    return reasons


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
    now = _utcnow()
    since = now - timedelta(days=1)
    previous_since = now - timedelta(days=2)
    async with AsyncSessionLocal() as session:
        states = (await session.execute(select(FrontSyncStateRow).order_by(FrontSyncStateRow.key.asc()))).scalars().all()
        visible_states = [state for state in states if state.key != FRONT_LAST_RUN_STATE_KEY]
        last_run_state = next((state for state in states if state.key == FRONT_LAST_RUN_STATE_KEY), None)
        last_run = _safe_json_loads(last_run_state.cursor if last_run_state else None)
        contact_count = (await session.execute(select(func.count(FrontContactRow.front_id)))).scalar_one()
        activity_count = (await session.execute(select(func.count(FrontFirmActivityRow.domain)))).scalar_one()
        matched_count = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain)).where(FrontFirmActivityRow.pif_id.isnot(None))
        )).scalar_one()
        warm_count = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain)).where(FrontFirmActivityRow.warm_score > 0)
        )).scalar_one()
        front_firm_contacts = (await session.execute(
            select(func.count(FirmContactRow.id)).where(
                (FirmContactRow.source == "front") | FirmContactRow.front_contact_id.isnot(None)
            )
        )).scalar_one()
        latest_contact = (await session.execute(
            select(FrontContactRow).order_by(desc(FrontContactRow.first_synced_at)).limit(1)
        )).scalar_one_or_none()
        contact_last = (await session.execute(
            select(func.count(FrontContactRow.front_id)).where(FrontContactRow.first_synced_at >= since)
        )).scalar_one()
        contact_prev = (await session.execute(
            select(func.count(FrontContactRow.front_id))
            .where(FrontContactRow.first_synced_at >= previous_since)
            .where(FrontContactRow.first_synced_at < since)
        )).scalar_one()
        domains_last = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain)).where(FrontFirmActivityRow.last_seen_at >= since)
        )).scalar_one()
        domains_prev = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain))
            .where(FrontFirmActivityRow.last_seen_at >= previous_since)
            .where(FrontFirmActivityRow.last_seen_at < since)
        )).scalar_one()
        matched_last = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain))
            .where(FrontFirmActivityRow.pif_id.isnot(None))
            .where(FrontFirmActivityRow.last_seen_at >= since)
        )).scalar_one()
        matched_prev = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain))
            .where(FrontFirmActivityRow.pif_id.isnot(None))
            .where(FrontFirmActivityRow.last_seen_at >= previous_since)
            .where(FrontFirmActivityRow.last_seen_at < since)
        )).scalar_one()
        firm_contacts_last = (await session.execute(
            select(func.count(FirmContactRow.id))
            .where((FirmContactRow.source == "front") | FirmContactRow.front_contact_id.isnot(None))
            .where(FirmContactRow.created_at >= since)
        )).scalar_one()
        firm_contacts_prev = (await session.execute(
            select(func.count(FirmContactRow.id))
            .where((FirmContactRow.source == "front") | FirmContactRow.front_contact_id.isnot(None))
            .where(FirmContactRow.created_at >= previous_since)
            .where(FirmContactRow.created_at < since)
        )).scalar_one()
        warm_last = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain))
            .where(FrontFirmActivityRow.warm_score > 0)
            .where(FrontFirmActivityRow.last_seen_at >= since)
        )).scalar_one()
        warm_prev = (await session.execute(
            select(func.count(FrontFirmActivityRow.domain))
            .where(FrontFirmActivityRow.warm_score > 0)
            .where(FrontFirmActivityRow.last_seen_at >= previous_since)
            .where(FrontFirmActivityRow.last_seen_at < since)
        )).scalar_one()
        timing_rows = (await session.execute(
            select(FrontFirmActivityRow)
            .where(
                or_(
                    FrontFirmActivityRow.last_referral_at >= now - timedelta(days=7),
                    FrontFirmActivityRow.last_seen_at >= now - timedelta(days=30),
                )
            )
            .order_by(desc(FrontFirmActivityRow.last_seen_at))
            .limit(60)
        )).scalars().all()
        firm_names = await _firm_names_for_pifs(session, {row.pif_id for row in timing_rows if row.pif_id})
    latest_state_at = max((state.updated_at for state in visible_states if state.updated_at), default=None)
    latest_watermark = max((state.watermark for state in visible_states if state.watermark), default=None)
    last_run_at = parse_front_datetime(last_run.get("finished_at")) or latest_state_at
    interval_seconds = int(os.getenv("FRONT_SYNC_INTERVAL_SECONDS", "86400") or "86400")
    next_daily_run_at = last_run_at + timedelta(seconds=interval_seconds) if last_run_at else None
    state_payloads = [
        {
            "key": row.key,
            "cursor": row.cursor,
            "watermark": _iso(row.watermark),
            "updated_at": _iso(row.updated_at),
            "watermark_age_hours": _age_hours(row.watermark, now=now),
            "updated_age_hours": _age_hours(row.updated_at, now=now),
        }
        for row in visible_states
    ]
    stale = last_run_at is None or (now - last_run_at) > timedelta(hours=36)
    return {
        "counts": {
            "front_contacts": int(contact_count or 0),
            "front_firm_activity": int(activity_count or 0),
            "matched_domains": int(matched_count or 0),
            "warm_domains": int(warm_count or 0),
            "front_firm_contacts": int(front_firm_contacts or 0),
        },
        "table_counts": {
            "front_contacts": int(contact_count or 0),
            "front_firm_activity": int(activity_count or 0),
            "front_sync_state": len(visible_states),
            "front_firm_contacts": int(front_firm_contacts or 0),
        },
        "funnel": [
            {"key": "contacts", "label": "Contacts", **_day_delta(contact_count, contact_last, contact_prev)},
            {"key": "domains", "label": "Domains", **_day_delta(activity_count, domains_last, domains_prev)},
            {"key": "matched_firms", "label": "Matched firms", **_day_delta(matched_count, matched_last, matched_prev)},
            {"key": "firm_contacts_added", "label": "Firm contacts added", **_day_delta(front_firm_contacts, firm_contacts_last, firm_contacts_prev)},
            {"key": "warm_list_size", "label": "Warm-list size", **_day_delta(warm_count, warm_last, warm_prev)},
        ],
        "states": state_payloads,
        "sync_health": {
            "last_run_at": _iso(last_run_at),
            "last_run_age_hours": _age_hours(last_run_at, now=now),
            "calls_used": last_run.get("calls_used"),
            "call_budget": int(last_run.get("call_budget") or os.getenv("FRONT_SYNC_MAX_CALLS", "300") or 300),
            "latest_watermark": _iso(latest_watermark),
            "latest_watermark_age_hours": _age_hours(latest_watermark, now=now),
            "next_daily_run_at": _iso(next_daily_run_at),
            "last_error": last_run.get("error"),
            "stale": stale,
            "stale_after_hours": 36,
        },
        "last_run": last_run,
        "latest_contact_synced_at": _iso(latest_contact.first_synced_at if latest_contact else None),
        "timing_feed": [
            {
                "domain": row.domain,
                "pif_id": row.pif_id,
                "firm_name": firm_names.get(row.pif_id or "", row.domain),
                "event_at": _iso(row.last_referral_at or row.last_seen_at),
                "last_referral_at": _iso(row.last_referral_at),
                "last_seen_at": _iso(row.last_seen_at),
                "kind": "weekly_referrer" if row.last_referral_at and row.last_referral_at >= now - timedelta(days=7) else "onboarding_moment",
                "contact_count": row.contact_count,
                "warm_score": row.warm_score,
            }
            for row in timing_rows
        ],
    }


async def list_front_contacts(*, firm: str = "", domain: str = "", q: str = "", limit: int = 50) -> list[dict[str, Any]]:
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
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(
                FrontContactRow.name.ilike(like),
                FrontContactRow.primary_email.ilike(like),
                FrontContactRow.domain.ilike(like),
                FrontFirmActivityRow.pif_id.ilike(like),
            ))
        stmt = stmt.order_by(desc(FrontContactRow.front_updated_at)).limit(max(1, min(limit, 500)))
        rows = (await session.execute(stmt)).all()
    return [
        {
            "front_id": contact.front_id,
            "name": contact.name,
            "primary_email": contact.primary_email,
            "domain": contact.domain,
            "front_updated_at": _iso(contact.front_updated_at),
            "pif_id": activity.pif_id if activity else None,
            "warm_score": activity.warm_score if activity else 0,
            "tech_signals": activity.tech_signals if activity else {},
            "last_seen_at": _iso(activity.last_seen_at) if activity else None,
            "last_referral_at": _iso(activity.last_referral_at) if activity else None,
        }
        for contact, activity in rows
    ]


async def front_warm_firms(*, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    async with AsyncSessionLocal() as session:
        activities = (await session.execute(
            select(FrontFirmActivityRow)
            .where(FrontFirmActivityRow.pif_id.isnot(None))
            .where(FrontFirmActivityRow.warm_score > 0)
            .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
            .limit(limit)
        )).scalars().all()
        pif_ids = {row.pif_id for row in activities if row.pif_id}
        firm_names = await _firm_names_for_pifs(session, pif_ids)
        contact_rows = (await session.execute(
            select(FirmContactRow)
            .where(FirmContactRow.pif_id.in_(pif_ids) if pif_ids else False)
            .where(FirmContactRow.email.isnot(None))
            .order_by(FirmContactRow.pif_id.asc(), FirmContactRow.full_name.asc())
        )).scalars().all() if pif_ids else []
        emailed = set((await session.execute(
            select(EmailLogRow.recipient_email)
            .where(EmailLogRow.recipient_email.in_([c.email for c in contact_rows if c.email]))
        )).scalars().all()) if contact_rows else set()
    contacts_by_pif: dict[str, list[dict[str, Any]]] = {}
    for contact in contact_rows:
        email = (contact.email or "").strip().lower()
        if not is_human_named_contact(contact.full_name, email):
            continue
        contacts_by_pif.setdefault(contact.pif_id, []).append({
            "id": contact.id,
            "name": contact.full_name,
            "email": email,
            "title": contact.title,
            "emailed_before": email in emailed,
            "front_last_seen": _iso(contact.front_last_seen),
            "source": contact.source,
        })
    return [
        {
            "domain": activity.domain,
            "firm_name": firm_names.get(activity.pif_id or "", activity.domain),
            "pif_id": activity.pif_id,
            "pif_match": bool(activity.pif_id),
            "warm_score": activity.warm_score,
            "last_seen_at": _iso(activity.last_seen_at),
            "last_referral_at": _iso(activity.last_referral_at),
            "last_records_at": _iso(activity.last_records_at),
            "contact_count": activity.contact_count,
            "named_contacts": contacts_by_pif.get(activity.pif_id or "", []),
            "eligible_contact_count": sum(1 for c in contacts_by_pif.get(activity.pif_id or "", []) if not c["emailed_before"]),
            "tech_signals": activity.tech_signals or {},
            "inbox_breakdown": activity.inbox_breakdown or {},
        }
        for activity in activities
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


async def front_signals() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        activities = (await session.execute(select(FrontFirmActivityRow))).scalars().all()
    tech_counts: dict[str, dict[str, int]] = {}
    inbox_mix: dict[str, dict[str, Any]] = {}
    suppress_flagged: list[dict[str, Any]] = []
    for activity in activities:
        for key, value in (activity.tech_signals or {}).items():
            if value in (None, "", [], {}):
                continue
            bucket = tech_counts.setdefault(str(key), {})
            label = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
            bucket[label] = bucket.get(label, 0) + 1
        for inbox_id, stats_raw in (activity.inbox_breakdown or {}).items():
            stats = stats_raw if isinstance(stats_raw, dict) else {}
            label = str(stats.get("name") or inbox_id)
            row = inbox_mix.setdefault(str(inbox_id), {
                "inbox_id": str(inbox_id),
                "name": label,
                "domains": 0,
                "conversation_count": 0,
                "last_seen_at": None,
            })
            row["domains"] += 1
            row["conversation_count"] += int(stats.get("conversation_count") or 0)
            last_seen = parse_front_datetime(stats.get("last_seen_at"))
            existing = parse_front_datetime(row.get("last_seen_at"))
            if last_seen and (existing is None or last_seen > existing):
                row["last_seen_at"] = last_seen.isoformat()
        reasons = _suppression_reasons(activity)
        if reasons:
            suppress_flagged.append({
                "domain": activity.domain,
                "pif_id": activity.pif_id,
                "reasons": reasons,
                "warm_score": activity.warm_score,
                "last_seen_at": _iso(activity.last_seen_at),
            })
    return {
        "tech_stack_counts": [
            {"signal": key, "values": [{"value": value, "count": count} for value, count in sorted(values.items())]}
            for key, values in sorted(tech_counts.items())
        ],
        "inbox_activity_mix": sorted(inbox_mix.values(), key=lambda row: row["conversation_count"], reverse=True),
        "suppress_flagged_firms": sorted(suppress_flagged, key=lambda row: (row["reasons"], row["domain"])),
    }


def build_front_warm_reason_json(
    *,
    activity: FrontFirmActivityRow,
    contact: FirmContactRow,
    firm_name: str,
    policy_version: str,
) -> dict[str, Any]:
    return {
        "basis": "front-warm",
        "reason": (
            f"Front-warm firm selected from synced relationship signals: "
            f"warm_score={activity.warm_score}, contact_count={activity.contact_count}."
        ),
        "contact_source": contact.source or "front",
        "policy_version": policy_version,
        "action_type": "first_touch",
        "priority_bucket": "front_warm",
        "source_type": "front_warm_domain",
        "source_id": activity.domain,
        "signals": [
            "front_warm_score",
            "front_contact",
            "front_activity",
            *(
                ["recent_referral"] if activity.last_referral_at else []
            ),
        ],
        "next_operator_action": "review_and_approve",
        "selection_policy_version": policy_version,
        "score_breakdown": {
            "warm_score": int(activity.warm_score or 0),
            "contact_count": int(activity.contact_count or 0),
            "last_seen_at": _iso(activity.last_seen_at),
            "last_referral_at": _iso(activity.last_referral_at),
            "tech_signals": activity.tech_signals or {},
        },
        "selection_features": {
            "domain": activity.domain,
            "firm_name": firm_name,
            "pif_id": activity.pif_id,
            "front_contact_id": contact.front_contact_id,
            "front_last_seen": _iso(contact.front_last_seen),
            "inbox_breakdown": activity.inbox_breakdown or {},
        },
        "suppressions": [],
    }


async def create_front_warm_batch(
    *,
    domains: list[str],
    name: str | None = None,
    template_key: str = DEFAULT_TEMPLATE_KEY,
    created_by: str = "operator",
) -> dict[str, Any]:
    clean_domains = list(dict.fromkeys(filter(None, (normalize_domain(domain) for domain in domains))))
    if not clean_domains:
        raise ValueError("domains_required")
    policy = await ensure_default_policy()
    batch_id = _new_lead_gen_id()
    async with AsyncSessionLocal() as session:
        activities = (await session.execute(
            select(FrontFirmActivityRow)
            .where(FrontFirmActivityRow.domain.in_(clean_domains))
            .where(FrontFirmActivityRow.pif_id.isnot(None))
            .order_by(desc(FrontFirmActivityRow.warm_score), desc(FrontFirmActivityRow.last_seen_at))
        )).scalars().all()
        if not activities:
            raise ValueError("no_matched_front_warm_domains")
        pif_ids = {row.pif_id for row in activities if row.pif_id}
        firm_names = await _firm_names_for_pifs(session, pif_ids)
        contacts = (await session.execute(
            select(FirmContactRow)
            .where(FirmContactRow.pif_id.in_(pif_ids))
            .where(FirmContactRow.email.isnot(None))
            .order_by(FirmContactRow.pif_id.asc(), FirmContactRow.full_name.asc())
        )).scalars().all()
        emailed = {
            (email or "").strip().lower()
            for email in (await session.execute(
                select(EmailLogRow.recipient_email)
                .where(EmailLogRow.recipient_email.in_([c.email for c in contacts if c.email]))
            )).scalars().all()
        }
        contacts_by_pif: dict[str, list[FirmContactRow]] = {}
        for contact in contacts:
            email = (contact.email or "").strip().lower()
            if not is_human_named_contact(contact.full_name, email):
                continue
            if email in emailed:
                continue
            contacts_by_pif.setdefault(contact.pif_id, []).append(contact)
        selected: list[tuple[FrontFirmActivityRow, FirmContactRow, str]] = []
        for activity in activities:
            pif_contacts = contacts_by_pif.get(activity.pif_id or "", [])
            if not pif_contacts:
                continue
            firm_name = firm_names.get(activity.pif_id or "", activity.domain)
            selected.append((activity, pif_contacts[0], firm_name))
        if not selected:
            raise ValueError("no_eligible_named_contacts")
        batch = LeadGenBatchRow(
            id=batch_id,
            name=name or f"Front warm batch {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            target_metric=TARGET_METRIC,
            template_key=template_key,
            policy_version=policy.version,
            status="recommended",
            counts_json={
                "basis": "front-warm",
                "requested_domains": len(clean_domains),
                "matched_domains": len(activities),
                "items": len(selected),
            },
            created_by=created_by,
        )
        session.add(batch)
        await session.flush()
        for activity, contact, firm_name in selected:
            session.add(LeadGenBatchItemRow(
                id=_new_lead_gen_id(),
                batch_id=batch_id,
                contact_id=contact.id,
                pif_id=contact.pif_id,
                firm_name=firm_name,
                contact_name=contact.full_name or "",
                contact_email=(contact.email or "").strip().lower(),
                contact_title=contact.title or "",
                persona="front_warm_contact",
                template_key=template_key,
                score=int(activity.warm_score or 0),
                reason_json=build_front_warm_reason_json(
                    activity=activity,
                    contact=contact,
                    firm_name=firm_name,
                    policy_version=policy.version,
                ),
                approval_status="pending",
            ))
        await session.commit()
    batch_data = await get_batch(batch_id)
    batch_data["link"] = f"/lead-gen?batch={batch_id}"
    return batch_data


async def _save_front_last_run(payload: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        row = await _get_state(session, FRONT_LAST_RUN_STATE_KEY)
        row.cursor = json.dumps(payload, sort_keys=True, default=str)
        row.watermark = parse_front_datetime(payload.get("finished_at") or payload.get("started_at"))
        row.updated_at = _utcnow()
        await session.commit()


async def run_front_sync(*, max_calls: int = 300, full: bool = False) -> dict[str, Any]:
    started_at = _utcnow()
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
    await _save_front_last_run({
        "started_at": started_at.isoformat(),
        "finished_at": _utcnow().isoformat(),
        "calls_used": budget.calls_made,
        "call_budget": budget.max_calls,
        "full": full,
        "contacts": contacts,
        "activity": activity,
        "resolve": resolve,
        "scores": scores,
        "error": None,
    })
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
        except Exception as e:
            await _save_front_last_run({
                "started_at": _utcnow().isoformat(),
                "finished_at": _utcnow().isoformat(),
                "calls_used": None,
                "call_budget": max_calls,
                "full": False,
                "error": f"{type(e).__name__}: {str(e)[:500]}",
            })
        await asyncio.sleep(interval_seconds)
