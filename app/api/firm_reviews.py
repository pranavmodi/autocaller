"""Firm-review endpoints.

GET  /api/firms/{pif_id}/reviews  → {google, yelp, updated_at}
PUT  /api/firms/{pif_id}/reviews  → upsert google + yelp blobs

The firm detail page is backed by an external service (Mediflow), but
operator-pasted reviews need to live locally. Reviews are split by
source — Google and Yelp each get their own free-form text blob. No
parsing, no per-review schema. PUT accepts either or both; omitted
fields leave the existing value alone so the UI can save one pane
without clobbering the other.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmReviewRow

router = APIRouter(prefix="/api/firms", tags=["firms"])


class ReviewsBody(BaseModel):
    google: Optional[str] = Field(default=None, max_length=200_000)
    yelp: Optional[str] = Field(default=None, max_length=200_000)


class ReviewsResponse(BaseModel):
    pif_id: str
    google: str
    yelp: str
    updated_at: str | None


def _row_to_response(pif_id: str, row: FirmReviewRow | None) -> ReviewsResponse:
    if row is None:
        return ReviewsResponse(pif_id=pif_id, google="", yelp="", updated_at=None)
    return ReviewsResponse(
        pif_id=row.pif_id,
        google=row.google_content or "",
        yelp=row.yelp_content or "",
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/{pif_id}/reviews", response_model=ReviewsResponse)
async def get_reviews(pif_id: str) -> ReviewsResponse:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
            )
        ).scalar_one_or_none()
    return _row_to_response(pif_id, row)


@router.put("/{pif_id}/reviews", response_model=ReviewsResponse)
async def put_reviews(pif_id: str, body: ReviewsBody) -> ReviewsResponse:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = FirmReviewRow(
                pif_id=pif_id,
                google_content=(body.google or "").strip(),
                yelp_content=(body.yelp or "").strip(),
            )
            session.add(row)
        else:
            # Patch semantics: only update fields the caller sent, so the
            # "Save Google" and "Save Yelp" buttons don't clobber each
            # other.
            if body.google is not None:
                row.google_content = body.google.strip()
            if body.yelp is not None:
                row.yelp_content = body.yelp.strip()
            row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
    return _row_to_response(pif_id, row)
