"""Database operations for operator-captured knowledge."""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from app.db import AsyncSessionLocal, async_engine
from app.db.models import KnowledgeEntryRow


_knowledge_table_checked = False


def derive_title(content: str) -> str:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "Untitled entry")
    return first_line[:252] + "..." if len(first_line) > 255 else first_line


def normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = tag.strip().lower()[:64]
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized[:20]


def knowledge_entry_to_dict(row: KnowledgeEntryRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "content": row.content,
        "source_type": row.source_type,
        "source_url": row.source_url,
        "author": row.author,
        "tags": row.tags or [],
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def ensure_knowledge_table() -> None:
    global _knowledge_table_checked
    if _knowledge_table_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(KnowledgeEntryRow.__table__.create, checkfirst=True)
    _knowledge_table_checked = True


async def create_knowledge_entry(
    *,
    content: str,
    title: str | None = None,
    source_type: str = "web",
    source_url: str | None = None,
    author: str | None = None,
    tags: list[str] | None = None,
    actor: str = "operator",
) -> dict[str, Any]:
    await ensure_knowledge_table()
    clean_content = content.strip()
    row = KnowledgeEntryRow(
        title=(title or "").strip() or derive_title(clean_content),
        content=clean_content,
        source_type=source_type,
        source_url=(source_url or "").strip() or None,
        author=(author or "").strip() or None,
        tags=normalize_tags(tags or []),
        created_by=actor,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return knowledge_entry_to_dict(row)


async def list_knowledge_entries(
    *, query: str | None = None, source_type: str | None = None, limit: int = 100,
) -> list[dict[str, Any]]:
    await ensure_knowledge_table()
    async with AsyncSessionLocal() as session:
        stmt = select(KnowledgeEntryRow).order_by(KnowledgeEntryRow.created_at.desc()).limit(limit)
        if source_type:
            stmt = stmt.where(KnowledgeEntryRow.source_type == source_type)
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(or_(
                KnowledgeEntryRow.title.ilike(pattern),
                KnowledgeEntryRow.content.ilike(pattern),
                KnowledgeEntryRow.author.ilike(pattern),
                KnowledgeEntryRow.source_url.ilike(pattern),
            ))
        rows = (await session.execute(stmt)).scalars().all()
        return [knowledge_entry_to_dict(row) for row in rows]


async def delete_knowledge_entry(entry_id: int) -> bool:
    await ensure_knowledge_table()
    async with AsyncSessionLocal() as session:
        row = await session.get(KnowledgeEntryRow, entry_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
