"""Durable inbox for quickly captured company job links."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal, async_engine
from app.db.models import QuickJobLinkRow


_table_checked = False


def quick_job_link_to_dict(row: QuickJobLinkRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "company_name": row.company_name,
        "job_url": row.job_url,
        "link_type": row.link_type,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def ensure_quick_job_links_table() -> None:
    global _table_checked
    if _table_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(QuickJobLinkRow.__table__.create, checkfirst=True)
    _table_checked = True


async def create_quick_job_link(
    *, company_name: str, job_url: str, link_type: str = "job", actor: str = "operator",
) -> dict[str, Any]:
    await ensure_quick_job_links_table()
    row = QuickJobLinkRow(
        company_name=company_name.strip(),
        job_url=job_url.strip(),
        link_type=link_type,
        created_by=actor,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("job_link_already_saved") from exc
        await session.refresh(row)
        return quick_job_link_to_dict(row)


async def list_quick_job_links(
    *, link_type: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    await ensure_quick_job_links_table()
    async with AsyncSessionLocal() as session:
        stmt = select(QuickJobLinkRow)
        if link_type:
            stmt = stmt.where(QuickJobLinkRow.link_type == link_type)
        rows = (await session.execute(
            stmt.order_by(QuickJobLinkRow.created_at.desc(), QuickJobLinkRow.id.desc()).limit(limit)
        )).scalars().all()
        return [quick_job_link_to_dict(row) for row in rows]


async def delete_quick_job_link(link_id: int) -> bool:
    await ensure_quick_job_links_table()
    async with AsyncSessionLocal() as session:
        row = await session.get(QuickJobLinkRow, link_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
