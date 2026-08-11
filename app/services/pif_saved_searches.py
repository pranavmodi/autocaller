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
    if view != "contacts":
        raise ValueError(f"unsupported_saved_search_view:{view}")
    await ensure_saved_searches_table()
    row = SavedLeadSearchRow(
        id=uuid4().hex,
        name=name.strip(),
        view=view,
        criteria_json=normalize_contact_search_criteria(criteria),
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
            row.criteria_json = normalize_contact_search_criteria(criteria)
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
