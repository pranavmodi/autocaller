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


@router.get("/with-reviews")
async def get_firms_with_reviews(source: str = "any") -> dict:
    """All firms with reviews stored, enriched with PIF Stats info.

    Used when the /firms page review filter is active. Avoids the
    "matches scattered across PIF-Stats pagination" problem by
    fetching each matched pif_id directly (concurrent /pif-info/{id}
    calls), so operators see every match in one view regardless of
    upstream sort order.

    `source` ∈ {any, google, yelp}. Defaults to any.

    Capped at 100 firms per request — the local review set is small
    (operators paste these manually). If it grows beyond that, this
    endpoint should paginate or move to a less round-trip-heavy
    join strategy.
    """
    import asyncio
    import os
    import httpx

    src = (source or "any").strip().lower()
    if src not in ("any", "google", "yelp"):
        src = "any"

    # Resolve which pif_ids match this source — same UUID-shape filter
    # as /reviews-summary.
    async with AsyncSessionLocal() as session:
        rows = list(
            (await session.execute(select(FirmReviewRow))).scalars().all()
        )
    pif_ids: list[str] = []
    review_meta: dict[str, dict] = {}
    for r in rows:
        if not _looks_like_pif_uuid(r.pif_id):
            continue
        g_len = len((r.google_content or "").strip())
        y_len = len((r.yelp_content or "").strip())
        match = (
            (src == "any" and (g_len > 0 or y_len > 0))
            or (src == "google" and g_len > 0)
            or (src == "yelp" and y_len > 0)
        )
        if not match:
            continue
        pif_ids.append(r.pif_id)
        review_meta[r.pif_id] = {
            "google_chars": g_len,
            "yelp_chars": y_len,
            "reviews_updated_at": (
                r.updated_at.isoformat() if r.updated_at else None
            ),
        }
    pif_ids = pif_ids[:100]

    pif_base = os.getenv(
        "PIFSTATS_BASE_URL",
        "https://emailprocessing.mediflow360.com/api/v1/pif-info",
    )

    async def _fetch_one(client: httpx.AsyncClient, pif_id: str) -> dict:
        try:
            resp = await client.get(f"{pif_base}/{pif_id}")
            if resp.status_code != 200:
                return {"pif_id": pif_id, "missing": True}
            d = resp.json()
            return {
                "pif_id": pif_id,
                "firm_name": d.get("firm_name") or "",
                "website": d.get("website"),
                "phones": d.get("phones") or [],
                "addresses": d.get("addresses") or [],
                "contacts_count": len(d.get("contacts") or []),
                "leadership_count": len(d.get("leadership") or []),
                "icp_tier": d.get("icp_tier"),
                "icp_score": d.get("icp_score"),
                "research_status": d.get("research_status"),
                "last_researched_at": d.get("last_researched_at"),
                "behavioral_data": d.get("behavioral_data"),
                "missing": False,
            }
        except Exception as e:
            return {
                "pif_id": pif_id,
                "missing": True,
                "error": f"{type(e).__name__}: {e}",
            }

    async with httpx.AsyncClient(timeout=15.0) as client:
        firms_data = await asyncio.gather(
            *(_fetch_one(client, p) for p in pif_ids),
            return_exceptions=False,
        )

    items = []
    for f in firms_data:
        meta = review_meta.get(f["pif_id"], {})
        items.append({**f, **meta})

    # Sort: prefer firms with newer review-paste dates first; fall back
    # to firm_name for stability when timestamps tie.
    items.sort(
        key=lambda i: (
            i.get("reviews_updated_at") or "",
            (i.get("firm_name") or "").lower(),
        ),
        reverse=True,
    )

    return {"items": items, "total": len(items), "source": src}


@router.get("/autorespond-summary")
async def get_firms_autorespond_summary(days: int = 7) -> dict:
    """Per-firm autorespond signal summary, sorted by most-recent event.

    Used by the /firms page when the operator activates the
    "autoresponds sent in last N days" filter. Returns enough data
    to render a list view directly (firm_name, latest_event_at,
    counts, top agent_types) without needing a follow-up fetch
    against PIF Stats — the firm-list endpoint doesn't support
    pif_id-list filtering, so trying to intersect with it would
    require N round-trips. Far simpler to render straight from the
    autorespond signal map.
    """
    from app.services.autorespond_signals import fetch_recent_events_grouped
    days = max(1, min(int(days or 7), 30))
    grouped = await fetch_recent_events_grouped(days=days)
    # Sort by latest_event_at desc — newest activity first.
    items = []
    for pif_id, sig in grouped.items():
        items.append({
            "pif_id": pif_id,
            "firm_name": sig.get("firm_name") or "",
            "events_24h": sig.get("events_24h", 0),
            "events_7d": sig.get("events_7d", 0),
            "latest_event_at": sig.get("latest_event_at"),
            "latest_subject": sig.get("latest_subject") or "",
            "top_agent_types": sig.get("top_agent_types") or [],
            "distinct_contact_count": sig.get("distinct_contact_count", 0),
        })
    items.sort(
        key=lambda i: i.get("latest_event_at") or "",
        reverse=True,
    )
    return {"items": items, "total": len(items), "days": days}


@router.get("/stats")
async def get_firms_stats() -> dict:
    """Aggregate stats strip for the /firms page header.

    Combines PIF Stats counts (total firms, researched count) with
    local-DB counts (firms with reviews, firms with autorespond
    activity in the last 7 days). Each subquery is independent so a
    transient upstream failure on one doesn't break the others —
    failed fields come back as None and the UI shows a placeholder.

    Cached 60s in-process to keep page-load cheap when the operator
    flips between filter pills.
    """
    import time
    import os
    import httpx
    from app.services.autorespond_signals import fetch_recent_events_grouped

    global _firms_stats_cache
    now = time.time()
    if (
        "_firms_stats_cache" in globals()
        and (now - _firms_stats_cache.get("at", 0)) < 60
    ):
        return _firms_stats_cache["data"]

    pif_base = os.getenv(
        "PIFSTATS_BASE_URL",
        "https://emailprocessing.mediflow360.com/api/v1/pif-info",
    )

    async def _pif_total(params: dict) -> int | None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{pif_base}/", params=params)
            if resp.status_code != 200:
                return None
            return int(resp.json().get("total") or 0)
        except Exception:
            return None

    # Total firms — single page_size=1 fetch just to read `total`.
    total_firms = await _pif_total({"page": 1, "page_size": 1})
    researched_count = await _pif_total(
        {"page": 1, "page_size": 1, "research_status": "completed"},
    )

    # Local: review presence (already filters out non-UUID test rows).
    async with AsyncSessionLocal() as session:
        rows = list(
            (await session.execute(select(FirmReviewRow))).scalars().all()
        )
    with_reviews_count = len(
        {
            r.pif_id for r in rows
            if _looks_like_pif_uuid(r.pif_id)
            and (
                (r.google_content or "").strip()
                or (r.yelp_content or "").strip()
            )
        }
    )

    # Autorespond activity in the last 7 days, unique firms.
    try:
        ar_grouped = await fetch_recent_events_grouped(days=7)
        autorespond_7d_count = len(ar_grouped)
    except Exception:
        autorespond_7d_count = None

    data = {
        "total_firms": total_firms,
        "researched_count": researched_count,
        "with_reviews_count": with_reviews_count,
        "autorespond_7d_count": autorespond_7d_count,
    }
    _firms_stats_cache = {"at": now, "data": data}
    return data


# Module-level cache for /stats. Populated on first call.
_firms_stats_cache: dict = {}


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
