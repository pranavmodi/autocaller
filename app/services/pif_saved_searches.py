"""Persistence and validation for reusable Leads contact searches."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal, async_engine
from app.db.models import SavedLeadSearchRow


CONTACT_SEARCH_DEFAULTS = {
    "source": "all",
    "leader": "any",
    "email_presence": "any",
}
CONTACT_SEARCH_KEYS = {
    "name",
    "firm",
    "vendor",
    "titles",
    "role_categories",
    "source",
    "leader",
    "email_presence",
}
FIRM_TRIGGER_SEARCH_DEFAULTS = {
    "sort_by": "updated_at",
    "autorespond_window": "any",
    "website_presence": "any",
    "research_presence": "any",
    "staff_presence": "any",
    "job_postings_presence": "any",
    "behavior_presence": "any",
    "icp_presence": "any",
    "vendor_presence": "any",
    "record_origin": "any",
    "first_contact_period": "any",
    "active_only": True,
}
FIRM_TRIGGER_SEARCH_KEYS = {
    "search", "sort_by", "icp_tier", "entity_type", "recently_researched",
    "contact_email_range", "staff_count_range", "autorespond_window", "autorespond_type",
    "website_presence", "research_presence", "staff_presence", "job_postings_presence",
    "job_posting_role", "job_posting_tag", "job_posting_query", "job_posted_within_days",
    "behavior_presence", "icp_presence", "vendor_presence", "vendor", "record_origin",
    "first_contact_period", "first_contacted_from", "first_contacted_to", "active_only",
}
_table_checked = False


def normalize_contact_search_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    unknown = set(criteria) - CONTACT_SEARCH_KEYS
    if unknown:
        raise ValueError(f"unsupported_search_criteria:{','.join(sorted(unknown))}")

    normalized: dict[str, Any] = dict(CONTACT_SEARCH_DEFAULTS)
    for key in ("name", "firm", "vendor"):
        value = str(criteria.get(key) or "").strip()
        if value:
            normalized[key] = value.lower() if key == "vendor" else value
    for key in ("titles", "role_categories"):
        values = criteria.get(key) or []
        cleaned = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if cleaned:
            normalized[key] = cleaned

    source = str(criteria.get("source") or "all").strip().lower()
    leader = str(criteria.get("leader") or "any").strip().lower()
    email_presence = str(criteria.get("email_presence") or "any").strip().lower()
    if source not in {"all", "leadership", "staff", "contacts"}:
        raise ValueError(f"unsupported_contact_source:{source}")
    if leader not in {"any", "leader", "non_leader"}:
        raise ValueError(f"unsupported_leader_filter:{leader}")
    if email_presence not in {"any", "has", "missing"}:
        raise ValueError(f"unsupported_email_presence:{email_presence}")
    normalized.update({
        "source": source,
        "leader": leader,
        "email_presence": email_presence,
    })
    return normalized


def normalize_firm_trigger_search_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    unknown = set(criteria) - FIRM_TRIGGER_SEARCH_KEYS
    if unknown:
        raise ValueError(f"unsupported_search_criteria:{','.join(sorted(unknown))}")

    normalized: dict[str, Any] = dict(FIRM_TRIGGER_SEARCH_DEFAULTS)
    for key in (
        "search", "icp_tier", "entity_type", "contact_email_range", "staff_count_range",
        "autorespond_type", "vendor", "first_contacted_from", "first_contacted_to",
        "job_posting_query", "job_posting_tag",
    ):
        value = str(criteria.get(key) or "").strip()
        if value:
            normalized[key] = value.lower() if key == "vendor" else value

    enum_values = {
        "sort_by": {"updated_at", "first_contacted_precise_at", "firm_name", "conversation_count"},
        "autorespond_window": {"any", "24h", "7d", "30d", "90d", "ever", "never"},
        "website_presence": {"any", "has", "missing", "resolved", "unresolved"},
        "research_presence": {"any", "completed", "missing", "queued_or_running", "failed"},
        "staff_presence": {"any", "completed", "missing", "queued_or_running", "failed"},
        "job_postings_presence": {"any", "has", "none", "not_researched", "queued_or_running", "failed"},
        "job_posting_role": {"", "intake", "marketing", "case_operations", "firm_operations", "technology"},
        "behavior_presence": {"any", "has", "missing"},
        "icp_presence": {"any", "has", "missing"},
        "vendor_presence": {"any", "has", "missing"},
        "record_origin": {"any", "manual", "synced"},
        "first_contact_period": {"any", "last_1_month", "last_6_months", "custom"},
    }
    for key, allowed in enum_values.items():
        value = str(criteria.get(key) or FIRM_TRIGGER_SEARCH_DEFAULTS.get(key) or "").strip()
        if value not in allowed:
            raise ValueError(f"unsupported_{key}:{value}")
        if value:
            normalized[key] = value

    for key in ("recently_researched", "job_posted_within_days"):
        raw = criteria.get(key)
        if raw not in (None, ""):
            value = int(raw)
            if value < 0 or value > 3650:
                raise ValueError(f"unsupported_{key}:{value}")
            normalized[key] = str(value)
    normalized["active_only"] = bool(criteria.get("active_only", True))
    return normalized


def normalize_saved_search_criteria(view: str, criteria: dict[str, Any]) -> dict[str, Any]:
    if view == "contacts":
        return normalize_contact_search_criteria(criteria)
    if view == "firms":
        return normalize_firm_trigger_search_criteria(criteria)
    raise ValueError(f"unsupported_saved_search_view:{view}")


def saved_search_to_dict(row: SavedLeadSearchRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "view": row.view,
        "criteria": row.criteria_json or {},
        "schema_version": row.schema_version,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def ensure_saved_searches_table() -> None:
    global _table_checked
    if _table_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(SavedLeadSearchRow.__table__.create, checkfirst=True)
    _table_checked = True


async def list_saved_searches(*, view: str = "contacts") -> list[dict[str, Any]]:
    await ensure_saved_searches_table()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(SavedLeadSearchRow)
            .where(SavedLeadSearchRow.view == view)
            .order_by(SavedLeadSearchRow.name.asc())
        )).scalars().all()
        return [saved_search_to_dict(row) for row in rows]


async def create_saved_search(
    *,
    name: str,
    criteria: dict[str, Any],
    view: str = "contacts",
    actor: str = "operator",
) -> dict[str, Any]:
    if view not in {"contacts", "firms"}:
        raise ValueError(f"unsupported_saved_search_view:{view}")
    await ensure_saved_searches_table()
    row = SavedLeadSearchRow(
        id=uuid4().hex,
        name=name.strip(),
        view=view,
        criteria_json=normalize_saved_search_criteria(view, criteria),
        schema_version=1,
        created_by=actor,
        updated_by=actor,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("saved_search_name_exists") from exc
        await session.refresh(row)
        return saved_search_to_dict(row)


async def update_saved_search(
    search_id: str,
    *,
    name: str | None = None,
    criteria: dict[str, Any] | None = None,
    actor: str = "operator",
) -> dict[str, Any] | None:
    await ensure_saved_searches_table()
    async with AsyncSessionLocal() as session:
        row = await session.get(SavedLeadSearchRow, search_id)
        if row is None:
            return None
        if name is not None:
            row.name = name.strip()
        if criteria is not None:
            row.criteria_json = normalize_saved_search_criteria(row.view, criteria)
        row.updated_by = actor
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("saved_search_name_exists") from exc
        await session.refresh(row)
        return saved_search_to_dict(row)


async def delete_saved_search(search_id: str) -> bool:
    await ensure_saved_searches_table()
    async with AsyncSessionLocal() as session:
        row = await session.get(SavedLeadSearchRow, search_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
