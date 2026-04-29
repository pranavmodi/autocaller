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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmReviewRow
from app.services.pifstats_sync import sync_pifstats_to_patients

router = APIRouter(prefix="/api/firms", tags=["firms"])


class SyncResponse(BaseModel):
    fetched: int
    inserted: int
    updated: int
    skipped: int


@router.post("/sync", response_model=SyncResponse)
async def sync_firms(
    limit: int = 500, recently_researched_days: int = 0,
) -> SyncResponse:
    """Force-pull researched firms from PIF Stats into the local
    `patients` table. Returns counts. Same shape as the background
    cadence-loop tick, just operator-triggered."""
    try:
        result = await sync_pifstats_to_patients(
            limit=max(1, min(2000, limit)),
            recently_researched_days=max(0, recently_researched_days),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"sync failed: {e}")
    return SyncResponse(**result)


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


def _looks_like_pif_uuid(pif_id: str) -> bool:
    """Real PIF Stats firm IDs are UUIDs (36 chars, 8-4-4-4-12). Test
    fixtures like "smoke-test" / "test-firm-1" leak into firm_reviews
    occasionally and should not pollute the /firms filter counts."""
    s = (pif_id or "").strip()
    return (
        len(s) == 36
        and s[8] == "-" and s[13] == "-"
        and s[18] == "-" and s[23] == "-"
    )


@router.get("/reviews-summary")
async def get_reviews_summary() -> dict:
    """Pif-IDs of firms that have any reviews stored locally.

    Used by the /firms list page to filter "show only firms with
    Google or Yelp reviews." Reviews live in our local DB, but the
    firm list itself is paginated server-side from PIF Stats, so the
    page fetches this small summary once when the filter activates
    and intersects the two on the client.

    Test-fixture rows (non-UUID pif_ids like "smoke-test") are
    filtered out so counts reflect real firms only.
    """
    async with AsyncSessionLocal() as session:
        rows = list(
            (await session.execute(select(FirmReviewRow))).scalars().all()
        )
    google_ids: list[str] = []
    yelp_ids: list[str] = []
    for r in rows:
        if not _looks_like_pif_uuid(r.pif_id):
            continue
        if (r.google_content or "").strip():
            google_ids.append(r.pif_id)
        if (r.yelp_content or "").strip():
            yelp_ids.append(r.pif_id)
    return {
        "google": google_ids,
        "yelp": yelp_ids,
        "any": sorted(set(google_ids) | set(yelp_ids)),
        "google_count": len(google_ids),
        "yelp_count": len(yelp_ids),
        "total_count": len(set(google_ids) | set(yelp_ids)),
    }


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
