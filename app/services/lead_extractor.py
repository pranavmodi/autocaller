"""LLM-based lead extractor.

Turns a raw Mission Control `pif_firm` record (or any similar messy source)
into a clean, structured lead for the autocaller: best contact, E.164 phone,
2-letter state, decision-maker confidence.

We use OpenAI structured outputs (`response_format` with a JSON schema) so
the model returns parseable JSON every time. Model is configurable via
`LEAD_EXTRACTOR_MODEL` env var (default `gpt-4o-mini` — cheap + fast enough).

Cost: ~$0.0005-0.001 per firm with gpt-4o-mini. A full sync of 1,700 firms
costs roughly $1-2.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("LEAD_EXTRACTOR_MODEL", "gpt-4o-mini")


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


EXTRACTION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_lead",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "usable": {
                    "type": "boolean",
                    "description": "False if the firm has no phone number suitable for cold-calling or is otherwise unreachable.",
                },
                "rejection_reason": {
                    "type": ["string", "null"],
                    "description": "If usable=false, one short sentence why.",
                },
                "name": {
                    "type": "string",
                    "description": "Best person to call. Prefer decision-makers (Partner, Principal, Owner, Managing, Attorney/Esq, Director, CEO/COO/CFO, President, Shareholder, Of Counsel, Founder). Fall back to best available contact if no DM exists. If no named contact, return the firm_name.",
                },
                "title": {
                    "type": ["string", "null"],
                    "description": "Exact title as shown on the contact record, or null if unknown.",
                },
                "is_decision_maker": {
                    "type": "boolean",
                    "description": "True if the selected contact's title strongly indicates authority over operational spending decisions at a PI firm (partner, principal, owner, managing attorney, director, C-suite). False for paralegals, case managers, receptionists, assistants, coordinators, intake staff, back-office.",
                },
                "decision_maker_confidence": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "How confident you are that this contact can greenlight a deal for custom software/AI tooling. 10 = named partner/owner, 7-8 = managing attorney/director, 4-6 = associate attorney or unclear, 0-3 = paralegal/case manager/receptionist.",
                },
                "phone_e164": {
                    "type": "string",
                    "description": "Best phone to dial, normalized to E.164 (e.g. +15551234567). Strip extensions. Prefer the contact's direct phone over the firm's main number if given. If no usable phone, return empty string and set usable=false.",
                },
                "firm_name": {
                    "type": "string",
                    "description": "Firm name, cleaned up (title-cased, no excess punctuation).",
                },
                "state": {
                    "type": ["string", "null"],
                    "description": "2-letter US state code from the firm's address, or null if not extractable.",
                },
                "email": {
                    "type": ["string", "null"],
                    "description": "Best contact email, lowercased. Prefer the selected contact's email over the firm's generic inbox. Null if none.",
                },
                "website": {
                    "type": ["string", "null"],
                    "description": "Firm website URL if present, otherwise null.",
                },
                "notes": {
                    "type": ["string", "null"],
                    "description": "One-sentence summary of anything non-obvious worth the caller knowing (e.g. 'recent volume of referrals' or 'firm specializes in mass torts'). Null if nothing material.",
                },
            },
            "required": [
                "usable",
                "rejection_reason",
                "name",
                "title",
                "is_decision_maker",
                "decision_maker_confidence",
                "phone_e164",
                "firm_name",
                "state",
                "email",
                "website",
                "notes",
            ],
        },
    },
}


SYSTEM_PROMPT = """You are a data-cleaning agent preparing cold-call leads \
for an outbound sales campaign targeting US personal-injury law firms.

You'll receive a raw firm record (possibly messy) and you must select the \
single best contact to call, normalize the phone number to E.164, extract \
the state, and score whether the contact is a decision-maker.

Strict rules:
- Prefer decision-maker titles (partner, principal, owner, managing attorney, \
  director, C-suite). Avoid paralegals, case managers, receptionists, \
  assistants, coordinators, back-office, intake staff.
- If NO decision-maker contact exists but a named attorney or director does, \
  pick them.
- If NO usable contact exists at all, fall back to the firm-level record: \
  use firm_name as the "name", pick the firm's main phone, set \
  is_decision_maker=false, decision_maker_confidence=2.
- Phone must be E.164. Strip extensions ("x123", ", ext. 5", etc.). If no \
  usable phone, set usable=false and explain briefly.
- Never fabricate data. Missing fields are null, not guessed."""


async def extract_lead(firm: dict, *, client: AsyncOpenAI, model: str = DEFAULT_MODEL) -> ExtractedLead:
    """Run the LLM extractor on a single firm record."""
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

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(compact, ensure_ascii=False)},
        ],
        response_format=EXTRACTION_SCHEMA,
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Bad JSON from extractor: %s — raw=%r", e, raw[:200])
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
            rejection_reason="extractor returned unparseable JSON",
        )

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
    )


async def extract_leads_batch(
    firms: list[dict],
    *,
    model: str = DEFAULT_MODEL,
    concurrency: int = 10,
    on_progress: Optional[Any] = None,
) -> list[ExtractedLead]:
    """Run the extractor across many firms with bounded concurrency."""
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    sem = asyncio.Semaphore(concurrency)
    results: list[Optional[ExtractedLead]] = [None] * len(firms)
    done = 0

    async def _one(i: int, f: dict):
        nonlocal done
        async with sem:
            try:
                results[i] = await extract_lead(f, client=client, model=model)
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
