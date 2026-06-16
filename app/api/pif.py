"""Native PI-firm directory (pulled from emailtag) endpoints.

Drives `bin/possibleos pif ...`. The directory mirrors emailtag's PifInfo into
possibleos Postgres so matching no longer depends on the stale mission.db cache.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.pif_directory import pif_directory_status, sync_pif_directory

router = APIRouter(prefix="/api/pif", tags=["pif-directory"])


@router.get("/status")
async def get_pif_status():
    return await pif_directory_status()


@router.post("/sync")
async def post_pif_sync(page_size: int = Query(100, ge=1, le=100)):
    try:
        return await sync_pif_directory(page_size=page_size)
    except Exception as exc:  # surface upstream API failures clearly to the CLI
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {str(exc)[:300]}")


@router.post("/ingest-contacts")
async def post_pif_ingest_contacts():
    """Populate firm_contacts from the synced directory's titled contacts +
    leadership, then map personas. Local-only (no upstream API calls)."""
    from app.services.firm_contacts_service import ingest_pif_directory_contacts

    try:
        return await ingest_pif_directory_contacts()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {str(exc)[:300]}")
