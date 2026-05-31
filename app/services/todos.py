"""DB-backed editable project todos."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import AsyncSessionLocal, async_engine
from app.db.models import TodoRow


_todos_table_checked = False


DEFAULT_TODOS: list[dict[str, Any]] = [
    {
        "area": "lead-gen",
        "section": "Not Started",
        "title": "Review Mich Lieben X Post For Lead-Gen Workflow Idea",
        "status": "not_started",
        "source_url": "https://x.com/MichLieben/status/2059265591761055888",
        "body": (
            "Status: Not started\n\n"
            "Source: https://x.com/MichLieben/status/2059265591761055888\n\n"
            "Acceptance Criteria:\n"
            "- Retrieve or manually capture the post contents.\n"
            "- Translate the idea into a concrete lead-gen workflow improvement.\n"
            "- Add implementation scope, safety rails, UI behavior, backend contract, "
            "CLI affordance, and verification plan before coding."
        ),
    },
    *[
        {
            "area": "lead-gen",
            "section": section,
            "title": title,
            "status": status,
            "source_url": None,
            "body": f"Status: {label}\n\nMigrated from the legacy lead-gen markdown backlog.",
        }
        for section, status, label, title in [
            ("Done", "done", "Done", "Dynamic Email Composer Skill"),
            ("Done", "done", "Done", "Human Approval For Every Generated Email"),
            ("Done", "done", "Done", "Non-Blocking Operator Action Center"),
            ("Done", "done", "Done", "Daily Send Budget"),
            ("Done", "done", "Done", "Daily Action Planner"),
            ("Done", "done", "Done", "California Scheduling And One-Hour Staggering"),
            ("Done", "done", "Done", "Explainable Contact-Selection Scorer"),
            ("Done", "done", "Done", "Zoho Inbound Reply Polling"),
            ("Done", "done_in_code", "Done in code, production config still required", "Resend Webhook Ingestion"),
            ("Done", "done_partial", "Done for proposal creation, not done for apply flow", "Policy Proposal Generation"),
            ("In Progress", "in_progress", "In progress", "First-Class Suppressions"),
            ("In Progress", "in_progress", "In progress", "Automated Inbox Polling"),
            ("In Progress", "in_progress", "In progress", "Delivery Feedback Productionization"),
            ("Not Started", "not_started", "Not started", "Daily Runner"),
            ("Not Started", "not_started", "Not started", "Contact Curation Skill"),
            ("Not Started", "not_started", "Not started", "Tool-Using Composer Agent"),
            ("Not Started", "not_started", "Not started", "Front Read-Only Enrichment"),
            ("Not Started", "not_started", "Not started", "Improved Reply Matching"),
            ("Not Started", "not_started", "Not started", "Observation Normalizer"),
            ("Not Started", "not_started", "Not started", "Booking Feedback"),
            ("Not Started", "not_started", "Not started", "Experiment Assignment"),
            ("Not Started", "not_started", "Not started", "Policy And Skill Proposal Upgrade"),
            ("Not Started", "not_started", "Not started", "Policy And Skill Apply Flow"),
            ("Not Started", "not_started", "Not started", "Control Dashboard"),
            ("Not Started", "not_started", "Not started", "Dashboard Signal Separation"),
            ("Not Started", "not_started", "Not started", "Safety Gates"),
            ("Not Started", "not_started", "Not started", "Gradual Automation"),
            ("Deferred", "deferred", "Deferred", "Non-Email Channels"),
        ]
    ],
]


def todo_to_dict(row: TodoRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "area": row.area,
        "section": row.section,
        "title": row.title,
        "status": row.status,
        "body": row.body,
        "source_url": row.source_url,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def ensure_todos_table() -> None:
    """Create the todo table on demand if Alembic has not run yet."""
    global _todos_table_checked
    if _todos_table_checked:
        return
    async with async_engine.begin() as conn:
        await conn.run_sync(TodoRow.__table__.create, checkfirst=True)
    _todos_table_checked = True


async def seed_default_todos() -> None:
    await ensure_todos_table()
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(TodoRow.id).limit(1))).first()
        if existing:
            return
        for item in DEFAULT_TODOS:
            session.add(TodoRow(created_by="migration", updated_by="migration", **item))
        await session.commit()


async def list_todos(*, area: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    await seed_default_todos()
    async with AsyncSessionLocal() as session:
        stmt = select(TodoRow).order_by(TodoRow.area.asc(), TodoRow.id.asc())
        if area:
            stmt = stmt.where(TodoRow.area == area)
        if status:
            stmt = stmt.where(TodoRow.status == status)
        rows = (await session.execute(stmt)).scalars().all()
        return [todo_to_dict(row) for row in rows]


async def create_todo(
    *,
    title: str,
    area: str = "general",
    section: str = "Not Started",
    status: str = "not_started",
    body: str = "",
    source_url: str | None = None,
    actor: str = "operator",
) -> dict[str, Any]:
    await ensure_todos_table()
    async with AsyncSessionLocal() as session:
        row = TodoRow(
            area=area,
            section=section,
            title=title,
            status=status,
            body=body,
            source_url=source_url,
            created_by=actor,
            updated_by=actor,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            raise ValueError("todo_already_exists") from e
        await session.refresh(row)
        return todo_to_dict(row)


async def update_todo(todo_id: int, **updates: Any) -> dict[str, Any] | None:
    await ensure_todos_table()
    async with AsyncSessionLocal() as session:
        row = await session.get(TodoRow, todo_id)
        if not row:
            return None
        actor = updates.pop("actor", "operator")
        for field in ("area", "section", "title", "status", "body", "source_url"):
            if field in updates:
                setattr(row, field, updates[field])
        row.updated_by = actor
        if row.status == "done" and row.completed_at is None:
            row.completed_at = datetime.now(timezone.utc)
        if row.status != "done":
            row.completed_at = None
        await session.commit()
        await session.refresh(row)
        return todo_to_dict(row)


async def delete_todo(todo_id: int) -> bool:
    await ensure_todos_table()
    async with AsyncSessionLocal() as session:
        row = await session.get(TodoRow, todo_id)
        if not row:
            return False
        await session.delete(row)
        await session.commit()
        return True
