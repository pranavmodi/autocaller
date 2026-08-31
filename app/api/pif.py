"""Native PI-firm directory (pulled from emailtag) endpoints.

Drives `bin/possibleos pif ...`. The directory mirrors EmailTag firm-intel into
possibleos Postgres so matching no longer depends on the stale mission.db cache.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.firm_intel_sync import (
    firm_intel_status,
    firm_intel_sync_status,
    list_extracted_vendors,
    list_mirrored_pif_people_filter_options,
    list_mirrored_pif_people,
    list_mirrored_pif_job_postings,
    list_mirrored_pif_firms,
    sync_firm_intel,
)
from app.services.pif_firm_crud import (
    PifFirmConflictError,
    PifFirmCrudError,
    PifFirmNotFoundError,
    PifFirmProtectedError,
    create_pif_firm,
    delete_pif_firm,
    get_pif_firm_for_crud,
    update_pif_firm,
    upsert_pif_firm,
)
from app.services.pif_saved_searches import (
    create_saved_search,
    delete_saved_search,
    list_saved_searches,
    update_saved_search,
)
from app.services.pif_job_posting_research import (
    PifResearchUpstreamError,
    get_research_status,
    queue_job_posting_classification_backfill,
    start_job_posting_research,
)
from app.services.pif_local_enrichment import (
    PifLocalEnrichmentError,
    get_local_enrichment_status,
    start_local_firm_enrichment,
)
from app.services.pif_sitemap_monitor import list_firm_sitemap_history

router = APIRouter(prefix="/api/pif", tags=["pif-directory"])


class PifFirmWriteRequest(BaseModel):
    """Fields operators may write to a local firm-intel record."""

    model_config = ConfigDict(extra="forbid")

    firm_id: str | None = Field(None, max_length=64)
    firm_name: str | None = Field(None, max_length=512)
    website: str | None = Field(None, max_length=512)
    canonical_website: str | None = Field(None, max_length=512)
    entity_type: str | None = Field(None, max_length=64)
    metro: str | None = Field(None, max_length=128)
    warm_score: float | None = None
    emails: list[str] | None = None
    phones: list[str] | None = None
    fax: str | None = Field(None, max_length=64)
    addresses: list[Any] | None = None
    contacts: list[dict[str, Any]] | None = None
    leadership: list[dict[str, Any]] | None = None
    staff: list[dict[str, Any]] | None = None
    contact_profiles: dict[str, Any] | None = None
    research_data: dict[str, Any] | None = None
    behavioral_data: dict[str, Any] | None = None
    score_breakdown: dict[str, Any] | None = None
    conversation_ids: list[str] | None = None
    extraction_notes: str | None = None
    vendor_stack: dict[str, Any] | None = None
    icp_score: int | None = None
    icp_tier: str | None = Field(None, max_length=16)
    research_status: str | None = Field(None, max_length=32)
    staff_research_status: str | None = Field(None, max_length=32)
    first_contacted_precise_at: datetime | None = None
    last_researched_at: datetime | None = None
    icp_scored_at: datetime | None = None
    aliases: dict[str, list[str]] | None = None
    provenance: dict[str, Any] | None = None


class ContactSearchCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=255)
    firm: str | None = Field(None, max_length=512)
    vendor: str | None = Field(None, max_length=128)
    titles: list[str] = Field(default_factory=list)
    role_categories: list[str] = Field(default_factory=list)
    source: Literal["all", "leadership", "staff", "contacts"] = "all"
    leader: Literal["any", "leader", "non_leader"] = "any"
    email_presence: Literal["any", "has", "missing"] = "any"


class SavedLeadSearchCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    view: Literal["contacts", "firms"] = "contacts"
    criteria: dict[str, Any]
    actor: str = Field("operator", max_length=128)


class SavedLeadSearchUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=255)
    criteria: dict[str, Any] | None = None
    actor: str = Field("operator", max_length=128)


def _raise_crud_http(exc: PifFirmCrudError) -> None:
    if isinstance(exc, PifFirmNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (PifFirmConflictError, PifFirmProtectedError)):
        detail: dict[str, Any] = {"message": str(exc)}
        if isinstance(exc, PifFirmConflictError) and exc.firm_id:
            detail["firm_id"] = exc.firm_id
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _raise_research_http(exc: PifResearchUpstreamError) -> None:
    status_code = exc.status_code if exc.status_code in {400, 404, 409, 422, 429} else 502
    raise HTTPException(status_code=status_code, detail=exc.detail) from exc


def _raise_local_enrichment_http(exc: PifLocalEnrichmentError) -> None:
    status_code = exc.status_code if exc.status_code in {400, 404, 409, 422, 429} else 500
    raise HTTPException(status_code=status_code, detail=exc.detail) from exc


@router.get("/status")
async def get_pif_status():
    return await firm_intel_status()


@router.get("/sync-status")
async def get_pif_sync_status():
    return await firm_intel_sync_status()


@router.get("/vendors")
async def get_pif_vendors():
    return await list_extracted_vendors()


@router.get("/people/filter-options")
async def get_pif_people_filter_options():
    return await list_mirrored_pif_people_filter_options()


@router.get("/people")
async def get_pif_people(
    name: str | None = Query(None),
    firm: str | None = Query(None),
    vendor: str | None = Query(None, description="Exact extracted vendor key for the person's firm"),
    title: list[str] | None = Query(None, description="Repeat to match any selected title"),
    role_category: list[str] | None = Query(None, description="Repeat to match any selected role"),
    source: str | None = Query("all", description="all, leadership, staff, or contacts"),
    leader: str | None = Query("any", description="any, leader, or non_leader"),
    email_presence: str | None = Query("any", description="any, has, or missing"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    try:
        return await list_mirrored_pif_people(
            name=name,
            firm=firm,
            vendor=vendor,
            title=title,
            role_category=role_category,
            source=source,
            leader=leader,
            email_presence=email_presence,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/job-postings")
async def get_pif_job_postings(
    search: str | None = Query(None, max_length=255),
    role_category: str | None = Query(None, max_length=64),
    trigger_tag: str | None = Query(None, max_length=64),
    technology: str | None = Query(None, max_length=128),
    gtm_relevance: str | None = Query(None, max_length=16),
    posted_within_days: int | None = Query(None, ge=0, le=3650),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    try:
        return await list_mirrored_pif_job_postings(
            search=search,
            role_category=role_category,
            trigger_tag=trigger_tag,
            technology=technology,
            gtm_relevance=gtm_relevance,
            posted_within_days=posted_within_days,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/saved-searches")
async def get_saved_lead_searches(view: Literal["contacts", "firms"] = Query("contacts")):
    return {"saved_searches": await list_saved_searches(view=view)}


@router.post("/saved-searches", status_code=201)
async def post_saved_lead_search(req: SavedLeadSearchCreateRequest):
    try:
        search = await create_saved_search(
            name=req.name,
            view=req.view,
            criteria=req.criteria,
            actor=req.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"saved_search": search}


@router.patch("/saved-searches/{search_id}")
async def patch_saved_lead_search(search_id: str, req: SavedLeadSearchUpdateRequest):
    try:
        search = await update_saved_search(
            search_id,
            name=req.name,
            criteria=req.criteria,
            actor=req.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if search is None:
        raise HTTPException(status_code=404, detail="saved_search_not_found")
    return {"saved_search": search}


@router.delete("/saved-searches/{search_id}")
async def remove_saved_lead_search(search_id: str):
    if not await delete_saved_search(search_id):
        raise HTTPException(status_code=404, detail="saved_search_not_found")
    return {"deleted": True, "id": search_id}


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
    contact_email_min: int | None = Query(None, ge=0),
    contact_email_max: int | None = Query(None, ge=0),
    staff_count_min: int | None = Query(None, ge=0),
    staff_count_max: int | None = Query(None, ge=0),
    autorespond_window: str | None = Query(None),
    autorespond_type: str | None = Query(None),
    website_presence: str | None = Query(None),
    research_presence: str | None = Query(None),
    staff_presence: str | None = Query(None),
    job_postings_presence: str | None = Query(None),
    job_posting_role: str | None = Query(None),
    job_posting_tag: str | None = Query(None, max_length=64),
    job_posting_query: str | None = Query(None, max_length=255),
    job_posted_within_days: int | None = Query(None, ge=0, le=3650),
    behavior_presence: str | None = Query(None),
    icp_presence: str | None = Query(None),
    vendor_presence: str | None = Query(None),
    vendor: str | None = Query(None, description="Exact extracted vendor key, e.g. filevine"),
    manually_added: bool | None = Query(None, description="True for operator-created firms; false for sync-origin firms"),
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
        contact_email_min=contact_email_min,
        contact_email_max=contact_email_max,
        staff_count_min=staff_count_min,
        staff_count_max=staff_count_max,
        autorespond_window=autorespond_window,
        autorespond_type=autorespond_type,
        website_presence=website_presence,
        research_presence=research_presence,
        staff_presence=staff_presence,
        job_postings_presence=job_postings_presence,
        job_posting_role=job_posting_role,
        job_posting_tag=job_posting_tag,
        job_posting_query=job_posting_query,
        job_posted_within_days=job_posted_within_days,
        behavior_presence=behavior_presence,
        icp_presence=icp_presence,
        vendor_presence=vendor_presence,
        vendor=vendor,
        manually_added=manually_added,
        first_contacted_from=first_contacted_from,
        first_contacted_to=first_contacted_to,
        active_only=active_only,
    )


@router.get("/firms/{firm_id}")
async def get_pif_firm(firm_id: str):
    item = await get_pif_firm_for_crud(firm_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="firm_not_found")


@router.get("/firms/{firm_id}/sitemap-history")
async def get_pif_firm_sitemap_history(firm_id: str, limit: int = Query(20, ge=1, le=100)):
    try:
        return await list_firm_sitemap_history(firm_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/firms/{firm_id}/research-job-postings")
async def post_job_posting_research(firm_id: str):
    try:
        return await start_job_posting_research(firm_id)
    except PifResearchUpstreamError as exc:
        _raise_research_http(exc)


@router.post("/job-postings/classify")
async def post_job_posting_classification_backfill(force: bool = Query(False)):
    return await queue_job_posting_classification_backfill(force=force)


@router.post("/firms/{firm_id}/research")
async def post_local_firm_research(firm_id: str):
    try:
        return await start_local_firm_enrichment(firm_id)
    except PifLocalEnrichmentError as exc:
        _raise_local_enrichment_http(exc)


@router.get("/enrichment-status/{task_id}")
async def get_pif_local_enrichment_status(task_id: str):
    try:
        return await get_local_enrichment_status(task_id)
    except PifLocalEnrichmentError as exc:
        _raise_local_enrichment_http(exc)


@router.post("/firms/{firm_id}/analyze-behavior")
async def post_local_behavior_analysis(firm_id: str):
    from app.services.pif_local_derivations import analyze_behavior_locally

    result = await analyze_behavior_locally(firm_id)
    if result is None:
        raise HTTPException(status_code=404, detail="firm_not_found")
    return result


@router.post("/firms/{firm_id}/score")
async def post_local_firm_score(firm_id: str):
    from app.services.pif_local_derivations import score_firm_locally

    result = await score_firm_locally(firm_id)
    if result is None:
        raise HTTPException(status_code=404, detail="firm_not_found")
    return result


@router.get("/research-status/{task_id}")
async def get_pif_research_status(task_id: str):
    try:
        return await get_research_status(task_id)
    except PifResearchUpstreamError as exc:
        _raise_research_http(exc)


@router.post("/firms", status_code=201)
async def create_pif_firm_endpoint(
    request: PifFirmWriteRequest,
    dry_run: bool = Query(False),
):
    """Create an operator-managed firm, deduplicated by canonical domain."""
    try:
        return await create_pif_firm(
            request.model_dump(exclude_unset=True),
            dry_run=dry_run,
        )
    except PifFirmCrudError as exc:
        _raise_crud_http(exc)


@router.post("/firms/upsert")
async def upsert_pif_firm_endpoint(
    request: PifFirmWriteRequest,
    dry_run: bool = Query(False),
):
    """Create by canonical domain or patch the existing matching firm."""
    try:
        return await upsert_pif_firm(
            request.model_dump(exclude_unset=True),
            dry_run=dry_run,
        )
    except PifFirmCrudError as exc:
        _raise_crud_http(exc)


@router.patch("/firms/{firm_id}")
async def update_pif_firm_endpoint(
    firm_id: str,
    request: PifFirmWriteRequest,
    dry_run: bool = Query(False),
):
    """Partially update a firm by ID or canonical domain."""
    try:
        return await update_pif_firm(
            firm_id,
            request.model_dump(exclude_unset=True),
            dry_run=dry_run,
        )
    except PifFirmCrudError as exc:
        _raise_crud_http(exc)


@router.delete("/firms/{firm_id}")
async def delete_pif_firm_endpoint(
    firm_id: str,
    force: bool = Query(False),
    dry_run: bool = Query(False),
):
    """Delete a directory record and its aliases, preserving operational history."""
    try:
        return await delete_pif_firm(firm_id, force=force, dry_run=dry_run)
    except PifFirmCrudError as exc:
        _raise_crud_http(exc)


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
