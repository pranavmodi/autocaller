"""Editable project todo endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.todos import create_todo, delete_todo, list_todos, update_todo


router = APIRouter(prefix="/api/todos", tags=["todos"])


class TodoCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    area: str = Field("general", max_length=64)
    section: str = Field("Not Started", max_length=64)
    status: str = Field("not_started", max_length=32)
    body: str = ""
    source_url: Optional[str] = Field(None, max_length=1024)
    actor: str = Field("operator", max_length=128)


class TodoUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    area: Optional[str] = Field(None, max_length=64)
    section: Optional[str] = Field(None, max_length=64)
    status: Optional[str] = Field(None, max_length=32)
    body: Optional[str] = None
    source_url: Optional[str] = Field(None, max_length=1024)
    actor: str = Field("operator", max_length=128)


@router.get("")
async def get_todos(
    area: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    return {"todos": await list_todos(area=area, status=status)}


@router.post("")
async def post_todo(req: TodoCreateRequest):
    try:
        return {"todo": await create_todo(**req.model_dump())}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/{todo_id}")
async def patch_todo(todo_id: int, req: TodoUpdateRequest):
    result = await update_todo(todo_id, **req.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(status_code=404, detail="todo_not_found")
    return {"todo": result}


@router.delete("/{todo_id}")
async def remove_todo(todo_id: int):
    deleted = await delete_todo(todo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="todo_not_found")
    return {"deleted": True, "id": todo_id}
