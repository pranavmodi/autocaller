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
    return f"<!-- EXTRACTED v2\n{body}\n-->\n\n{_RAW_MARKER}\n{raw}"


_COMPLAINT_DEFAULT_SENTIMENT = -0.6
_EVIDENCE_KINDS = {"complaint", "praise", "fact", "request", "outcome"}

# Preference order when choosing the single primary hook for an email. Complaint
# is the strongest hook for our product (we solve ops/communication pain), then
# praise ("scale what you're known for"), then outcome, then fact.
_KIND_PRIORITY = {"complaint": 0, "praise": 1, "outcome": 2, "fact": 3, "request": 4}


def evidence_gate_kinds() -> set[str]:
    """Which evidence kinds count as 'enough to personalize a first-touch email'
    — used by both the compose gate and the composer's primary-hook pick so they
    agree. Override via REVIEW_EVIDENCE_GATE_KINDS (comma-separated)."""
    raw = os.getenv("REVIEW_EVIDENCE_GATE_KINDS", "complaint,praise,fact")
    kinds = {k.strip().lower() for k in raw.split(",") if k.strip()}
    return {k for k in kinds if k in _EVIDENCE_KINDS} or {"complaint"}


def _has_content(item: dict[str, Any]) -> bool:
    return bool(item.get("quote") or item.get("paraphrase"))


def select_primary_evidence(
    items: list[dict[str, Any]], *, kinds: set[str] | None = None
) -> dict[str, Any] | None:
    """Pick the single best hook from a ranked evidence list: among items of the
    allowed kinds that carry usable content, prefer by kind priority then the
    list's existing confidence ranking."""
    allowed = kinds or evidence_gate_kinds()
    candidates = [e for e in items if e.get("kind") in allowed and _has_content(e)]
    if not candidates:
        return None
    return min(
        enumerate(candidates),
        key=lambda iv: (_KIND_PRIORITY.get(iv[1].get("kind"), 9), iv[0]),
    )[1]


def _normalize_evidence_item(raw: dict[str, Any], *, idx: int) -> dict[str, Any]:
    try:
        confidence = float(raw.get("confidence")) if raw.get("confidence") is not None else 0.0
    except (TypeError, ValueError):
        confidence = 0.0
    kind = str(raw.get("kind") or "complaint").strip().lower()
    return {
        "id": raw.get("id") or f"ev_{idx:02d}",
        "kind": kind if kind in _EVIDENCE_KINDS else "complaint",
        "theme": str(raw.get("theme") or "").strip(),
        "quote": raw.get("quote"),
        "paraphrase": raw.get("paraphrase"),
        "reviewer_name": raw.get("reviewer_name"),
        "review_date": raw.get("review_date"),
        "star_rating": raw.get("star_rating"),
        "sentiment": raw.get("sentiment"),
        "confidence": confidence,
        "outreach_usable": bool(raw.get("outreach_usable", True)),
        "usable_reason": raw.get("usable_reason"),
        "tags": raw.get("tags") or [],
    }


def evidence_items_from_extraction(extraction: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize a stored extraction block into a flat list of typed evidence
    items. Understands BOTH the v2 `evidence` list and the legacy v1
    `pain_points` map (mapped to kind=complaint), so old blocks keep working."""
    if not isinstance(extraction, dict):
        return []
    if isinstance(extraction.get("evidence"), list):
        return [
            _normalize_evidence_item(e, idx=i)
            for i, e in enumerate(extraction["evidence"], 1)
            if isinstance(e, dict)
        ]
    # Legacy v1: pain_points: { <theme>: [ {quote, reviewer_name, ...} ] }
    out: list[dict[str, Any]] = []
    i = 1
    for theme, quotes in (extraction.get("pain_points") or {}).items():
        for q in quotes or []:
            if not isinstance(q, dict):
                continue
            out.append(_normalize_evidence_item({
                "kind": "complaint",
                "theme": theme,
                "quote": q.get("quote"),
                "reviewer_name": q.get("reviewer_name"),
                "review_date": q.get("review_date"),
                "star_rating": q.get("star_rating"),
                "confidence": q.get("confidence"),
                "sentiment": _COMPLAINT_DEFAULT_SENTIMENT,
                "outreach_usable": bool(q.get("quote")),
            }, idx=i))
            i += 1
    return out


async def firms_with_usable_evidence(
    pif_ids: set[str], *, kinds: set[str] | None = None
) -> set[str]:
    """Batch: of the given firms, which have >=1 outreach-usable evidence item
    of the allowed kinds (with a quote or paraphrase). One query + in-memory
    parse — cheap enough to run over the daily candidate pool during selection."""
    pif_ids = {p for p in pif_ids if p}
    if not pif_ids:
        return set()
    allowed = kinds or evidence_gate_kinds()
    out: set[str] = set()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(FirmReviewRow).where(FirmReviewRow.pif_id.in_(pif_ids))
        )).scalars().all()
    for row in rows:
        for item in evidence_items_from_extraction(existing_extraction(row.yelp_content)):
            if (
                item.get("kind") in allowed
                and item.get("outreach_usable")
                and (item.get("quote") or item.get("paraphrase"))
            ):
                out.add(row.pif_id)
                break
    return out


async def fetch_review_evidence(
    pif_id: str,
    *,
    kinds: set[str] | None = None,
    themes: set[str] | None = None,
    min_confidence: float = 0.0,
    outreach_usable_only: bool = True,
    require_quote: bool = True,
    limit: int = 5,
    purpose: str = "compose",
) -> dict[str, Any]:
    """Generalized reader over a firm's stored review extraction. Returns a
    ranked list of typed evidence items plus firm-level signals. Callers select
    the slice they want (compose hook, gate check, targeting). Reads both v1 and
    v2 blocks. `purpose` is reserved for future ranking tweaks."""
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(FirmReviewRow).where(FirmReviewRow.pif_id == pif_id)
        )).scalar_one_or_none()
        yelp = row.yelp_content if row else None

    extraction = existing_extraction(yelp) or {}
    items = evidence_items_from_extraction(extraction)
    if kinds:
        items = [e for e in items if e["kind"] in kinds]
    if themes:
        items = [e for e in items if e["theme"] in themes]
    if outreach_usable_only:
        items = [e for e in items if e.get("outreach_usable")]
    items = [e for e in items if (e.get("confidence") or 0.0) >= min_confidence]
    if require_quote:
        items = [e for e in items if e.get("quote")]
    items.sort(
        key=lambda e: ((e.get("confidence") or 0.0), e.get("review_date") or ""),
        reverse=True,
    )
    return {
        "pif_id": pif_id,
        "items": items[: max(1, limit)],
        "firm_summary": extraction.get("firm_summary"),
        "themes_present": extraction.get("themes_present") or {},
        "themes_absent": extraction.get("themes_absent") or {},
        "extracted_at": extraction.get("extracted_at"),
        "extractor_version": extraction.get("extractor_version"),
    }


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
            required_fields=["evidence"],
            model=os.getenv("REVIEW_EXTRACTOR_MODEL", "openclaw/proxy"),
        )
    except LLMGatewayError as exc:
        logger.warning("review extraction gateway failed for %s: %s", pif_id, exc)
        return {"pif_id": pif_id, "status": "gateway_error", "error": str(exc)[:200]}

    parsed = result.parsed or {}
    evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
    extraction = {
        "extractor_version": "review-intel-v2",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": raw_h,
        "evidence": evidence,
        "themes_present": parsed.get("themes_present") or {},
        "themes_absent": parsed.get("themes_absent") or {},
        "firm_summary": parsed.get("firm_summary"),
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

    kinds = sorted({str(e.get("kind")) for e in evidence if isinstance(e, dict) and e.get("kind")})
    usable = sum(1 for e in evidence if isinstance(e, dict) and e.get("outreach_usable") and e.get("quote"))
    return {
        "pif_id": pif_id,
        "status": "extracted",
        "evidence_count": len(evidence),
        "usable_quote_count": usable,
        "kinds": kinds,
        "themes": sorted((extraction["themes_present"] or {}).keys()),
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
