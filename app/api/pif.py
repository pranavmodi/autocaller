"""Native PI-firm directory (pulled from emailtag) endpoints.

Drives `bin/possibleos pif ...`. The directory mirrors EmailTag firm-intel into
possibleos Postgres so matching no longer depends on the stale mission.db cache.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.firm_intel_sync import (
    firm_intel_status,
    firm_intel_sync_status,
    get_mirrored_pif_firm,
    list_extracted_vendors,
    list_mirrored_pif_people,
    list_mirrored_pif_firms,
    sync_firm_intel,
)

router = APIRouter(prefix="/api/pif", tags=["pif-directory"])


@router.get("/status")
async def get_pif_status():
    return await firm_intel_status()


@router.get("/sync-status")
async def get_pif_sync_status():
    return await firm_intel_sync_status()


@router.get("/vendors")
async def get_pif_vendors():
    return await list_extracted_vendors()


@router.get("/people")
async def get_pif_people(
    name: str | None = Query(None),
    firm: str | None = Query(None),
    title: str | None = Query(None),
    role_category: str | None = Query(None),
    source: str | None = Query("all", description="all, leadership, staff, or contacts"),
    leader: str | None = Query("any", description="any, leader, or non_leader"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    return await list_mirrored_pif_people(
        name=name,
        firm=firm,
        title=title,
        role_category=role_category,
        source=source,
        leader=leader,
        page=page,
        page_size=page_size,
    )


@router.get("/firms")
async def get_pif_firms(
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    sort_by: str | None = Query("updated_at"),
    research_status: str | None = Query(None),
    icp_tier: str | None = Query(None),
    entity_type: str | None = Query(None),
    recently_researched: int | None = Query(None, ge=0),
    website_presence: str | None = Query(None),
    research_presence: str | None = Query(None),
    staff_presence: str | None = Query(None),
    behavior_presence: str | None = Query(None),
    icp_presence: str | None = Query(None),
    vendor_presence: str | None = Query(None),
    vendor: str | None = Query(None, description="Exact extracted vendor key, e.g. filevine"),
    first_contacted_from: date | None = Query(None),
    first_contacted_to: date | None = Query(None),
    active_only: bool = Query(True),
):
    return await list_mirrored_pif_firms(
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        research_status=research_status,
        icp_tier=icp_tier,
        entity_type=entity_type,
        recently_researched=recently_researched,
        website_presence=website_presence,
        research_presence=research_presence,
        staff_presence=staff_presence,
        behavior_presence=behavior_presence,
        icp_presence=icp_presence,
        vendor_presence=vendor_presence,
        vendor=vendor,
        first_contacted_from=first_contacted_from,
        first_contacted_to=first_contacted_to,
        active_only=active_only,
    )


@router.get("/firms/{firm_id}")
async def get_pif_firm(firm_id: str):
    item = await get_mirrored_pif_firm(firm_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="firm_not_found")


@router.post("/sync")
async def post_pif_sync(
    full: bool = Query(False),
    limit: int | None = Query(None, ge=1),
):
    try:
        return await sync_firm_intel(full=full, limit=limit)
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
