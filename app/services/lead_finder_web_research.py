"""Bounded, source-backed web research for one Lead Finder candidate."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from app.services.llm_gateway import LLMGatewayError, call_skill_json


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/lead-finder-web-research/SKILL.md"
OPENAI_WEB_RESEARCH_MODEL = os.getenv("LEAD_FINDER_OPENAI_MODEL", "gpt-5.6-luna")
OPENCLAW_WEB_RESEARCH_MODEL = os.getenv("LEAD_FINDER_WEB_RESEARCH_MODEL", "openclaw/main")
WEB_RESEARCH_PROVIDERS = {"openai", "openclaw"}


OPENAI_RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "person": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "current_role": {"type": ["string", "null"]},
                "organization": {"type": ["string", "null"]},
                "official_profile_url": {"type": ["string", "null"]},
                "identity_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": [
                "name", "current_role", "organization", "official_profile_url",
                "identity_confidence",
            ],
            "additionalProperties": False,
        },
        "profile_summary": {"type": "string"},
        "recent_signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": ["string", "null"]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "relevance": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["date", "title", "summary", "relevance", "source_url"],
                "additionalProperties": False,
            },
        },
        "outreach_angles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "why_relevant": {"type": "string"},
                    "evidence": {"type": "string"},
                    "question": {"type": "string"},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "title", "why_relevant", "evidence", "question", "source_urls",
                ],
                "additionalProperties": False,
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "published_date": {"type": ["string", "null"]},
                    "source_type": {"type": "string"},
                    "supports": {"type": "string"},
                },
                "required": ["url", "title", "published_date", "source_type", "supports"],
                "additionalProperties": False,
            },
        },
        "contrary_evidence": {"type": "array", "items": {"type": "string"}},
        "researched_at": {"type": "string"},
    },
    "required": [
        "person", "profile_summary", "recent_signals", "outreach_angles", "sources",
        "contrary_evidence", "researched_at",
    ],
    "additionalProperties": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text.lower().startswith(("http://", "https://")) else None


def _short(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def normalize_person_research(raw: Any, *, request: dict[str, Any]) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    raw_person = value.get("person") if isinstance(value.get("person"), dict) else {}
    try:
        confidence = float(raw_person.get("identity_confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0.0, min(1.0, confidence))
    person = {
        "name": _short(raw_person.get("name") or request.get("person_name"), 160),
        "current_role": _short(raw_person.get("current_role"), 240) or None,
        "organization": _short(
            raw_person.get("organization") or request.get("organization"), 240
        ) or None,
        "official_profile_url": _url(raw_person.get("official_profile_url")),
        "identity_confidence": confidence,
    }

    sources: list[dict[str, Any]] = []
    source_urls: set[str] = set()
    for item in value.get("sources") if isinstance(value.get("sources"), list) else []:
        if not isinstance(item, dict) or not (url := _url(item.get("url"))):
            continue
        source_urls.add(url)
        sources.append({
            "url": url,
            "title": _short(item.get("title"), 500),
            "published_date": _short(item.get("published_date"), 32) or None,
            "source_type": _short(item.get("source_type"), 64) or "other",
            "supports": _short(item.get("supports"), 1_500),
        })
        if len(sources) >= 15:
            break

    recent_signals: list[dict[str, Any]] = []
    for item in value.get("recent_signals") if isinstance(value.get("recent_signals"), list) else []:
        if not isinstance(item, dict) or not (url := _url(item.get("source_url"))):
            continue
        if url not in source_urls:
            if len(sources) >= 15:
                continue
            sources.append({
                "url": url,
                "title": _short(item.get("title"), 500),
                "published_date": _short(item.get("date"), 32) or None,
                "source_type": "other",
                "supports": _short(item.get("summary"), 1_500),
            })
            source_urls.add(url)
        recent_signals.append({
            "date": _short(item.get("date"), 32) or None,
            "title": _short(item.get("title"), 500),
            "summary": _short(item.get("summary"), 2_000),
            "relevance": _short(item.get("relevance"), 1_500),
            "source_url": url,
        })
        if len(recent_signals) >= 8:
            break

    outreach_angles: list[dict[str, Any]] = []
    for item in value.get("outreach_angles") if isinstance(value.get("outreach_angles"), list) else []:
        if not isinstance(item, dict):
            continue
        urls = [
            url for raw_url in (item.get("source_urls") or [])
            if (url := _url(raw_url)) and url in source_urls
        ] if isinstance(item.get("source_urls"), list) else []
        if not urls:
            continue
        outreach_angles.append({
            "title": _short(item.get("title"), 240),
            "why_relevant": _short(item.get("why_relevant"), 2_000),
            "evidence": _short(item.get("evidence"), 2_000),
            "question": _short(item.get("question"), 1_000),
            "source_urls": urls[:5],
        })
        if len(outreach_angles) >= 5:
            break

    contrary = [
        _short(item, 1_000)
        for item in (value.get("contrary_evidence") or [])
        if _short(item, 1_000)
    ] if isinstance(value.get("contrary_evidence"), list) else []
    return {
        "person": person,
        "profile_summary": _short(value.get("profile_summary"), 4_000),
        "recent_signals": recent_signals,
        "outreach_angles": outreach_angles,
        "sources": sources[:15],
        "contrary_evidence": contrary[:10],
        "mission_control_evidence": request.get("mission_control_evidence") or [],
        "researched_at": _short(value.get("researched_at"), 64) or _now(),
    }


def normalize_web_research_provider(value: str | None) -> str:
    provider = str(value or "openai").strip().lower()
    if provider not in WEB_RESEARCH_PROVIDERS:
        raise ValueError("web_research_provider_must_be_openai_or_openclaw")
    return provider


def web_research_model(provider: str) -> str:
    return (
        OPENAI_WEB_RESEARCH_MODEL
        if normalize_web_research_provider(provider) == "openai"
        else OPENCLAW_WEB_RESEARCH_MODEL
    )


def web_research_provider_status(provider: str) -> dict[str, Any]:
    selected = normalize_web_research_provider(provider)
    return {
        "provider": selected,
        "model": web_research_model(selected),
        "configured": selected != "openai" or bool(
            os.getenv("LEAD_FINDER_OPENAI_API_KEY", "").strip()
        ),
    }


async def _research_person_openclaw(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    response = await call_skill_json(
        skill_path=SKILL_PATH,
        payload=payload,
        required_fields=[
            "person",
            "profile_summary",
            "recent_signals",
            "outreach_angles",
            "sources",
            "contrary_evidence",
            "researched_at",
        ],
        model=OPENCLAW_WEB_RESEARCH_MODEL,
        timeout_s=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_TIMEOUT_S", "300")),
        max_tokens=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_MAX_TOKENS", "5000")),
        retries=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_RETRIES", "1")),
    )
    return response.parsed, {
        "provider": "openclaw",
        "model": response.model,
        "usage": response.usage or {},
    }


async def _research_person_openai(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.getenv("LEAD_FINDER_OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("direct_openai_api_key_not_configured")
    timeout = int(os.getenv("LEAD_FINDER_OPENAI_TIMEOUT_S", "300"))
    model = OPENAI_WEB_RESEARCH_MODEL
    async with AsyncOpenAI(api_key=api_key, timeout=timeout) as client:
        response = await client.responses.create(
            model=model,
            instructions=SKILL_PATH.read_text(encoding="utf-8"),
            input=json.dumps(payload, indent=2, ensure_ascii=False),
            tools=[{"type": "web_search"}],
            include=["web_search_call.action.sources"],
            max_tool_calls=int(os.getenv("LEAD_FINDER_OPENAI_MAX_TOOL_CALLS", "6")),
            max_output_tokens=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_MAX_TOKENS", "5000")),
            prompt_cache_key="possible-os-lead-finder-web-research-v1",
            prompt_cache_retention="24h",
            store=False,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "lead_finder_person_research",
                    "strict": True,
                    "schema": OPENAI_RESEARCH_SCHEMA,
                }
            },
        )
    if response.status != "completed" or not response.output_text:
        detail = getattr(response, "incomplete_details", None)
        raise RuntimeError(f"direct_openai_response_{response.status}:{detail}")
    try:
        parsed = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("direct_openai_response_invalid_json") from exc
    usage = response.usage.model_dump() if response.usage else {}
    search_calls = sum(1 for item in response.output if getattr(item, "type", None) == "web_search_call")
    return parsed, {
        "provider": "openai",
        "model": response.model,
        "response_id": response.id,
        "search_calls": search_calls,
        "usage": usage,
    }


async def research_person(
    arguments: dict[str, Any],
    *,
    provider: str = "openai",
) -> dict[str, Any]:
    payload = {
        **arguments,
        "as_of_date": datetime.now(timezone.utc).date().isoformat(),
    }
    selected = normalize_web_research_provider(provider)
    try:
        if selected == "openai":
            raw, metadata = await _research_person_openai(payload)
        else:
            raw, metadata = await _research_person_openclaw(payload)
    except LLMGatewayError as exc:
        raise RuntimeError(f"web_research_gateway_failed:{exc}") from exc
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        if detail.startswith(("web_research_", "direct_openai_")):
            raise RuntimeError(detail) from exc
        raise RuntimeError(f"web_research_{selected}_failed:{detail}") from exc
    normalized = normalize_person_research(raw, request=arguments)
    normalized["_meta"] = metadata
    return normalized
