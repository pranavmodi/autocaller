"""Knowledge capture and retrieval endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from app.services.knowledge import (
    create_knowledge_entry,
    delete_knowledge_entry,
    list_knowledge_entries,
)


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
SourceType = Literal["linkedin", "web", "article", "transcript", "note", "other"]


class KnowledgeCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=250_000)
    title: str | None = Field(None, max_length=255)
    source_type: SourceType = "web"
    source_url: HttpUrl | None = None
    author: str | None = Field(None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=20)
    actor: str = Field("operator", max_length=128)


@router.get("")
async def get_knowledge_entries(
    query: str | None = Query(None, max_length=255),
    source_type: SourceType | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    entries = await list_knowledge_entries(query=query, source_type=source_type, limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.post("", status_code=201)
async def post_knowledge_entry(req: KnowledgeCreateRequest):
    payload = req.model_dump()
    payload["source_url"] = str(req.source_url) if req.source_url else None
    return {"entry": await create_knowledge_entry(**payload)}


@router.delete("/{entry_id}")
async def remove_knowledge_entry(entry_id: int):
    if not await delete_knowledge_entry(entry_id):
        raise HTTPException(status_code=404, detail="knowledge_entry_not_found")
    return {"deleted": True, "id": entry_id}
