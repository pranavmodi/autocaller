"""Demand-driven LinkedIn profile resolver for firm contacts."""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.db.models import FirmContactRow, LeadGenBatchItemRow, LeadGenBatchRow, PatientRow, PifFirmRow


LINKEDIN_PROFILE_RE = re.compile(r"^https?://([a-z]+\.)?linkedin\.com/in/")
DEFAULT_MODEL = "gpt-4o-mini"
MODEL_ENV = "LINKEDIN_RESOLVER_MODEL"

SYSTEM_PROMPT = (
    "You resolve personal LinkedIn profile URLs for named professional contacts. "
    "Return only valid JSON. Never return company pages, search pages, or explanatory text."
)


def _model_name() -> str:
    return (os.getenv(MODEL_ENV) or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _clean(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def validate_linkedin_url(value: Any) -> str | None:
    """Return a normalized personal LinkedIn URL, or None when unsafe."""
    url = _clean(value, 512)
    if not url:
        return None
    if any(ch.isspace() for ch in url):
        return None
    if not LINKEDIN_PROFILE_RE.match(url):
        return None
    lowered = url.lower()
    if "/company/" in lowered or "/search/" in lowered:
        return None
    return url


def _city_state_from_addresses(addresses: Any) -> str:
    if not isinstance(addresses, list):
        return ""
    for item in addresses:
        city = ""
        state = ""
        if isinstance(item, dict):
            city = _clean(item.get("city") or item.get("locality"), 128)
            state = _clean(item.get("state") or item.get("region"), 32)
            raw = _clean(item.get("address") or item.get("full_address"), 512)
        else:
            raw = _clean(item, 512)
        if city:
            return f"{city}, {state}".strip().strip(",")
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[-2][:128]
    return ""


def _city_state_from_research_data(research_data: Any) -> str:
    if not isinstance(research_data, dict):
        return ""
    for key in ("city", "location_city", "metro"):
        value = _clean(research_data.get(key), 128)
        if value:
            state = _clean(research_data.get("state") or research_data.get("location_state"), 32)
            if state and state.lower() not in value.lower():
                return f"{value}, {state}"
            return value
    location = research_data.get("location")
    if isinstance(location, dict):
        city = _clean(location.get("city"), 128)
        state = _clean(location.get("state"), 32)
        if city:
            return f"{city}, {state}".strip().strip(",")
    return ""


async def _firm_context(session, contact: FirmContactRow) -> dict[str, str]:
    pif_id = _clean(contact.pif_id, 64)
    firm = ""
    location = ""
    if pif_id:
        pif = await session.get(PifFirmRow, pif_id)
        if pif:
            firm = _clean(pif.firm_name, 512)
            location = (
                _city_state_from_addresses(pif.addresses)
                or _city_state_from_research_data(pif.research_data)
                or _clean(pif.metro, 128)
            )
        if not firm:
            rows = (await session.execute(
                select(PatientRow.patient_id, PatientRow.firm_name).where(
                    PatientRow.patient_id.in_([f"pif-{pif_id}", f"mc-{pif_id}"])
                )
            )).all()
            fallback: dict[str, str] = {}
            for patient_id, firm_name in rows:
                if firm_name:
                    fallback[str(patient_id)] = str(firm_name)
            firm = fallback.get(f"pif-{pif_id}") or fallback.get(f"mc-{pif_id}") or ""
    return {"firm": firm, "location": location}


def _user_prompt(*, name: str, title: str, firm: str, location: str) -> str:
    title_clause = f", {title}" if title else ""
    firm_clause = f" at **{firm}**" if firm else ""
    location_clause = f", in {location}" if location else ""
    return (
        f"Find the personal LinkedIn profile URL for **{name}**{title_clause}"
        f"{firm_clause}{location_clause}. Return ONLY a JSON object "
        "{\"linkedin_url\": \"https://www.linkedin.com/in/...\"} or "
        "{\"linkedin_url\": null} if you cannot confidently identify the specific person. "
        "Never return a company page (/company/), a search page, or explanatory text."
    )


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()
    raw = response.model_dump(mode="json") if hasattr(response, "model_dump") else {}
    chunks: list[str] = []
    for item in raw.get("output") or []:
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("text"):
                chunks.append(str(content.get("text")))
    return "\n".join(chunks).strip()


def _parse_linkedin_response(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return validate_linkedin_url(parsed.get("linkedin_url"))


async def _openai_client(client: Any | None) -> Any:
    if client is not None:
        return client
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))


async def resolve_linkedin_for_contact(
    contact_id: str,
    *,
    force: bool = False,
    client: Any | None = None,
) -> dict:
    """Resolve one contact's personal LinkedIn URL and write it when valid."""
    model = _model_name()
    async with AsyncSessionLocal() as session:
        contact = await session.get(FirmContactRow, contact_id)
        if not contact:
            raise ValueError("contact_not_found")
        existing = _clean(contact.linkedin_url, 512)
        if existing and not force:
            return {"status": "skipped", "linkedin_url": existing}

        context = await _firm_context(session, contact)
        name = _clean(contact.full_name, 255)
        title = _clean(contact.title or contact.research_title, 255)
        firm = context.get("firm") or ""
        location = context.get("location") or ""

        cli = await _openai_client(client)
        response = await cli.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            instructions=SYSTEM_PROMPT,
            input=_user_prompt(name=name, title=title, firm=firm, location=location),
            max_output_tokens=200,
        )
        linkedin_url = _parse_linkedin_response(_extract_response_text(response))
        if not linkedin_url:
            return {"status": "not_found", "model": model}

        contact.linkedin_url = linkedin_url
        contact.updated_at = datetime.now(UTC)
        await session.commit()
        return {"status": "resolved", "linkedin_url": linkedin_url, "model": model}


def _is_decision_maker(contact: FirmContactRow) -> bool:
    persona = _clean(contact.persona, 64).lower()
    title = _clean(contact.title or contact.research_title, 255).lower()
    if persona in {"founder_owner", "decision_maker", "managing_partner", "owner"}:
        return True
    markers = (
        "owner",
        "founder",
        "partner",
        "principal",
        "president",
        "ceo",
        "chief",
        "managing attorney",
        "managing lawyer",
        "managing partner",
        "attorney",
        "lawyer",
    )
    return any(marker in title for marker in markers)


async def _batch_contacts(batch_id: str, *, only_decision_makers: bool, force: bool) -> list[dict[str, str]]:
    async with AsyncSessionLocal() as session:
        batch = await session.get(LeadGenBatchRow, batch_id)
        if not batch:
            raise ValueError("batch_not_found")
        rows = (await session.execute(
            select(FirmContactRow)
            .join(LeadGenBatchItemRow, LeadGenBatchItemRow.contact_id == FirmContactRow.id)
            .where(LeadGenBatchItemRow.batch_id == batch_id)
            .order_by(LeadGenBatchItemRow.score.desc(), FirmContactRow.full_name.asc())
        )).scalars().all()

    seen: set[str] = set()
    contacts: list[dict[str, str]] = []
    for contact in rows:
        if contact.id in seen:
            continue
        seen.add(contact.id)
        if not force and _clean(contact.linkedin_url, 512):
            continue
        if only_decision_makers and not _is_decision_maker(contact):
            continue
        contacts.append({
            "id": contact.id,
            "name": contact.full_name or "",
            "title": contact.title or contact.research_title or "",
        })
    return contacts


async def resolve_linkedin_for_batch(
    batch_id: str,
    *,
    force: bool = False,
    only_decision_makers: bool = True,
    limit: int = 25,
    client: Any | None = None,
) -> dict:
    """Resolve LinkedIn URLs for contacts in one lead-gen batch."""
    limit = max(0, min(int(limit or 0), 25))
    candidates = await _batch_contacts(
        batch_id,
        only_decision_makers=only_decision_makers,
        force=force,
    )
    selected = candidates[:limit]
    results: list[dict] = []
    summary = {
        "resolved": 0,
        "not_found": 0,
        "skipped": 0,
        "errors": 0,
        "attempted": 0,
        "limited_to": limit,
        "eligible": len(candidates),
    }
    for index, contact in enumerate(selected):
        if index:
            await asyncio.sleep(0.5)
        try:
            result = await resolve_linkedin_for_contact(contact["id"], force=force, client=client)
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
            summary["errors"] += 1
        else:
            status = result.get("status") or "unknown"
            if status in summary:
                summary[status] += 1
            if status != "skipped":
                summary["attempted"] += 1
        results.append({
            "contact_id": contact["id"],
            "contact_name": contact.get("name") or "",
            "contact_title": contact.get("title") or "",
            **result,
        })
    return {
        "batch_id": batch_id,
        "only_decision_makers": only_decision_makers,
        "force": force,
        "limit": limit,
        "results": results,
        "summary": summary,
    }
