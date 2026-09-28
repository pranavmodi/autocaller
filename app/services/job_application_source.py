"""Find and verify an exact official application page for a saved job."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.services.career_search_web import fetch_page
from app.services.job_browser_ai import strict_schema
from app.services.job_search_ai import response_schema
from app.services.llm_gateway import call_skill_json


SKILL = Path(__file__).resolve().parents[1] / "skills/job-application-source-recovery/SKILL.md"


class SourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: HttpUrl
    reason: str = Field(max_length=500)


class SourceDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidates: list[SourceCandidate] = Field(max_length=8)


class SourceVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    matched: bool
    selected_url: str
    evidence_url: str
    source_type: Literal["employer", "ats", "none"]
    match_scope: Literal["direct_role", "official_jobs_portal", "none"]
    exact_role_quote: str
    exact_employer_quote: str
    exact_application_quote: str
    reason: str = Field(max_length=1000)
    confidence: float = Field(ge=0, le=1)


FORMATS = {"discover": SourceDiscovery, "verify": SourceVerification}


async def _direct(mode: str, payload: dict, model: str) -> tuple[dict, dict]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("Direct OpenAI API requires OPENAI_API_KEY on the server.")
    output_type = FORMATS[mode]
    try:
        async with AsyncOpenAI(api_key=key, base_url="https://api.openai.com/v1",
                               timeout=90, max_retries=0) as client:
            response = await client.responses.create(
                model=model,
                instructions=SKILL.read_text(),
                input=json.dumps({"mode": mode, **payload}, ensure_ascii=False),
                text={"format": {"type": "json_schema", "name": output_type.__name__,
                                 "strict": True,
                                 "schema": response_schema(strict_schema(output_type.model_json_schema()))}},
                tools=[{"type": "web_search"}] if mode == "discover" else [],
                tool_choice="required" if mode == "discover" else "none",
                include=["web_search_call.action.sources"] if mode == "discover" else [],
                store=False,
                max_output_tokens=3500,
                prompt_cache_key="possibleos:job-application-source-recovery:v1",
            )
    except APITimeoutError as exc:
        raise ValueError("Official application-page search timed out.") from exc
    except APIConnectionError as exc:
        raise ValueError("Could not connect to OpenAI for official application-page search.") from exc
    except APIStatusError as exc:
        raise ValueError(f"OpenAI application-page search returned HTTP {exc.status_code}.") from exc
    if response.status != "completed" or not response.output_text:
        raise ValueError("Official application-page search returned no complete result.")
    try:
        parsed = output_type.model_validate_json(response.output_text)
    except ValueError as exc:
        raise ValueError("Official application-page search returned an invalid result.") from exc
    return parsed.model_dump(mode="json"), {
        "provider": "openai", "model": response.model, "response_id": response.id,
        "usage": response.usage.model_dump() if response.usage else None,
    }


async def _model(mode: str, payload: dict, *, provider: str, model: str) -> tuple[dict, dict]:
    if provider == "openai":
        return await _direct(mode, payload, model)
    payload = {**payload, "output_schema": FORMATS[mode].model_json_schema()}
    required = ["candidates"] if mode == "discover" else [
        "matched", "selected_url", "source_type", "exact_role_quote",
        "evidence_url", "match_scope", "exact_employer_quote",
        "exact_application_quote", "reason", "confidence",
    ]
    result = await call_skill_json(
        skill_path=SKILL,
        payload={"mode": mode, **payload},
        required_fields=required,
        model="openclaw/main",
        lane="possibleos-interactive",
        allow_tools=mode == "discover",
        timeout_s=90,
        retries=1,
        max_tokens=3500,
    )
    return result.parsed, {"provider": "gateway", "model": result.model, "usage": result.usage}


def _contains_quote(content: str, quote: str) -> bool:
    return bool(quote.strip()) and " ".join(quote.split()) in " ".join(content.split())


async def resolve_official_application_source(posting: dict, *, provider: str,
                                              model: str) -> dict:
    """Return a freshly fetched, semantically verified exact-role application URL."""
    discovery, discovery_model = await _model("discover", {
        "job": {key: posting.get(key) for key in (
            "firm_name", "title", "location", "source_url", "source_urls",
            "website", "employer_evidence_url", "requisition_id")},
        "objective": "Find the exact role on the employer website or its official ATS application page.",
    }, provider=provider, model=model)
    discovered = SourceDiscovery.model_validate(discovery)
    urls = list(dict.fromkeys(str(item.url) for item in discovered.candidates))
    if not urls:
        raise ValueError("No official employer or ATS page was found for this exact role.")

    fetched = await asyncio.gather(*(fetch_page(url, attempts=1) for url in urls),
                                   return_exceptions=True)
    pages = []
    errors = []
    for url, result in zip(urls, fetched):
        if isinstance(result, Exception):
            errors.append({"url": url, "error": str(result)[:300]})
            continue
        if result.get("http_status") == 200:
            pages.append({"requested_url": url, "final_url": result["final_url"],
                          "content": result["content"][:24000]})
        else:
            errors.append({"url": url, "error": f"HTTP {result.get('http_status')}"})
    if not pages:
        raise ValueError("Official application pages were found, but none could be fetched for exact-role verification.")

    verification, verification_model = await _model("verify", {
        "job": {key: posting.get(key) for key in (
            "firm_name", "title", "location", "source_url", "website",
            "employer_evidence_url", "requisition_id")},
        "pages": pages,
        "fetch_errors": errors,
    }, provider=provider, model=model)
    verified = SourceVerification.model_validate(verification)
    if (not verified.matched or verified.source_type == "none"
            or verified.match_scope == "none" or not verified.selected_url):
        raise ValueError(verified.reason or "No exact official application page could be verified.")
    selected_page = next((item for item in pages if verified.selected_url in {
        item["requested_url"], item["final_url"]}), None)
    evidence_page = next((item for item in pages if verified.evidence_url in {
        item["requested_url"], item["final_url"]}), None)
    if not selected_page or not evidence_page:
        raise ValueError("The selected application page was not one of the freshly fetched sources.")
    quotes = [
        ("employer", verified.exact_employer_quote),
        ("application", verified.exact_application_quote),
    ]
    if verified.match_scope == "direct_role":
        quotes.insert(0, ("role", verified.exact_role_quote))
    elif verified.selected_url not in evidence_page["content"]:
        raise ValueError("The official employer evidence page did not link to the selected jobs portal.")
    for label, quote in quotes:
        if not _contains_quote(evidence_page["content"], quote):
            raise ValueError(f"The verified {label} evidence was not present on the selected page.")
    return {
        "url": selected_page["final_url"],
        "source_type": verified.source_type,
        "match_scope": verified.match_scope,
        "reason": verified.reason,
        "confidence": verified.confidence,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "evidence": {
            "role": verified.exact_role_quote,
            "employer": verified.exact_employer_quote,
            "application": verified.exact_application_quote,
            "source_url": evidence_page["final_url"],
        },
        "discovery_model": discovery_model,
        "verification_model": verification_model,
        "checked_urls": urls,
    }
