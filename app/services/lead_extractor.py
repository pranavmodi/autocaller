"""LLM-based lead extractor.

Turns a raw Mission Control `pif_firm` record (or any similar messy source)
into a clean, structured lead for the autocaller: best contact, E.164 phone,
2-letter state, decision-maker confidence.

The extractor runs through the OpenClaw proxy gateway (OAuth — "Sign in with
ChatGPT"), driven by `app/skills/lead-extractor/SKILL.md`. The gateway has no
structured-output enforcement, so the SKILL.md specifies the exact JSON shape
and the gateway's tolerant JSON parser extracts it. Model/agent is configurable
via `LEAD_EXTRACTOR_MODEL` env var (default `openclaw/proxy`).

Cost: billed against the gateway's ChatGPT account quota, not per-token API.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.services.llm_gateway import call_skill_json

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("LEAD_EXTRACTOR_MODEL", "openclaw/proxy")
_SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/lead-extractor/SKILL.md"
_REQUIRED_FIELDS = [
    "usable",
    "name",
    "is_decision_maker",
    "decision_maker_confidence",
    "phone_e164",
    "firm_name",
    "name_is_person",
]


@dataclass
class ExtractedLead:
    """Structured lead ready to upsert into the `patients` table."""
    name: str
    phone_e164: str
    firm_name: str
    state: Optional[str]
    email: Optional[str]
    title: Optional[str]
    website: Optional[str]
    # Confidence fields
    is_decision_maker: bool
    decision_maker_confidence: int      # 0-10
    # Optional meta
    practice_area: str = "personal injury"
    notes: Optional[str] = None
    # Extractor-provided flags
    usable: bool = True                  # False means "don't call this lead"
    rejection_reason: Optional[str] = None
    name_is_person: bool = True          # False = name is a firm/brand, not a human


async def extract_lead(firm: dict, *, model: str = DEFAULT_MODEL) -> ExtractedLead:
    """Run the gateway extractor (OAuth) on a single firm record."""
    compact = {
        "firm_name": firm.get("firm_name"),
        "website": firm.get("website"),
        "phones": firm.get("phones") or [],
        "emails": firm.get("emails") or [],
        "addresses": firm.get("addresses") or [],
        "contacts": [
            {
                "name": c.get("name"),
                "title": c.get("title"),
                "phone": c.get("phone"),
                "email": c.get("email"),
                "extension": c.get("extension"),
            }
            for c in (firm.get("contacts") or [])
        ],
        "icp_tier": firm.get("icp_tier"),
        "outreach_notes": firm.get("outreach_notes") or firm.get("extraction_notes"),
    }

    try:
        result = await call_skill_json(
            skill_path=_SKILL_PATH,
            payload=compact,
            required_fields=_REQUIRED_FIELDS,
            model=model,
            max_tokens=int(os.getenv("LEAD_EXTRACTOR_MAX_TOKENS", "700")),
        )
    except Exception as e:
        logger.warning("extractor gateway call failed: %s", e)
        return ExtractedLead(
            name=firm.get("firm_name") or "(unknown)",
            phone_e164="",
            firm_name=firm.get("firm_name") or "",
            state=None,
            email=None,
            title=None,
            website=None,
            is_decision_maker=False,
            decision_maker_confidence=0,
            usable=False,
            rejection_reason=f"extractor gateway error: {type(e).__name__}",
        )

    data = result.parsed
    return ExtractedLead(
        name=data.get("name") or firm.get("firm_name") or "",
        phone_e164=data.get("phone_e164") or "",
        firm_name=data.get("firm_name") or firm.get("firm_name") or "",
        state=data.get("state"),
        email=data.get("email"),
        title=data.get("title"),
        website=data.get("website"),
        is_decision_maker=bool(data.get("is_decision_maker")),
        decision_maker_confidence=int(data.get("decision_maker_confidence") or 0),
        notes=data.get("notes"),
        usable=bool(data.get("usable")),
        rejection_reason=data.get("rejection_reason"),
        name_is_person=bool(data.get("name_is_person", True)),
    )


async def extract_leads_batch(
    firms: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    concurrency: int = 10,
    on_progress: Optional[Any] = None,
) -> list[ExtractedLead]:
    """Run the extractor across many firms with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    results: list[Optional[ExtractedLead]] = [None] * len(firms)
    done = 0

    async def _one(i: int, f: dict):
        nonlocal done
        async with sem:
            try:
                results[i] = await extract_lead(f, model=model)
            except Exception as e:
                logger.warning("extract_lead failed on firm %s: %s", f.get("firm_name"), e)
                results[i] = ExtractedLead(
                    name=f.get("firm_name") or "(unknown)",
                    phone_e164="",
                    firm_name=f.get("firm_name") or "",
                    state=None,
                    email=None,
                    title=None,
                    website=None,
                    is_decision_maker=False,
                    decision_maker_confidence=0,
                    usable=False,
                    rejection_reason=f"extractor error: {type(e).__name__}",
                )
            done += 1
            if on_progress:
                on_progress(done, len(firms))

    await asyncio.gather(*[_one(i, f) for i, f in enumerate(firms)])
    return [r for r in results if r is not None]  # type: ignore[misc]
