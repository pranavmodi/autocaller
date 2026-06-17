"""Programmatic Yelp-review extraction.

Turns operator-pasted raw Yelp reviews (firm_reviews.yelp_content) into the
structured `<!-- EXTRACTED vN ... -->` block that the lead-email gate and the
yelp-pain-quote composer variant read via fetch_pain_quote_for_firm.

Before this module the EXTRACTED block was produced by hand (an agent running
the yelp-review-quotes runbook). This makes it automatic: callable on save,
as a pre-compose safety net, or from the CLI. Idempotent — re-extracts only
when the raw text changed (tracked by content_hash in the stored block).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmReviewRow
from app.services.llm_gateway import LLMGatewayError, call_skill_json

logger = logging.getLogger(__name__)

_SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/review-quote-extractor/SKILL.md"
_EXTRACTED_RE = re.compile(r"<!--\s*EXTRACTED v\d+\s*([\s\S]*?)\s*-->")
_RAW_MARKER = "<!-- RAW YELP -->"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def auto_extract_enabled() -> bool:
    return _truthy(os.getenv("REVIEW_AUTO_EXTRACT", "true"))


def split_raw_reviews(yelp_content: str | None) -> str:
    """Return just the operator's raw review text, stripped of any prior
    EXTRACTED block. Honors the `<!-- RAW YELP -->` fence when present."""
    text = yelp_content or ""
    if _RAW_MARKER in text:
        return text.split(_RAW_MARKER, 1)[1].strip()
    return _EXTRACTED_RE.sub("", text).strip()


def existing_extraction(yelp_content: str | None) -> dict[str, Any] | None:
    m = _EXTRACTED_RE.search(yelp_content or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _raw_hash(raw: str) -> str:
    # Whitespace-normalized so trivial re-pastes don't trigger re-extraction.
    norm = " ".join((raw or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _render_block(extraction: dict[str, Any], raw: str) -> str:
    body = json.dumps(extraction, indent=2, ensure_ascii=False)
    return f"<!-- EXTRACTED v1\n{body}\n-->\n\n{_RAW_MARKER}\n{raw}"


def is_extraction_current(yelp_content: str | None) -> bool:
    """True when the stored EXTRACTED block matches the current raw text."""
    raw = split_raw_reviews(yelp_content)
    if not raw:
        return True  # nothing to extract
    prior = existing_extraction(yelp_content)
    return bool(prior and prior.get("content_hash") == _raw_hash(raw))


async def extract_review_quotes(
    pif_id: str,
    *,
    firm_name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Extract pain-point quotes from a firm's raw Yelp reviews and persist the
    `<!-- EXTRACTED v1 ... -->` block into firm_reviews.yelp_content. Idempotent:
    a no-op when the raw text is unchanged (unless force=True)."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
        )).scalar_one_or_none()
        yelp = row.yelp_content if row else None

    raw = split_raw_reviews(yelp)
    if not raw:
        return {"pif_id": pif_id, "status": "no_raw"}

    raw_h = _raw_hash(raw)
    if not force:
        prior = existing_extraction(yelp)
        if prior and prior.get("content_hash") == raw_h:
            return {"pif_id": pif_id, "status": "skipped_unchanged"}

    try:
        result = await call_skill_json(
            skill_path=_SKILL_PATH,
            payload={"firm_name": firm_name or "", "raw_reviews": raw[:20000]},
            required_fields=["pain_points"],
            model=os.getenv("REVIEW_EXTRACTOR_MODEL", "openclaw/proxy"),
        )
    except LLMGatewayError as exc:
        logger.warning("review extraction gateway failed for %s: %s", pif_id, exc)
        return {"pif_id": pif_id, "status": "gateway_error", "error": str(exc)[:200]}

    parsed = result.parsed or {}
    extraction = {
        "extractor_version": "yelp-quotes-v1",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": raw_h,
        "pain_points": parsed.get("pain_points") or {},
        "absent_pain_points": parsed.get("absent_pain_points") or {},
    }
    block = _render_block(extraction, raw)

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
        )).scalar_one_or_none()
        if row is None:
            row = FirmReviewRow(pif_id=pif_id, yelp_content=block)
            session.add(row)
        else:
            row.yelp_content = block
            row.updated_at = datetime.now(timezone.utc)
        await session.commit()

    quote_count = sum(len(v or []) for v in (extraction["pain_points"] or {}).values())
    return {
        "pif_id": pif_id,
        "status": "extracted",
        "quote_count": quote_count,
        "pain_point_keys": sorted((extraction["pain_points"] or {}).keys()),
    }


async def ensure_review_extracted(
    pif_id: str, *, firm_name: str | None = None
) -> dict[str, Any]:
    """Extract only when raw reviews exist and the stored extraction is missing
    or stale. Cheap no-op otherwise (hash compare, no LLM call)."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
        )).scalar_one_or_none()
        yelp = row.yelp_content if row else None
    if not split_raw_reviews(yelp):
        return {"pif_id": pif_id, "status": "no_raw"}
    if is_extraction_current(yelp):
        return {"pif_id": pif_id, "status": "skipped_unchanged"}
    return await extract_review_quotes(pif_id, firm_name=firm_name)


async def extract_all_pending(*, limit: int = 200, force: bool = False) -> dict[str, Any]:
    """Extract every firm that has raw Yelp reviews but a missing/stale block."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(FirmReviewRow))).scalars().all()
        candidates = [
            r.pif_id for r in rows
            if split_raw_reviews(r.yelp_content)
            and (force or not is_extraction_current(r.yelp_content))
        ][: max(1, limit)]

    results = []
    for pid in candidates:
        try:
            results.append(await extract_review_quotes(pid, force=force))
        except Exception as exc:  # never let one firm abort the batch
            logger.exception("extract_all_pending failed for %s", pid)
            results.append({"pif_id": pid, "status": "error", "error": str(exc)[:200]})
    extracted = sum(1 for r in results if r.get("status") == "extracted")
    return {"candidates": len(candidates), "extracted": extracted, "results": results}
