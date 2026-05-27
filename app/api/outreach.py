"""Outreach API — blog-post campaigns, per-recipient compose/preview/send,
plus the public open-pixel + click-redirect endpoints.

All `/api/outreach/*` routes are auth-gated by the global middleware.
The `/t/o/` and `/t/c/` routes are public (email clients fetch them) —
they're added to `_AUTH_EXEMPT_PREFIXES` in main.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.services import outreach_service as svc
from app.services import blog_post_service


router = APIRouter(tags=["outreach"])


# --- Schemas ---------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    post_slug: str
    name: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    sender_title: Optional[str] = None
    bcc_email: Optional[str] = None
    intent: str = "share"
    notes: Optional[str] = None
    with_excerpts: bool = True
    composer_model: str = "openclaw"


class CampaignDTO(BaseModel):
    id: int
    name: str
    post_slug: str
    post_title: str
    status: str
    intent: str
    sender_name: str
    sender_email: str
    bcc_email: Optional[str] = None
    created_at: str


class CampaignDetailDTO(CampaignDTO):
    post_url: str
    post_description: str
    post_category: Optional[str]
    post_tags: list[str]
    post_excerpts: list[str]
    sender_title: Optional[str]
    composer_model: str
    notes: Optional[str]
    updated_at: str
    stats: "CampaignStatsDTO"


class CampaignStatsDTO(BaseModel):
    campaign_id: int
    total: int
    pending: int
    composed: int
    sent: int
    skipped: int
    failed: int
    opens: int
    unique_opens: int
    clicks: int
    unique_clicks: int


class AddAudienceRequest(BaseModel):
    contact_ids: list[str] = Field(default_factory=list)
    pif_ids: list[str] = Field(default_factory=list)
    exclude_recent_days: int = 14


class AudienceResultDTO(BaseModel):
    added: int
    skipped_no_email: int
    skipped_duplicate: int
    skipped_recent_outreach: int


class SendDTO(BaseModel):
    id: int
    campaign_id: int
    contact_id: Optional[str]
    pif_id: Optional[str]
    recipient_email: str
    recipient_name: Optional[str]
    recipient_first_name: Optional[str]
    recipient_title: Optional[str]
    firm_name: Optional[str]
    token: str
    status: str
    composed_subject: Optional[str]
    composed_preheader: Optional[str]
    composed_body_html: Optional[str]
    composed_plaintext: Optional[str]
    composed_reasoning: Optional[str]
    composed_at: Optional[str]
    composer_model: Optional[str]
    edited_subject: Optional[str]
    edited_body_html: Optional[str]
    edited_plaintext: Optional[str]
    edited_by: Optional[str]
    edited_at: Optional[str]
    skip_reason: Optional[str]
    failure_reason: Optional[str]
    send_attempted_at: Optional[str]
    sent_at: Optional[str]
    message_id: Optional[str]
    transport: Optional[str]
    # Engagement aggregates (populated by list endpoints; zero if no events).
    opens: int = 0
    clicks: int = 0
    last_event_at: Optional[str] = None


class LinkEventDTO(BaseModel):
    """One open/click event with the recipient email pre-joined for display."""
    id: int
    send_id: int
    recipient_email: str
    kind: str  # 'open' | 'click'
    url: Optional[str]
    ip: Optional[str]
    user_agent: Optional[str]
    ts: str


class ComposeRequest(BaseModel):
    regenerate: bool = False
    model: Optional[str] = None


class PreviewDTO(BaseModel):
    send_id: int
    subject: str
    full_html: str
    full_plaintext: str
    from_header: str
    to: str
    tracked_click_url: str
    open_pixel_url: str


class SkipRequest(BaseModel):
    reason: str


class EditRequest(BaseModel):
    subject: Optional[str] = None
    body_html: Optional[str] = None
    plaintext: Optional[str] = None
    by: Optional[str] = None


class SendResultDTO(BaseModel):
    send_id: int
    message_id: str
    transport: str


class BlogPostSlugDTO(BaseModel):
    slug: str


# --- Helpers ---------------------------------------------------------------

def _send_to_dto(row, engagement=None) -> SendDTO:
    """engagement: optional SendEngagement; when None, opens/clicks default to 0.
    Pass it on list endpoints to avoid N+1 queries."""
    return SendDTO(
        id=row.id,
        campaign_id=row.campaign_id,
        contact_id=row.contact_id,
        pif_id=row.pif_id,
        recipient_email=row.recipient_email,
        recipient_name=row.recipient_name,
        recipient_first_name=row.recipient_first_name,
        recipient_title=row.recipient_title,
        firm_name=row.firm_name,
        token=row.token,
        status=row.status,
        composed_subject=row.composed_subject,
        composed_preheader=row.composed_preheader,
        composed_body_html=row.composed_body_html,
        composed_plaintext=row.composed_plaintext,
        composed_reasoning=row.composed_reasoning,
        composed_at=row.composed_at.isoformat() if row.composed_at else None,
        composer_model=row.composer_model,
        edited_subject=row.edited_subject,
        edited_body_html=row.edited_body_html,
        edited_plaintext=row.edited_plaintext,
        edited_by=row.edited_by,
        edited_at=row.edited_at.isoformat() if row.edited_at else None,
        skip_reason=row.skip_reason,
        failure_reason=row.failure_reason,
        send_attempted_at=row.send_attempted_at.isoformat() if row.send_attempted_at else None,
        sent_at=row.sent_at.isoformat() if row.sent_at else None,
        message_id=row.message_id,
        transport=row.transport,
        opens=engagement.opens if engagement else 0,
        clicks=engagement.clicks if engagement else 0,
        last_event_at=(
            engagement.last_event_at.isoformat()
            if engagement and engagement.last_event_at else None
        ),
    )


def _stats_to_dto(s) -> CampaignStatsDTO:
    return CampaignStatsDTO(
        campaign_id=s.campaign_id,
        total=s.total, pending=s.pending, composed=s.composed,
        sent=s.sent, skipped=s.skipped, failed=s.failed,
        opens=s.opens, unique_opens=s.unique_opens,
        clicks=s.clicks, unique_clicks=s.unique_clicks,
    )


# --- Campaign endpoints ----------------------------------------------------

@router.post("/api/outreach/campaigns", response_model=CampaignDTO)
async def create_campaign(req: CreateCampaignRequest) -> CampaignDTO:
    try:
        summary = await svc.create_campaign(
            post_slug=req.post_slug,
            name=req.name,
            sender_email=req.sender_email,
            sender_name=req.sender_name,
            sender_title=req.sender_title,
            bcc_email=req.bcc_email,
            intent=req.intent,
            notes=req.notes,
            with_excerpts=req.with_excerpts,
            composer_model=req.composer_model,
        )
    except blog_post_service.BlogPostNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CampaignDTO(
        id=summary.id, name=summary.name, post_slug=summary.post_slug,
        post_title=summary.post_title, status=summary.status,
        intent=summary.intent, sender_name=summary.sender_name,
        sender_email=summary.sender_email,
        bcc_email=summary.bcc_email,
        created_at=summary.created_at.isoformat(),
    )


@router.get("/api/outreach/campaigns", response_model=list[CampaignDTO])
async def list_campaigns(status: Optional[str] = None, limit: int = 50) -> list[CampaignDTO]:
    rows = await svc.list_campaigns(status=status, limit=limit)
    return [
        CampaignDTO(
            id=r.id, name=r.name, post_slug=r.post_slug, post_title=r.post_title,
            status=r.status, intent=r.intent, sender_name=r.sender_name,
            sender_email=r.sender_email, bcc_email=r.bcc_email,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/api/outreach/campaigns/{campaign_id}", response_model=CampaignDetailDTO)
async def get_campaign(campaign_id: int) -> CampaignDetailDTO:
    try:
        camp = await svc.get_campaign(campaign_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    stats = await svc.campaign_stats(campaign_id)
    return CampaignDetailDTO(
        id=camp.id, name=camp.name, post_slug=camp.post_slug,
        post_title=camp.post_title, status=camp.status, intent=camp.intent,
        sender_name=camp.sender_name, sender_email=camp.sender_email,
        bcc_email=camp.bcc_email,
        created_at=camp.created_at.isoformat(),
        post_url=camp.post_url,
        post_description=camp.post_description or "",
        post_category=camp.post_category,
        post_tags=list(camp.post_tags or []),
        post_excerpts=list(camp.post_excerpts or []),
        sender_title=camp.sender_title,
        composer_model=camp.composer_model,
        notes=camp.notes,
        updated_at=camp.updated_at.isoformat(),
        stats=_stats_to_dto(stats),
    )


@router.get("/api/outreach/campaigns/{campaign_id}/stats", response_model=CampaignStatsDTO)
async def campaign_stats(campaign_id: int) -> CampaignStatsDTO:
    return _stats_to_dto(await svc.campaign_stats(campaign_id))


class UpdateCampaignBccRequest(BaseModel):
    bcc_email: Optional[str] = None  # empty/None clears it


@router.patch("/api/outreach/campaigns/{campaign_id}/bcc", response_model=CampaignDTO)
async def update_campaign_bcc(
    campaign_id: int, req: UpdateCampaignBccRequest,
) -> CampaignDTO:
    try:
        row = await svc.update_campaign_bcc(campaign_id, req.bcc_email)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return CampaignDTO(
        id=row.id, name=row.name, post_slug=row.post_slug,
        post_title=row.post_title, status=row.status, intent=row.intent,
        sender_name=row.sender_name, sender_email=row.sender_email,
        bcc_email=row.bcc_email,
        created_at=row.created_at.isoformat(),
    )


@router.post(
    "/api/outreach/campaigns/{campaign_id}/audience",
    response_model=AudienceResultDTO,
)
async def add_audience(campaign_id: int, req: AddAudienceRequest) -> AudienceResultDTO:
    ids = list(req.contact_ids)
    if req.pif_ids:
        ids.extend(await svc.resolve_contacts_by_pif_ids(req.pif_ids))
        ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(
            status_code=400, detail="contact_ids or pif_ids must be non-empty",
        )
    res = await svc.add_contacts_to_campaign(
        campaign_id=campaign_id,
        contact_ids=ids,
        exclude_recent_days=req.exclude_recent_days,
    )
    return AudienceResultDTO(
        added=res.added, skipped_no_email=res.skipped_no_email,
        skipped_duplicate=res.skipped_duplicate,
        skipped_recent_outreach=res.skipped_recent_outreach,
    )


@router.get(
    "/api/outreach/campaigns/{campaign_id}/sends",
    response_model=list[SendDTO],
)
async def list_campaign_sends(
    campaign_id: int, status: Optional[str] = None, limit: int = 200,
) -> list[SendDTO]:
    rows = await svc.list_sends(campaign_id, status=status, limit=limit)
    eng = await svc.engagement_by_send(campaign_id)
    return [_send_to_dto(r, eng.get(r.id)) for r in rows]


@router.get(
    "/api/outreach/campaigns/{campaign_id}/next",
    response_model=Optional[SendDTO],
)
async def campaign_next(campaign_id: int) -> Optional[SendDTO]:
    row = await svc.get_next_for_review(campaign_id)
    return _send_to_dto(row) if row else None


@router.get(
    "/api/outreach/campaigns/{campaign_id}/events",
    response_model=list[LinkEventDTO],
)
async def campaign_events(
    campaign_id: int, kind: Optional[str] = None, limit: int = 200,
) -> list[LinkEventDTO]:
    """Newest-first feed of open + click events for this campaign.
    Filter by kind='open' or kind='click'."""
    events = await svc.list_events(campaign_id, kind=kind, limit=limit)
    return [
        LinkEventDTO(
            id=e.id,
            send_id=e.send_id,
            recipient_email=e.recipient_email,
            kind=e.kind,
            url=e.url,
            ip=e.ip,
            user_agent=e.user_agent,
            ts=e.ts.isoformat(),
        )
        for e in events
    ]


# --- Send endpoints --------------------------------------------------------

@router.get("/api/outreach/sends/{send_id}", response_model=SendDTO)
async def get_send(send_id: int) -> SendDTO:
    try:
        return _send_to_dto(await svc.get_send(send_id))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/api/outreach/sends/{send_id}/compose", response_model=SendDTO,
)
async def compose(send_id: int, req: ComposeRequest) -> SendDTO:
    try:
        row = await svc.compose_for_send(
            send_id, regenerate=req.regenerate, model=req.model,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _send_to_dto(row)


@router.get("/api/outreach/sends/{send_id}/preview", response_model=PreviewDTO)
async def preview(send_id: int) -> PreviewDTO:
    try:
        r = await svc.render_send(send_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return PreviewDTO(
        send_id=send_id,
        subject=r.subject, full_html=r.full_html, full_plaintext=r.full_plaintext,
        from_header=r.from_header, to=r.to,
        tracked_click_url=r.tracked_click_url,
        open_pixel_url=r.open_pixel_url,
    )


@router.post("/api/outreach/sends/{send_id}/send", response_model=SendResultDTO)
async def send(send_id: int) -> SendResultDTO:
    try:
        res = await svc.send_now(send_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}")
    return SendResultDTO(
        send_id=res.send_id, message_id=res.message_id, transport=res.transport,
    )


@router.post("/api/outreach/sends/{send_id}/skip", response_model=SendDTO)
async def skip(send_id: int, req: SkipRequest) -> SendDTO:
    try:
        await svc.skip(send_id, reason=req.reason)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _send_to_dto(await svc.get_send(send_id))


@router.post("/api/outreach/sends/{send_id}/edit", response_model=SendDTO)
async def edit(send_id: int, req: EditRequest) -> SendDTO:
    try:
        row = await svc.apply_edits(
            send_id,
            edited_subject=req.subject,
            edited_body_html=req.body_html,
            edited_plaintext=req.plaintext,
            edited_by=req.by,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _send_to_dto(row)


# --- Blog post helpers (for the UI campaign builder) -----------------------

@router.get("/api/outreach/blog-posts", response_model=list[BlogPostSlugDTO])
async def list_blog_posts() -> list[BlogPostSlugDTO]:
    """All blog-post slugs known to the local webnew repo."""
    return [BlogPostSlugDTO(slug=s) for s in blog_post_service.list_local_slugs()]


# --- Public tracking endpoints (no auth) -----------------------------------

@router.get("/t/o/{token}.gif")
async def tracking_open(token: str, request: Request) -> Response:
    """1x1 transparent GIF — fetched by email clients when an outreach
    message is opened. Always returns 200 + the pixel regardless of token
    validity so we don't 404 a recipient's inbox view."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    try:
        await svc.record_open(token, ip=ip, user_agent=ua)
    except Exception:
        # Never let logging failure prevent the pixel from rendering.
        pass
    return Response(
        content=svc.TRANSPARENT_GIF_BYTES,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/t/c/{token}")
async def tracking_click(token: str, request: Request) -> Response:
    """Logs the click, then 302-redirects to the canonical blog post URL.
    Unknown tokens redirect to the website root rather than 404 — a stale
    or malformed token in a recipient's inbox is not the user's problem."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    referer = request.headers.get("referer")
    try:
        dest = await svc.record_click(token, ip=ip, user_agent=ua, referer=referer)
    except Exception:
        dest = None
    if not dest:
        import os
        dest = os.getenv("WEBSITE_URL", "https://getpossibleminds.com").rstrip("/")
    return RedirectResponse(url=dest, status_code=302)
