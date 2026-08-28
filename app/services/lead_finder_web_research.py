"""Bounded, source-backed web research for one Lead Finder candidate."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.llm_gateway import LLMGatewayError, call_skill_json


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills/lead-finder-web-research/SKILL.md"


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


async def research_person(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **arguments,
        "as_of_date": datetime.now(timezone.utc).date().isoformat(),
    }
    try:
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
            model=os.getenv("LEAD_FINDER_WEB_RESEARCH_MODEL", "openclaw/main"),
            timeout_s=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_TIMEOUT_S", "300")),
            max_tokens=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_MAX_TOKENS", "5000")),
            retries=int(os.getenv("LEAD_FINDER_WEB_RESEARCH_RETRIES", "1")),
        )
    except LLMGatewayError as exc:
        raise RuntimeError(f"web_research_gateway_failed:{exc}") from exc
    return normalize_person_research(response.parsed, request=arguments)
