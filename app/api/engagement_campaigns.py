"""Cross-channel campaign management and public tracking redirects."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.services.engagement_campaigns import (
    EngagementCampaignError,
    campaign_analytics,
    create_campaign,
    create_tracking_link,
    list_campaigns,
    mark_tracking_link_sent,
    record_campaign_click,
    search_contacts,
    tracked_destination,
)
from app.services.lead_gen_cybernetic import record_observation


router = APIRouter(tags=["engagement-campaigns"])


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    campaign_date: date
    timezone: str = Field(default="UTC", max_length=64)
    workflow: str = Field(default="content", max_length=64)
    destination_url: str = Field(default="", max_length=2048)
    notes: str = Field(default="", max_length=4000)
    created_by: str = Field(default="operator", max_length=128)


class CampaignLinkCreateRequest(BaseModel):
    channel: Literal["email", "linkedin", "public"]
    destination_url: str = Field(default="", max_length=2048)
    contact_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=255)
    mark_sent: bool = False


def _raise_campaign_error(exc: EngagementCampaignError) -> None:
    detail = str(exc)
    status = 404 if detail in {
        "campaign_not_found",
        "contact_not_found",
        "tracking_link_not_found",
    } else 400
    raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/api/engagement-campaigns")
async def create_campaign_endpoint(req: CampaignCreateRequest):
    try:
        return await create_campaign(
            name=req.name,
            campaign_date=req.campaign_date,
            timezone_name=req.timezone,
            workflow=req.workflow,
            destination_url=req.destination_url,
            notes=req.notes,
            created_by=req.created_by,
        )
    except EngagementCampaignError as exc:
        _raise_campaign_error(exc)


@router.get("/api/engagement-campaigns")
async def list_campaigns_endpoint(
    search: str = Query("", max_length=255),
    limit: int = Query(100, ge=1, le=500),
):
    return {"campaigns": await list_campaigns(search=search, limit=limit)}


@router.get("/api/engagement-campaigns/contact-options")
async def campaign_contact_options(
    q: str = Query("", max_length=255),
    limit: int = Query(30, ge=1, le=100),
):
    return {"contacts": await search_contacts(query=q, limit=limit)}


@router.get("/api/engagement-campaigns/{campaign_id}")
async def get_campaign_endpoint(campaign_id: str):
    try:
        return await campaign_analytics(campaign_id)
    except EngagementCampaignError as exc:
        _raise_campaign_error(exc)


@router.get("/api/engagement-campaigns/{campaign_id}/analytics")
async def campaign_analytics_endpoint(campaign_id: str):
    try:
        return await campaign_analytics(campaign_id)
    except EngagementCampaignError as exc:
        _raise_campaign_error(exc)


@router.post("/api/engagement-campaigns/{campaign_id}/links")
async def create_campaign_link_endpoint(campaign_id: str, req: CampaignLinkCreateRequest):
    try:
        return await create_tracking_link(
            campaign_id=campaign_id,
            channel=req.channel,
            destination_url=req.destination_url,
            contact_id=req.contact_id,
            label=req.label,
            mark_sent=req.mark_sent,
        )
    except EngagementCampaignError as exc:
        _raise_campaign_error(exc)


@router.post("/api/engagement-campaigns/links/{code}/mark-sent")
async def mark_campaign_link_sent_endpoint(code: str):
    try:
        return await mark_tracking_link_sent(code)
    except EngagementCampaignError as exc:
        _raise_campaign_error(exc)


@router.get("/t/{code}")
async def campaign_tracking_redirect(code: str, request: Request):
    forwarded = request.headers.get("x-forwarded-for") or ""
    ip = next((part.strip() for part in forwarded.split(",") if part.strip()), "")
    if not ip and request.client:
        ip = request.client.host
    recorded = await record_campaign_click(
        code,
        ip=ip,
        user_agent=request.headers.get("user-agent") or "",
        referer=request.headers.get("referer") or "",
    )
    if recorded is None:
        return RedirectResponse("https://getpossibleminds.com", status_code=302)
    link, campaign, click = recorded
    await record_observation(
        event_type="link_clicked",
        raw_event={
            "source": f"campaign_{link.channel}",
            "channel": link.channel,
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "click_id": click.id,
            "link_code": link.code,
        },
        contact_id=link.contact_id,
        infer_batch_from_contact=False,
    )
    return RedirectResponse(tracked_destination(link, campaign, click.id), status_code=302)
